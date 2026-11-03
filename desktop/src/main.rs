// Screen Narrator's desktop side on COSMIC. The reader's helper (cosmic_desktop.py) calls
// this D-Bus service for the focused window, screenshots, an area to drag and page-turn
// keys; it is the same interface the GNOME extension offered, so the reader is unchanged.
// It also draws the passage highlight (highlight.json) over the book window.
//
// The panel applet starts it and starts it again if it ends. Screenshots and keys are only
// given while reading is on and only to the installed reader's helper, and a screenshot
// only goes into the reader's private runtime folder. Tools: grim (screenshots), slurp
// (area) and wtype (keys).

mod wayland;

use std::fs::OpenOptions;
use std::io::{BufWriter, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use cosmic_client_toolkit::sctk::reexports::calloop::channel::Sender;
use serde_json::Value;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Command as Process;
use tokio::sync::oneshot;
use wayland::{Command, Shared, Snapshot};
use zbus::message::Header;
use zbus::{Connection, interface};

const NAME: &str = "io.github.ubruckhaus.ScreenNarrator";
const PATH: &str = "/io/github/ubruckhaus/ScreenNarrator";
// How long a page-turn key may wait for the book window to take the focus it lends.
const FOCUS_WAIT: Duration = Duration::from_millis(300);
const TOOL_TIMEOUT: Duration = Duration::from_secs(5);
const SELECT_TIMEOUT: Duration = Duration::from_secs(90);

fn home() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default()
}

fn capture_file() -> PathBuf {
    wayland::runtime_dir().join("window.png")
}

fn helper() -> PathBuf {
    let data = std::env::var_os("XDG_DATA_HOME").map(PathBuf::from).unwrap_or_else(|| home().join(".local/share"));
    data.join("kindle-reader/app/cosmic_desktop.py")
}

// "X,Y WxH" (slurp's and grim's format).
fn geometry(text: &str) -> Option<(i32, i32, i32, i32)> {
    let (at, size) = text.split_once(' ')?;
    let (x, y) = at.split_once(',')?;
    let (w, h) = size.split_once('x')?;
    let (x, y, w, h) = (x.parse().ok()?, y.parse().ok()?, w.parse::<i32>().ok()?, h.parse::<i32>().ok()?);
    (w > 0 && h > 0).then_some((x, y, w, h))
}

// The reader's light poll: is reading on?
async fn reading() -> bool {
    let ask = async {
        let socket = wayland::runtime_dir().join("control.sock");
        let mut stream = tokio::net::UnixStream::connect(socket).await.ok()?;
        stream.write_all(b"{\"command\": \"watch\"}\n").await.ok()?;
        let mut line = String::new();
        BufReader::new(stream).read_line(&mut line).await.ok()?;
        let state: Value = serde_json::from_str(&line).ok()?;
        Some(state.get("enabled").and_then(Value::as_bool) == Some(true))
    };
    tokio::time::timeout(Duration::from_secs(2), ask).await.ok().flatten().unwrap_or(false)
}

fn proc_text(pid: u32, file: &str) -> Option<String> {
    std::fs::read(format!("/proc/{pid}/{file}")).ok().map(|b| String::from_utf8_lossy(&b).into_owned())
}

// The caller is the installed reader's helper (cosmic_desktop.py) of this user: it calls
// through busctl, so the caller is busctl and its parent the helper.
async fn from_reader(connection: &Connection, header: &Header<'_>) -> bool {
    let Some(sender) = header.sender() else { return false };
    let Ok(dbus) = zbus::fdo::DBusProxy::new(connection).await else { return false };
    let Ok(pid) = dbus.get_connection_unix_process_id(sender.clone().into()).await else { return false };
    let check = || -> Option<bool> {
        let cmdline = proc_text(pid, "cmdline")?;
        let status = proc_text(pid, "status")?;
        let ppid: u32 = status.lines().find_map(|l| l.strip_prefix("PPid:"))?.trim().parse().ok()?;
        let parent = proc_text(ppid, "cmdline")?;
        let helper = helper();
        let helper = helper.to_string_lossy();
        Some(cmdline.split('\0').next()?.ends_with("busctl") && parent.split('\0').any(|a| a == helper))
    };
    check().unwrap_or(false)
}

