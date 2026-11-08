// The Wayland side: which windows there are (ext-foreign-toplevel-list with COSMIC's
// toplevel info for geometry, state and workspaces), focusing one (COSMIC's toplevel
// manager), and the passage highlight: boxes over the book window on an overlay layer,
// drawn while the book has the focus. Runs on its own thread with a calloop loop; the
// D-Bus side reads the window list from `Shared` and sends `Command`s.

use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime};

use cctk::cosmic_protocols::toplevel_info::v1::client::zcosmic_toplevel_handle_v1::State as ToplevelState;
use cctk::cosmic_protocols::toplevel_management::v1::client::zcosmic_toplevel_manager_v1::ZcosmicToplelevelManagementCapabilitiesV1;
use cctk::sctk::compositor::{CompositorHandler, CompositorState, Region};
use cctk::sctk::output::{OutputHandler, OutputState};
use cctk::sctk::reexports::calloop::channel::{self, Channel, Event as ChannelEvent};
use cctk::sctk::reexports::calloop::timer::{TimeoutAction, Timer};
use cctk::sctk::reexports::calloop::{EventLoop, LoopHandle};
use cctk::sctk::reexports::calloop_wayland_source::WaylandSource;
use cctk::sctk::registry::{ProvidesRegistryState, RegistryState};
use cctk::sctk::seat::{Capability, SeatHandler, SeatState};
use cctk::sctk::shell::WaylandSurface;
use cctk::sctk::shell::wlr_layer::{
    Anchor, KeyboardInteractivity, Layer, LayerShell, LayerShellHandler, LayerSurface, LayerSurfaceConfigure,
};
use cctk::sctk::shm::slot::SlotPool;
use cctk::sctk::shm::{Shm, ShmHandler};
use cctk::sctk::{
    delegate_compositor, delegate_layer, delegate_output, delegate_registry, delegate_seat, delegate_shm,
    registry_handlers,
};
use cctk::toplevel_info::{ToplevelInfoHandler, ToplevelInfoState};
use cctk::toplevel_management::{ToplevelManagerHandler, ToplevelManagerState};
use cctk::wayland_client::globals::registry_queue_init;
use cctk::wayland_client::protocol::{wl_output, wl_seat, wl_shm, wl_surface};
use cctk::wayland_client::{Connection, QueueHandle, WEnum};
use cctk::wayland_protocols::ext::foreign_toplevel_list::v1::client::ext_foreign_toplevel_handle_v1::ExtForeignToplevelHandleV1;
use cctk::wayland_protocols::ext::workspace::v1::client::ext_workspace_handle_v1;
use cctk::workspace::{WorkspaceHandler, WorkspaceState};
use cosmic_client_toolkit as cctk;
use serde_json::{Value, json};
use tokio::sync::oneshot;

const HIGHLIGHT_POLL: Duration = Duration::from_millis(150);
// .maprisma-narrator-highlight of the GNOME extension: a soft amber box, 2 px around the passage.
const FILL: [u8; 4] = premultiply(255, 213, 79, 0.22);
const BORDER: [u8; 4] = premultiply(255, 193, 7, 0.6);
const GROW: i32 = 2;

const fn premultiply(r: u8, g: u8, b: u8, a: f32) -> [u8; 4] {
    let alpha = (a * 255.0) as u32;
    // ARGB8888 little endian: B, G, R, A.
    [(b as u32 * alpha / 255) as u8, (g as u32 * alpha / 255) as u8, (r as u32 * alpha / 255) as u8, alpha as u8]
}

#[derive(Clone, Debug, Default)]
pub struct Window {
    pub address: String,
    pub title: String,
    pub class: String,
    pub at: (i32, i32),
    pub size: (i32, i32),
    pub focused: bool,
    pub shown: bool,
}

impl Window {
    // What hyprctl / the GNOME extension answered for a window.
    pub fn json(&self) -> Value {
        json!({
            "address": self.address,
            "at": [self.at.0, self.at.1],
            "size": [self.size.0, self.size.1],
            "title": self.title,
            "class": self.class,
            "focused": self.focused,
            "shown": self.shown,
        })
    }
}

