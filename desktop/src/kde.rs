//! KWin scripting, ScreenShot2 and restricted fake-input backend.
use crate::wayland::{Shared, Window};
use serde_json::Value;
use std::{
    collections::HashMap,
    io::Write,
    os::{
        fd::{FromRawFd, OwnedFd},
        unix::fs::OpenOptionsExt,
    },
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::Duration,
};
use zbus::{
    Connection, interface,
    zvariant::{Fd, OwnedValue},
};
pub static ENABLED: AtomicBool = AtomicBool::new(false);
pub fn enabled() -> bool {
    ENABLED.load(Ordering::Acquire)
}
pub fn requested() -> bool {
    std::env::var("XDG_CURRENT_DESKTOP")
        .unwrap_or_default()
        .split(':')
        .any(|s| s.eq_ignore_ascii_case("KDE"))
}
static SEQUENCE: AtomicU64 = AtomicU64::new(0);
const CALLBACK: &str = "/com/maprisma/Narrator/KWin";
/// The one long-lived KWin script that reports window changes (a fixed name,
/// so a helper that starts again replaces the script of an earlier one).
const WATCHER: &str = "maprisma_narrator_watch";

/// KWin script code: `here(w)` is whether a window can be seen now (not
/// minimised, on the current virtual desktop and in the current Activity; an
/// empty `activities` list means all of them), `rows()` is every normal window
/// as the reader's JSON, `send()` hands it to this helper (its unique bus name
/// in [service]).
fn rows_js(service: &str) -> String {
    format!(
        r#"function here(w) {{
  return !w.minimized && (w.onAllDesktops || w.desktops.indexOf(workspace.currentDesktop)>=0)
    && (!w.activities || w.activities.length === 0 || w.activities.indexOf(workspace.currentActivity)>=0);
}}
function rows() {{
  return workspace.windowList().filter(function(w) {{ return w.normalWindow; }}).map(function(w) {{
    var g = w.frameGeometry;
    return {{address:String(w.internalId),pid:w.pid,title:w.caption,class:String(w.resourceClass || w.desktopFileName),
      at:[Math.round(g.x),Math.round(g.y)],size:[Math.round(g.width),Math.round(g.height)],
      focused:w===workspace.activeWindow,
      shown:here(w)}};
  }});
}}
function send() {{ callDBus({service}, "{CALLBACK}", "com.maprisma.Narrator.KWin", "State", JSON.stringify(rows())); }}
"#,
        service = serde_json::to_string(service).unwrap()
    )
}
#[derive(Clone)]
pub struct Kde {
    pub connection: Connection,
    serial: Arc<tokio::sync::Mutex<()>>,
    replies: Arc<AtomicU64>,
}
struct Callback {
    shared: Shared,
    replies: Arc<AtomicU64>,
}
#[interface(name = "com.maprisma.Narrator.KWin")]
impl Callback {
    async fn state(
        &self,
        text: &str,
        #[zbus(connection)] c: &Connection,
        #[zbus(header)] h: zbus::message::Header<'_>,
    ) {
        let Ok(dbus) = zbus::fdo::DBusProxy::new(c).await else {
            return;
        };
        let Ok(owner) = dbus
            .get_name_owner("org.kde.KWin".try_into().unwrap())
            .await
        else {
            return;
        };
        if h.sender().map(|s| s.as_str()) != Some(owner.as_str()) {
            return;
        }
        if let Ok(Value::Array(rows)) = serde_json::from_str(text) {
            let windows = rows.iter().filter_map(window).collect();
            if let Ok(mut s) = self.shared.lock() {
                s.windows = windows;
                s.ready = true;
                self.replies.fetch_add(1, Ordering::Release);
            }
        }
    }
}
/// A spawned task that is aborted when this goes out of scope.
struct AbortOnDrop<T>(tokio::task::JoinHandle<T>);
impl<T> Drop for AbortOnDrop<T> {
    fn drop(&mut self) {
        self.0.abort();
    }
}

