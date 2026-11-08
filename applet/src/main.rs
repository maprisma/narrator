// Maprisma Narrator: the headphones in the panel. Left click opens the menu
// (Start / Pause / Stop, what needs setting up, reading area, speed, settings); right
// click starts or stops reading, middle click pauses. A green line under the icon while
// reading, yellow while paused.
//
// The reader is a user service (ocrvox.service, set up from the menu); the applet talks
// to it through backend/bridge.py like the GNOME extension did, and keeps the desktop
// service (maprisma-narrator-desktop: windows, screenshots, keys, highlight) running.

use std::path::PathBuf;
use std::process::Stdio;
use std::sync::LazyLock;
use std::time::Duration;

use cosmic::app::{Core, Task};
use cosmic::applet::cosmic_panel_config::PanelAnchor;
use cosmic::applet::{menu_button, padded_control};
use cosmic::iced::platform_specific::shell::wayland::commands::popup::destroy_popup;
use cosmic::iced::widget::{container as iced_container, text as iced_text};
use cosmic::iced::{Alignment, Background, Border, Color, Length, Rectangle, Subscription, stream, window};
use cosmic::widget::rectangle_tracker::{RectangleTracker, RectangleUpdate, rectangle_tracker_subscription};
use cosmic::widget::{Id, autosize, button, column, container, divider, icon, mouse_area, row, slider, space, text};
use cosmic::{Element, theme};
use serde_json::{Value, json};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

const APP_ID: &str = "io.github.ubruckhaus.CosmicMaprismaNarrator";
const ICON: &str = "audio-headphones-symbolic";
const MIN_SPEED: f32 = 0.6;
const MAX_SPEED: f32 = 2.0;
const POPUP_WIDTH: f32 = 360.0;
const RESTART_DELAY: Duration = Duration::from_secs(5);
static AUTOSIZE_ID: LazyLock<Id> = LazyLock::new(|| Id::new("maprisma-narrator-autosize"));

const GREEN: Color = Color::from_rgb(0x33 as f32 / 255.0, 0xd1 as f32 / 255.0, 0x7a as f32 / 255.0);
const AMBER: Color = Color::from_rgb(0xf6 as f32 / 255.0, 0xd3 as f32 / 255.0, 0x2d as f32 / 255.0);

fn main() -> cosmic::iced::Result {
    cosmic::applet::run::<Narrator>(())
}

// ------------------------------------------------------------------------- paths

fn home() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default()
}

fn data_home() -> PathBuf {
    std::env::var_os("XDG_DATA_HOME").map(PathBuf::from).unwrap_or_else(|| home().join(".local/share"))
}

// SCREEN_NARRATOR_BACKEND (development) or the installed copy.
fn bridge_script() -> PathBuf {
    std::env::var_os("SCREEN_NARRATOR_BACKEND")
        .map(PathBuf::from)
        .unwrap_or_else(|| data_home().join("maprisma-narrator/backend"))
        .join("bridge.py")
}

fn runtime() -> PathBuf {
    std::env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/run/user/1000"))
        .join("kindle-reader")
}

fn sibling(name: &str) -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join(name)))
        .filter(|p| p.is_file())
        .unwrap_or_else(|| name.into())
}

// ------------------------------------------------------------------------- reader

// One request through the bridge (one JSON line in, one out): the reader's full state, or {error}.
async fn request(payload: Value) -> Value {
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
            stdin.write_all(format!("{payload}\n").as_bytes()).await.map_err(|e| e.to_string())?;
        }
        let out = child.wait_with_output().await.map_err(|e| e.to_string())?;
        let text = String::from_utf8_lossy(&out.stdout);
        serde_json::from_str::<Value>(text.trim().lines().last().unwrap_or("{}")).map_err(|e| e.to_string())
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
async fn watch() -> Option<Value> {
    let ask = async {
        let mut stream = tokio::net::UnixStream::connect(runtime().join("control.sock")).await.ok()?;
        stream.write_all(b"{\"command\": \"watch\"}\n").await.ok()?;
        let mut line = String::new();
        BufReader::new(stream).read_line(&mut line).await.ok()?;
        serde_json::from_str(&line).ok()
    };
    tokio::time::timeout(Duration::from_secs(2), ask).await.ok().flatten()
}

fn flag(state: &Value, key: &str) -> bool {
    state.get(key).and_then(Value::as_bool) == Some(true)
}

fn string<'a>(state: &'a Value, key: &str) -> &'a str {
    state.get(key).and_then(Value::as_str).unwrap_or("")
}

struct Step {
    text: String,
    label: String,
    payload: Option<Value>,
}