#[derive(Default)]
pub struct Snapshot {
    pub windows: Vec<Window>,
    // The compositor has listed the windows once: before that every window would look closed.
    pub ready: bool,
}

impl Snapshot {
    pub fn find(&self, address: &str) -> Option<&Window> {
        self.windows.iter().find(|w| w.address == address)
    }

    pub fn focused(&self) -> Option<&Window> {
        self.windows.iter().find(|w| w.focused)
    }
}

pub type Shared = Arc<Mutex<Snapshot>>;

pub enum Command {
    Activate(String),
    // Hides the highlight (for a capture or a lent focus); answers once it is gone.
    Hide(bool, oneshot::Sender<()>),
}

struct Overlay {
    layer: LayerSurface,
    output: wl_output::WlOutput,
    size: Option<(u32, u32)>,
}

#[derive(Default, PartialEq)]
struct Highlight {
    rectangles: Vec<(i32, i32, i32, i32)>,
    target: String,
}

struct App {
    registry: RegistryState,
    outputs: OutputState,
    seats: SeatState,
    compositor: CompositorState,
    shm: Shm,
    layer_shell: Option<LayerShell>,
    toplevels: ToplevelInfoState,
    manager: Option<ToplevelManagerState>,
    workspaces: WorkspaceState,
    pool: Option<SlotPool>,
    overlays: Vec<Overlay>,
    highlight: Highlight,
    highlight_file: PathBuf,
    highlight_mtime: Option<SystemTime>,
    hidden: bool,
    shared: Shared,
}

pub fn runtime_dir() -> PathBuf {
    std::env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(format!("/run/user/{}", unsafe { libc::getuid() })))
        .join("kindle-reader")
}

pub fn run(shared: Shared, commands: Channel<Command>) -> Result<(), String> {
    let conn = Connection::connect_to_env().map_err(|e| format!("no Wayland display: {e}"))?;
    let (globals, mut queue) = registry_queue_init::<App>(&conn).map_err(|e| e.to_string())?;
    let qh = queue.handle();
    let registry = RegistryState::new(&globals);
    let toplevels =
        ToplevelInfoState::try_new(&registry, &qh).ok_or("the compositor does not list windows (ext-foreign-toplevel-list)")?;
    let compositor = CompositorState::bind(&globals, &qh).map_err(|e| e.to_string())?;
    let shm = Shm::bind(&globals, &qh).map_err(|e| e.to_string())?;
    let mut app = App {
        outputs: OutputState::new(&globals, &qh),
        seats: SeatState::new(&globals, &qh),
        layer_shell: LayerShell::bind(&globals, &qh).ok(),
        manager: ToplevelManagerState::try_new(&registry, &qh),
        workspaces: WorkspaceState::new(&registry, &qh),
        registry,
        compositor,
        shm,
        toplevels,
        pool: None,
        overlays: Vec::new(),
        highlight: Highlight::default(),
        highlight_file: runtime_dir().join("highlight.json"),
        highlight_mtime: None,
        hidden: false,
        shared,
    };

    // Load the window list before the D-Bus side answers: a fresh start (the applet restarts
    // this service) would otherwise answer {} for the book and the reader would stop.
    for _ in 0..3 {
        queue.roundtrip(&mut app).map_err(|e| e.to_string())?;
    }
    app.publish(&qh);
    if let Ok(mut shared) = app.shared.lock() {
        shared.ready = true;
    }

    let mut event_loop: EventLoop<App> = EventLoop::try_new().map_err(|e| e.to_string())?;
    let handle: LoopHandle<App> = event_loop.handle();
    WaylandSource::new(conn.clone(), queue).insert(handle.clone()).map_err(|e| e.to_string())?;
    let command_qh = qh.clone();
    handle
        .insert_source(commands, move |event, _, app| {
            if let ChannelEvent::Msg(command) = event {
                app.command(command, &command_qh);
            }
        })
        .map_err(|e| e.to_string())?;
    let timer_qh = qh.clone();
    handle
        .insert_source(Timer::from_duration(HIGHLIGHT_POLL), move |_, _, app| {
            app.load_highlight(&timer_qh);
            TimeoutAction::ToDuration(HIGHLIGHT_POLL)
        })
        .map_err(|e| e.to_string())?;
    loop {
        event_loop.dispatch(None, &mut app).map_err(|e| e.to_string())?;
    }
}