pub fn window(v: &Value) -> Option<Window> {
    let pair = |key| {
        let a = v.get(key)?.as_array()?;
        Some((a.first()?.as_i64()? as i32, a.get(1)?.as_i64()? as i32))
    };
    Some(Window {
        address: v["address"].as_str()?.into(),
        pid: Some(v["pid"].as_u64().unwrap_or(0) as u32),
        title: v["title"].as_str().unwrap_or("").into(),
        class: v["class"].as_str().unwrap_or("").into(),
        at: pair("at")?,
        size: pair("size")?,
        focused: v["focused"] == true,
        shown: v["shown"] == true,
    })
}
impl Kde {
    pub async fn new(connection: Connection, shared: Shared) -> zbus::Result<Self> {
        let replies = Arc::new(AtomicU64::new(0));
        connection
            .object_server()
            .at(
                CALLBACK,
                Callback {
                    shared: shared.clone(),
                    replies: replies.clone(),
                },
            )
            .await?;
        Ok(Self {
            connection,
            replies,
            serial: Arc::new(tokio::sync::Mutex::new(())),
        })
    }
    pub async fn refresh(&self, activate: Option<&str>) -> Result<(), String> {
        let _guard = self.serial.lock().await;
        let name = format!(
            "maprisma_narrator_{}_{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        );
        let path = crate::wayland::runtime_dir().join(format!("{name}.js"));
        std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
        let target = serde_json::to_string(&activate).unwrap();
        let source = format!(
            r#"{rows}var target = {target};
if (target) workspace.windowList().forEach(function(w) {{ if (w.normalWindow && String(w.internalId) === target && here(w)) workspace.activeWindow = w; }});
send();"#,
            rows = rows_js(self.connection.unique_name().unwrap().as_str())
        );
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .map_err(|e| e.to_string())?;
        file.write_all(source.as_bytes())
            .map_err(|e| e.to_string())?;
        let before = self.replies.load(Ordering::Acquire);
        let work = async {
            let p = zbus::Proxy::new(
                &self.connection,
                "org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting",
            )
            .await?;
            let id: i32 = p
                .call(
                    "loadScript",
                    &(path.to_string_lossy().as_ref(), name.as_str()),
                )
                .await?;
            if id < 0 {
                return Err(zbus::Error::Failure("KWin refused script".into()));
            }
            let script_path = format!("/Scripting/Script{id}");
            let s = zbus::Proxy::new(
                &self.connection,
                "org.kde.KWin",
                script_path.as_str(),
                "org.kde.kwin.Script",
            )
            .await?;
            s.call::<_, _, ()>("run", &()).await?;
            // callDBus is asynchronous; allow its callback to arrive before unloading.
            while self.replies.load(Ordering::Acquire) == before {
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
            Ok::<(), zbus::Error>(())
        };
        let result = tokio::time::timeout(Duration::from_secs(2), work)
            .await
            .map_err(|e| e.to_string())
            .and_then(|r| r.map_err(|e| e.to_string()));
        if let Ok(p) = zbus::Proxy::new(
            &self.connection,
            "org.kde.KWin",
            "/Scripting",
            "org.kde.kwin.Scripting",
        )
        .await
        {
            let _ = tokio::time::timeout(
                Duration::from_secs(1),
                p.call::<_, _, bool>("unloadScript", &(name.as_str(),)),
            )
            .await;
        }
        let _ = std::fs::remove_file(path);
        result
    }
    /// Keeps the window list current: the watcher script reports every change
    /// as it happens (no polling in KWin); every 10 s a check reloads it when it
    /// is gone (KWin restarted) and refreshes once, as a safety net.
    pub async fn poll(self) {
        // A watcher an earlier helper left (crash, SIGKILL) reports to that
        // helper's bus name: replaced at once, whatever is loaded.
        if let Err(e) = self.start_watcher().await {
            eprintln!("[Maprisma Narrator] KWin watcher: {e}");
        }
        loop {
            tokio::time::sleep(Duration::from_secs(10)).await;
            if !self.watcher_loaded().await {
                if let Err(e) = self.start_watcher().await {
                    eprintln!("[Maprisma Narrator] KWin watcher: {e}");
                }
            }
            if let Err(e) = self.refresh(None).await {
                eprintln!("[Maprisma Narrator] KWin: {e}");
            }
        }
    }

    async fn scripting(&self) -> zbus::Result<zbus::Proxy<'static>> {
        zbus::Proxy::new(&self.connection, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting").await
    }

    async fn watcher_loaded(&self) -> bool {
        match self.scripting().await {
            Ok(p) => p.call::<_, _, bool>("isScriptLoaded", &(WATCHER,)).await.unwrap_or(false),
            Err(_) => false,
        }
    }

    /// Loads the watcher (replacing one an earlier helper left behind).
    async fn start_watcher(&self) -> Result<(), String> {
        let _guard = self.serial.lock().await;
        let p = self.scripting().await.map_err(|e| e.to_string())?;
        let _ = p.call::<_, _, bool>("unloadScript", &(WATCHER,)).await;
        let path = crate::wayland::runtime_dir().join(format!("{WATCHER}_{}.js", std::process::id()));
        std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
        let source = format!(
            r#"{rows}function hook(w) {{
  ["frameGeometryChanged", "captionChanged", "minimizedChanged", "desktopsChanged", "activitiesChanged"].forEach(function(n) {{ if (w[n]) w[n].connect(send); }});
}}
workspace.windowList().forEach(hook);
workspace.windowAdded.connect(function(w) {{ hook(w); send(); }});
workspace.windowRemoved.connect(send);
workspace.windowActivated.connect(send);
workspace.currentDesktopChanged.connect(send);
if (workspace.currentActivityChanged) workspace.currentActivityChanged.connect(send);
send();"#,
            rows = rows_js(self.connection.unique_name().unwrap().as_str())
        );
        let _ = std::fs::remove_file(&path);
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .map_err(|e| e.to_string())?;
        file.write_all(source.as_bytes()).map_err(|e| e.to_string())?;
        let result = async {
            let id: i32 = p.call("loadScript", &(path.to_string_lossy().as_ref(), WATCHER)).await?;
            if id < 0 {
                return Err(zbus::Error::Failure("KWin refused the watcher script".into()));
            }
            let script_path = format!("/Scripting/Script{id}");
            let s = zbus::Proxy::new(&self.connection, "org.kde.KWin", script_path.as_str(), "org.kde.kwin.Script").await?;
            s.call::<_, _, ()>("run", &()).await
        }
        .await
        .map_err(|e| e.to_string());
        let _ = std::fs::remove_file(path);
        result
    }

