//! KDE StatusNotifierItem; Activate toggles reading, secondary menu uses DBusMenu.
#[path = "../../applet/src/control.rs"]
mod control;
use serde_json::{Value, json};
use std::{collections::HashMap, sync::Arc, time::Duration};
use tokio::sync::{Mutex, mpsc};
use zbus::{
    Connection, interface,
    object_server::SignalEmitter,
    zvariant::{OwnedObjectPath, OwnedValue, Structure, Value as Variant},
};
const NAME: &str = "com.maprisma.Narrator.Tray";
const ITEM: &str = "/StatusNotifierItem";
const MENU: &str = "/MenuBar";
type Props = HashMap<String, OwnedValue>;
#[derive(Clone, Debug, PartialEq)]
struct Entry {
    id: i32,
    label: String,
    enabled: bool,
    action: Option<Value>,
}
fn model(s: &Value) -> Vec<Entry> {
    let enabled = control::flag(s, "enabled");
    let paused = control::flag(s, "paused");
    let ready = !control::flag(s, "setup_busy")
        && s.get("backend_ready")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        && s.get("missing_packages")
            .and_then(Value::as_array)
            .is_none_or(|a| a.is_empty());
    let mut rows = vec![
        (
            1,
            "Start".into(),
            ready && !enabled,
            Some(json!({"command":"on"})),
        ),
        (
            2,
            if paused { "Resume" } else { "Pause" }.into(),
            enabled,
            Some(json!({"command":"pause"})),
        ),
        (3, "Stop".into(), enabled, Some(json!({"command":"off"}))),
        (
            4,
            s.get("status")
                .and_then(Value::as_str)
                .unwrap_or("Reader unavailable")
                .into(),
            false,
            None,
        ),
        (
            5,
            "Read the active window".into(),
            enabled,
            Some(json!({"command":"read"})),
        ),
        (
            6,
            "Select reading area…".into(),
            ready,
            Some(json!({"command":"select-area"})),
        ),
        (
            7,
            "Reset reading area".into(),
            ready,
            Some(json!({"command":"clear-area"})),
        ),
    ];
    if let Some(step) = control::next_step(s) {
        rows.push((
            8,
            format!("{}: {}", step.label, step.text),
            !step.label.is_empty(),
            step.payload,
        ));
    }
    let speed = s["settings"]["speed"].as_f64().unwrap_or(1.0);
    for (i, v) in [0.6, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0].iter().enumerate() {
        rows.push((
            20 + i as i32,
            format!(
                "Reading speed {v:.2}×{}",
                if (speed - v).abs() < 0.01 { " ✓" } else { "" }
            ),
            true,
            Some(json!({"command":"configure","settings":{"speed":v}})),
        ));
    }
    rows.push((9, "Settings…".into(), true, None));
    rows.into_iter()
        .map(|(id, label, enabled, action)| Entry {
            id,
            label,
            enabled,
            action,
        })
        .collect()
}
fn props(e: &Entry) -> Props {
    HashMap::from([
        (
            "label".into(),
            OwnedValue::from(zbus::zvariant::Str::from(e.label.as_str())),
        ),
        ("enabled".into(), OwnedValue::from(e.enabled)),
        ("visible".into(), OwnedValue::from(true)),
    ])
}
#[derive(Clone)]
struct State {
    value: Arc<Mutex<Value>>,
    tx: mpsc::UnboundedSender<Value>,
}
struct Item(State);
type Pixmaps = Vec<(i32, i32, Vec<u8>)>;
#[interface(name = "org.kde.StatusNotifierItem")]
impl Item {
    fn activate(&self, _x: i32, _y: i32) {
        let _ = self.0.tx.send(json!({"command":"toggle"}));
    }
    fn secondary_activate(&self, _x: i32, _y: i32) {
        let _ = self.0.tx.send(json!({"command":"pause"}));
    }
    fn context_menu(&self, _x: i32, _y: i32) {}
    fn scroll(&self, _delta: i32, _orientation: &str) {}
    #[zbus(property)]
    fn category(&self) -> &str {
        "ApplicationStatus"
    }
    #[zbus(property)]
    fn id(&self) -> &str {
        NAME
    }
    #[zbus(property)]
    fn title(&self) -> &str {
        "Maprisma Narrator"
    }
    #[zbus(property)]
    async fn status(&self) -> String {
        if control::flag(&*self.0.value.lock().await, "enabled") {
            "NeedsAttention"
        } else {
            "Active"
        }
        .into()
    }
    #[zbus(property)]
    async fn icon_name(&self) -> String {
        let s = self.0.value.lock().await;
        if control::flag(&s, "paused") {
            "media-playback-pause"
        } else if control::flag(&s, "enabled") {
            "media-playback-start"
        } else {
            "audio-headphones"
        }
        .into()
    }
    #[zbus(property)]
    async fn attention_icon_name(&self) -> String {
        self.icon_name().await
    }
    #[zbus(property)]
    fn icon_pixmap(&self) -> Pixmaps {
        vec![]
    }
    #[zbus(property)]
    fn attention_icon_pixmap(&self) -> Pixmaps {
        vec![]
    }
    #[zbus(property)]
    fn overlay_icon_name(&self) -> &str {
        ""
    }
    #[zbus(property)]
    fn overlay_icon_pixmap(&self) -> Pixmaps {
        vec![]
    }
    #[zbus(property)]
    fn icon_theme_path(&self) -> &str {
        ""
    }
    #[zbus(property)]
    fn item_is_menu(&self) -> bool {
        false
    }
    #[zbus(property)]
    fn menu(&self) -> OwnedObjectPath {
        MENU.try_into().unwrap()
    }
    #[zbus(property)]
    async fn tool_tip(&self) -> (String, Pixmaps, String, String) {
        let s = self.0.value.lock().await;
        (
            "audio-headphones".into(),
            vec![],
            "Maprisma Narrator".into(),
            s["status"].as_str().unwrap_or("Reader unavailable").into(),
        )
    }
    #[zbus(signal)]
    async fn new_icon(e: &SignalEmitter<'_>) -> zbus::Result<()>;
    #[zbus(signal)]
    async fn new_attention_icon(e: &SignalEmitter<'_>) -> zbus::Result<()>;
    #[zbus(signal)]
    async fn new_tool_tip(e: &SignalEmitter<'_>) -> zbus::Result<()>;
    #[zbus(signal)]
    async fn new_status(e: &SignalEmitter<'_>, status: &str) -> zbus::Result<()>;
}
struct Menu {
    state: State,
    revision: Arc<std::sync::atomic::AtomicU32>,
}
impl Menu {
    async fn click(&self, id: i32, event: &str) {
        if event != "clicked" {
            return;
        }
        let rows = model(&*self.state.value.lock().await);
        if let Some(e) = rows.into_iter().find(|e| e.id == id && e.enabled) {
            if let Some(a) = e.action {
                let _ = self.state.tx.send(a);
            } else {
                let _ = std::process::Command::new(control::sibling("maprisma-narrator")).spawn();
            }
        }
    }
}
#[interface(name = "com.canonical.dbusmenu")]
impl Menu {
    #[zbus(property)]
    fn version(&self) -> u32 {
        3
    }
    #[zbus(property)]
    fn text_direction(&self) -> &str {
        "ltr"
    }
    #[zbus(property)]
    fn status(&self) -> &str {
        "normal"
    }
    #[zbus(property)]
    fn icon_theme_path(&self) -> Vec<String> {
        vec![]
    }
    async fn get_layout(
        &self,
        parent_id: i32,
        recursion_depth: i32,
        property_names: Vec<String>,
    ) -> (u32, (i32, Props, Vec<OwnedValue>)) {
        let rows = model(&*self.state.value.lock().await);
        let filter = |mut p: Props| {
            if !property_names.is_empty() {
                p.retain(|k, _| property_names.contains(k));
            }
            p
        };
        let children = if parent_id == 0 && recursion_depth != 0 {
            rows.iter()
                .map(|e| {
                    let structure =
                        Structure::from((e.id, filter(props(e)), Vec::<OwnedValue>::new()));
                    OwnedValue::try_from(Variant::from(structure)).unwrap()
                })
                .collect()
        } else {
            vec![]
        };
        let p = rows
            .iter()
            .find(|e| e.id == parent_id)
            .map(|e| filter(props(e)))
            .unwrap_or_default();
        (
            self.revision.load(std::sync::atomic::Ordering::Relaxed),
            (parent_id, p, children),
        )
    }
    async fn get_group_properties(&self, ids: Vec<i32>, names: Vec<String>) -> Vec<(i32, Props)> {
        model(&*self.state.value.lock().await)
            .iter()
            .filter(|e| ids.is_empty() || ids.contains(&e.id))
            .map(|e| {
                let mut p = props(e);
                if !names.is_empty() {
                    p.retain(|k, _| names.contains(k));
                }
                (e.id, p)
            })
            .collect()
    }
    async fn get_property(&self, id: i32, name: &str) -> zbus::fdo::Result<OwnedValue> {
        model(&*self.state.value.lock().await)
            .iter()
            .find(|e| e.id == id)
            .and_then(|e| props(e).remove(name))
            .ok_or_else(|| zbus::fdo::Error::InvalidArgs("Unknown menu property".into()))
    }
    async fn event(&self, id: i32, event_id: &str, _data: OwnedValue, _timestamp: u32) {
        self.click(id, event_id).await;
    }
    async fn event_group(&self, events: Vec<(i32, String, OwnedValue, u32)>) -> Vec<i32> {
        let mut errors = vec![];
        for (id, event, _, _) in events {
            if model(&*self.state.value.lock().await)
                .iter()
                .any(|e| e.id == id)
            {
                self.click(id, &event).await;
            } else {
                errors.push(id)
            }
        }
        errors
    }
    async fn about_to_show(&self, _id: i32) -> bool {
        let _ = self.state.tx.send(json!({"command":"status"}));
        false
    }
    async fn about_to_show_group(&self, _ids: Vec<i32>) -> (Vec<i32>, Vec<i32>) {
        let _ = self.state.tx.send(json!({"command":"status"}));
        (vec![], vec![])
    }
    #[zbus(signal)]
    async fn layout_updated(e: &SignalEmitter<'_>, revision: u32, parent: i32) -> zbus::Result<()>;
}
async fn update(c: &Connection, state: &State, rev: &std::sync::atomic::AtomicU32, next: Value) {
    let mut old = state.value.lock().await;
    if *old == next {
        return;
    }
    *old = next;
    let status = if control::flag(&old, "enabled") {
        "NeedsAttention"
    } else {
        "Active"
    };
    drop(old);
    let e = SignalEmitter::new(c, ITEM).unwrap();
    let _ = Item::new_icon(&e).await;
    let _ = Item::new_attention_icon(&e).await;
    let _ = Item::new_tool_tip(&e).await;
    let _ = Item::new_status(&e, status).await;
    let e = SignalEmitter::new(c, MENU).unwrap();
    let r = rev.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
    let _ = Menu::layout_updated(&e, r, 0).await;
}
#[tokio::main(flavor = "current_thread")]
async fn main() -> zbus::Result<()> {
    let (tx, mut rx) = mpsc::unbounded_channel();
    let state = State {
        value: Arc::new(Mutex::new(json!({}))),
        tx,
    };
    let rev = Arc::new(std::sync::atomic::AtomicU32::new(1));
    let c = match zbus::connection::Builder::session()?
        .serve_at(ITEM, Item(state.clone()))?
        .serve_at(
            MENU,
            Menu {
                state: state.clone(),
                revision: rev.clone(),
            },
        )?
        .build()
        .await
    {
        Ok(c) => c,
        Err(e) => return Err(e),
    };
    // One tray per session: a second one ends here (zbus would otherwise
    // queue the name request and keep running, with a second helper).
    match c.request_name_with_flags(NAME, zbus::fdo::RequestNameFlags::DoNotQueue.into()).await {
        Ok(_) => {}
        Err(zbus::Error::NameTaken) => return Ok(()),
        Err(e) => return Err(e),
    }
    tokio::spawn(control::run_desktop_service());
    let bus = zbus::fdo::DBusProxy::new(&c).await?;
    let mut owner = String::new();
    let mut timer = tokio::time::interval(Duration::from_secs(1));
    loop {
        tokio::select! {
        Some(payload)=rx.recv()=>{let next=control::request(payload).await;if let Some(e)=next["error"].as_str(){eprintln!("[Maprisma Narrator] {e}");}else{update(&c,&state,&rev,next).await;}},
        _=timer.tick()=>{
        let current=bus.get_name_owner("org.kde.StatusNotifierWatcher".try_into().unwrap()).await.map(|s|s.to_string()).unwrap_or_default();
        if current!=owner {owner.clear();if !current.is_empty(){if let Ok(p)=zbus::Proxy::new(&c,"org.kde.StatusNotifierWatcher","/StatusNotifierWatcher","org.kde.StatusNotifierWatcher").await {if p.call::<_,_,()>("RegisterStatusNotifierItem",&(c.unique_name().unwrap().as_str(),)).await.is_ok(){owner=current;}}}}
        // While setup runs, the full status every tick (its progress, readiness
        // and errors), as the COSMIC applet does while its popup is open.
        if control::flag(&*state.value.lock().await, "setup_busy") {let _ = state.tx.send(json!({"command":"status"}));}
        else if let Some(next)=control::watch().await {let mut merged=state.value.lock().await.clone();if let(Some(a),Some(b))=(merged.as_object_mut(),next.as_object()){a.extend(b.clone());}update(&c,&state,&rev,merged).await;}
        }
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn menu_actions() {
        let rows = model(
            &json!({"enabled":true,"paused":true,"backend_ready":true,"settings":{"speed":1.25}}),
        );
        assert_eq!(rows.iter().find(|e| e.id == 2).unwrap().label, "Resume");
        assert!(!rows[0].enabled);
        assert_eq!(
            rows.iter().find(|e| e.id == 5).unwrap().action,
            Some(json!({"command":"read"}))
        );
        assert_eq!(
            rows.iter()
                .filter(|e| e.label.starts_with("Reading speed"))
                .count(),
            7
        );
        assert_eq!(rows.iter().filter(|e| e.id == 9).count(), 1);
    }
}