impl App {
    fn command(&mut self, command: Command, qh: &QueueHandle<Self>) {
        match command {
            Command::Activate(address) => {
                let Some(manager) = &self.manager else { return };
                let Some(seat) = self.seats.seats().next() else { return };
                let handle = self
                    .toplevels
                    .toplevels()
                    .find(|info| info.identifier == address)
                    .and_then(|info| info.cosmic_toplevel.clone());
                if let Some(handle) = handle {
                    manager.manager.activate(&handle, &seat);
                }
            }
            Command::Hide(hidden, done) => {
                self.hidden = hidden;
                self.sync_overlay(qh);
                let _ = done.send(());
            }
        }
    }

    // The window list for the D-Bus side; called whenever a window, workspace or output changes.
    fn publish(&mut self, qh: &QueueHandle<Self>) {
        let active: HashSet<_> = self
            .workspaces
            .workspaces()
            .filter(|w| w.state.contains(ext_workspace_handle_v1::State::Active))
            .map(|w| w.handle.clone())
            .collect();
        let windows = self
            .toplevels
            .toplevels()
            .map(|info| {
                let geometry = info
                    .geometry
                    .iter()
                    .find(|(output, _)| info.output.contains(*output))
                    .or_else(|| info.geometry.iter().next());
                let (at, size) = match geometry {
                    Some((output, g)) => {
                        let origin = self.outputs.info(output).and_then(|i| i.logical_position).unwrap_or((0, 0));
                        ((origin.0 + g.x, origin.1 + g.y), (g.width.max(1), g.height.max(1)))
                    }
                    None => ((0, 0), (1, 1)),
                };
                let minimized = info.state.contains(&ToplevelState::Minimized);
                let on_screen = active.is_empty() || info.workspace.iter().any(|w| active.contains(w));
                Window {
                    address: info.identifier.clone(),
                    title: info.title.clone(),
                    class: info.app_id.clone(),
                    at,
                    size,
                    focused: info.state.contains(&ToplevelState::Activated),
                    shown: !minimized && on_screen,
                }
            })
            .collect();
        if let Ok(mut shared) = self.shared.lock() {
            shared.windows = windows;
        }
        self.sync_overlay(qh);
    }

    // highlight.json: {rectangles: [{x, y, width, height}], target}, replaced by the reader.
    fn load_highlight(&mut self, qh: &QueueHandle<Self>) {
        let mtime = std::fs::metadata(&self.highlight_file).and_then(|m| m.modified()).ok();
        if mtime == self.highlight_mtime {
            return;
        }
        self.highlight_mtime = mtime;
        let state: Value = std::fs::read_to_string(&self.highlight_file)
            .ok()
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or(Value::Null);
        let rectangles = state
            .get("rectangles")
            .and_then(Value::as_array)
            .map(|list| {
                list.iter()
                    .filter_map(|r| {
                        let n = |k: &str| r.get(k).and_then(Value::as_f64).filter(|v| v.is_finite());
                        Some((n("x")?.round() as i32, n("y")?.round() as i32, n("width")?.round() as i32, n("height")?.round() as i32))
                    })
                    .collect()
            })
            .unwrap_or_default();
        let target = state.get("target").and_then(Value::as_str).unwrap_or("").to_string();
        let highlight = Highlight { rectangles, target };
        if highlight != self.highlight {
            self.highlight = highlight;
            self.redraw_all(qh);
        }
    }

    fn wanted(&self) -> bool {
        if self.hidden || self.highlight.rectangles.is_empty() || self.layer_shell.is_none() {
            return false;
        }
        let target = self.highlight.target.trim_start_matches("0x");
        self.toplevels.toplevels().any(|info| {
            info.state.contains(&ToplevelState::Activated) && info.identifier.trim_start_matches("0x") == target
        })
    }