    /// Unloads the watcher (the helper ends).
    pub async fn stop_watcher(&self) {
        if let Ok(p) = self.scripting().await {
            let _ = tokio::time::timeout(Duration::from_secs(1), p.call::<_, _, bool>("unloadScript", &(WATCHER,))).await;
        }
    }
    pub async fn capture(
        &self,
        address: Option<&str>,
        area: (i32, i32, i32, i32),
    ) -> Result<(usize, usize, Vec<u8>), String> {
        let mut fds = [0; 2];
        if unsafe { libc::pipe2(fds.as_mut_ptr(), libc::O_CLOEXEC) } != 0 {
            return Err(std::io::Error::last_os_error().to_string());
        }
        let read = unsafe { OwnedFd::from_raw_fd(fds[0]) };
        let write = unsafe { OwnedFd::from_raw_fd(fds[1]) };
        // An async read (no blocking thread): when the capture gives up early
        // (timeout, error) the guard aborts it and closes the read end, even if
        // KWin still holds its write end.
        let receiver = tokio::net::unix::pipe::Receiver::from_owned_fd(read).map_err(|e| e.to_string())?;
        let mut reader = AbortOnDrop(tokio::spawn(async move {
            use tokio::io::AsyncReadExt;
            let mut bytes = Vec::new();
            receiver
                .take(512 * 1024 * 1024)
                .read_to_end(&mut bytes)
                .await
                .map(|_| bytes)
        }));
        let p = zbus::Proxy::new(
            &self.connection,
            "org.kde.KWin",
            "/org/kde/KWin/ScreenShot2",
            "org.kde.KWin.ScreenShot2",
        )
        .await
        .map_err(|e| e.to_string())?;
        let options: HashMap<&str, OwnedValue> = HashMap::from([
            ("include-decoration", OwnedValue::from(true)),
            ("include-shadow", OwnedValue::from(false)),
            // Full pixels on scaled screens (OCR reads them better).
            ("native-resolution", OwnedValue::from(true)),
        ]);
        let reply = tokio::time::timeout(Duration::from_secs(3), async {
            let result: zbus::Result<HashMap<String, OwnedValue>> = if let Some(id) = address {
                p.call("CaptureWindow", &(id, options, Fd::from(&write)))
                    .await
            } else {
                p.call(
                    "CaptureArea",
                    &(
                        area.0,
                        area.1,
                        area.2 as u32,
                        area.3 as u32,
                        options,
                        Fd::from(&write),
                    ),
                )
                .await
            };
            result
        })
        .await;
        drop(write);
        let meta = reply
            .map_err(|e| e.to_string())?
            .map_err(|e| e.to_string())?;
        let bytes = tokio::time::timeout(Duration::from_secs(3), &mut reader.0)
            .await
            .map_err(|e| e.to_string())?
            .map_err(|e| e.to_string())?
            .map_err(|e| e.to_string())?;
        let n = |k| {
            meta.get(k)
                .and_then(|v| u32::try_from(v).ok())
                .ok_or_else(|| format!("missing screenshot {k}"))
        };
        let (w, h, stride, format) = (
            n("width")? as usize,
            n("height")? as usize,
            n("stride")? as usize,
            n("format")?,
        );
        Ok((w, h, raw_rgb(w, h, stride, format, &bytes)?))
    }
}
// QImage::Format_RGB32/ARGB32/Premultiplied and RGB888/RGBA8888 variants.
pub fn raw_rgb(
    w: usize,
    h: usize,
    stride: usize,
    format: u32,
    bytes: &[u8],
) -> Result<Vec<u8>, String> {
    let bpp = match format {
        4 | 5 | 6 | 16 | 17 | 18 => 4,
        13 => 3,
        _ => return Err(format!("unsupported QImage format {format}")),
    };
    let row = w.checked_mul(bpp).ok_or("image overflow")?;
    if w == 0 || h == 0 || stride < row || h.checked_mul(stride).is_none_or(|n| n > bytes.len()) {
        return Err("invalid screenshot dimensions".into());
    }
    let mut rgb = Vec::with_capacity(w * h * 3);
    for y in 0..h {
        for px in bytes[y * stride..y * stride + row].chunks_exact(bpp) {
            let (r, g, b) = if matches!(format, 4 | 5 | 6) {
                if cfg!(target_endian = "little") {
                    (px[2], px[1], px[0])
                } else {
                    (px[1], px[2], px[3])
                }
            } else {
                (px[0], px[1], px[2])
            };
            let (r, g, b) = if matches!(format, 6 | 18) {
                let a = if format == 6 && cfg!(target_endian = "big") {
                    px[0]
                } else {
                    px[3]
                };
                let straight = |v: u8| {
                    if a == 0 {
                        0
                    } else {
                        ((v as u32 * 255 + a as u32 / 2) / a as u32).min(255) as u8
                    }
                };
                (straight(r), straight(g), straight(b))
            } else {
                (r, g, b)
            };
            rgb.extend_from_slice(&[r, g, b]);
        }
    }
    Ok(rgb)
}
pub fn evdev(key: &str) -> Option<u32> {
    Some(match key {
        "Right" => 106,
        "Left" => 105,
        "Next" | "Page_Down" => 109,
        "Prior" | "Page_Up" => 104,
        "space" => 57,
        "Return" => 28,
        "Up" => 103,
        "Down" => 108,
        "Home" => 102,
        "End" => 107,
        "Escape" => 1,
        "n" => 49,
        "p" => 25,
        "b" => 48,
        _ => return None,
    })
}

