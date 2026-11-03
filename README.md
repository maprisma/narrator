# Screen Narrator for COSMIC

Reads any window, PDF or Kindle page aloud, and can **translate it first**. Screen Narrator
recognizes the text of a window with local OCR (Tesseract) and speaks it with a
local voice (Kokoro or Piper) in 51 languages. With **Translation → Speak in** it reads, say,
an English page and you hear it in German: translation runs through your own llama.cpp,
LM Studio or Ollama server, or offline with NLLB-200.

This is the COSMIC desktop version of the Omarchy plugin
[Screen Narrator](https://github.com/uBruckhaus/omarchy-simple-reader) and
[Screen Narrator for GNOME](../gnome-narrator):

- **`applet/` (`cosmic-narrator-applet`)** — the headphones icon and popup menu in the COSMIC panel (`libcosmic`).
- **`desktop/` (`cosmic-narrator-desktop`)** — the Wayland (`ext-foreign-toplevel-list`, `zcosmic-toplevel-info`, `zcosmic-toplevel-manager`, `wlr-layer-shell`) and D-Bus (`io.github.ubruckhaus.ScreenNarrator`) helper started by the applet for window tracking, screenshots (`grim`), area selection (`slurp`), page-turn keys (`wtype`), and live passage highlighting.
- **`settings/` (`screen-narrator-settings`)** — the Flutter desktop settings window (`Reading`, `Voice`, `Qwen voice`, `Speech server`, `Translation`, and top status/playback controls).
- **`backend/`** — the Python OCR/TTS reader (`ocrvox.service`), first-use setup (`setup_backend.py`), and JSON line bridge (`bridge.py`).

## Install

```sh
./install.sh
```

Installs for the current user (no root needed):

- `~/.local/bin/cosmic-narrator-applet`
- `~/.local/bin/cosmic-narrator-desktop`
- `~/.local/bin/screen-narrator-settings` (and bundle in `~/.local/share/cosmic-narrator/settings/`)
- `~/.local/share/cosmic-narrator/backend/`
- `~/.local/share/applications/io.github.ubruckhaus.CosmicScreenNarrator.desktop`
- `~/.local/share/applications/io.github.ubruckhaus.ScreenNarratorSettings.desktop`

Add **Screen Narrator** in **COSMIC Settings → Desktop → Panel → Applets**, or open **Screen Narrator Settings** (`screen-narrator-settings`) from the application launcher.

## Use

- **Headphones icon in the panel.** Left click opens the menu with **Start**, **Pause**, **Stop**,
  the reader's status, **Read the active window**, **Select reading area…**, the reading speed and
  **Settings…**. Right click starts or stops reading; middle click pauses. A green line appears under
  the icon while reading (amber while paused).
- **First use.** The menu and the top card of **Screen Narrator Settings** show what is missing and a
  **Set up automatically** button: it installs missing system packages (`imagemagick`, `tesseract`,
  `tesseract-data-<language>`, `mpv`, `libpulse`, `libnotify`, `grim`, `slurp`, `wtype`), a private
  Python runtime in `~/.local/share/kindle-reader`, and a voice for your language.
- **Settings (`screen-narrator-settings`)** apply at once: text language, speed, reading new pages,
  passage highlighting, PDF page only, Kindle toolbar crop, automatic page turning, reading area,
  voice and audio output, voices for other languages, Qwen3-TTS voice cloning, OpenAI-compatible
  speech servers, and translation (server and model, or the offline NLLB-200 translator, with a test).

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
