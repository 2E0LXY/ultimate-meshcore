#!/bin/sh
# Installs Ultimate MeshCore Desktop for the current user.
set -e
cd "$(dirname "$0")"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/256x256/apps"
install -m 755 ultimate-meshcore-desktop "$HOME/.local/bin/ultimate-meshcore-desktop"
install -m 644 icon.png "$HOME/.local/share/icons/hicolor/256x256/apps/ultimate-meshcore-desktop.png"
install -m 644 ultimate-meshcore-desktop.desktop "$HOME/.local/share/applications/ultimate-meshcore-desktop.desktop"
echo "Installed. Start it from your applications menu, or run: ultimate-meshcore-desktop"
if ! id -nG | grep -qw dialout; then
  echo
  echo "For USB radios your account needs serial port access. Run this once, then log out and in:"
  echo "  sudo usermod -aG dialout $USER"
fi
