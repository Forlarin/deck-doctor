"""Read-only helpers for Steam's files on disk.

Everything here only reads. Changes (switching Proton, verifying files) are
made from the frontend through Steam's own client API, the same way the
game's Properties menu does it.
"""

import glob
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

LINE_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)$")
ADDED_RE = re.compile(r'^Game process (added|updated) : AppID (\d+) "(.*)", ProcID (\d+)')
REMOVED_RE = re.compile(r'^Game process removed: AppID (\d+) ".*", ProcID (\d+)')
PROTON_RE = re.compile(r"(?:steamapps/common|compatibilitytools\.d)/([^/]+?)'?/proton ")


@dataclass
class Launch:
    appid: int
    start: datetime
    end: Optional[datetime] = None
    command: str = ""
    proc_ids: set = field(default_factory=set)

    @property
    def running(self) -> bool:
        return self.end is None

    @property
    def seconds(self) -> Optional[float]:
        return None if self.end is None else (self.end - self.start).total_seconds()

    @property
    def proton(self) -> Optional[str]:
        """Display name of the compatibility tool, e.g. "Proton 10.0", or None for native games."""
        m = PROTON_RE.search(self.command)
        return m.group(1) if m else None

    @property
    def launch_env(self) -> str:
        """The launch-options part Steam puts before its own wrapper, e.g. env vars."""
        i = self.command.find("/ubuntu12_32/steam-launch-wrapper")
        if i == -1:
            return ""
        head = self.command[:i]
        return head[: head.rfind(" ")].strip() if " " in head else ""


def _read_lines(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def parse_launches(lines) -> list:
    """Turn console_log lines into a list of Launch records, oldest first.

    A launch starts when Steam adds a game process while none is running for
    that app, and ends when the last of its processes is removed.
    """
    launches, current = [], {}
    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        when = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        text = m.group(2)
        if a := ADDED_RE.match(text):
            kind, appid, cmd, pid = a.group(1), int(a.group(2)), a.group(3), a.group(4)
            launch = current.get(appid)
            if launch is None:
                launch = current[appid] = Launch(appid, when)
                launches.append(launch)
            launch.command = cmd
            # "updated" means Steam now tracks a different process for the same launch
            # (launcher -> game), so it replaces the previous PID rather than adding one.
            if kind == "updated":
                launch.proc_ids.clear()
            launch.proc_ids.add(pid)
        elif r := REMOVED_RE.match(text):
            appid, pid = int(r.group(1)), r.group(2)
            launch = current.get(appid)
            if launch:
                launch.proc_ids.discard(pid)
                if not launch.proc_ids:
                    launch.end = when
                    del current[appid]
    return launches


def console_lines(steam_root: str) -> list:
    logs = os.path.join(steam_root, "logs")
    return _read_lines(os.path.join(logs, "console_log.previous.txt")) + _read_lines(
        os.path.join(logs, "console_log.txt")
    )


def library_folders(steam_root: str) -> list:
    """Every steamapps folder: internal storage plus SD cards / extra drives."""
    folders = [os.path.join(steam_root, "steamapps")]
    text = "\n".join(_read_lines(os.path.join(steam_root, "steamapps", "libraryfolders.vdf")))
    for path in re.findall(r'"path"\s+"([^"]+)"', text):
        sa = os.path.join(path, "steamapps")
        if sa not in folders:
            folders.append(sa)
    return folders


def app_manifest(steam_root: str, appid: int) -> Optional[dict]:
    for sa in library_folders(steam_root):
        path = os.path.join(sa, f"appmanifest_{appid}.acf")
        if os.path.exists(path):
            text = "\n".join(_read_lines(path))
            info = dict(re.findall(r'^\s*"(\w+)"\s+"([^"]*)"', text, re.M))
            info["_library"] = sa
            return info
    return None


def _vdf_block(text: str, key: str) -> list:
    """Bodies of every `"key" { ... }` block in a VDF file."""
    out = []
    for m in re.finditer(r'"%s"\s*\{' % re.escape(key), text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out.append(text[m.end():i - 1])
    return out


def launch_options(steam_root: str, appid: int) -> Optional[str]:
    """The game's launch options as typed in Steam (Properties → Launch Options), or None."""
    paths = glob.glob(os.path.join(steam_root, "userdata", "*", "config", "localconfig.vdf"))
    for path in sorted(paths, key=os.path.getmtime, reverse=True):
        text = "\n".join(_read_lines(path))
        for body in _vdf_block(text, str(appid)):
            m = re.search(r'^\s*"LaunchOptions"\s+"((?:[^"\\]|\\.)*)"', body, re.M)
            if m:
                return re.sub(r'\\(.)', r'\1', m.group(1))  # VDF escapes " and \ with a backslash
    return None


def compat_tool_for(steam_root: str, appid: int) -> Optional[str]:
    """Internal name of the tool forced for this game (e.g. "proton_10"), or None if it uses the default."""
    text = "\n".join(_read_lines(os.path.join(steam_root, "config", "config.vdf")))
    start = text.find('"CompatToolMapping"')
    if start == -1:
        return None
    m = re.search(r'"%d"\s*\{\s*"name"\s*"([^"]*)"' % appid, text[start:])
    return m.group(1) or None if m else None


def internal_tool_name(display: str) -> Optional[str]:
    """Map a Valve Proton folder name to Steam's internal tool name.

    "Proton - Experimental" -> "proton_experimental", "Proton 10.0" -> "proton_10",
    "Proton 6.3" -> "proton_63". Custom tools (GE-Proton) use their folder's
    compatibilitytool.vdf name instead, handled in installed_tools().
    """
    if "Experimental" in display:
        return "proton_experimental"
    m = re.match(r"Proton (\d+)\.(\d+)", display)
    if not m:
        return None
    major, minor = m.groups()
    return f"proton_{major}" if minor == "0" else f"proton_{major}{minor}"


def installed_tools(steam_root: str) -> list:
    """[{"name": internal name, "label": display name}] for every installed Proton."""
    tools = []
    for sa in library_folders(steam_root):
        common = os.path.join(sa, "common")
        for d in sorted(os.listdir(common)) if os.path.isdir(common) else []:
            if d.startswith("Proton") and (name := internal_tool_name(d)):
                tools.append({"name": name, "label": d})
    custom = os.path.join(steam_root, "compatibilitytools.d")
    for d in sorted(os.listdir(custom)) if os.path.isdir(custom) else []:
        vdf = "\n".join(_read_lines(os.path.join(custom, d, "compatibilitytool.vdf")))
        m = re.search(r'"compat_tools"\s*\{\s*"([^"]+)"', vdf)
        if m and "proton" in d.lower():
            tools.append({"name": m.group(1), "label": d})
    return tools
