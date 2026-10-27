"""Fixes that normally need Desktop Mode, run from Game Mode instead.

Protontricks (the Flathub app) installs Windows runtimes such as .NET into a
game's Proton prefix. Deck Doctor runs it in the background as the normal
`deck` user, never as root, and only for the verbs in ALLOWED_VERBS.
"""

import asyncio
import os
import pwd
import time
from typing import Optional

PROTONTRICKS = "com.github.Matoking.protontricks"

# Winetricks verbs Deck Doctor may run, with a label for the UI.
ALLOWED_VERBS = {
    "dotnet48": ".NET Framework 4.8",
    "vcrun2022": "Visual C++ 2015-2022 runtimes",
}


def user_command(user: str, args: list) -> list:
    """Wrap a command so it runs as `user` with their desktop session environment.

    Deck Doctor's backend runs as root (for moving plugin folders), but
    Protontricks and Flatpak must run as the user who owns the game's files.
    """
    uid = pwd.getpwnam(user).pw_uid
    home = pwd.getpwnam(user).pw_dir
    env = [f"HOME={home}", f"USER={user}", f"XDG_RUNTIME_DIR=/run/user/{uid}",
           f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus"]
    if os.geteuid() == 0:
        return ["runuser", "-u", user, "--", "env", *env, *args]
    return ["env", *env, *args]


def protontricks_installed(run=None) -> bool:
    import subprocess
    run = run or subprocess.run
    try:
        return run(["flatpak", "info", PROTONTRICKS], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def needs_sd_access(library: Optional[str]) -> bool:
    """Flatpak Protontricks can't see games on an SD card or extra drive until granted access."""
    return bool(library) and library.startswith("/run/media/")


class Job:
    """One background Protontricks run. Only one runs at a time."""

    def __init__(self, appid: int, verb: str, log_path: str):
        self.appid, self.verb, self.log_path = appid, verb, log_path
        self.status = "running"     # running | done | failed
        self.step = "Starting"
        self.message = ""
        self.started = time.time()
        self.finished: Optional[float] = None

    def as_dict(self) -> dict:
        tail = ""
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as f:
                lines = [l.strip() for l in f.read().splitlines() if l.strip()]
            tail = lines[-1][:160] if lines else ""
        except OSError:
            pass
        return {
            "appid": self.appid, "verb": self.verb, "label": ALLOWED_VERBS.get(self.verb, self.verb),
            "status": self.status, "step": self.step, "message": self.message, "last_line": tail,
            "elapsed": int((self.finished or time.time()) - self.started),
        }


async def _run(cmd: list, log, timeout: float) -> int:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=log, stderr=log, stdin=asyncio.subprocess.DEVNULL)
    try:
        return await asyncio.wait_for(proc.wait(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise


async def run_protontricks(job: Job, user: str, library: Optional[str], game_running: bool) -> None:
    """Install Protontricks if needed, grant SD card access if needed, then run the verb."""
    if job.verb not in ALLOWED_VERBS:
        job.status, job.message = "failed", f"Not an allowed fix: {job.verb}"
        return
    if game_running:
        job.status, job.message = "failed", "Close the game first, then try again."
        return
    os.makedirs(os.path.dirname(job.log_path), exist_ok=True)
    with open(job.log_path, "w") as log:
        try:
            if not protontricks_installed():
                job.step = "Installing Protontricks"
                code = await _run(["flatpak", "install", "--system", "-y", "--noninteractive",
                                   "flathub", PROTONTRICKS], log, 900)
                if code != 0:
                    raise RuntimeError("Couldn't install Protontricks. Is the Deck online?")
            if needs_sd_access(library):
                job.step = "Letting Protontricks see your SD card"
                await _run(user_command(user, ["flatpak", "override", "--user",
                                               "--filesystem=/run/media", PROTONTRICKS]), log, 60)
            job.step = f"Installing {ALLOWED_VERBS[job.verb]} (this can take 5-15 minutes)"
            code = await _run(user_command(user, ["flatpak", "run", PROTONTRICKS, str(job.appid),
                                                  "-q", job.verb]), log, 3600)
            if code != 0:
                raise RuntimeError("Protontricks reported an error. The last line of its log is shown above.")
            job.status, job.step = "done", "Finished"
            job.message = f"{ALLOWED_VERBS[job.verb]} is installed. Launch the game to try it."
        except asyncio.TimeoutError:
            job.status, job.message = "failed", "It took over an hour and was stopped."
        except Exception as e:  # report anything else to the panel instead of failing silently
            job.status, job.message = "failed", str(e)
        finally:
            job.finished = time.time()


def save_steps_to_desktop(home: str, user: str, title: str, markdown: str) -> str:
    """Write a guide to ~/Desktop as plain text, so it's waiting in Desktop Mode."""
    desktop = os.path.join(home, "Desktop")
    os.makedirs(desktop, exist_ok=True)
    safe = "".join(c for c in title if c.isalnum() or c in " -_").strip()[:60] or "Fix"
    path = os.path.join(desktop, f"Deck Doctor - {safe}.txt")
    with open(path, "w") as f:
        f.write(markdown.replace("**", "").replace("`", ""))
    if os.geteuid() == 0:
        pw = pwd.getpwnam(user)
        os.chown(path, pw.pw_uid, pw.pw_gid)
    return path