// The first thing standing in the way of reading, with the one button that does it.
fn next_step(state: &Value) -> Option<Step> {
    let settings = state.get("settings").unwrap_or(&Value::Null);
    let language = settings.get("language").and_then(Value::as_str).unwrap_or("en");
    let phase = string(state, "setup_phase");
    if flag(state, "setup_busy") {
        let text = Some(string(state, "setup_message")).filter(|m| !m.is_empty()).unwrap_or("Setting up…");
        return Some(Step {
            text: text.into(),
            label: if phase == "packages" { String::new() } else { "Cancel".into() },
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
            return Some(Step { text: string(state, "setup_message").into(), label: "Retry setup".into(), payload });
        }
        let extra = if missing.is_empty() { String::new() } else { format!(" It installs {}.", missing.join(", ")) };
        return Some(Step {
            text: format!("Maprisma Narrator needs its reader, a voice and text recognition.{extra}"),
            label: "Set up automatically".into(),
            payload,
        });
    }
    let failed = state
        .get("checks")
        .and_then(Value::as_array)
        .and_then(|checks| checks.iter().find(|c| c.get("ok").and_then(Value::as_bool) != Some(true)))?;
    if flag(state, "enabled") {
        return None;
    }
    let problem = string(failed, "problem").to_string();
    let fix = failed
        .get("fixes")
        .and_then(Value::as_array)
        .and_then(|fixes| fixes.iter().find(|f| f.get("command").is_some() || f.get("settings").is_some()));
    let Some(fix) = fix else {
        return Some(Step { text: problem, label: "Settings…".into(), payload: None });
    };
    let payload = match fix.get("command").and_then(Value::as_str) {
        Some(command) => {
            let mut payload = json!({ "command": command });
            if let (Some(map), Some(args)) = (payload.as_object_mut(), fix.get("args").and_then(Value::as_object)) {
                map.extend(args.clone());
            }
            payload
        }
        None => json!({ "command": "configure", "settings": fix.get("settings").cloned().unwrap_or(Value::Null) }),
    };
    Some(Step { text: problem, label: string(fix, "label").into(), payload: Some(payload) })
}

fn notify(text: &str) {
    let _ = std::process::Command::new("notify-send")
        .args(["--app-name=Maprisma Narrator", "-i", ICON, "Maprisma Narrator", text])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
}

// ------------------------------------------------------------------------- widgets

fn dim_text(theme: &cosmic::Theme) -> iced_text::Style {
    let mut color = Color::from(theme.cosmic().on_bg_color());
    color.a = 0.6;
    iced_text::Style { color: Some(color), ..Default::default() }
}

fn fill(color: Color, radius: f32) -> theme::Container<'static> {
    theme::Container::custom(move |_| iced_container::Style {
        background: Some(Background::Color(color)),
        border: Border { radius: radius.into(), ..Default::default() },
        ..Default::default()
    })
}

// ------------------------------------------------------------------------- applet

#[derive(Default)]
struct Narrator {
    core: Core,
    popup: Option<window::Id>,
    rectangle: Rectangle,
    tracker: Option<RectangleTracker<u32>>,
    state: Value, // the full state, while the menu is open
    reading: bool,
    paused: bool,
    speed: Option<f32>, // while the slider is being moved
    busy: bool,         // a request is on its way
}

#[derive(Debug, Clone)]
enum Message {
    Poll,
    Watched(Option<Value>),
    State(Value),
    Answer(Value),
    Send(Value),
    TogglePopup,
    CloseRequested(window::Id),
    Rectangle(RectangleUpdate<u32>),
    Speed(f32),
    SpeedDone,
    Step,
    OpenSettings,
}

impl Narrator {
    fn line_color(&self) -> Option<Color> {
        if self.paused {
            Some(AMBER)
        } else if self.reading {
            Some(GREEN)
        } else {
            None
        }
    }

    fn set_reading(&mut self, state: Option<&Value>) {
        self.reading = state.is_some_and(|s| flag(s, "enabled"));
        self.paused = state.is_some_and(|s| flag(s, "paused"));
    }

    fn settings_speed(&self) -> f32 {
        self.state.get("settings").and_then(|s| s.get("speed")).and_then(Value::as_f64).unwrap_or(1.0) as f32
    }

