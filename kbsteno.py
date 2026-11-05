#!/usr/bin/env python3
"""kbsteno - use a normal keyboard as a steno machine (Plover-style) on Linux.

How it works:
  1. Grabs your keyboard exclusively via evdev (so keys don't leak to apps).
  2. Collects every steno key you press; when ALL keys are released, that's one stroke.
  3. Looks the stroke up in a Plover-format dictionary (JSON) and types the result
     through a virtual keyboard (uinput) - works on Wayland, X11 and TTYs.

Keys that aren't steno keys (space, enter, shift, arrows...) pass through untouched,
and anything pressed together with Ctrl/Alt/Super passes through too, so shortcuts work.
Press the toggle key (F12 by default) to switch steno on/off.
"""
import argparse
import copy
import json
import re
import select
import subprocess
import sys
import time
from pathlib import Path

try:
    import evdev
    from evdev import InputDevice, UInput, ecodes as e
except ImportError:
    sys.exit("Missing dependency. Run:  sudo pacman -S --needed python-evdev")

CONFIG_DIR = Path.home() / ".config" / "kbsteno"

# ---------------------------------------------------------------- steno basics
ORDER = ["#", "S-", "T-", "K-", "P-", "W-", "H-", "R-", "A-", "O-", "*",
         "-E", "-U", "-F", "-R", "-P", "-B", "-L", "-G", "-T", "-S", "-D", "-Z"]
NUMBERS = {"S-": "1", "T-": "2", "P-": "3", "H-": "4", "A-": "5", "O-": "0",
           "-F": "6", "-P": "7", "-L": "8", "-T": "9"}

# Plover's default QWERTY layout.
DEFAULT_KEYMAP = {
    "#": ["KEY_1", "KEY_2", "KEY_3", "KEY_4", "KEY_5", "KEY_6", "KEY_7", "KEY_8",
          "KEY_9", "KEY_0", "KEY_MINUS", "KEY_EQUAL"],
    "S-": ["KEY_Q", "KEY_A"], "T-": ["KEY_W"], "K-": ["KEY_S"], "P-": ["KEY_E"],
    "W-": ["KEY_D"], "H-": ["KEY_R"], "R-": ["KEY_F"],
    "A-": ["KEY_C"], "O-": ["KEY_V"],
    "*": ["KEY_T", "KEY_G", "KEY_Y", "KEY_H"],
    "-E": ["KEY_N"], "-U": ["KEY_M"],
    "-F": ["KEY_U"], "-R": ["KEY_J"], "-P": ["KEY_I"], "-B": ["KEY_K"],
    "-L": ["KEY_O"], "-G": ["KEY_L"], "-T": ["KEY_P"], "-S": ["KEY_SEMICOLON"],
    "-D": ["KEY_LEFTBRACE"], "-Z": ["KEY_APOSTROPHE"],
}

DEFAULT_CONFIG = {
    "toggle_key": "KEY_F12",   # on/off switch
    "type_delay": 0.002,       # seconds between emulated key events
    "keymap": DEFAULT_KEYMAP,
}

# Tiny built-in dictionary so it does something out of the box.
# Drop Plover's main.json at ~/.config/kbsteno/dict.json for the real thing.
BUILTIN_DICT = {
    "-T": "the", "SKP": "and", "TO": "to", "-F": "of", "KAT": "cat", "TKOG": "dog",
    "TEFT": "test", "TEFTS": "tests", "HEL/HRO": "hello", "WORLD": "world",
    "-G": "{^ing}", "-S": "{^s}", "-D": "{^ed}",
    "TP-PL": "{.}", "KW-BG": "{,}", "*": "=undo",
}

# Modifiers that make steno keys pass through (so Ctrl+C, Super+Q etc. still work).
BLOCK_MODS = {e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL, e.KEY_LEFTALT, e.KEY_RIGHTALT,
              e.KEY_LEFTMETA, e.KEY_RIGHTMETA}


