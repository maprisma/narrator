#[path = "../../translations/i18n.rs"]
mod i18n;
use i18n::{message, tr, trf};
#[allow(dead_code)] // the shared copy of every Maprisma COSMIC app; not every part is used here
mod corners;
mod look;
mod shot;
mod shot_files;
use shot::{Shot, ShotMsg};
// Maprisma Narrator: the headphones in the panel. Left click opens the menu (again: closes it; Esc
// closes it too)
// (Start / Pause / Stop, what needs setting up, reading area, speed, settings); right
// click starts or stops reading, middle click pauses. An accent-coloured line under the icon while
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
use cosmic::iced::widget::{container as iced_container, svg as iced_svg, text as iced_text};
use cosmic::iced::{
    Alignment, Background, Border, Color, Length, Rectangle, Subscription, stream, window,
};
use cosmic::widget::rectangle_tracker::{
    RectangleTracker, RectangleUpdate, rectangle_tracker_subscription,
};
use cosmic::widget::{
    Id, autosize, button, column, container, divider, icon, mouse_area, row, scrollable, slider, space,
    text, toggler,
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
/// warning colour (the theme accent and yellow).
#[derive(Debug, Clone, Copy, PartialEq)]
enum Line {
    Reading,
    Paused,
}

impl Line {
    fn color(self, theme: &cosmic::Theme) -> Color {
        match self {
            Line::Reading => theme.cosmic().accent_color(),
            Line::Paused => theme.cosmic().warning_color(),
        }
        .into()
    }
}

/// Debug builds only: `MAPRISMA_SHOT_PAGE=settings` opens the popup on the settings page (for
/// screenshots).
fn shot_page_settings() -> bool {
    cfg!(debug_assertions) && std::env::var("MAPRISMA_SHOT_PAGE").as_deref() == Ok("settings")
}

fn main() -> cosmic::iced::Result {
    crate::look::keep_fonts();
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

fn lit_svg() -> theme::Svg {
    theme::Svg::custom(|theme: &cosmic::Theme| iced_svg::Style { color: Some(theme.cosmic().accent_color().into()) })
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
/// then an open Language / Corners list, then Back from the settings page, then the popup
/// closes; elsewhere (the panel button) nothing.
#[derive(Debug, PartialEq)]
enum Escape {
    Note,
    Menus,
    Back,
    ClosePopup,
    Nothing,
}

fn escape(id: window::Id, popup: Option<window::Id>, note: bool, menus: bool, settings: bool) -> Escape {
    if note {
        Escape::Note
    } else if popup != Some(id) {
        Escape::Nothing
    } else if menus {
        Escape::Menus
    } else if settings {
        Escape::Back
    } else {
        Escape::ClosePopup
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
    /// The settings page (Language, F12, Corners) is shown instead of the menu.
    settings_open: bool,
    language_open: bool,
    corners_open: bool,
    setting_error: bool,
}

/// Settings › F12 saves a screenshot (on unless `"screenshot_key": false`) and › Corners
/// (`"corners"`), set in the settings window and kept in the same settings.json as its language.
fn settings_file() -> std::path::PathBuf {
    std::env::var_os("XDG_CONFIG_HOME")
        .filter(|v| !v.is_empty())
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| {
            std::path::PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".config")
        })
        .join("maprisma-narrator/settings.json")
}

fn look_settings() -> (bool, String) {
    let saved = std::fs::read_to_string(settings_file())
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .unwrap_or(Value::Null);
    (
        saved.get("screenshot_key").and_then(Value::as_bool) != Some(false),
        corners::normalize(saved.get("corners").and_then(Value::as_str).unwrap_or("")).to_string(),
    )
}

/// Saves one setting into settings.json, keeping every other key (as the settings window does).
fn save_setting(key: &str, value: Value) -> std::io::Result<()> {
    let file = settings_file();
    let mut settings = std::fs::read_to_string(&file)
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .filter(Value::is_object)
        .unwrap_or_else(|| json!({}));
    settings[key] = value;
    if let Some(parent) = file.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let temporary = file.with_extension("json.tmp");
    std::fs::write(&temporary, serde_json::to_vec(&settings)?)?;
    std::fs::rename(&temporary, &file)
}

const LANGUAGES: &[(&str, &str)] = &[
    ("en", "English"),
    ("de", "Deutsch"),
    ("fr", "Français"),
    ("es", "Español"),
    ("it", "Italiano"),
    ("pt", "Português"),
    ("nl", "Nederlands"),
    ("pl", "Polski"),
];

/// Settings › Language: the system's and the eight languages, "✓ " before the chosen one.
fn language_options() -> Vec<(&'static str, String)> {
    let saved = std::fs::read_to_string(settings_file())
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .and_then(|v| v.get("interface_language").and_then(Value::as_str).map(str::to_owned))
        .filter(|c| LANGUAGES.iter().any(|(code, _)| code == c))
        .unwrap_or_else(|| "auto".into());
    let system = i18n::system_language(|k| std::env::var(k).ok());
    let name = LANGUAGES.iter().find(|(c, _)| *c == system).map_or("English", |(_, n)| n);
    std::iter::once(("auto", trf("System ({0})", &[name])))
        .chain(LANGUAGES.iter().map(|(c, n)| (*c, n.to_string())))
        .map(|(c, label)| (c, if saved == c { format!("✓ {label}") } else { label }))
        .collect()
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
    ToggleSettings,
    ToggleLanguage,
    ToggleCorners,
    Language(&'static str),
    Corners(&'static str),
    SetShotKey(bool),
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
        let mut headphones = icon::from_name(ICON).size(size).symbolic(true).icon();
        if self.reading && !self.paused {
            // Green while reading, as every Maprisma bar icon that is on (Hue's lit bulb).
            headphones = headphones.class(lit_svg());
        }
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
            text::body(status).width(Length::Fill),
            // Settings at the header's right end, as in Maprisma Launcher.
            cosmic::widget::tooltip(
                button::icon(icon::from_name("emblem-system-symbolic").symbolic(true))
                    .on_press(Message::ToggleSettings),
                text::body(tr("Settings")),
                cosmic::widget::tooltip::Position::Bottom,
            ),
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

    /// Settings (as Maprisma Launcher's page): ← Back and the title, then one row per setting,
    /// words at the left and the control at the right; a list opens under its row.
    fn settings_page(&self) -> Element<'_, Message> {
        let header = row![
            button::text(tr("Back"))
                .leading_icon(icon::from_name("go-previous-symbolic").size(16))
                .on_press(Message::ToggleSettings),
            space::horizontal().width(Length::Fill),
            text::caption(tr("Settings").to_uppercase()).class(theme::Text::Custom(dim_text)),
        ]
        .align_y(Alignment::Center);
        let choice = |label: String, open: bool, message: Message| -> Element<'static, Message> {
            button::text(label)
                .trailing_icon(
                    icon::from_name(if open { "pan-up-symbolic" } else { "pan-down-symbolic" })
                        .size(16),
                )
                .on_press(message)
                .into()
        };
        let setting = |label: &str, control: Element<'static, Message>| {
            padded_control(
                row![
                    text::body(label.to_owned()),
                    space::horizontal().width(Length::Fill),
                    control
                ]
                .spacing(12)
                .align_y(Alignment::Center),
            )
        };
        let options = language_options();
        let current = options
            .iter()
            .find_map(|(_, l)| l.strip_prefix("✓ ").map(str::to_owned))
            .unwrap_or_default();
        let mut page = column![padded_control(header), divider::horizontal::default()];
        page = page.push(setting(
            tr("Language"),
            choice(current, self.language_open, Message::ToggleLanguage),
        ));
        if self.language_open {
            for (code, label) in options {
                page = page.push(menu_button(text::body(label)).on_press(Message::Language(code)));
            }
        }
        page = page.push(setting(
            tr("F12 saves a screenshot"),
            toggler(self.screenshot_key).on_toggle(Message::SetShotKey).into(),
        ));
        let desktop = corners::desktop_radius().round().to_string();
        let corner_choices = [
            ("desktop", trf("Like the desktop ({0} px)", &[&desktop])),
            ("slight", trf("Slightly rounded ({0} px)", &["6"])),
            ("rounded", trf("Rounded ({0} px)", &["12"])),
            ("square", tr("Square").to_owned()),
        ];
        let current = corner_choices
            .iter()
            .find(|(c, _)| *c == self.corners)
            .map(|(_, l)| l.clone())
            .unwrap_or_default();
        page = page.push(setting(
            tr("Corners"),
            choice(current, self.corners_open, Message::ToggleCorners),
        ));
        if self.corners_open {
            for (choice, label) in corner_choices {
                let label = if self.corners == choice { format!("✓ {label}") } else { label };
                page = page.push(menu_button(text::body(label)).on_press(Message::Corners(choice)));
            }
        }
        if self.setting_error {
            page = page.push(padded_control(text::body(tr("Could not save the setting."))));
        }
        scrollable(page.width(Length::Fixed(POPUP_WIDTH)).padding([0, 0, 8, 0]))
            .height(Length::Shrink)
            .into()
    }

    fn save(&mut self, key: &str, value: Value) {
        self.setting_error = save_setting(key, value).is_err();
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
        self.reset_page();
        match self.popup.take() {
            Some(popup) => {
                self.shot.closed(popup);
                destroy_popup(popup)
            }
            None => Task::none(),
        }
    }

    /// The popup opens on the menu again.
    fn reset_page(&mut self) {
        self.settings_open = shot_page_settings();
        self.language_open = false;
        self.corners_open = false;
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
        let mut core = core;
        crate::look::solid(&mut core);
        let mut app = Self {
            core,
            shot: Shot::new(SHOT_FOLDER),
            settings_open: shot_page_settings(),
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
                let menus = self.language_open || self.corners_open;
                return match escape(id, self.popup, self.shot.showing(id), menus, self.settings_open) {
                    Escape::Note => self.shot.update(ShotMsg::Escape(id), self.screenshot_key, true, Message::Shot),
                    Escape::Menus => {
                        self.language_open = false;
                        self.corners_open = false;
                        Task::none()
                    }
                    Escape::Back => {
                        self.settings_open = false;
                        Task::none()
                    }
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
            Message::ToggleSettings => {
                self.settings_open = !self.settings_open;
                self.language_open = false;
                self.corners_open = false;
            }
            Message::ToggleLanguage => {
                self.language_open = !self.language_open;
                self.corners_open = false;
            }
            Message::ToggleCorners => {
                self.corners_open = !self.corners_open;
                self.language_open = false;
            }
            Message::Language(code) => {
                self.save("interface_language", json!(code));
                self.language_open = false;
            }
            Message::Corners(choice) => {
                self.save("corners", json!(choice));
                self.corners_open = false;
                self.corners = choice.to_string();
                corners::set_current(&self.corners);
            }
            Message::SetShotKey(on) => {
                self.save("screenshot_key", json!(on));
                self.screenshot_key = on;
            }
            Message::Rectangle(update) => match update {
                RectangleUpdate::Rectangle(r) => self.rectangle = r.1,
                RectangleUpdate::Init(tracker) => self.tracker = Some(tracker),
            },
            Message::CloseRequested(id) => {
                self.shot.closed(id);
                if self.popup == Some(id) {
                    self.popup = None;
                    self.reset_page();
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
        crate::look::keep_fonts();
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
        crate::look::keep_fonts();
        let page = if self.settings_open { self.settings_page() } else { self.menu() };
        let content = match self.shot.card(id, Message::Shot) {
            Some(card) => column![card, page].width(Length::Fixed(POPUP_WIDTH)).into(),
            None => page,
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
    fn escape_closes_the_innermost_thing_first() {
        let popup = window::Id::unique();
        let other = window::Id::unique();
        assert_eq!(escape(popup, Some(popup), true, true, true), Escape::Note);
        assert_eq!(escape(popup, Some(popup), false, true, true), Escape::Menus);
        assert_eq!(escape(popup, Some(popup), false, false, true), Escape::Back);
        assert_eq!(escape(popup, Some(popup), false, false, false), Escape::ClosePopup);
        // Not from the open popup (e.g. the panel button): nothing.
        assert_eq!(escape(other, Some(popup), false, true, true), Escape::Nothing);
        assert_eq!(escape(popup, None, false, false, false), Escape::Nothing);
    }
}