    fn panel_content(&self) -> Element<'_, Message> {
        let size = self.core.applet.suggested_size(true).0;
        let headphones = icon::from_name(ICON).size(size).symbolic(true).icon();
        let line: Element<Message> = match self.line_color() {
            Some(color) => container(space::horizontal())
                .width(Length::Fixed(size as f32))
                .height(Length::Fixed(2.0))
                .class(fill(color, 1.0))
                .into(),
            None => space::vertical().height(Length::Fixed(2.0)).into(),
        };
        column![headphones, line].spacing(2).align_x(Alignment::Center).into()
    }

    fn menu(&self) -> Element<'_, Message> {
        let state = &self.state;
        let loaded = state.get("status").is_some();
        let ready = flag(state, "backend_ready") && !flag(state, "setup_busy");
        let mut status = Some(string(state, "status")).filter(|s| !s.is_empty()).unwrap_or("Maprisma Narrator").to_string();
        let book = string(state, "window");
        if self.reading && !book.is_empty() {
            status += &format!(" · {book}");
        }
        let header = row![icon::from_name(ICON).size(24).symbolic(true).icon(), text::body(status).width(Length::Fill)]
            .spacing(10)
            .align_y(Alignment::Center);

        let idle = !self.busy;
        let can_start = ready && !self.reading && state.get("can_start").and_then(Value::as_bool) != Some(false);
        let control = |icon_name: &'static str, label: &'static str, payload: Value, enabled: bool| {
            button::standard(label)
                .leading_icon(icon::from_name(icon_name).size(16).symbolic(true))
                .width(Length::Fill)
                .on_press_maybe((enabled && idle).then_some(Message::Send(payload)))
        };
        let controls = row![
            control("media-playback-start-symbolic", "Start", json!({"command": "on"}), can_start),
            if self.paused {
                control("media-playback-start-symbolic", "Resume", json!({"command": "pause"}), self.reading)
            } else {
                control("media-playback-pause-symbolic", "Pause", json!({"command": "pause"}), self.reading)
            },
            control("media-playback-stop-symbolic", "Stop", json!({"command": "off"}), self.reading),
        ]
        .spacing(6);

        let mut top = column![header, controls].spacing(10);
        if let Some(step) = loaded.then(|| next_step(state)).flatten() {
            let mut block = column![text::caption(step.text).class(theme::Text::Custom(dim_text))].spacing(6);
            if !step.label.is_empty() {
                block = block.push(button::suggested(step.label).on_press_maybe(idle.then_some(Message::Step)));
            }
            top = top.push(block);
        }

        let mut actions = column![divider::horizontal::default()];
        actions = actions
            .push(
                menu_button(text::body("Read the active window"))
                    .on_press_maybe(self.reading.then_some(Message::Send(json!({"command": "read"})))),
            )
            .push(
                menu_button(text::body("Select reading area…"))
                    .on_press_maybe(ready.then_some(Message::Send(json!({"command": "select-area"})))),
            );
        let custom_area = flag(state, "custom_area")
            || state.get("settings").and_then(|s| s.get("kindle_area")).is_some_and(|a| !a.is_null());
        if custom_area {
            actions = actions.push(
                menu_button(text::body("Reset reading area")).on_press(Message::Send(json!({"command": "clear-area"}))),
            );
        }
        if ready {
            let speed = self.speed.unwrap_or_else(|| self.settings_speed());
            actions = actions.push(padded_control(
                row![
                    icon::from_name("media-seek-forward-symbolic").size(16).symbolic(true),
                    slider(MIN_SPEED..=MAX_SPEED, speed, Message::Speed).step(0.05_f32).on_release(Message::SpeedDone),
                    text::body(format!("{speed:.2}×")).width(Length::Fixed(48.0)),
                ]
                .spacing(10)
                .align_y(Alignment::Center),
            ));
        }
        actions = actions
            .push(divider::horizontal::default())
            .push(menu_button(text::body("Settings…")).on_press(Message::OpenSettings));

        column![padded_control(top).padding([12, 16]), actions]
            .width(Length::Fixed(POPUP_WIDTH))
            .padding([0, 0, 8, 0])
            .into()
    }

    fn close_popup(&mut self) -> Task<Message> {
        match self.popup.take() {
            Some(popup) => destroy_popup(popup),
            None => Task::none(),
        }
    }

    fn send(&mut self, payload: Value) -> Task<Message> {
        self.busy = true;
        Task::perform(request(payload), |state| cosmic::Action::App(Message::Answer(state)))
    }
}

impl cosmic::Application for Narrator {
    type Executor = cosmic::SingleThreadExecutor;
    type Flags = ();
    type Message = Message;
    const APP_ID: &'static str = APP_ID;

    fn core(&self) -> &Core {
        &self.core
    }

    fn core_mut(&mut self) -> &mut Core {
        &mut self.core
    }

    fn init(core: Core, _flags: ()) -> (Self, Task<Message>) {
        (Self { core, ..Default::default() }, Task::done(cosmic::Action::App(Message::Poll)))
    }

    fn on_close_requested(&self, id: window::Id) -> Option<Message> {
        Some(Message::CloseRequested(id))
    }

    fn subscription(&self) -> Subscription<Message> {
        Subscription::batch(vec![
            rectangle_tracker_subscription(0).map(|update| Message::Rectangle(update.1)),
            cosmic::iced::time::every(Duration::from_secs(1)).map(|_| Message::Poll),
            Subscription::run_with("maprisma-narrator-desktop", |_| {
                stream::channel(1, |_output: cosmic::iced::futures::channel::mpsc::Sender<Message>| async move {
                    run_desktop_service().await;
                })
            }),
        ])
    }

    fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            // Light poll for the icon; while the menu is open the full state instead.
            Message::Poll => {
                if self.popup.is_some() {
                    if !self.busy {
                        return Task::perform(request(json!({"command": "status"})), |s| {
                            cosmic::Action::App(Message::State(s))
                        });
                    }
                } else {
                    return Task::perform(watch(), |s| cosmic::Action::App(Message::Watched(s)));
                }
            }
            Message::Watched(state) => self.set_reading(state.as_ref()),
            Message::State(state) => {
                if state.get("error").is_none() {
                    self.set_reading(Some(&state));
                    self.state = state;
                }
            }
            Message::Answer(state) => {
                self.busy = false;
                if let Some(error) = state.get("error").and_then(Value::as_str) {
                    notify(error);
                } else {
                    self.set_reading(Some(&state));
                    self.state = state;
                }
            }
            Message::Send(payload) => {
                // The area picker needs the screen: the menu goes first.
                let close = payload.get("command").and_then(Value::as_str) == Some("select-area");
                let task = self.send(payload);
                if close {
                    return Task::batch([self.close_popup(), task]);
                }
                return task;
            }
            Message::Step => {
                if let Some(step) = next_step(&self.state) {
                    return match step.payload {
                        Some(payload) => self.send(payload),
                        None => self.update(Message::OpenSettings),
                    };
                }
            }
            Message::Speed(speed) => self.speed = Some((speed * 20.0).round() / 20.0),
            Message::SpeedDone => {
                if let Some(speed) = self.speed.take() {
                    if let Some(settings) = self.state.get_mut("settings").and_then(Value::as_object_mut) {
                        settings.insert("speed".into(), json!(speed));
                    }
                    return self.send(json!({"command": "configure", "settings": {"speed": speed}}));
                }
            }
            Message::OpenSettings => {
                let _ = std::process::Command::new(sibling("maprisma-narrator"))
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn();
                return self.close_popup();
            }
            Message::Rectangle(update) => match update {
                RectangleUpdate::Rectangle(r) => self.rectangle = r.1,
                RectangleUpdate::Init(tracker) => self.tracker = Some(tracker),
            },
            Message::CloseRequested(id) => {
                if self.popup == Some(id) {
                    self.popup = None;
                }
            }
            Message::TogglePopup => {
                if self.popup.is_some() {
                    return self.close_popup();
                }
                let refresh =
                    Task::perform(request(json!({"command": "status"})), |s| cosmic::Action::App(Message::State(s)));
                let open = cosmic::surface::surface_task(cosmic::surface::action::app_popup(
                    |_| Default::default(),
                    |app: &mut Self| {
                        let id = window::Id::unique();
                        app.popup = Some(id);
                        let mut settings =
                            app.core.applet.get_popup_settings(app.core.main_window_id().unwrap(), id, None, None, None);
                        let Rectangle { x, y, width, height } = app.rectangle;
                        settings.positioner.anchor_rect = Rectangle::<i32> {
                            x: x.max(1.0) as i32,
                            y: y.max(1.0) as i32,
                            width: width.max(1.0) as i32,
                            height: height.max(1.0) as i32,
                        };
                        settings.positioner.size = None;
                        settings
                    },
                    None,
                ));
                return Task::batch([open, refresh]);
            }
        }
        Task::none()
    }

    fn view(&self) -> Element<'_, Message> {
        let horizontal = matches!(self.core.applet.anchor, PanelAnchor::Top | PanelAnchor::Bottom);
        let padding = self.core.applet.suggested_padding(true).0;
        let button = button::custom(self.panel_content())
            .padding(if horizontal { [0, padding] } else { [padding, 0] })
            .on_press_down(Message::TogglePopup)
            .class(theme::Button::AppletIcon);
        // Right click starts or stops, middle click pauses.
        let button = mouse_area(button)
            .on_right_press(Message::Send(json!({"command": "toggle"})))
            .on_middle_press(Message::Send(json!({"command": "pause"})));
        let content: Element<Message> = match self.tracker.as_ref() {
            Some(tracker) => tracker.container(0, button).ignore_bounds(true).into(),
            None => button.into(),
        };
        autosize::autosize(content, AUTOSIZE_ID.clone()).into()
    }

    fn view_window(&self, _id: window::Id) -> Element<'_, Message> {
        self.core.applet.popup_container(self.menu()).into()
    }

    fn style(&self) -> Option<cosmic::iced::theme::Style> {
        Some(cosmic::applet::style())
    }
}

// Keeps the desktop service running while the applet runs; starts it again after it ends.
async fn run_desktop_service() {
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
        tokio::time::sleep(RESTART_DELAY).await;
    }
}
