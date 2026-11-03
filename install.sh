#!/usr/bin/env bash
# Build and install Screen Narrator for COSMIC for the current user (no root needed):
#   ~/.local/bin/cosmic-narrator-applet         the panel applet (headphones)
#   ~/.local/bin/cosmic-narrator-desktop        windows, screenshots, keys, highlight (the applet starts it)
#   ~/.local/bin/screen-narrator-settings       the settings window (Flutter), if it could be built
#   ~/.local/share/cosmic-narrator/backend/     the reader; "Set up automatically" in the menu installs it
# Needs for building: cargo; for the settings also flutter (FLUTTER, default /mnt/Data/flutter/bin/flutter),
# cmake and ninja. The reader needs grim, slurp and wtype (setup installs them).
set -euo pipefail
cd "$(dirname "$0")"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
bin="$HOME/.local/bin"
flutter="${FLUTTER:-/mnt/Data/flutter/bin/flutter}"

if command -v cargo >/dev/null; then
  cargo build --release
elif [[ ! -x target/release/cosmic-narrator-applet || ! -x target/release/cosmic-narrator-desktop ]]; then
  echo "cargo not found and prebuilt binaries are missing in target/release." >&2
  exit 1
fi
install -Dm755 target/release/cosmic-narrator-applet "$bin/cosmic-narrator-applet"
install -Dm755 target/release/cosmic-narrator-desktop "$bin/cosmic-narrator-desktop"

mkdir -p "$data/cosmic-narrator"
rm -rf "$data/cosmic-narrator/backend.new"
cp -r backend "$data/cosmic-narrator/backend.new"
find "$data/cosmic-narrator/backend.new" -name __pycache__ -prune -exec rm -rf {} +
rm -rf "$data/cosmic-narrator/backend"
mv "$data/cosmic-narrator/backend.new" "$data/cosmic-narrator/backend"

if command -v cmake >/dev/null && command -v ninja >/dev/null && [[ -x $flutter ]]; then
  (cd settings && "$flutter" build linux --release)
  rm -rf "$data/cosmic-narrator/settings"
  cp -r settings/build/linux/x64/release/bundle "$data/cosmic-narrator/settings"
  ln -sf "$data/cosmic-narrator/settings/screen-narrator-settings" "$bin/screen-narrator-settings"
  install -Dm644 data/io.github.ubruckhaus.ScreenNarratorSettings.desktop \
    "$data/applications/io.github.ubruckhaus.ScreenNarratorSettings.desktop"
  sed -i "s|^Exec=.*|Exec=$bin/screen-narrator-settings|" "$data/applications/io.github.ubruckhaus.ScreenNarratorSettings.desktop"
else
  echo "Settings window skipped: needs cmake, ninja and flutter ($flutter)." >&2
fi

# The panel starts applets without ~/.local/bin in PATH: the full path.
mkdir -p "$data/applications"
sed "s|^Exec=.*|Exec=$bin/cosmic-narrator-applet|" data/io.github.ubruckhaus.CosmicScreenNarrator.desktop \
  > "$data/applications/io.github.ubruckhaus.CosmicScreenNarrator.desktop"
echo "Installed. Add “Screen Narrator” in COSMIC Settings › Desktop › Panel › Applets."
