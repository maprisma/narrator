# Maprisma Narrator

Reads any window, PDF or Kindle page aloud, and can **translate it first**. Maprisma Narrator
recognizes the text of a window with local OCR (Tesseract) and speaks it with a
local voice (Kokoro or Piper) in 51 languages. With **Translation → Speak in** it reads, say,
an English page and you hear it in German: translation runs through your own llama.cpp,
LM Studio or Ollama server, or offline with NLLB-200.

Part of the [Maprisma](https://github.com/maprisma) apps for the COSMIC desktop. It grew out of the
Omarchy plugin [Screen Narrator](https://github.com/uBruckhaus/omarchy-simple-reader). Its parts:

- **`applet/` (`maprisma-narrator-applet`)** — the headphones icon and popup menu in the COSMIC panel (`libcosmic`).
- **`desktop/` (`maprisma-narrator-desktop`)** — the Wayland (`ext-foreign-toplevel-list`, `zcosmic-toplevel-info`, `zcosmic-toplevel-manager`, `wlr-layer-shell`) and D-Bus (`com.maprisma.Narrator.Desktop`) helper started by the applet for window tracking, screenshots (`grim`), area selection (`slurp`), page-turn keys (`wtype`), and live passage highlighting.
- **`settings/` (`maprisma-narrator`)** — the Flutter desktop settings window (`Reading`, `Voice`, `Qwen voice`, `Speech server`, `Translation`, and top status/playback controls).
- **`backend/`** — the Python OCR/TTS reader (`ocrvox.service`), first-use setup (`setup_backend.py`), and JSON line bridge (`bridge.py`).

## Install

```sh
./install.sh
```

Installs for the current user (no root needed):

- `~/.local/bin/maprisma-narrator-applet`
- `~/.local/bin/maprisma-narrator-desktop`
- `~/.local/bin/maprisma-narrator` (and bundle in `~/.local/share/maprisma-narrator/settings/`)
- `~/.local/share/maprisma-narrator/backend/`
- `~/.local/share/applications/io.github.ubruckhaus.CosmicMaprismaNarrator.desktop`
- `~/.local/share/applications/com.maprisma.Narrator.desktop`

Add **Maprisma Narrator** in **COSMIC Settings → Desktop → Panel → Applets**, or open **Maprisma Narrator** (`maprisma-narrator`) from the application launcher.

## Use

- **Headphones icon in the panel.** Left click opens the menu with **Start**, **Pause**, **Stop**,
  the reader's status, **Read the active window**, **Select reading area…**, the reading speed and
  **Settings…**. Right click starts or stops reading; middle click pauses. A green line appears under
  the icon while reading (amber while paused).
- **First use.** The menu and the top card of **Maprisma Narrator** show what is missing and a
  **Set up automatically** button: it installs missing system packages (`imagemagick`, `tesseract`,
  `tesseract-data-<language>`, `mpv`, `libpulse`, `libnotify`, `grim`, `slurp`, `wtype`), a private
  Python runtime in `~/.local/share/kindle-reader`, and a voice for your language.
- **Settings (`maprisma-narrator`)** apply at once: text language, speed, reading new pages,
  passage highlighting, PDF page only, Kindle toolbar crop, automatic page turning, reading area,
  voice and audio output, voices for other languages, Qwen3-TTS voice cloning, OpenAI-compatible
  speech servers, and translation (server and model, or the offline NLLB-200 translator, with a test).

## F12: a screenshot with a note

While the panel popup or the settings window (`maprisma-narrator`) has the keyboard, **F12** (without Ctrl, Shift, Alt or Super) saves a picture of it, for telling what is wrong with it, as in the other Maprisma apps:

- **Only on F12, and only that popup or window.** The popup is drawn once more by iced into the picture (`window::screenshot`, encoded as PNG in the applet), the settings window by Flutter (`RepaintBoundary.toImage`, dialogs included). No screenshot program runs (the reader's `grim` captures are not involved), nothing else on the screen is in it, and nothing is uploaded or sent anywhere. Not captured: the KDE tray's menu (drawn by Plasma), the passage highlight and the area selection (layer surfaces without keyboard).
- **Where:** `~/Pictures/Maprisma Narrator/maprisma-narrator-<date>-<time>.png`. The pictures folder comes from `~/.config/user-dirs.dirs` when it is set there (read only as a regular file of at most 64 KiB, never through a link). The app then names the file and asks **What is wrong? (optional)**; **Enter** or **Done** saves the text next to the picture as a `.txt` with the same name (at most 4000 characters; no text, no file), **Esc** skips it, and closing the popup keeps what was typed. F12 waits until that is closed.
- **Private files:** the folder is made `0700` when missing and only used when it is a real folder of yours (not a link) that no one else can write to, checked on the opened folder; pictures and notes are new `0600` files made inside that folder, never through a link and never over an existing file (`-2`, `-3` … are added instead, also when only a note has the name), synced to disk, and removed again when they cannot be written completely.
- **Off:** switch **F12 saves a screenshot** off in the settings window (top group, below Language); stored as `"screenshot_key": false` in `$XDG_CONFIG_HOME/maprisma-narrator/settings.json` (next to `interface_language`); the applet picks it up within a second.

## Corners

**Corners** in the settings window (below Language): *Like the desktop (N px)* (the default: the COSMIC theme exactly as it is, the native look; N is the theme's medium corner radius, 16, 8 or 2 px by COSMIC Settings › Appearance, 16 px where there is no COSMIC theme, e.g. on KDE), *Slightly rounded (6 px)*, *Rounded (12 px)* or *Square*, as in the other Maprisma COSMIC apps. With one of the last three, popups, cards, the note card and drop-down menus take that radius; drop-downs, text fields and menu rows at most 8 px; small parts (bars and their tracks, slider tracks, check boxes) at most 4 px; pills (libcosmic's buttons and toggles, round dots) stay round, or square in *Square*. In the applet's popup: libcosmic's widgets take their corners from the theme, so the popup's content is drawn with a copy of the active theme with these corner radii (iced's `themer`); slider knobs take the full radius. The panel button keeps the panel's look. In the settings window, *Like the desktop* keeps Material's own corners; otherwise cards and dialogs take the radius, buttons and choice buttons at most 8 px, check boxes at most 4 px; Material's switches stay pills, and the borderless text fields have no corners. The reading highlight keeps its own look. Stored as `"corners"` (`desktop`, `slight`, `rounded`, `square`) in the same `settings.json`; a file without it stays valid and means *Like the desktop*.

## Tests

```sh
# Flutter settings tests & static analysis
cd settings
/mnt/Data/flutter/bin/flutter test
/mnt/Data/flutter/bin/flutter analyze

# Python setup & reader tests
cd ../backend
PYTHONPATH=.:reader python3 -m unittest test_setup
QT_QPA_PLATFORM=offscreen ~/.local/share/kindle-reader/venv/bin/python -m unittest discover -s reader -p 'test_*.py'
```

MIT license.

## KDE Plasma

On **KDE Plasma 6.8 Wayland**, `./install.sh` also installs
`~/.local/bin/maprisma-narrator-tray` and a KDE-only autostart entry at
`~/.config/autostart/com.maprisma.Narrator.Tray.desktop` (respecting XDG overrides).
Log in again, or run the installed tray executable. Use either the tray or the
COSMIC applet in a session. The tray supervises the same desktop helper.

The tray's context menu offers Start, Pause/Resume, Stop, reader status, setup and
repair actions, Read the active window, Select reading area…, Reset reading area,
reading speed presets (0.60–2.00×), and Settings…. **Activate (normally left click)
starts/stops reading; middle click pauses/resumes; right click opens the menu.**
The icon changes for reading/paused state and exposes the reader status in its tooltip.

The helper selects KWin on KDE, or when the COSMIC window globals are absent.
It polls windows through short-lived KWin scripts, captures windows/areas through
KWin ScreenShot2, sends page keys through KDE fake-input, and keeps the existing
layer-shell passage highlight and `slurp` area selector. It preserves the Python
reader and `com.maprisma.Narrator.Desktop` interface. COSMIC retains its existing
window protocols, `grim` captures and `wtype` keys.

The installed hidden `com.maprisma.Narrator.Desktop.desktop` grants ScreenShot2
and fake-input access to the helper's **real installed executable path**. Run the
installed helper through the tray: a binary under `target/` does not match that
permission entry. KDE does not require `grim` or `wtype` for helper operations;
the unchanged backend setup may still list/install them. `slurp` is required.
Minimized windows and windows on other desktops are excluded from capture/key
operations; temporary focus for a page turn is restored when still appropriate.

Rust verification (offline registry required):

```sh
cargo test --offline
cargo build --release --offline
```

Live validation on Plasma is still required for compositor permissions, scaling,
focus restoration, area selection, highlights and the tray host; Rust tests cover
window mapping, page-key mapping, screenshot pixels and the menu model.

## Interface languages

The settings window has a **Language** choice at the top: **System (<name>)** or
English, Deutsch, Français, Español, Italiano, Português, Nederlands, or Polski.
System uses the first non-empty `LC_ALL`, `LC_MESSAGES`, or `LANG`; unsupported
languages fall back to English. This choice is separate from the reader's text,
voice, and translation languages. It is stored as `interface_language` (`auto` or
a language code) in `$XDG_CONFIG_HOME/maprisma-narrator/settings.json`, defaulting
to `~/.config/maprisma-narrator/settings.json`. The settings window changes
immediately; the applet and tray pick up changes on their next refresh.

English wording is the gettext-style key: `tr('Start')` or
`trf('Reading: {0}', [window])`. Catalogs are bundled; nothing is downloaded.
No reader/narrator catalog was found in `/mnt/Data/Projects/omarchy*` (the only
translation directories found were AI Playground and AI Agents Map), so the base
`translations/<code>.json` files are empty and this port's translations live in
`translations/extra/<code>.json`. No original repository was modified.

After editing catalogs, run `tools/gen-translations`. It generates
`translations/compiled.json` for Rust, `settings/lib/translations.g.dart` for
Flutter, and `backend/translations_generated.py` for the setup bridge. Commit
these generated files with their catalogs. Check coverage, placeholders, desktop
entries, locale fallback, and generated-file consistency with:

```sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s backend -p 'test_*.py'
cargo test --offline
cd settings && flutter test --no-pub
```

The shared `backend/reader/` runtime is unchanged. The port translates common
runtime statuses and readiness messages at its presentation boundaries; unknown
runtime messages, external tool output, and operating-system diagnostics retain
their original text. Device/model names, paths, filenames, book titles, and other
data retain their supplied values. Reader-generated desktop notifications are
still emitted by the unchanged shared runtime and may remain English.