    // One overlay surface per output while the highlight shows; none otherwise.
    fn sync_overlay(&mut self, qh: &QueueHandle<Self>) {
        if !self.wanted() {
            self.overlays.clear();
            return;
        }
        if !self.overlays.is_empty() {
            return;
        }
        let Some(layer_shell) = &self.layer_shell else { return };
        for output in self.outputs.outputs() {
            let surface = self.compositor.create_surface(qh);
            let layer = layer_shell.create_layer_surface(
                qh,
                surface,
                Layer::Overlay,
                Some("maprisma-narrator-highlight"),
                Some(&output),
            );
            layer.set_anchor(Anchor::TOP | Anchor::BOTTOM | Anchor::LEFT | Anchor::RIGHT);
            layer.set_exclusive_zone(-1);
            layer.set_keyboard_interactivity(KeyboardInteractivity::None);
            // Clicks go through to the book.
            if let Ok(region) = Region::new(&self.compositor) {
                layer.wl_surface().set_input_region(Some(region.wl_region()));
            }
            layer.commit();
            self.overlays.push(Overlay { layer, output, size: None });
        }
    }

    fn redraw_all(&mut self, qh: &QueueHandle<Self>) {
        self.sync_overlay(qh);
        for index in 0..self.overlays.len() {
            self.draw(index);
        }
    }

    fn draw(&mut self, index: usize) {
        let Some(overlay) = self.overlays.get(index) else { return };
        let Some((width, height)) = overlay.size else { return };
        let origin = self.outputs.info(&overlay.output).and_then(|i| i.logical_position).unwrap_or((0, 0));
        let stride = width as i32 * 4;
        let needed = (stride * height as i32) as usize;
        let pool = match &mut self.pool {
            Some(pool) => pool,
            None => match SlotPool::new(needed, &self.shm) {
                Ok(pool) => self.pool.insert(pool),
                Err(_) => return,
            },
        };
        let Ok((buffer, canvas)) = pool.create_buffer(width as i32, height as i32, stride, wl_shm::Format::Argb8888)
        else {
            return;
        };
        canvas.fill(0);
        let (w, h) = (width as i32, height as i32);
        for &(x, y, rw, rh) in &self.highlight.rectangles {
            let left = (x - origin.0 - GROW).clamp(0, w);
            let top = (y - origin.1 - GROW).clamp(0, h);
            let right = (x - origin.0 + rw + GROW).clamp(0, w);
            let bottom = (y - origin.1 + rh + GROW).clamp(0, h);
            for py in top..bottom {
                for px in left..right {
                    let edge = py == top || py == bottom - 1 || px == left || px == right - 1;
                    let at = ((py * w + px) * 4) as usize;
                    canvas[at..at + 4].copy_from_slice(if edge { &BORDER } else { &FILL });
                }
            }
        }
        let surface = overlay.layer.wl_surface();
        if buffer.attach_to(surface).is_ok() {
            surface.damage_buffer(0, 0, w, h);
            overlay.layer.commit();
        }
    }
}

impl CompositorHandler for App {
    fn scale_factor_changed(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &wl_surface::WlSurface, _: i32) {}
    fn transform_changed(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &wl_surface::WlSurface, _: wl_output::Transform) {}
    fn frame(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &wl_surface::WlSurface, _: u32) {}
    fn surface_enter(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &wl_surface::WlSurface, _: &wl_output::WlOutput) {}
    fn surface_leave(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &wl_surface::WlSurface, _: &wl_output::WlOutput) {}
}

impl OutputHandler for App {
    fn output_state(&mut self) -> &mut OutputState {
        &mut self.outputs
    }
    fn new_output(&mut self, _: &Connection, qh: &QueueHandle<Self>, _: wl_output::WlOutput) {
        self.overlays.clear();
        self.publish(qh);
    }
    fn update_output(&mut self, _: &Connection, qh: &QueueHandle<Self>, _: wl_output::WlOutput) {
        self.overlays.clear();
        self.publish(qh);
    }
    fn output_destroyed(&mut self, _: &Connection, qh: &QueueHandle<Self>, _: wl_output::WlOutput) {
        self.overlays.clear();
        self.publish(qh);
    }
}

impl LayerShellHandler for App {
    fn closed(&mut self, _: &Connection, _: &QueueHandle<Self>, layer: &LayerSurface) {
        self.overlays.retain(|o| &o.layer != layer);
    }