def format_stroke(keys):
    """Set of steno keys -> Plover stroke string, e.g. {'H-','E','-L'} -> 'HEL'."""
    nums = "#" in keys and any(k in NUMBERS for k in keys)

    def ch(k):
        return NUMBERS[k] if nums and k in NUMBERS else k.strip("-")

    left = "".join(ch(k) for k in ORDER[1:8] if k in keys)
    mid = "".join(ch(k) for k in ORDER[8:13] if k in keys)
    right = "".join(ch(k) for k in ORDER[13:] if k in keys)
    out = ("#" if "#" in keys and not nums else "") + left + mid
    if right:
        out += right if mid else "-" + right
    return out


# ---------------------------------------------------------------- typing output
def _build_charmap():
    cm = {}
    for c in "abcdefghijklmnopqrstuvwxyz":
        code = e.ecodes["KEY_" + c.upper()]
        cm[c] = (code, False)
        cm[c.upper()] = (code, True)
    for c, n in zip("1234567890", "1234567890"):
        cm[c] = (e.ecodes["KEY_" + n], False)
    for c, n in zip("!@#$%^&*()", "1234567890"):
        cm[c] = (e.ecodes["KEY_" + n], True)
    plain = {" ": "SPACE", "\n": "ENTER", "\t": "TAB", "-": "MINUS", "=": "EQUAL",
             "[": "LEFTBRACE", "]": "RIGHTBRACE", "\\": "BACKSLASH", ";": "SEMICOLON",
             "'": "APOSTROPHE", "`": "GRAVE", ",": "COMMA", ".": "DOT", "/": "SLASH"}
    shifted = {"_": "MINUS", "+": "EQUAL", "{": "LEFTBRACE", "}": "RIGHTBRACE",
               "|": "BACKSLASH", ":": "SEMICOLON", '"': "APOSTROPHE", "~": "GRAVE",
               "<": "COMMA", ">": "DOT", "?": "SLASH"}
    for c, n in plain.items():
        cm[c] = (e.ecodes["KEY_" + n], False)
    for c, n in shifted.items():
        cm[c] = (e.ecodes["KEY_" + n], True)
    return cm


CHARMAP = _build_charmap()  # assumes a US QWERTY layout in the OS


class Typer:
    def __init__(self, ui, delay):
        self.ui, self.delay = ui, delay

    def _key(self, code, val):
        self.ui.write(e.EV_KEY, code, val)
        self.ui.syn()
        time.sleep(self.delay)

    def type(self, text):
        for ch in text:
            code, shift = CHARMAP[ch]
            if shift:
                self._key(e.KEY_LEFTSHIFT, 1)
            self._key(code, 1)
            self._key(code, 0)
            if shift:
                self._key(e.KEY_LEFTSHIFT, 0)

    def backspace(self, n):
        for _ in range(n):
            self._key(e.KEY_BACKSPACE, 1)
            self._key(e.KEY_BACKSPACE, 0)


class DryTyper:
    def type(self, text):
        print(f"   type: {text!r}")

    def backspace(self, n):
        if n:
            print(f"   backspace x{n}")


# ---------------------------------------------------------------- translation
def render(value, attach, cap):
    """Turn a dictionary value into text. Returns (text, attach_next, cap_next)."""
    out = ""
    for tok in re.split(r"(\{[^}]*\})", value):
        if not tok:
            continue
        if tok.startswith("{") and tok.endswith("}"):
            inner = tok[1:-1]
            if inner in (".", "?", "!"):
                out += inner
                attach, cap = False, True
            elif inner in (",", ":", ";"):
                out += inner
                attach = False
            elif inner == "-|":
                cap = True
            elif "^" in inner and not inner.startswith("PLOVER:"):
                lead, trail = inner.startswith("^"), inner.endswith("^")
                body = inner.strip("^")
                if not lead and not attach:
                    out += " "
                if body and cap:
                    body, cap = body[0].upper() + body[1:], False
                out += body
                attach = trail
            # any other {command} is ignored
        else:
            if not attach:
                out += " "
            if cap:
                tok, cap = tok[0].upper() + tok[1:], False
            out += tok
            attach = False
    return out, attach, cap


