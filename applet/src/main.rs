#[path = "../../translations/i18n.rs"]
mod i18n;
use i18n::{message, tr};
#[allow(dead_code)] // the shared copy of every Maprisma COSMIC app; not every part is used here
mod corners;
mod look;
mod shot;
mod shot_files;
use shot::{Shot, ShotMsg};
// Maprisma Narrator: the headphones in the panel. Left click opens the menu (again: closes it; Esc
// closes it too)
// (Start / Pause / Stop, what needs setting up, reading area, speed, settings); right
// click starts or stops reading, middle click pauses. A green line under the icon while
// reading, yellow while paused.
//
// The reader is a user service (ocrvox.service, set up from the menu); the applet talks
// to it through backend/bridge.py like the GNOME extension did, and keeps the desktop
// service (maprisma-narrator-desktop: windows, screenshots, keys, highlight) running.

use std::process::Stdio;
use std::sync::LazyLock;
use std::time::Duration;

use cosmic::app::{Core, Task};
use cosmic::applet::cosmic_panel_config::PanelAnchor;
use cosmic::applet::{menu_button, padded_control};
use cosmic::iced::platform_specific::shell::wayland::commands::popup::destroy_popup;
use cosmic::iced::widget::{container as iced_container, text as iced_text};
use cosmic::iced::{
    Alignment, Background, Border, Color, Length, Rectangle, Subscription, stream, window,
};
use cosmic::widget::rectangle_tracker::{
    RectangleTracker, RectangleUpdate, rectangle_tracker_subscription,
};
use cosmic::widget::{
    Id, autosize, button, column, container, divider, icon, mouse_area, row, slider, space, text,
};
use cosmic::{Element, theme};
use serde_json::{Value, json};

const APP_ID: &str = "io.github.ubruckhaus.CosmicMaprismaNarrator";
const ICON: &str = "io.github.ubruckhaus.CosmicMaprismaNarrator-symbolic";
const MIN_SPEED: f32 = 0.6;
const MAX_SPEED: f32 = 2.0;
const POPUP_WIDTH: f32 = 360.0;
/// F12's folder in ~/Pictures and (as a slug) its file names (the settings window's too).
const SHOT_FOLDER: &str = "Maprisma Narrator";
static AUTOSIZE_ID: LazyLock<Id> = LazyLock::new(|| Id::new("maprisma-narrator-autosize"));

/// The line under the panel icon: reading in the theme's success colour, paused in its
/// warning colour (the desktop's green and yellow).
#[derive(Debug, Clone, Copy, PartialEq)]
enum Line {
    Reading,
    Paused,
}

impl Line {
    fn color(self, theme: &cosmic::Theme) -> Color {
        match self {
            Line::Reading => theme.cosmic().success_color(),
            Line::Paused => theme.cosmic().warning_color(),
        }
        .into()
    }
}

fn main() -> cosmic::iced::Result {
    cosmic::applet::run::<Narrator>(())
}

// ------------------------------------------------------------------------- paths

mod control;
use control::*;

fn notify(text: &str) {
    let _ = std::process::Command::new("notify-send")
        .args([
            "--app-name=Maprisma Narrator",
            "-i",
            ICON,
            tr("Maprisma Narrator"),
            &message(text),
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
}

// ------------------------------------------------------------------------- widgets

fn dim_text(theme: &cosmic::Theme) -> iced_text::Style {
    let mut color = Color::from(theme.cosmic().on_bg_color());
    color.a = 0.6;
    iced_text::Style {
        color: Some(color),
        ..Default::default()
    }
}

fn fill(line: Line, radius: f32) -> theme::Container<'static> {
    theme::Container::custom(move |theme| iced_container::Style {
        background: Some(Background::Color(line.color(theme))),
        border: Border {
            radius: radius.into(),
            ..Default::default()
        },
        ..Default::default()
    })
}

// ------------------------------------------------------------------------- applet

/// What Esc in a surface of the applet does: the screenshot note goes first (shot.rs skips it),
/// then the popup closes; elsewhere (the panel button) nothing.
#[derive(Debug, PartialEq)]
enum Escape {
    Note,
    ClosePopup,
    Nothing,
}

fn escape(id: window::Id, popup: Option<window::Id>, note: bool) -> Escape {
    if note {
        Escape::Note
    } else if popup == Some(id) {
        Escape::ClosePopup
    } else {
        Escape::Nothing
    }
}

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
    shot: Shot,
    corners: String, // Settings › Corners (corners.rs)
    screenshot_key: bool,
}

