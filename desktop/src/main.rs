// Maprisma Narrator's desktop side on COSMIC. The reader's helper (cosmic_desktop.py) calls
// this D-Bus service for the focused window, screenshots, an area to drag and page-turn
// keys; it is the same interface the GNOME extension offered, so the reader is unchanged.
// It also draws the passage highlight (highlight.json) over the book window.
//
// The panel applet starts it and starts it again if it ends. Screenshots and keys are only
// given while reading is on and only to the installed reader's helper, and a screenshot
// only goes into the reader's private runtime folder. Tools: grim (screenshots), slurp
// (area) and wtype (keys).

mod hypr;
mod kde;
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

const NAME: &str = "com.maprisma.Narrator.Desktop";
const PATH: &str = "/com/maprisma/Narrator/Desktop";
// How long a page-turn key may wait for the book window to take the focus it lends.
const FOCUS_WAIT: Duration = Duration::from_millis(500);
const FOCUS_SETTLE: Duration = Duration::from_millis(40);
const TOOL_TIMEOUT: Duration = Duration::from_secs(5);
const SELECT_TIMEOUT: Duration = Duration::from_secs(90);

fn home() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default()
}

fn capture_file() -> PathBuf {
    wayland::runtime_dir().join("window.png")
}

fn helper() -> PathBuf {
    let data = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| home().join(".local/share"));
    data.join("kindle-reader/app/cosmic_desktop.py")
}

// "X,Y WxH" (slurp's and grim's format).
fn geometry(text: &str) -> Option<(i32, i32, i32, i32)> {
    let (at, size) = text.split_once(' ')?;
    let (x, y) = at.split_once(',')?;
    let (w, h) = size.split_once('x')?;
    let (x, y, w, h) = (
        x.parse().ok()?,
        y.parse().ok()?,
        w.parse::<i32>().ok()?,
        h.parse::<i32>().ok()?,
    );
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
    tokio::time::timeout(Duration::from_secs(2), ask)
        .await
        .ok()
        .flatten()
        .unwrap_or(false)
}

fn proc_text(pid: u32, file: &str) -> Option<String> {
    std::fs::read(format!("/proc/{pid}/{file}"))
        .ok()
        .map(|b| String::from_utf8_lossy(&b).into_owned())
}