async fn tool(argv: &[&str], timeout: Duration) -> Option<Vec<u8>> {
    let child = Process::new(argv[0])
        .args(&argv[1..])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .output();
    match tokio::time::timeout(timeout, child).await {
        Ok(Ok(out)) if out.status.success() => Some(out.stdout),
        Ok(Ok(out)) => {
            eprintln!("[Screen Narrator] {} failed: {}", argv[0], String::from_utf8_lossy(&out.stderr).trim());
            None
        }
        Ok(Err(error)) => {
            eprintln!("[Screen Narrator] {} could not run: {error}", argv[0]);
            None
        }
        Err(_) => {
            eprintln!("[Screen Narrator] {} took too long", argv[0]);
            None
        }
    }
}

// A binary PPM (grim -t ppm): width, height, RGB bytes.
fn parse_ppm(data: &[u8]) -> Option<(usize, usize, &[u8])> {
    let mut fields = Vec::new();
    let mut at = 0;
    while fields.len() < 4 {
        while at < data.len() && data[at].is_ascii_whitespace() {
            at += 1;
        }
        if data.get(at) == Some(&b'#') {
            while at < data.len() && data[at] != b'\n' {
                at += 1;
            }
            continue;
        }
        let start = at;
        while at < data.len() && !data[at].is_ascii_whitespace() {
            at += 1;
        }
        fields.push(std::str::from_utf8(&data[start..at]).ok()?);
    }
    if fields[0] != "P6" || fields[3] != "255" {
        return None;
    }
    let (width, height): (usize, usize) = (fields[1].parse().ok()?, fields[2].parse().ok()?);
    let pixels = data.get(at + 1..at + 1 + width * height * 3)?;
    Some((width, height, pixels))
}

fn write_png(path: &Path, width: usize, height: usize, rgb: &[u8]) -> std::io::Result<()> {
    let file = OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).open(path)?;
    let mut encoder = png::Encoder::new(BufWriter::new(file), width as u32, height as u32);
    encoder.set_color(png::ColorType::Rgb);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder.write_header().map_err(std::io::Error::other)?;
    writer.write_image_data(rgb).map_err(std::io::Error::other)?;
    writer.finish().map_err(std::io::Error::other)?;
    Ok(())
}

struct Desktop {
    shared: Shared,
    commands: Mutex<Sender<Command>>,
}

impl Desktop {
    fn snapshot<T>(&self, f: impl FnOnce(&Snapshot) -> T) -> T {
        f(&self.shared.lock().unwrap_or_else(|e| e.into_inner()))
    }

    fn send(&self, command: Command) {
        if let Ok(sender) = self.commands.lock() {
            let _ = sender.send(command);
        }
    }

    async fn hide(&self, hidden: bool) {
        let (done, wait) = oneshot::channel();
        self.send(Command::Hide(hidden, done));
        let _ = tokio::time::timeout(Duration::from_millis(500), wait).await;
        if hidden {
            // Let the compositor draw a frame without the boxes.
            tokio::time::sleep(Duration::from_millis(60)).await;
        }
    }

    fn shown(&self, address: &str) -> bool {
        self.snapshot(|s| s.find(address).is_some_and(|w| w.shown))
    }

    fn focused(&self) -> Option<String> {
        self.snapshot(|s| s.focused().map(|w| w.address.clone()))
    }

    async fn capture_area(&self, area: &str, path: &Path) -> bool {
        self.hide(true).await;
        let ok = tool(&["grim", "-g", area, &path.to_string_lossy()], TOOL_TIMEOUT).await.is_some();
        self.hide(false).await;
        ok
    }

