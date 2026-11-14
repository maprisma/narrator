//! Hyprland backend: the window list from Hyprland's IPC socket (the same JSON as
//! `hyprctl clients -j`, which the reader was first written for), kept current by the
//! event socket, and focus through a dispatch. Capture (grim), area selection (slurp)
//! and keys (wtype) work on Hyprland as they are.
use crate::wayland::{Shared, Window};
use serde_json::Value;
use std::{
    path::PathBuf,
    sync::atomic::{AtomicBool, Ordering},
    time::Duration,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    net::UnixStream,
};

pub static ENABLED: AtomicBool = AtomicBool::new(false);
pub fn enabled() -> bool {
    ENABLED.load(Ordering::Acquire)
}
/// A Hyprland session: XDG_CURRENT_DESKTOP names Hyprland, or (only without
/// XDG_CURRENT_DESKTOP) its instance signature is set and its socket is there. A
/// stale signature stays in the systemd user environment after a Hyprland session,
/// and a Hyprland running in another session has a socket too: neither is this one.
pub fn requested() -> bool {
    session(
        &std::env::var("XDG_CURRENT_DESKTOP").unwrap_or_default(),
        || socket_dir().is_some_and(|d| d.join(".socket.sock").exists()),
    )
}

pub fn session(current: &str, socket: impl FnOnce() -> bool) -> bool {
    if current.trim().is_empty() {
        return socket();
    }
    current.split(':').any(|d| d.trim().eq_ignore_ascii_case("hyprland"))
}

fn socket_dir() -> Option<PathBuf> {
    let signature = std::env::var("HYPRLAND_INSTANCE_SIGNATURE").ok()?;
    // Only a plain name: it becomes part of a path.
    if signature.is_empty() || !signature.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return None;
    }
    let runtime = std::env::var_os("XDG_RUNTIME_DIR")?;
    Some(PathBuf::from(runtime).join("hypr").join(signature))
}

/// One request on Hyprland's command socket ("j/clients", "dispatch …").
async fn request(command: &str) -> Result<String, String> {
    let path = socket_dir().ok_or("not a Hyprland session")?.join(".socket.sock");
    let exchange = async {
        let mut stream = UnixStream::connect(&path).await?;
        stream.write_all(command.as_bytes()).await?;
        let mut answer = String::new();
        stream.read_to_string(&mut answer).await?;
        Ok::<_, std::io::Error>(answer)
    };
    tokio::time::timeout(Duration::from_secs(2), exchange)
        .await
        .map_err(|_| format!("Hyprland did not answer {command}"))?
        .map_err(|e| e.to_string())
}

async fn json(command: &str) -> Result<Value, String> {
    serde_json::from_str(&request(command).await?).map_err(|e| format!("{command}: {e}"))
}

fn pair(v: &Value, key: &str) -> Option<(i32, i32)> {
    let a = v.get(key)?.as_array()?;
    Some((a.first()?.as_i64()? as i32, a.get(1)?.as_i64()? as i32))
}

/// The windows from `clients`, `activewindow` and `monitors`. A window is shown when it is
/// mapped, not a hidden tab of a group, and on a workspace (or special workspace) that a
/// monitor shows, or pinned on that monitor.
pub fn windows(clients: &Value, active: &Value, monitors: &Value) -> Vec<Window> {
    let focused = active["address"].as_str().unwrap_or("");
    let mut visible = Vec::new();
    let mut pinned_monitors = Vec::new();
    for m in monitors.as_array().into_iter().flatten() {
        if let Some(id) = m["activeWorkspace"]["id"].as_i64() {
            visible.push(id);
        }
        if let Some(id) = m["specialWorkspace"]["id"].as_i64().filter(|id| *id != 0) {
            visible.push(id);
        }
        if let Some(id) = m["id"].as_i64() {
            pinned_monitors.push(id);
        }
    }
    clients
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|c| {
            let address = c["address"].as_str()?;
            let workspace = c["workspace"]["id"].as_i64().unwrap_or(i64::MIN);
            let on_screen = visible.contains(&workspace)
                || (c["pinned"] == true
                    && c["monitor"].as_i64().is_some_and(|m| pinned_monitors.contains(&m)));
            Some(Window {
                address: address.into(),
                pid: c["pid"].as_i64().filter(|p| *p > 0).map(|p| p as u32),
                title: c["title"].as_str().unwrap_or("").into(),
                class: c["class"].as_str().unwrap_or("").into(),
                at: pair(c, "at")?,
                size: pair(c, "size")?,
                focused: !focused.is_empty() && address == focused,
                shown: c["mapped"] != false && c["hidden"] != true && on_screen,
                capture_id: c["stableId"]
                    .as_str()
                    .filter(|id| !id.is_empty() && id.chars().all(|c| c.is_ascii_alphanumeric()))
                    .map(String::from),
            })
        })
        .collect()
}

#[derive(Clone)]
pub struct Hypr {
    shared: Shared,
}

impl Hypr {
    pub fn new(shared: Shared) -> Self {
        Self { shared }
    }