class Translator:
    def __init__(self, dic, typer):
        self.dic, self.typer = dic, typer
        self.maxlen = max((k.count("/") + 1 for k in dic), default=1)
        self.hist = []
        self.attach = False
        self.cap = False

    def stroke(self, s):
        if s == "*" or self.dic.get(s) == "=undo":
            return self.undo()
        # Retroactive multi-stroke matching: glue onto previous translations.
        for k in range(min(len(self.hist), self.maxlen - 1), 0, -1):
            prev = self.hist[-k:]
            strokes = [x for en in prev for x in en["strokes"]] + [s]
            if len(strokes) > self.maxlen:
                continue
            key = "/".join(strokes)
            if key in self.dic:
                return self._apply(prev, strokes, self.dic[key])
        return self._apply([], [s], self.dic.get(s, s))  # unknown -> raw steno

    def _apply(self, prev, strokes, value):
        if prev:
            self.typer.backspace(sum(len(en["text"]) for en in prev))
            self.attach, self.cap = prev[0]["before"]
            del self.hist[-len(prev):]
        before = (self.attach, self.cap)
        text, self.attach, self.cap = render(value, self.attach, self.cap)
        text = "".join(c for c in text if c in CHARMAP)
        self.typer.type(text)
        self.hist.append({"strokes": strokes, "text": text, "before": before})
        del self.hist[:-30]

    def undo(self):
        if not self.hist:
            return
        en = self.hist.pop()
        self.typer.backspace(len(en["text"]))
        self.attach, self.cap = en["before"]
        for s in en["strokes"][:-1]:  # un-merge a multi-stroke entry
            self.stroke(s)


# ---------------------------------------------------------------- setup helpers
def load_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    path = CONFIG_DIR / "config.json"
    if path.exists():
        cfg.update(json.loads(path.read_text()))
    return cfg


def load_dict(path):
    dic = dict(BUILTIN_DICT)
    p = Path(path) if path else CONFIG_DIR / "dict.json"
    if p.exists():
        dic.update(json.loads(p.read_text()))
        print(f"Loaded dictionary: {p} ({len(dic)} entries)")
    else:
        print(f"No dictionary at {p}; using the tiny built-in one.")
    return dic


def all_keyboards():
    devs = []
    for path in sorted(evdev.list_devices()):
        try:
            d = InputDevice(path)
        except PermissionError:
            sys.exit("Permission denied on /dev/input. Run install.sh, then log out and back in.")
        caps = d.capabilities().get(e.EV_KEY, [])
        if e.KEY_A in caps and e.KEY_SPACE in caps and "kbsteno" not in d.name:
            devs.append(d)
    return devs


def pick_device(path):
    if path:
        return InputDevice(path)
    devs = all_keyboards()
    if not devs:
        sys.exit("No keyboard found. Try:  kbsteno --list")
    for d in devs:
        if "keyboard" in d.name.lower():
            return d
    return devs[0]


def notify(msg):
    try:
        subprocess.Popen(["notify-send", "-t", "1500", "kbsteno", msg])
    except OSError:
        pass


# ---------------------------------------------------------------- modes
def cmd_list():
    for d in all_keyboards():
        print(f"{d.path}\t{d.name}")


def cmd_test(args):
    """Shows how many keys your keyboard registers at once (rollover check)."""
    dev = pick_device(args.device)
    print(f"Testing {dev.name}. Mash lots of keys at once; Ctrl+C to quit.\n"
          "If 'max' stops growing (or keys vanish) your keyboard ghosts/limits rollover.\n")
    held, mx = set(), 0
    try:
        for ev in dev.read_loop():
            if ev.type == e.EV_KEY and ev.value in (0, 1):
                (held.add if ev.value else held.discard)(ev.code)
                mx = max(mx, len(held))
                names = []
                for c in sorted(held):
                    n = e.KEY.get(c, c)
                    names.append((n[0] if isinstance(n, list) else str(n)).replace("KEY_", ""))
                print(f"\rheld={len(held):2d}  max={mx:2d}  {' '.join(names):<60}", end="", flush=True)
    except KeyboardInterrupt:
        print(f"\n\nMax simultaneous keys seen: {mx}")


