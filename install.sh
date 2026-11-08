#!/usr/bin/env bash
# Build and install Maprisma Narrator for the current user (no root needed):
#   ~/.local/bin/maprisma-narrator-applet         the panel applet (headphones)
#   ~/.local/bin/maprisma-narrator-desktop        windows, screenshots, keys, highlight (the applet starts it)
#   ~/.local/bin/maprisma-narrator       the settings window (Flutter), if it could be built
#   ~/.local/share/maprisma-narrator/backend/     the reader; "Set up automatically" in the menu installs it
# Needs for building: cargo; for the settings also flutter (FLUTTER, default /mnt/Data/flutter/bin/flutter),
# cmake and ninja. The reader needs grim, slurp and wtype (setup installs them).
set -euo pipefail
cd "$(dirname "$0")"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
bin="$HOME/.local/bin"
flutter="${FLUTTER:-/mnt/Data/flutter/bin/flutter}"

# Escape the Exec argument, then the desktop-entry string value layer.
# Percent signs are field codes even inside quotes.
desktop_entry() {
  python3 - "$1" "$2" "$3" <<'PYDESKTOP'
import pathlib, sys
source, destination, executable = sys.argv[1:]
argument = executable.replace('%', '%%')
argument = ''.join('\\' + c if c in '\\"`$' else c for c in argument)
value = ('"' + argument + '"').replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
target = pathlib.Path(destination)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text('\n'.join('Exec=' + value if line.startswith('Exec=') else line for line in pathlib.Path(source).read_text().splitlines()) + '\n')
PYDESKTOP
}

if command -v cargo >/dev/null; then
  cargo build --release --offline
elif [[ ! -x target/release/maprisma-narrator-applet || ! -x target/release/maprisma-narrator-desktop || ! -x target/release/maprisma-narrator-tray ]]; then
  echo "cargo not found and prebuilt binaries are missing in target/release." >&2
  exit 1
fi
install -Dm755 target/release/maprisma-narrator-tray "$bin/maprisma-narrator-tray"
install -Dm755 target/release/maprisma-narrator-applet "$bin/maprisma-narrator-applet"
install -Dm755 target/release/maprisma-narrator-desktop "$bin/maprisma-narrator-desktop"

mkdir -p "$data/maprisma-narrator"
rm -rf "$data/maprisma-narrator/backend.new"
cp -r backend "$data/maprisma-narrator/backend.new"
find "$data/maprisma-narrator/backend.new" -name __pycache__ -prune -exec rm -rf {} +
rm -rf "$data/maprisma-narrator/backend"
mv "$data/maprisma-narrator/backend.new" "$data/maprisma-narrator/backend"

if command -v cmake >/dev/null && command -v ninja >/dev/null && [[ -x $flutter ]]; then
  (cd settings && "$flutter" build linux --release)
  rm -rf "$data/maprisma-narrator/settings"
  cp -r settings/build/linux/x64/release/bundle "$data/maprisma-narrator/settings"
  ln -sf "$data/maprisma-narrator/settings/maprisma-narrator" "$bin/maprisma-narrator"
  install -Dm644 data/com.maprisma.Narrator.desktop \
    "$data/applications/com.maprisma.Narrator.desktop"
  desktop_entry data/com.maprisma.Narrator.desktop "$data/applications/com.maprisma.Narrator.desktop" "$bin/maprisma-narrator"
else
  echo "Settings window skipped: needs cmake, ninja and flutter ($flutter)." >&2
fi

# The panel starts applets without ~/.local/bin in PATH: the full path.
mkdir -p "$data/applications"
desktop_entry data/io.github.ubruckhaus.CosmicMaprismaNarrator.desktop "$data/applications/io.github.ubruckhaus.CosmicMaprismaNarrator.desktop" "$bin/maprisma-narrator-applet"
desktop_entry data/com.maprisma.Narrator.Desktop.desktop "$data/applications/com.maprisma.Narrator.Desktop.desktop" "$(readlink -f "$bin/maprisma-narrator-desktop")"
desktop_entry data/com.maprisma.Narrator.Tray.desktop "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/com.maprisma.Narrator.Tray.desktop" "$bin/maprisma-narrator-tray"
echo "Installed. Add “Maprisma Narrator” in COSMIC Settings › Desktop › Panel › Applets."
