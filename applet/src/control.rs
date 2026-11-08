use serde_json::{Value, json};
use std::{path::PathBuf, process::Stdio, time::Duration};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
pub fn home() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default()
}

pub fn data_home() -> PathBuf {
    std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| home().join(".local/share"))
}

// SCREEN_NARRATOR_BACKEND (development) or the installed copy.
pub fn bridge_script() -> PathBuf {
    std::env::var_os("SCREEN_NARRATOR_BACKEND")
        .map(PathBuf::from)
        .unwrap_or_else(|| data_home().join("maprisma-narrator/backend"))
        .join("bridge.py")
}

pub fn runtime() -> PathBuf {
    std::env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/run/user/1000"))
        .join("kindle-reader")
}

pub fn sibling(name: &str) -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join(name)))
        .filter(|p| p.is_file())
        .unwrap_or_else(|| name.into())
}

// ------------------------------------------------------------------------- reader

// One request through the bridge (one JSON line in, one out): the reader's full state, or {error}.
pub async fn request(payload: Value) -> Value {
    let run = async {
        let mut child = tokio::process::Command::new("python3")
            .arg(bridge_script())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| e.to_string())?;
        if let Some(mut stdin) = child.stdin.take() {
            stdin
                .write_all(format!("{payload}\n").as_bytes())
                .await
                .map_err(|e| e.to_string())?;
        }
        let out = child.wait_with_output().await.map_err(|e| e.to_string())?;
        let text = String::from_utf8_lossy(&out.stdout);
        serde_json::from_str::<Value>(text.trim().lines().last().unwrap_or("{}"))
            .map_err(|e| e.to_string())
    };
    // Setup and installs return at once (they run on their own); the rest answers quickly.
    match tokio::time::timeout(Duration::from_secs(60), run).await {
        Ok(Ok(state)) => state,
        Ok(Err(error)) => json!({ "error": error }),
        Err(_) => json!({ "error": "The reader did not answer." }),
    }
}

// The light poll ({enabled, paused, status}) straight on the reader's socket, so nothing is
// started while the reader is off. None when the reader does not run.
pub async fn watch() -> Option<Value> {
    let ask = async {
        let mut stream = tokio::net::UnixStream::connect(runtime().join("control.sock"))
            .await
            .ok()?;
        stream.write_all(b"{\"command\": \"watch\"}\n").await.ok()?;
        let mut line = String::new();
        BufReader::new(stream).read_line(&mut line).await.ok()?;
        serde_json::from_str(&line).ok()
    };
    tokio::time::timeout(Duration::from_secs(2), ask)
        .await
        .ok()
        .flatten()
}

pub fn flag(state: &Value, key: &str) -> bool {
    state.get(key).and_then(Value::as_bool) == Some(true)
}

pub fn string<'a>(state: &'a Value, key: &str) -> &'a str {
    state.get(key).and_then(Value::as_str).unwrap_or("")
}

pub struct Step {
    pub text: String,
    pub label: String,
    pub payload: Option<Value>,
}

// The first thing standing in the way of reading, with the one button that does it.
pub fn next_step(state: &Value) -> Option<Step> {
    let settings = state.get("settings").unwrap_or(&Value::Null);
    let language = settings
        .get("language")
        .and_then(Value::as_str)
        .unwrap_or("en");
    let phase = string(state, "setup_phase");
    if flag(state, "setup_busy") {
        let text = Some(string(state, "setup_message"))
            .filter(|m| !m.is_empty())
            .unwrap_or("Setting up…");
        return Some(Step {
            text: text.into(),
            label: if phase == "packages" {
                String::new()
            } else {
                "Cancel".into()
            },
            payload: Some(json!({ "command": "cancel-setup" })),
        });
    }
    let missing: Vec<&str> = state
        .get("missing_packages")
        .and_then(Value::as_array)
        .map(|a| a.iter().filter_map(Value::as_str).collect())
        .unwrap_or_default();
    if state.get("backend_ready").and_then(Value::as_bool) == Some(false) || !missing.is_empty() {
        let payload = Some(json!({ "command": "setup", "language": language }));
        if phase == "error" || phase == "cancelled" {
            return Some(Step {
                text: string(state, "setup_message").into(),
                label: "Retry setup".into(),
                payload,
            });
        }
        let extra = if missing.is_empty() {
            String::new()
        } else {
            format!(" It installs {}.", missing.join(", "))
        };
        return Some(Step {
            text: format!(
                "Maprisma Narrator needs its reader, a voice and text recognition.{extra}"
            ),
            label: "Set up automatically".into(),
            payload,
        });
    }
    let failed = state
        .get("checks")
        .and_then(Value::as_array)
        .and_then(|checks| {
            checks
                .iter()
                .find(|c| c.get("ok").and_then(Value::as_bool) != Some(true))
        })?;
    if flag(state, "enabled") {
        return None;
    }
    let problem = string(failed, "problem").to_string();
    let fix = failed
        .get("fixes")
        .and_then(Value::as_array)
        .and_then(|fixes| {
            fixes
                .iter()
                .find(|f| f.get("command").is_some() || f.get("settings").is_some())
        });
    let Some(fix) = fix else {
        return Some(Step {
            text: problem,
            label: "Settings…".into(),
            payload: None,
        });
    };
    let payload = match fix.get("command").and_then(Value::as_str) {
        Some(command) => {
            let mut payload = json!({ "command": command });
            if let (Some(map), Some(args)) = (
                payload.as_object_mut(),
                fix.get("args").and_then(Value::as_object),
            ) {
                map.extend(args.clone());
            }
            payload
        }
        None => {
            json!({ "command": "configure", "settings": fix.get("settings").cloned().unwrap_or(Value::Null) })
        }
    };
    Some(Step {
        text: problem,
        label: string(fix, "label").into(),
        payload: Some(payload),
    })
}

pub async fn run_desktop_service() {
    loop {
        let child = tokio::process::Command::new(sibling("maprisma-narrator-desktop"))
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .spawn();
        if let Ok(mut child) = child {
            let _ = child.wait().await;
        }
        tokio::time::sleep(Duration::from_secs(5)).await;
    }
}
