#!/usr/bin/env bash
# One-shot installer for kbsteno on Arch / Omarchy.
set -e
cd "$(dirname "$0")"

echo "==> Installing dependency (python-evdev)"
sudo pacman -S --needed --noconfirm python-evdev libnotify

echo "==> Letting your user read keyboards and create a virtual keyboard"
sudo usermod -aG input "$USER"
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-kbsteno.rules >/dev/null
echo uinput | sudo tee /etc/modules-load.d/uinput.conf >/dev/null
sudo modprobe uinput
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "==> Installing the program to ~/.local/bin/kbsteno"
mkdir -p "$HOME/.local/bin" "$HOME/.config/kbsteno"
install -m755 kbsteno.py "$HOME/.local/bin/kbsteno"

DICT="$HOME/.config/kbsteno/dict.json"
if [ ! -f "$DICT" ]; then
  echo "==> Downloading Plover's main dictionary"
  curl -fL -o "$DICT" \
    https://raw.githubusercontent.com/openstenoproject/plover/main/plover/assets/main.json \
    || echo "   (download failed - you can add it later, the built-in mini dictionary still works)"
fi

echo
echo "Done. LOG OUT AND BACK IN (or reboot) once so the 'input' group applies, then run:  kbsteno --test"