/// Settings › F12 saves a screenshot (on unless `"screenshot_key": false`) and › Corners
/// (`"corners"`), set in the settings window and kept in the same settings.json as its language.
fn look_settings() -> (bool, String) {
    let config = std::env::var_os("XDG_CONFIG_HOME")
        .filter(|v| !v.is_empty())
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            std::path::PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".config")
        });
    let saved = std::fs::read_to_string(config.join("maprisma-narrator/settings.json"))
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .unwrap_or(Value::Null);
    (
        saved.get("screenshot_key").and_then(Value::as_bool) != Some(false),
        corners::normalize(saved.get("corners").and_then(Value::as_str).unwrap_or("")).to_string(),
    )
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
    Shot(ShotMsg),
}

impl Narrator {
    fn line_color(&self) -> Option<Line> {
        if self.paused {
            Some(Line::Paused)
        } else if self.reading {
            Some(Line::Reading)
        } else {
            None
        }
    }

    fn set_reading(&mut self, state: Option<&Value>) {
        self.reading = state.is_some_and(|s| flag(s, "enabled"));
        self.paused = state.is_some_and(|s| flag(s, "paused"));
    }

    fn settings_speed(&self) -> f32 {
        self.state
            .get("settings")
            .and_then(|s| s.get("speed"))
            .and_then(Value::as_f64)
            .unwrap_or(1.0) as f32
    }

