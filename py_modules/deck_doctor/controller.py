"""Controller layout check: a game's Steam Input layout where a main button does the wrong thing.

Real case: Assassin's Creed Mirage had a saved layout where the A button sent RB,
so nothing on the Deck sent A and the game felt broken.

Which layout Steam uses for a game on the Deck's built-in controller:
1. configset_<serial>.vdf for the Deck's own controller (the preferences_<serial>.vdf
   whose name is "Steam Deck Controller"), else configset_controller_neptune.vdf;
2. its entry for the app is a "template" (Steam's own, fine), a "workshop" layout
   (community, not checked) or "autosave" (the user's saved layout, read from
   <appid>/controller_neptune.vdf).
"""

import glob
import os
import re
from typing import Optional

from .diagnose import Finding, Fix

FACE = {"button_a": "A", "button_b": "B", "button_x": "X", "button_y": "Y"}
BUTTON_NAMES = {"A": "A", "B": "B", "X": "X", "Y": "Y", "SHOULDER_LEFT": "LB", "SHOULDER_RIGHT": "RB",
                "START": "Start (☰)", "SELECT": "View (⧉)", "JOYSTICK_LEFT": "L3", "JOYSTICK_RIGHT": "R3",
                "DPAD_UP": "D-pad up", "DPAD_DOWN": "D-pad down", "DPAD_LEFT": "D-pad left",
                "DPAD_RIGHT": "D-pad right"}
TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text: str) -> list:
    """VDF as nested [(key, value)] lists, keeping repeated keys such as "group"."""
    stack, cur, key = [], [], None
    for m in TOKEN_RE.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            child = []
            cur.append((key, child))
            stack.append(cur)
            cur, key = child, None
        elif brace == "}":
            cur = stack.pop() if stack else cur
        elif key is None:
            key = s
        else:
            cur.append((key, s))
            key = None
    return cur


def _get(node: list, key: str, default=None):
    return next((v for k, v in node if k == key), default)


def _all(node: list, key: str) -> list:
    return [v for k, v in node if k == key]


def _bindings(inp: list) -> list:
    """xinput buttons an input sends on a normal press."""
    out = []
    press = _get(_get(inp, "activators", []), "Full_Press", [])
    for b in _all(_get(press, "bindings", []), "binding") if isinstance(press, list) else []:
        m = re.match(r"xinput_button (\w+)", b)
        if m:
            out.append(m.group(1).upper())
    return out


def face_button_problems(layout_text: str) -> Optional[dict]:
    """{"missing": [...], "remapped": {"A": "SHOULDER_RIGHT"}} for the default action set, or None if fine."""
    root = _get(parse_vdf(layout_text), "controller_mappings", [])
    groups = {_get(g, "id"): g for g in _all(root, "group")}
    preset = next((p for p in _all(root, "preset") if _get(p, "id") == "0"), None)
    if preset is None:
        return None
    active = [gid for gid, src in _get(preset, "group_source_bindings", []) if src.endswith(" active")]
    sent, remapped = set(), {}
    for gid in active:
        group = groups.get(gid, [])
        source = dict(_get(preset, "group_source_bindings", [])).get(gid, "")
        for name, inp in _get(group, "inputs", []):
            outs = _bindings(inp)
            sent.update(outs)
            if source.startswith("button_diamond") and name in FACE and outs and FACE[name] not in outs:
                remapped[FACE[name]] = outs[0]
    missing = [b for b in "ABXY" if b not in sent]
    return {"missing": missing, "remapped": remapped} if missing or remapped else None


def deck_layout_entry(config_dir: str, appid: int) -> Optional[dict]:
    """The Deck's own controller entry for the app, e.g. {"template": "..."} or {"autosave": "1"}."""
    deck_sets = []
    for pref in glob.glob(os.path.join(config_dir, "preferences_*.vdf")):
        with open(pref, encoding="utf-8", errors="replace") as f:
            if '"Steam Deck Controller"' in f.read():
                serial = os.path.basename(pref)[len("preferences_"):-len(".vdf")]
                deck_sets.append(os.path.join(config_dir, f"configset_{serial}.vdf"))
    deck_sets.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
    for path in deck_sets + [os.path.join(config_dir, "configset_controller_neptune.vdf")]:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                root = parse_vdf(f.read())
        except OSError:
            continue
        entry = _get(_get(root, "controller_config", []), str(appid))
        if isinstance(entry, list):
            return dict(e for e in entry if isinstance(e[1], str))
    return None


def config_dirs(steam_root: str) -> list:
    dirs = glob.glob(os.path.join(steam_root, "steamapps", "common", "Steam Controller Configs", "*", "config"))
    return sorted(dirs, key=os.path.getmtime, reverse=True)


def check_layout(steam_root: str, appid: int) -> list:
    """Findings about the game's controller layout on the Deck's built-in controller."""
    for config_dir in config_dirs(steam_root):
        entry = deck_layout_entry(config_dir, appid)
        if entry is None:
            continue
        if "autosave" not in entry:
            return []  # one of Steam's templates or a community layout
        path = os.path.join(config_dir, str(appid), "controller_neptune.vdf")
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                problems = face_button_problems(f.read())
        except OSError:
            return []
        if not problems:
            return []
        parts = [f"{b} sends {BUTTON_NAMES.get(t, t)}" for b, t in problems["remapped"].items()]
        if problems["missing"]:
            parts.append("no button sends " + " or ".join(problems["missing"]))
        return [Finding(
            "controller_layout", "problem", "This game's controller layout has a button mixed up",
            "Steam is using a controller layout you saved for this game, and one of the main buttons "
            "doesn't do what the game expects, so the controls feel broken. Switch to one of Steam's "
            "standard layouts: Steam button → Controller Settings → Edit Layout → Templates → "
            "Gamepad with Joystick Trackpad → Apply.",
            evidence="In the saved layout, " + ", ".join(parts),
            fixes=[Fix("open_controller_settings", "Open controller settings")])]
    return []