def run(args):
    cfg = load_config()
    dev = pick_device(args.device)
    toggle = e.ecodes[cfg["toggle_key"]]
    rev = {}
    for steno, names in cfg["keymap"].items():
        for n in names:
            rev[e.ecodes[n]] = steno
    dic = load_dict(args.dict)

    ui = UInput({e.EV_KEY: list(range(1, 249))}, name="kbsteno virtual keyboard")
    typer = DryTyper() if args.dry else Typer(ui, cfg["type_delay"])
    tr = Translator(dic, typer)

    print(f"Keyboard: {dev.name} ({dev.path})")
    print(f"Steno is ON. {cfg['toggle_key']} toggles it. Ctrl+C (in the terminal) quits.")
    time.sleep(0.4)  # let the Enter key you just pressed be released first
    dev.grab()

    enabled = True
    down, chord, passed, held_mods = set(), set(), set(), set()
    deadline = time.time() + args.timeout if args.timeout else None

    def fwd(code, val):
        ui.write(e.EV_KEY, code, val)
        ui.syn()

    try:
        while True:
            wait = None
            if deadline:
                wait = deadline - time.time()
                if wait <= 0:
                    break
            if not select.select([dev.fd], [], [], wait)[0]:
                continue
            try:
                events = list(dev.read())
            except BlockingIOError:
                continue
            for ev in events:
                if ev.type != e.EV_KEY:
                    continue
                code, val = ev.code, ev.value

                if code in BLOCK_MODS:
                    (held_mods.add if val else held_mods.discard)(code)
                    fwd(code, val)
                    continue
                if code == toggle:
                    if val == 1:
                        enabled = not enabled
                        down.clear()
                        chord.clear()
                        notify("Steno ON" if enabled else "Steno OFF")
                        print("Steno", "ON" if enabled else "OFF")
                    continue
                steno = rev.get(code)
                if not enabled or steno is None:
                    fwd(code, val)
                    continue
                if code in passed:
                    fwd(code, val)
                    if val == 0:
                        passed.discard(code)
                    continue

                if val == 1:
                    if not down and held_mods:   # Ctrl+C etc: not a steno stroke
                        passed.add(code)
                        fwd(code, 1)
                        continue
                    down.add(code)
                    chord.add(steno)
                elif val == 0:
                    if code in down:
                        down.discard(code)
                        if not down:             # all fingers up -> stroke done
                            s = format_stroke(chord)
                            chord = set()
                            if args.verbose or args.dry:
                                print(f"stroke: {s}")
                            try:
                                tr.stroke(s)
                            except Exception as ex:  # never crash with the keyboard grabbed
                                print("error:", ex)
                    else:
                        fwd(code, 0)
                # val == 2 (autorepeat) is ignored for steno keys
    except (KeyboardInterrupt, OSError):
        pass
    finally:
        try:
            dev.ungrab()
        except OSError:
            pass
        ui.close()
        print("\nBye - keyboard released.")


def main():
    ap = argparse.ArgumentParser(description="Keyboard stenography for Linux")
    ap.add_argument("--list", action="store_true", help="list keyboards and exit")
    ap.add_argument("--test", action="store_true", help="test how many keys your keyboard can hold at once")
    ap.add_argument("--device", help="e.g. /dev/input/event3 (default: auto)")
    ap.add_argument("--dict", help="path to a Plover-format JSON dictionary")
    ap.add_argument("--dry", action="store_true", help="print strokes instead of typing")
    ap.add_argument("-v", "--verbose", action="store_true", help="print each stroke")
    ap.add_argument("--timeout", type=float, help="auto-quit after N seconds (safety for testing)")
    args = ap.parse_args()
    if args.list:
        cmd_list()
    elif args.test:
        cmd_test(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
