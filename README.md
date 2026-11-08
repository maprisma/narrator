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
