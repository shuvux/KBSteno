# kbsteno

Use a normal keyboard as a stenotype machine on Linux, Plover-style. One small Python file, one dependency, no compiling.

- Chord detection: keys are collected while you press and the stroke fires when **all keys are released**
- Types through a virtual keyboard (`uinput`), so it works on Wayland, X11 and TTYs
- Reads Plover-format JSON dictionaries
- Multi-stroke words (retroactive matching) and `*` undo
- Non-steno keys and Ctrl/Alt/Super shortcuts pass straight through
- Toggle steno on and off with a hotkey (F12 by default)
- Built-in rollover test to check whether your keyboard can handle chording

Developed and tested for Arch-based systems (Omarchy / Hyprland), but it should work on any Linux with evdev.

## Requirements

- Linux with `uinput` available
- Python 3.8+
- [`python-evdev`](https://python-evdev.readthedocs.io/)
- Optional: `notify-send` (libnotify) for on/off notifications

## Install

### Arch / Omarchy (automatic)

```bash
git clone https://github.com/<your-username>/kbsteno.git
cd kbsteno
chmod +x install.sh
./install.sh
```

The script installs `python-evdev`, adds you to the `input` group, sets up a udev rule for `/dev/uinput`, installs the program to `~/.local/bin/kbsteno`, and downloads Plover's main dictionary to `~/.config/kbsteno/dict.json`.

**Log out and back in once** afterwards so the group change applies.

### Other distros (manual)

```bash
pip install evdev            # or your distro's python-evdev package
sudo usermod -aG input "$USER"
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-kbsteno.rules
echo uinput | sudo tee /etc/modules-load.d/uinput.conf
sudo modprobe uinput && sudo udevadm control --reload-rules && sudo udevadm trigger
mkdir -p ~/.local/bin ~/.config/kbsteno
install -m755 kbsteno.py ~/.local/bin/kbsteno
```

Log out and back in, and make sure `~/.local/bin` is in your `PATH`.

## Usage

```bash
kbsteno --test     # check how many keys your keyboard can hold at once
kbsteno --dry      # practice mode: prints strokes instead of typing
kbsteno            # the real thing
```

| Flag | What it does |
| --- | --- |
| `--list` | List detected keyboards |
| `--device /dev/input/eventN` | Use a specific keyboard instead of auto-detecting |
| `--dict PATH` | Use a specific Plover-format JSON dictionary |
| `--dry` | Print strokes and output instead of typing |
| `-v`, `--verbose` | Print each stroke |
| `--timeout N` | Auto-quit after N seconds (handy for first tries, since the keyboard is grabbed while running) |
| `--test` | Show simultaneous key count (rollover / ghosting test) |

Press **F12** to toggle steno on and off. Press **Ctrl+C** in the terminal to quit.

### Check your keyboard first

Run `kbsteno --test` and press as many keys as you can at once. If the `max` count stalls below 6 to 8, or keys disappear, your keyboard ghosts or has limited rollover. Steno needs reliable chording, and no software can fix that. A mechanical keyboard with N-key rollover is ideal.

## Default key layout

Plover's default QWERTY map:

```
 1 2 3 4 5 6 7 8 9 0 - =      <- number bar (#)
 Q W E R T   Y U I O P        S- T- P- H- *  *  -F -P -L -T
 A S D F G   H J K L ; [ '    S- K- W- R- *  *  -R -B -G -S -D -Z
     C V       N M            A- O-         -E -U
```

Stroke order is always `# S T K P W H R A O * E U F R P B L G T S D Z`.

## Configuration

Optional file: `~/.config/kbsteno/config.json`

```json
{
  "toggle_key": "KEY_F12",
  "type_delay": 0.002,
  "keymap": {
    "S-": ["KEY_Q", "KEY_A"],
    "T-": ["KEY_W"]
  }
}
```

- `toggle_key`: any evdev key name
- `type_delay`: seconds between emulated key events. Raise it (e.g. `0.005`) if characters are dropped in some apps.
- `keymap`: overrides the **whole** default keymap, so include every steno key you want mapped. See `DEFAULT_KEYMAP` in `kbsteno.py` for the full list.

## Dictionaries

kbsteno uses the same JSON format as Plover (`{"KAT": "cat", "HEL/HRO": "hello"}`). Put one at `~/.config/kbsteno/dict.json`, or pass `--dict`. Entries from the file override a tiny built-in dictionary.

Supported dictionary formatting: plain text, suffix `{^ing}`, prefix `{con^}`, attach `{^}`, punctuation `{.} {,} {?} {!} {:} {;}`, capitalize next `{-|}`, and `=undo`. Other Plover commands and fingerspelling (`{&a}`) are ignored.

## Start on login (Hyprland)

Add this to your Hyprland autostart config:

```
exec-once = ~/.local/bin/kbsteno
```

## Troubleshooting

- **"Permission denied on /dev/input"**: you haven't logged out and back in since being added to the `input` group.
- **Can't create the virtual keyboard**: check that `uinput` is loaded (`lsmod | grep uinput`) and that `/dev/uinput` is group `input` with mode `0660`.
- **Wrong keyboard picked**: run `kbsteno --list`, then use `--device`.
- **Wrong characters typed**: output assumes a **US QWERTY** layout in your OS keyboard settings.
- **Keys stuck or missing during chords**: run `--test`. This is usually a keyboard rollover limit.
- **Keyboard unresponsive while running**: kbsteno grabs the keyboard exclusively. Switch to a TTY or SSH in and kill it, or use `--timeout` when experimenting.

## Limitations

- US QWERTY output only
- Partial Plover dictionary formatting support (see above)
- Single dictionary, no GUI
- Keyboard steno has no pressure sensitivity and is limited by your keyboard's rollover

## License

MIT. Add a `LICENSE` file before publishing, or swap in whichever license you prefer.