pub fn send_key(key: &str) -> bool {
    use cosmic_client_toolkit::wayland_client::{
        Connection, Dispatch, QueueHandle, globals::registry_queue_init,
    };
    use wayland_protocols_plasma::fake_input::client::org_kde_kwin_fake_input::OrgKdeKwinFakeInput;
    struct Input;
    impl Dispatch<OrgKdeKwinFakeInput, ()> for Input {
        fn event(
            _: &mut Self,
            _: &OrgKdeKwinFakeInput,
            _: wayland_protocols_plasma::fake_input::client::org_kde_kwin_fake_input::Event,
            _: &(),
            _: &Connection,
            _: &QueueHandle<Self>,
        ) {
        }
    }
    impl
        Dispatch<
            cosmic_client_toolkit::wayland_client::protocol::wl_registry::WlRegistry,
            cosmic_client_toolkit::wayland_client::globals::GlobalListContents,
        > for Input
    {
        fn event(
            _: &mut Self,
            _: &cosmic_client_toolkit::wayland_client::protocol::wl_registry::WlRegistry,
            _: cosmic_client_toolkit::wayland_client::protocol::wl_registry::Event,
            _: &cosmic_client_toolkit::wayland_client::globals::GlobalListContents,
            _: &Connection,
            _: &QueueHandle<Self>,
        ) {
        }
    }
    let Some(code) = evdev(key) else { return false };
    let run = || -> Result<(), Box<dyn std::error::Error>> {
        let c = Connection::connect_to_env()?;
        let (g, mut q) = registry_queue_init::<Input>(&c)?;
        let input: OrgKdeKwinFakeInput = g.bind(&q.handle(), 4..=5, ())?;
        input.authenticate("Maprisma Narrator".into(), "Turn the reading page".into());
        q.roundtrip(&mut Input)?;
        input.keyboard_key(code, 1);
        c.flush()?;
        std::thread::sleep(Duration::from_millis(20));
        input.keyboard_key(code, 0);
        q.roundtrip(&mut Input)?;
        Ok(())
    };
    run().is_ok()
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn mapping() {
        let v = json!({"address":"{uuid}","pid":42,"title":"Book","class":"reader","at":[-20,4],"size":[800,600],"focused":true,"shown":false});
        assert_eq!(window(&v).unwrap().json(), v);
    }
    #[test]
    fn shown_means_this_desktop_and_activity() {
        let js = rows_js(":1.5");
        assert!(js.contains("w.activities.indexOf(workspace.currentActivity)"));
        assert!(js.contains("shown:here(w)"));
        assert!(js.contains("callDBus(\":1.5\""));
    }
    #[test]
    fn keys() {
        assert_eq!(evdev("Next"), evdev("Page_Down"));
        assert_eq!(evdev("Prior"), Some(104));
        assert_eq!(evdev("space"), Some(57));
        assert_eq!(evdev("bad"), None);
    }
    #[test]
    fn pixels() {
        assert_eq!(
            raw_rgb(
                1,
                2,
                8,
                4,
                &[3, 2, 1, 255, 0, 0, 0, 0, 6, 5, 4, 255, 0, 0, 0, 0]
            )
            .unwrap(),
            [1, 2, 3, 4, 5, 6]
        );
        assert!(raw_rgb(2, 2, 4, 4, &[0; 8]).is_err());
        assert_eq!(raw_rgb(1, 1, 4, 17, &[1, 2, 3, 255]).unwrap(), [1, 2, 3]);
    }
}