    pub async fn refresh(&self) -> Result<(), String> {
        let clients = json("j/clients").await?;
        let active = json("j/activewindow").await?;
        let monitors = json("j/monitors").await?;
        let list = windows(&clients, &active, &monitors);
        if let Ok(mut s) = self.shared.lock() {
            s.windows = list;
            s.ready = true;
        }
        Ok(())
    }

    /// Gives a window the focus (it must be on screen; the caller checks).
    pub async fn activate(&self, address: &str) -> Result<(), String> {
        let valid = address.starts_with("0x")
            && address.len() > 2
            && address[2..].chars().all(|c| c.is_ascii_hexdigit());
        if !valid {
            return Err(format!("not a window address: {address}"));
        }
        let answer = request(&format!("dispatch hl.dsp.focus({{ window = \"address:{address}\" }})")).await?;
        if answer.trim() != "ok" {
            return Err(answer.trim().to_string());
        }
        self.refresh().await
    }

    /// Keeps the window list current: every event on the event socket refreshes it (a
    /// burst of events once), and every 10 s a refresh runs anyway as a safety net, also
    /// while the event socket is gone.
    pub async fn poll(self) {
        loop {
            let events = async {
                let path = socket_dir().ok_or("not a Hyprland session")?.join(".socket2.sock");
                let stream = UnixStream::connect(&path).await.map_err(|e| e.to_string())?;
                let mut lines = BufReader::new(stream).lines();
                loop {
                    match tokio::time::timeout(Duration::from_secs(10), lines.next_line()).await {
                        Ok(Ok(Some(_))) => {
                            // Let the rest of a burst (open, focus, move) arrive first, but
                            // at most 100 ms: a window that changes its title all the time
                            // must not hold the refresh back.
                            tokio::time::sleep(Duration::from_millis(30)).await;
                            let until = tokio::time::Instant::now() + Duration::from_millis(100);
                            while tokio::time::Instant::now() < until {
                                match tokio::time::timeout(Duration::from_millis(5), lines.next_line()).await {
                                    Ok(Ok(Some(_))) => {}
                                    _ => break,
                                }
                            }
                        }
                        Ok(Ok(None)) => return Err::<(), String>("event socket closed".into()),
                        Ok(Err(e)) => return Err(e.to_string()),
                        Err(_) => {}
                    }
                    if let Err(e) = self.refresh().await {
                        eprintln!("[Maprisma Narrator] Hyprland: {e}");
                    }
                }
            };
            if let Err(e) = events.await {
                eprintln!("[Maprisma Narrator] Hyprland events: {e}");
            }
            tokio::time::sleep(Duration::from_secs(10)).await;
            let _ = self.refresh().await;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hyprland_only_in_its_own_session() {
        // KDE / COSMIC with a stale signature (or another session's Hyprland): not asked.
        assert!(!session("KDE", || panic!("asked")));
        assert!(!session("COSMIC", || panic!("asked")));
        assert!(session("Hyprland", || false));
        assert!(session("foo:hyprland", || false));
        // No XDG_CURRENT_DESKTOP: only a live socket.
        assert!(session("", || true));
        assert!(!session(" ", || false));
    }
    use serde_json::json;

    #[test]
    fn shown_focused_and_hidden() {
        let monitors = json!([{ "id": 0, "activeWorkspace": { "id": 2 }, "specialWorkspace": { "id": 0 } }]);
        let active = json!({ "address": "0xb" });
        let clients = json!([
            { "address": "0xa", "pid": 10, "title": "Book", "class": "kindle", "at": [0, 30], "size": [800, 600],
              "workspace": { "id": 1 }, "mapped": true, "hidden": false, "pinned": false, "monitor": 0 },
            { "address": "0xb", "pid": 11, "title": "Term", "class": "foot", "at": [10, 40], "size": [400, 300],
              "workspace": { "id": 2 }, "mapped": true, "hidden": false, "pinned": false, "monitor": 0 },
            { "address": "0xc", "pid": 12, "title": "Tab", "class": "foot", "at": [10, 40], "size": [400, 300],
              "workspace": { "id": 2 }, "mapped": true, "hidden": true, "pinned": false, "monitor": 0 },
            { "address": "0xd", "pid": 13, "title": "Pinned", "class": "mpv", "at": [5, 5], "size": [100, 100],
              "workspace": { "id": 1 }, "mapped": true, "hidden": false, "pinned": true, "monitor": 0 }
        ]);
        let w = windows(&clients, &active, &monitors);
        assert_eq!(w.len(), 4);
        assert!(!w[0].shown && !w[0].focused, "other workspace");
        assert!(w[1].shown && w[1].focused);
        assert!(!w[2].shown, "a hidden group tab");
        assert!(w[3].shown, "pinned");
        assert_eq!(w[1].json()["at"], json!([10, 40]));
        assert_eq!(w[0].pid, Some(10));
    }

    #[test]
    fn special_workspace_counts_and_no_active_window() {
        let monitors = json!([{ "id": 0, "activeWorkspace": { "id": 1 }, "specialWorkspace": { "id": -98 } }]);
        let clients = json!([
            { "address": "0xe", "at": [0, 0], "size": [1, 1], "workspace": { "id": -98 }, "mapped": true }
        ]);
        let w = windows(&clients, &json!({}), &monitors);
        assert!(w[0].shown && !w[0].focused);
    }
}