    // Part of one window from the window's own picture: windows over it or the focus
    // elsewhere do not matter.
    async fn crop_window(&self, address: &str, area: (i32, i32, i32, i32), path: &Path) -> Result<(), String> {
        let window = self.snapshot(|s| s.find(address).cloned()).ok_or(format!("window {address} is gone"))?;
        if !window.shown {
            return Err(format!("window {address} is not on screen"));
        }
        let data = tool(&["grim", "-t", "ppm", "-T", address, "-"], TOOL_TIMEOUT)
            .await
            .ok_or(format!("window {address} could not be captured"))?;
        let (width, height, pixels) = parse_ppm(&data).ok_or("grim gave no picture")?;
        // The picture is the window at its own scale; a picture larger than the window's
        // frame on both sides has a border (shadows) around it, split evenly.
        let scale = width as f64 / window.size.0.max(1) as f64;
        let scale_y = height as f64 / window.size.1.max(1) as f64;
        let scale = scale.min(scale_y).max(0.01);
        let pad_x = ((width as f64 - window.size.0 as f64 * scale) / 2.0).max(0.0);
        let pad_y = ((height as f64 - window.size.1 as f64 * scale) / 2.0).max(0.0);
        let (x, y, w, h) = area;
        let left = ((x - window.at.0) as f64 * scale + pad_x).round().clamp(0.0, width as f64) as usize;
        let top = ((y - window.at.1) as f64 * scale + pad_y).round().clamp(0.0, height as f64) as usize;
        let right = ((x + w - window.at.0) as f64 * scale + pad_x).round().clamp(0.0, width as f64) as usize;
        let bottom = ((y + h - window.at.1) as f64 * scale + pad_y).round().clamp(0.0, height as f64) as usize;
        if right <= left || bottom <= top {
            return Err(format!("{x},{y} {w}x{h} is outside window {address}"));
        }
        let mut crop = Vec::with_capacity((right - left) * (bottom - top) * 3);
        for row in top..bottom {
            crop.extend_from_slice(&pixels[(row * width + left) * 3..(row * width + right) * 3]);
        }
        write_png(path, right - left, bottom - top, &crop).map_err(|e| e.to_string())
    }
}

#[interface(name = "io.github.ubruckhaus.ScreenNarrator.Desktop")]
impl Desktop {
    fn active_window(&self) -> String {
        self.snapshot(|s| s.focused().map_or("{}".into(), |w| w.json().to_string()))
    }

    // The book window the reader pinned, wherever the focus is; {} once it is closed.
    fn window(&self, address: &str) -> String {
        self.snapshot(|s| s.find(address).map_or("{}".into(), |w| w.json().to_string()))
    }

    fn clients(&self) -> String {
        self.snapshot(|s| Value::Array(s.windows.iter().map(|w| w.json()).collect()).to_string())
    }

    async fn capture(
        &self,
        #[zbus(connection)] connection: &Connection,
        #[zbus(header)] header: Header<'_>,
        area: String,
        path: String,
    ) -> bool {
        let file = capture_file();
        if geometry(&area).is_none() || Path::new(&path) != file {
            eprintln!("[Screen Narrator] capture refused: not the reader's capture: {area} {path}");
            return false;
        }
        if !reading().await || !from_reader(connection, &header).await {
            eprintln!("[Screen Narrator] capture refused: reading is off or not asked by the installed reader");
            return false;
        }
        self.capture_area(&area, &file).await
    }

    async fn capture_window(
        &self,
        #[zbus(connection)] connection: &Connection,
        #[zbus(header)] header: Header<'_>,
        address: String,
        area: String,
        path: String,
    ) -> bool {
        let file = capture_file();
        let Some(area) = geometry(&area).filter(|_| Path::new(&path) == file) else {
            eprintln!("[Screen Narrator] window capture refused: not the reader's capture: {area} {path}");
            return false;
        };
        if !reading().await || !from_reader(connection, &header).await {
            eprintln!("[Screen Narrator] window capture refused: reading is off or not asked by the installed reader");
            return false;
        }
        match self.crop_window(&address, area, &file).await {
            Ok(()) => true,
            Err(error) => {
                eprintln!("[Screen Narrator] window capture failed: {error}");
                false
            }
        }
    }