    fn panel_content(&self) -> Element<'_, Message> {
        let size = self.core.applet.suggested_size(true).0;
        let headphones = icon::from_name(ICON).size(size).symbolic(true).icon();
        let line: Element<Message> = match self.line_color() {
            Some(color) => container(space::horizontal())
                .width(Length::Fixed(size as f32))
                .height(Length::Fixed(2.0))
                .class(fill(color, corners::now().small.min(1.0)))
                .into(),
            None => space::vertical().height(Length::Fixed(2.0)).into(),
        };
        // 2 px: the panel's icon slot (not a layout gap), as the Omarchy original.
        column![headphones, line]
            .spacing(2)
            .align_x(Alignment::Center)
            .into()
    }

    fn menu(&self) -> Element<'_, Message> {
        let state = &self.state;
        let loaded = state.get("status").is_some();
        let ready = flag(state, "backend_ready") && !flag(state, "setup_busy");
        let mut status = Some(string(state, "status"))
            .filter(|s| !s.is_empty())
            .map(message)
            .unwrap_or_else(|| tr("Maprisma Narrator").into());
        let book = string(state, "window");
        if self.reading && !book.is_empty() {
            status += &format!(" · {book}");
        }
        let header = row![
            icon::from_name(ICON).size(24).symbolic(true).icon(),
            text::body(status).width(Length::Fill)
        ]
        .spacing(12)
        .align_y(Alignment::Center);

        let idle = !self.busy;
        let can_start = ready
            && !self.reading
            && state.get("can_start").and_then(Value::as_bool) != Some(false);
        let control =
            |icon_name: &'static str, label: &'static str, payload: Value, enabled: bool| {
                button::standard(label)
                    .leading_icon(icon::from_name(icon_name).size(16).symbolic(true))
                    .width(Length::Fill)
                    .on_press_maybe((enabled && idle).then_some(Message::Send(payload)))
            };
        let controls = row![
            control(
                "media-playback-start-symbolic",
                tr("Start"),
                json!({"command": "on"}),
                can_start
            ),
            if self.paused {
                control(
                    "media-playback-start-symbolic",
                    tr("Resume"),
                    json!({"command": "pause"}),
                    self.reading,
                )
            } else {
                control(
                    "media-playback-pause-symbolic",
                    tr("Pause"),
                    json!({"command": "pause"}),
                    self.reading,
                )
            },
            control(
                "media-playback-stop-symbolic",
                tr("Stop"),
                json!({"command": "off"}),
                self.reading
            ),
        ]
        .spacing(8);

        let mut top = column![header, controls].spacing(12);
        if let Some(step) = loaded.then(|| next_step(state)).flatten() {
            let mut block =
                column![text::caption(step.text).class(theme::Text::Custom(dim_text))].spacing(8);
            if !step.label.is_empty() {
                block = block.push(
                    button::suggested(step.label).on_press_maybe(idle.then_some(Message::Step)),
                );
            }
            top = top.push(block);
        }

        let mut actions = column![divider::horizontal::default()];
        actions = actions
            .push(
                menu_button(text::body(tr("Read the active window"))).on_press_maybe(
                    self.reading
                        .then_some(Message::Send(json!({"command": "read"}))),
                ),
            )
            .push(
                menu_button(text::body(tr("Select reading area…"))).on_press_maybe(
                    ready.then_some(Message::Send(json!({"command": "select-area"}))),
                ),
            );
        let custom_area = flag(state, "custom_area")
            || state
                .get("settings")
                .and_then(|s| s.get("kindle_area"))
                .is_some_and(|a| !a.is_null());
        if custom_area {
            actions = actions.push(
                menu_button(text::body(tr("Reset reading area")))
                    .on_press(Message::Send(json!({"command": "clear-area"}))),
            );
        }
        if ready {
            let speed = self.speed.unwrap_or_else(|| self.settings_speed());
            actions = actions.push(padded_control(
                row![
                    icon::from_name("media-seek-forward-symbolic")
                        .size(16)
                        .symbolic(true),
                    slider(MIN_SPEED..=MAX_SPEED, speed, Message::Speed)
                        .step(0.05_f32)
                        .on_release(Message::SpeedDone),
                    text::body(format!("{speed:.2}×")).width(Length::Fixed(48.0)),
                ]
                .spacing(12)
                .align_y(Alignment::Center),
            ));
        }
        actions = actions
            .push(divider::horizontal::default())
            .push(menu_button(text::body(tr("Settings…"))).on_press(Message::OpenSettings));

        column![padded_control(top).padding([12, 16]), actions]
            .width(Length::Fixed(POPUP_WIDTH))
            .padding([0, 0, 8, 0])
            .into()
    }

    fn read_look(&mut self) -> Task<Message> {
        let (screenshot_key, corners) = look_settings();
        self.screenshot_key = screenshot_key;
        self.corners = corners;
        corners::set_current(&self.corners);
        // The desktop's colours and corners (Maprisma Theme can change them any time); the
        // popup's view reads them (corners::apply), this only re-reads them (at most every 5 s).
        look::refresh();
        Task::none()
    }

    fn close_popup(&mut self) -> Task<Message> {
        match self.popup.take() {
            Some(popup) => {
                self.shot.closed(popup);
                destroy_popup(popup)
            }
            None => Task::none(),
        }
    }

    fn send(&mut self, payload: Value) -> Task<Message> {
        self.busy = true;
        Task::perform(request(payload), |state| {
            cosmic::Action::App(Message::Answer(state))
        })
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
        let mut app = Self {
            core,
            shot: Shot::new(SHOT_FOLDER),
            ..Default::default()
        };
        let look = app.read_look();
        (app, Task::batch([look, Task::done(cosmic::Action::App(Message::Poll))]))
    }

    fn on_close_requested(&self, id: window::Id) -> Option<Message> {
        Some(Message::CloseRequested(id))
    }

    fn subscription(&self) -> Subscription<Message> {
        Subscription::batch(vec![
            rectangle_tracker_subscription(0).map(|update| Message::Rectangle(update.1)),
            cosmic::iced::time::every(Duration::from_secs(1)).map(|_| Message::Poll),
            Shot::subscription().map(Message::Shot),
            Subscription::run_with("maprisma-narrator-desktop", |_| {
                stream::channel(
                    1,
                    |_output: cosmic::iced::futures::channel::mpsc::Sender<Message>| async move {
                        run_desktop_service().await;
                    },
                )
            }),
        ])
    }

    fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            // Light poll for the icon; while the menu is open the full state instead.
            Message::Poll => {
                let look = self.read_look();
                if self.popup.is_some() {
                    if !self.busy {
                        let status = Task::perform(request(json!({"command": "status"})), |s| {
                            cosmic::Action::App(Message::State(s))
                        });
                        return Task::batch([look, status]);
                    }
                } else {
                    let watched =
                        Task::perform(watch(), |s| cosmic::Action::App(Message::Watched(s)));
                    return Task::batch([look, watched]);
                }
                return look;
            }
            Message::Shot(ShotMsg::Escape(id)) => {
                return match escape(id, self.popup, self.shot.showing(id)) {
                    Escape::Note => self.shot.update(ShotMsg::Escape(id), self.screenshot_key, true, Message::Shot),
                    Escape::ClosePopup => self.close_popup(),
                    Escape::Nothing => Task::none(),
                };
            }
            Message::Shot(message) => {
                // F12 takes the open popup, not the panel button.
                let ours = match &message {
                    ShotMsg::Key(id) => self.popup == Some(*id),
                    _ => true,
                };
                return self.shot.update(message, self.screenshot_key, ours, Message::Shot);
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
                    if let Some(settings) = self
                        .state
                        .get_mut("settings")
                        .and_then(Value::as_object_mut)
                    {
                        settings.insert("speed".into(), json!(speed));
                    }
                    return self
                        .send(json!({"command": "configure", "settings": {"speed": speed}}));
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
                self.shot.closed(id);
                if self.popup == Some(id) {
                    self.popup = None;
                }
            }
            Message::TogglePopup => {
                if self.popup.is_some() {
                    return self.close_popup();
                }
                let refresh = Task::perform(request(json!({"command": "status"})), |s| {
                    cosmic::Action::App(Message::State(s))
                });
                let open = cosmic::surface::surface_task(cosmic::surface::action::app_popup(
                    |_| Default::default(),
                    |app: &mut Self| {
                        let id = window::Id::unique();
                        app.popup = Some(id);
                        let mut settings = app.core.applet.get_popup_settings(
                            app.core.main_window_id().unwrap(),
                            id,
                            None,
                            None,
                            None,
                        );
                        let Rectangle {
                            x,
                            y,
                            width,
                            height,
                        } = app.rectangle;
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
        let horizontal = matches!(
            self.core.applet.anchor,
            PanelAnchor::Top | PanelAnchor::Bottom
        );
        let padding = self.core.applet.suggested_padding(true).0;
        let button = button::custom(self.panel_content())
            .padding(if horizontal {
                [0, padding]
            } else {
                [padding, 0]
            })
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

    fn view_window(&self, id: window::Id) -> Element<'_, Message> {
        let content = match self.shot.card(id, Message::Shot) {
            Some(card) => column![card, self.menu()].width(Length::Fixed(POPUP_WIDTH)).into(),
            None => self.menu(),
        };
        corners::apply(&self.corners, self.core.applet.popup_container(content))
    }

    fn style(&self) -> Option<cosmic::iced::theme::Style> {
        Some(cosmic::applet::style())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn escape_closes_the_note_first_then_the_popup() {
        let popup = window::Id::unique();
        let other = window::Id::unique();
        assert_eq!(escape(popup, Some(popup), true), Escape::Note);
        assert_eq!(escape(popup, Some(popup), false), Escape::ClosePopup);
        assert_eq!(escape(other, Some(popup), false), Escape::Nothing);
        assert_eq!(escape(popup, None, false), Escape::Nothing);
    }
}
