"""Freezes: a game that locks up never "exits", so its logs rarely say anything.

What a freeze leaves behind instead:
- the kernel log (journald keeps it across reboots on SteamOS) records a GPU
  hang ("ring gfx timeout", "GPU reset") or the out-of-memory killer;
- Steam's console log has a launch that never ended, because the Deck was
  forced off with the power button or Steam was restarted.
"""

import os
import re
import signal
import subprocess
from datetime import datetime
from typing import Optional

KERNEL_PATTERNS = (
    ("gpu_hang", re.compile(r"ring \S+ timeout|GPU reset begin|amdgpu_job_timedout|GPU recovery", re.I)),
    ("out_of_memory", re.compile(r"Out of memory: Killed process|invoked oom-killer", re.I)),
)
OOM_VICTIM_RE = re.compile(r"Killed process \d+ \(([^)]+)\)")


def kernel_hits(lines) -> dict:
    """{"gpu_hang": line, "out_of_memory": line} for the first matching kernel message of each kind."""
    hits = {}
    for line in lines:
        for fid, pattern in KERNEL_PATTERNS:
            if fid not in hits and pattern.search(line):
                hits[fid] = line.strip()
    # Prefer the line naming what was killed over the "invoked oom-killer" one.
    for line in lines:
        if OOM_VICTIM_RE.search(line):
            hits["out_of_memory"] = line.strip()
            break
    return hits


def oom_victim(line: str) -> Optional[str]:
    m = OOM_VICTIM_RE.search(line or "")
    return m.group(1) if m else None


def kernel_log(since: datetime, until: Optional[datetime], run=None) -> list:
    """Kernel messages between two local times, across reboots. Empty if journald can't be read."""
    run = run or subprocess.run
    cmd = ["journalctl", "-k", "-q", "--no-pager", "-o", "short-iso",
           "--since", since.strftime("%Y-%m-%d %H:%M:%S")]
    if until:
        cmd += ["--until", until.strftime("%Y-%m-%d %H:%M:%S")]
    try:
        return run(cmd, capture_output=True, text=True, timeout=30).stdout.splitlines()
    except Exception:
        return []


def _belongs_to(pid: str, appid: int, proc: str) -> bool:
    """Process IDs get reused after a reboot, so check the process really is this game's."""
    for name, marker in (("cmdline", f"AppId={appid}"), ("environ", f"SteamGameId={appid}")):
        try:
            with open(os.path.join(proc, pid, name), "rb") as f:
                if f" {marker} ".encode() in b" " + f.read().replace(b"\0", b" ") + b" ":
                    return True
        except OSError:
            continue
    return False


def game_processes(appid: int, proc: str = "/proc") -> list:
    """Every running process Steam started for this game: launcher, Proton, Wine, the game, trainers."""
    try:
        pids = list(filter(str.isdigit, os.listdir(proc)))
    except OSError:
        return []
    return [p for p in pids if _belongs_to(p, appid, proc)]


def _children(proc: str) -> dict:
    tree = {}
    for pid in filter(str.isdigit, os.listdir(proc)):
        try:
            with open(os.path.join(proc, pid, "stat")) as f:
                # The name field is in parentheses and may contain spaces; the parent PID follows it.
                ppid = f.read().rsplit(")", 1)[1].split()[1]
        except (OSError, IndexError):
            continue
        tree.setdefault(ppid, []).append(pid)
    return tree


def force_close(appid: int, proc: str = "/proc", kill=os.kill) -> int:
    """Kill a frozen game and everything it started. Returns how many processes were killed.

    Steam only logs the last process it tracks (often the game's .exe), but the
    launcher, Proton, Wine and any trainer around it also have to go before
    Steam sees the game as closed. Every one of them carries the game's
    SteamGameId or AppId, so kill all of those and anything they started.
    """
    todo = game_processes(appid, proc)
    if not todo:
        return 0
    tree = _children(proc)
    victims = []
    while todo:
        pid = todo.pop()
        if pid not in victims:
            victims.append(pid)
            todo.extend(tree.get(pid, []))
    for pid in reversed(victims):
        try:
            kill(int(pid), signal.SIGKILL)
        except OSError:
            pass
    return len(victims)