    // "X,Y WxH" like slurp, or "" when cancelled.
    async fn select_area(&self, #[zbus(connection)] connection: &Connection, #[zbus(header)] header: Header<'_>) -> String {
        if !from_reader(connection, &header).await {
            return String::new();
        }
        tool(&["slurp"], SELECT_TIMEOUT)
            .await
            .map(|out| String::from_utf8_lossy(&out).trim().to_string())
            .filter(|area| geometry(area).is_some())
            .unwrap_or_default()
    }

    // key: an X keysym name ("Right", "n", "Next") for the book window. Keys only go to the
    // focused window, so a book in the background gets the focus for a moment and the
    // window that had it gets it back. Not for a book on another workspace or minimized.
    async fn send_key(
        &self,
        #[zbus(connection)] connection: &Connection,
        #[zbus(header)] header: Header<'_>,
        address: String,
        key: String,
    ) -> bool {
        let valid = !key.is_empty() && key.len() <= 32 && key.chars().all(|c| c.is_ascii_alphanumeric() || c == '_');
        if !valid || !reading().await || !from_reader(connection, &header).await || !self.shown(&address) {
            return false;
        }
        let previous = self.focused();
        let lent = previous.as_deref() != Some(address.as_str());
        let mut ok = true;
        if lent {
            self.hide(true).await;
            self.send(Command::Activate(address.clone()));
            let mut waited = Duration::ZERO;
            while self.focused().as_deref() != Some(address.as_str()) && waited < FOCUS_WAIT {
                tokio::time::sleep(Duration::from_millis(20)).await;
                waited += Duration::from_millis(20);
            }
        }
        // The waits let reading stop, the book leave the screen or the focus move meanwhile:
        // the focus is checked last, right before the key.
        ok &= self.shown(&address) && reading().await && self.focused().as_deref() == Some(address.as_str());
        if ok {
            ok = tool(&["wtype", "-k", &key], TOOL_TIMEOUT).await.is_some();
        }
        if lent {
            // Let the key reach the book before the focus goes back, and only give it back if
            // nothing else took the focus meanwhile and that window is still on screen.
            tokio::time::sleep(Duration::from_millis(80)).await;
            if let Some(previous) = previous
                && self.focused().as_deref() == Some(address.as_str())
                && self.shown(&previous)
            {
                self.send(Command::Activate(previous));
            }
            self.hide(false).await;
        }
        ok
    }

    fn open_settings(&self) {
        open_settings();
    }
}

// The Flutter settings window: next to this program, in the data folder, or on PATH.
fn open_settings() {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(dir) = std::env::current_exe().ok().and_then(|e| e.parent().map(Path::to_path_buf)) {
        candidates.push(dir.join("screen-narrator-settings"));
    }
    candidates.push(home().join(".local/share/cosmic-narrator/settings/screen-narrator-settings"));
    let program = candidates.into_iter().find(|p| p.is_file()).unwrap_or_else(|| "screen-narrator-settings".into());
    let _ = std::process::Command::new(program)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
}

fn main() {
    let shared: Shared = Arc::new(Mutex::new(Snapshot::default()));
    let (sender, receiver) = wayland::channel();
    let wayland_shared = shared.clone();
    let wayland_thread = std::thread::spawn(move || wayland::run(wayland_shared, receiver));

    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build().expect("tokio runtime");
    let result: zbus::Result<()> = runtime.block_on(async {
        let desktop = Desktop { shared, commands: Mutex::new(sender) };
        let _connection = zbus::connection::Builder::session()?
            .name(NAME)?
            .serve_at(PATH, desktop)?
            .build()
            .await?;
        // Serves until the Wayland side ends (the session is over).
        while !wayland_thread.is_finished() {
            tokio::time::sleep(Duration::from_secs(1)).await;
        }
        if let Ok(Err(error)) = wayland_thread.join() {
            eprintln!("[Screen Narrator] Wayland: {error}");
        }
        Ok(())
    });
    match result {
        Err(zbus::Error::NameTaken) => eprintln!("[Screen Narrator] the desktop service runs already"),
        Err(error) => eprintln!("[Screen Narrator] desktop service: {error}"),
        Ok(()) => {}
    }
    let _ = std::io::stderr().flush();
}