    fn configure(
        &mut self,
        _: &Connection,
        _: &QueueHandle<Self>,
        layer: &LayerSurface,
        configure: LayerSurfaceConfigure,
        _: u32,
    ) {
        let Some(index) = self.overlays.iter().position(|o| &o.layer == layer) else { return };
        let (width, height) = configure.new_size;
        if width == 0 || height == 0 {
            return;
        }
        self.overlays[index].size = Some((width, height));
        self.draw(index);
    }
}

impl ShmHandler for App {
    fn shm_state(&mut self) -> &mut Shm {
        &mut self.shm
    }
}

impl SeatHandler for App {
    fn seat_state(&mut self) -> &mut SeatState {
        &mut self.seats
    }
    fn new_seat(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_seat::WlSeat) {}
    fn new_capability(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_seat::WlSeat, _: Capability) {}
    fn remove_capability(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_seat::WlSeat, _: Capability) {}
    fn remove_seat(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_seat::WlSeat) {}
}

impl ToplevelInfoHandler for App {
    fn toplevel_info_state(&mut self) -> &mut ToplevelInfoState {
        &mut self.toplevels
    }
    fn new_toplevel(&mut self, _: &Connection, qh: &QueueHandle<Self>, _: &ExtForeignToplevelHandleV1) {
        self.publish(qh);
    }
    fn update_toplevel(&mut self, _: &Connection, qh: &QueueHandle<Self>, _: &ExtForeignToplevelHandleV1) {
        self.publish(qh);
    }
    fn toplevel_closed(&mut self, _: &Connection, qh: &QueueHandle<Self>, toplevel: &ExtForeignToplevelHandleV1) {
        // Still listed during this call: published again without it.
        let closed = self.toplevels.info(toplevel).map(|i| i.identifier.clone());
        self.publish(qh);
        if let (Some(closed), Ok(mut shared)) = (closed, self.shared.lock()) {
            shared.windows.retain(|w| w.address != closed);
        }
    }
}

impl ToplevelManagerHandler for App {
    fn toplevel_manager_state(&mut self) -> &mut ToplevelManagerState {
        self.manager.as_mut().expect("toplevel manager events without a manager")
    }
    fn capabilities(
        &mut self,
        _: &Connection,
        _: &QueueHandle<Self>,
        _: Vec<WEnum<ZcosmicToplelevelManagementCapabilitiesV1>>,
    ) {
    }
}

impl WorkspaceHandler for App {
    fn workspace_state(&mut self) -> &mut WorkspaceState {
        &mut self.workspaces
    }
    fn done(&mut self) {
        // No queue handle here; the next toplevel or timer event publishes. Update the
        // shown flags right away so a workspace switch counts at once.
        let active: HashSet<_> = self
            .workspaces
            .workspaces()
            .filter(|w| w.state.contains(ext_workspace_handle_v1::State::Active))
            .map(|w| w.handle.clone())
            .collect();
        let shown: Vec<(String, bool)> = self
            .toplevels
            .toplevels()
            .map(|info| {
                let minimized = info.state.contains(&ToplevelState::Minimized);
                let on_screen = active.is_empty() || info.workspace.iter().any(|w| active.contains(w));
                (info.identifier.clone(), !minimized && on_screen)
            })
            .collect();
        if let Ok(mut shared) = self.shared.lock() {
            for (address, shown) in shown {
                if let Some(w) = shared.windows.iter_mut().find(|w| w.address == address) {
                    w.shown = shown;
                }
            }
        }
    }
}

impl ProvidesRegistryState for App {
    fn registry(&mut self) -> &mut RegistryState {
        &mut self.registry
    }
    registry_handlers![OutputState, SeatState];
}

delegate_compositor!(App);
delegate_output!(App);
delegate_layer!(App);
delegate_shm!(App);
delegate_seat!(App);
delegate_registry!(App);
cctk::delegate_toplevel_info!(App);
cctk::delegate_toplevel_manager!(App);
cctk::delegate_workspace!(App);

pub fn channel() -> (channel::Sender<Command>, Channel<Command>) {
    channel::channel()
}