// The caller is the installed reader's helper (cosmic_desktop.py) of this user: it calls
// through busctl, so the caller is busctl and its parent the helper.
async fn from_reader(connection: &Connection, header: &Header<'_>) -> bool {
    let Some(sender) = header.sender() else {
        return false;
    };
    let Ok(dbus) = zbus::fdo::DBusProxy::new(connection).await else {
        return false;
    };
    let Ok(pid) = dbus
        .get_connection_unix_process_id(sender.clone().into())
        .await
    else {
        return false;
    };
    let check = || -> Option<bool> {
        let cmdline = proc_text(pid, "cmdline")?;
        let status = proc_text(pid, "status")?;
        let ppid: u32 = status
            .lines()
            .find_map(|l| l.strip_prefix("PPid:"))?
            .trim()
            .parse()
            .ok()?;
        let parent = proc_text(ppid, "cmdline")?;
        let helper = helper();
        let helper = helper.to_string_lossy();
        Some(
            cmdline.split('\0').next()?.ends_with("busctl")
                && parent.split('\0').any(|a| a == helper),
        )
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
            eprintln!(
                "[Maprisma Narrator] {} failed: {}",
                argv[0],
                String::from_utf8_lossy(&out.stderr).trim()
            );
            None
        }
        Ok(Err(error)) => {
            eprintln!("[Maprisma Narrator] {} could not run: {error}", argv[0]);
            None
        }
        Err(_) => {
            eprintln!("[Maprisma Narrator] {} took too long", argv[0]);
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
    let file = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(path)?;
    let mut encoder = png::Encoder::new(BufWriter::new(file), width as u32, height as u32);
    encoder.set_color(png::ColorType::Rgb);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder.write_header().map_err(std::io::Error::other)?;
    writer
        .write_image_data(rgb)
        .map_err(std::io::Error::other)?;
    writer.finish().map_err(std::io::Error::other)?;
    Ok(())
}

struct Desktop {
    shared: Shared,
    kde: Option<kde::Kde>,
    hypr: Option<hypr::Hypr>,
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
        let ok = if let Some(kde) = &self.kde {
            match kde.capture(None, geometry(area).unwrap()).await {
                Ok((w, h, rgb)) => write_png(path, w, h, &rgb).is_ok(),
                Err(e) => {
                    eprintln!("[Maprisma Narrator] ScreenShot2: {e}");
                    false
                }
            }
        } else {
            tool(&["grim", "-g", area, &path.to_string_lossy()], TOOL_TIMEOUT)
                .await
                .is_some()
        };
        self.hide(false).await;
        ok
    }

    // Part of one window from the window's own picture: windows over it or the focus
    // elsewhere do not matter.
    async fn crop_window(
        &self,
        address: &str,
        area: (i32, i32, i32, i32),
        path: &Path,
    ) -> Result<(), String> {
        let window = self
            .snapshot(|s| s.find(address).cloned())
            .ok_or(format!("window {address} is gone"))?;
        if !window.shown {
            return Err(format!("window {address} is not on screen"));
        }
        if self.hypr.is_some() {
            // grim cannot capture one Hyprland window by itself: the window's part of the
            // screen (it is on screen; a floating window over it would show too).
            let (x, y, w, h) = area;
            let inside = x >= window.at.0
                && y >= window.at.1
                && x + w <= window.at.0 + window.size.0
                && y + h <= window.at.1 + window.size.1;
            if !inside {
                return Err(format!("{x},{y} {w}x{h} is outside window {address}"));
            }
            return if self.capture_area(&format!("{x},{y} {w}x{h}"), path).await {
                Ok(())
            } else {
                Err("screen capture failed".into())
            };
        }
        let kde_picture;
        let cosmic_picture;
        let (width, height, pixels) = if let Some(kde) = &self.kde {
            kde_picture = kde.capture(Some(address), area).await?;
            (kde_picture.0, kde_picture.1, kde_picture.2.as_slice())
        } else {
            cosmic_picture = tool(&["grim", "-t", "ppm", "-T", address, "-"], TOOL_TIMEOUT)
                .await
                .ok_or("window could not be captured")?;
            parse_ppm(&cosmic_picture).ok_or("grim gave no picture")?
        };
        // The picture is the window at its own scale; a picture larger than the window's
        // frame on both sides has a border (shadows) around it, split evenly.
        let scale = width as f64 / window.size.0.max(1) as f64;
        let scale_y = height as f64 / window.size.1.max(1) as f64;
        let scale = scale.min(scale_y).max(0.01);
        let pad_x = ((width as f64 - window.size.0 as f64 * scale) / 2.0).max(0.0);
        let pad_y = ((height as f64 - window.size.1 as f64 * scale) / 2.0).max(0.0);
        let (x, y, w, h) = area;
        let left = ((x - window.at.0) as f64 * scale + pad_x)
            .round()
            .clamp(0.0, width as f64) as usize;
        let top = ((y - window.at.1) as f64 * scale + pad_y)
            .round()
            .clamp(0.0, height as f64) as usize;
        let right = ((x + w - window.at.0) as f64 * scale + pad_x)
            .round()
            .clamp(0.0, width as f64) as usize;
        let bottom = ((y + h - window.at.1) as f64 * scale + pad_y)
            .round()
            .clamp(0.0, height as f64) as usize;
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

#[interface(name = "com.maprisma.Narrator.Desktop")]
impl Desktop {
    fn active_window(&self) -> String {
        self.snapshot(|s| s.focused().map_or("{}".into(), |w| w.json().to_string()))
    }

    // The book window the reader pinned, wherever the focus is; {} once it is closed.
    fn window(&self, address: &str) -> String {
        self.snapshot(|s| {
            s.find(address)
                .map_or("{}".into(), |w| w.json().to_string())
        })
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
            eprintln!(
                "[Maprisma Narrator] capture refused: not the reader's capture: {area} {path}"
            );
            return false;
        }
        if !reading().await || !from_reader(connection, &header).await {
            eprintln!(
                "[Maprisma Narrator] capture refused: reading is off or not asked by the installed reader"
            );
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
            eprintln!(
                "[Maprisma Narrator] window capture refused: not the reader's capture: {area} {path}"
            );
            return false;
        };
        if !reading().await || !from_reader(connection, &header).await {
            eprintln!(
                "[Maprisma Narrator] window capture refused: reading is off or not asked by the installed reader"
            );
            return false;
        }
        match self.crop_window(&address, area, &file).await {
            Ok(()) => true,
            Err(error) => {
                eprintln!("[Maprisma Narrator] window capture failed: {error}");
                false
            }
        }
    }

    // "X,Y WxH" like slurp, or "" when cancelled.
    async fn select_area(
        &self,
        #[zbus(connection)] connection: &Connection,
        #[zbus(header)] header: Header<'_>,
    ) -> String {
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
        let valid = !key.is_empty()
            && key.len() <= 32
            && key.chars().all(|c| c.is_ascii_alphanumeric() || c == '_');
        if !valid
            || !reading().await
            || !from_reader(connection, &header).await
            || !self.shown(&address)
        {
            return false;
        }
        let previous = self.focused();
        let lent = previous.as_deref() != Some(address.as_str());
        let mut ok = true;
        if lent {
            self.hide(true).await;
            if let Some(kde) = &self.kde {
                let _ = kde.refresh(Some(&address)).await;
            } else if let Some(hypr) = &self.hypr {
                if let Err(e) = hypr.activate(&address).await {
                    eprintln!("[Maprisma Narrator] Hyprland focus: {e}");
                }
            } else {
                self.send(Command::Activate(address.clone()));
            }
            let mut waited = Duration::ZERO;
            while self.focused().as_deref() != Some(address.as_str()) && waited < FOCUS_WAIT {
                tokio::time::sleep(Duration::from_millis(20)).await;
                waited += Duration::from_millis(20);
            }
            if self.focused().as_deref() == Some(address.as_str()) {
                tokio::time::sleep(FOCUS_SETTLE).await;
            }
        }
        // The waits let reading stop, the book leave the screen or the focus move meanwhile:
        // the focus is checked last, right before the key.
        ok &= self.shown(&address)
            && reading().await
            && self.focused().as_deref() == Some(address.as_str());
        if ok {
            ok = if self.kde.is_some() {
                let key = key.clone();
                tokio::task::spawn_blocking(move || kde::send_key(&key))
                    .await
                    .unwrap_or(false)
            } else {
                tool(&["wtype", "-s", "20", "-k", &key], TOOL_TIMEOUT)
                    .await
                    .is_some()
            };
        }
        if lent {
            // Let the key reach the book before the focus goes back, and only give it back if
            // nothing else took the focus meanwhile and that window is still on screen.
            tokio::time::sleep(Duration::from_millis(80)).await;
            if let Some(previous) = previous
                && self.focused().as_deref() == Some(address.as_str())
                && self.shown(&previous)
            {
                if let Some(kde) = &self.kde {
                    let _ = kde.refresh(Some(&previous)).await;
                } else if let Some(hypr) = &self.hypr {
                    let _ = hypr.activate(&previous).await;
                } else {
                    self.send(Command::Activate(previous));
                }
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
    if let Some(dir) = std::env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(Path::to_path_buf))
    {
        candidates.push(dir.join("maprisma-narrator"));
    }
    candidates.push(home().join(".local/share/maprisma-narrator/settings/maprisma-narrator"));
    let program = candidates
        .into_iter()
        .find(|p| p.is_file())
        .unwrap_or_else(|| "maprisma-narrator".into());
    let _ = std::process::Command::new(program)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
}

/// `maprisma-narrator-desktop --self-test DIR` (KDE): lists the windows through
/// KWin and captures the active window and a screen area through ScreenShot2
/// into DIR/window.png and DIR/area.png, to check the KDE backend and its
/// authorisation (KWin only lets this installed program capture). Sends no keys.
fn self_test(dir: &Path) -> i32 {
    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build().expect("tokio runtime");
    runtime.block_on(async {
        let report = |ok: bool, what: &str| {
            println!("{} {what}", if ok { "ok  " } else { "FAIL" });
            ok
        };
        let Ok(builder) = zbus::connection::Builder::session() else { return 1 };
        let Ok(connection) = builder.build().await else { return 1 };
        let shared: Shared = Arc::new(Mutex::new(Snapshot::default()));
        let Ok(kde) = kde::Kde::new(connection, shared.clone()).await else { return 1 };
        let listed = kde.refresh(None).await.is_ok();
        let active = shared.lock().ok().and_then(|s| s.focused().cloned());
        let mut ok = report(listed && active.is_some(), "windows from KWin (an active window)");
        if let Some(w) = active {
            let picture = kde.capture(Some(&w.address), (w.at.0, w.at.1, w.size.0, w.size.1)).await;
            ok &= report(
                matches!(&picture, Ok((wd, ht, _)) if *wd > 0 && *ht > 0)
                    && picture.as_ref().is_ok_and(|(wd, ht, rgb)| write_png(&dir.join("window.png"), *wd, *ht, rgb).is_ok()),
                &format!("window capture (ScreenShot2): {}", picture.as_ref().err().cloned().unwrap_or_default()),
            );
        }
        let area = kde.capture(None, (0, 0, 400, 300)).await;
        ok &= report(
            area.as_ref().is_ok_and(|(wd, ht, rgb)| write_png(&dir.join("area.png"), *wd, *ht, rgb).is_ok()),
            &format!("area capture (ScreenShot2): {}", area.as_ref().err().cloned().unwrap_or_default()),
        );
        if ok { 0 } else { 1 }
    })
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() == 3 && args[1] == "--self-test" {
        std::process::exit(self_test(Path::new(&args[2])));
    }
    // `--self-test-key KEY`: one key to the focused window through KWin's
    // fake input (checks its authorisation); only by hand, for tests.
    if args.len() == 3 && args[1] == "--self-test-key" {
        let ok = kde::send_key(&args[2]);
        println!("{} key {} (fake input)", if ok { "ok  " } else { "FAIL" }, args[2]);
        std::process::exit(if ok { 0 } else { 1 });
    }
    // Ends with the applet that started it, also when the applet is killed (a panel restart):
    // otherwise an old service would keep running beside the new one.
    unsafe {
        libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM);
    }
    if std::os::unix::process::parent_id() == 1 {
        return;
    }
    let shared: Shared = Arc::new(Mutex::new(Snapshot::default()));
    let (sender, receiver) = wayland::channel();
    let wayland_shared = shared.clone();
    let wayland_thread = std::thread::spawn(move || wayland::run(wayland_shared, receiver));

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("tokio runtime");
    let result: zbus::Result<()> = runtime.block_on(async {
        let mut waited = Duration::ZERO;
        while !shared.lock().map(|s| s.ready).unwrap_or(true)
            && !wayland_thread.is_finished()
            && waited < Duration::from_secs(5)
        {
            tokio::time::sleep(Duration::from_millis(20)).await;
            waited += Duration::from_millis(20);
        }
        let connection = zbus::connection::Builder::session()?.build().await?;
        // A second service ends with NameTaken (zbus would otherwise queue it).
        connection.request_name_with_flags(NAME, zbus::fdo::RequestNameFlags::DoNotQueue.into()).await?;
        let kde = if kde::enabled() {
            Some(kde::Kde::new(connection.clone(), shared.clone()).await?)
        } else {
            None
        };
        if let Some(kde) = &kde {
            let _ = kde.refresh(None).await;
            tokio::spawn(kde.clone().poll());
        }
        let hypr = hypr::enabled().then(|| hypr::Hypr::new(shared.clone()));
        if let Some(hypr) = &hypr {
            if let Err(e) = hypr.refresh().await {
                eprintln!("[Maprisma Narrator] Hyprland: {e}");
            }
            tokio::spawn(hypr.clone().poll());
        }
        let desktop_kde = kde.clone();
        let desktop = Desktop {
            shared,
            kde,
            hypr,
            commands: Mutex::new(sender),
        };
        connection.object_server().at(PATH, desktop).await?;
        // Serves until the Wayland side ends (the session is over) or it is told
        // to stop (its tray or applet ended): then KWin's watcher script goes too.
        let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()).ok();
        while !wayland_thread.is_finished() {
            let stop = async {
                match term.as_mut() {
                    Some(t) => {
                        t.recv().await;
                    }
                    None => std::future::pending::<()>().await,
                }
            };
            tokio::select! {
                _ = tokio::time::sleep(Duration::from_secs(1)) => {}
                _ = stop => {
                    if let Some(kde) = &desktop_kde {
                        kde.stop_watcher().await;
                    }
                    return Ok(());
                }
            }
        }
        if let Ok(Err(error)) = wayland_thread.join() {
            eprintln!("[Maprisma Narrator] Wayland: {error}");
        }
        if let Some(kde) = &desktop_kde {
            kde.stop_watcher().await;
        }
        Ok(())
    });
    match result {
        Err(zbus::Error::NameTaken) => {
            eprintln!("[Maprisma Narrator] the desktop service runs already")
        }
        Err(error) => eprintln!("[Maprisma Narrator] desktop service: {error}"),
        Ok(()) => {}
    }
    let _ = std::io::stderr().flush();
}
