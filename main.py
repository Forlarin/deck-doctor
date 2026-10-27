import json
import os

import decky

import asyncio
import re

from deck_doctor import available_tools, diagnose, recent_games, steam
from deck_doctor.fixes import ALLOWED_VERBS, Job, run_protontricks, save_steps_to_desktop
from deck_doctor.health import move_plugin_to_backup, plugin_health

STEAM_ROOT = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "Steam")
UNDO_FILE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "undo.json")
GUIDES_DIR = os.path.join(decky.DECKY_PLUGIN_DIR, "docs", "fixes")


def _guide_text(finding_id: str) -> str:
    if not re.fullmatch(r"\w+", finding_id):
        raise ValueError("bad guide id")
    with open(os.path.join(GUIDES_DIR, f"{finding_id}.md"), encoding="utf-8") as f:
        # The "Still stuck?" footer links to GitHub, which the panel offers as its own button.
        return f.read().split("\n---\n")[0].strip()


def _load_undo() -> dict:
    try:
        with open(UNDO_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_undo(data: dict) -> None:
    os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)
    with open(UNDO_FILE, "w") as f:
        json.dump(data, f)


class Plugin:
    job = None  # the current or last background Protontricks run

    async def recent_games(self) -> list:
        return recent_games(STEAM_ROOT)

    async def checkup(self, appid: int) -> dict:
        report = diagnose(STEAM_ROOT, int(appid), decky.DECKY_USER_HOME)
        report["undo_tool"] = _load_undo().get(str(appid))
        decky.logger.info("checkup %s: %s", appid, [f["id"] for f in report["findings"]])
        return report

    async def tools(self) -> list:
        return available_tools(STEAM_ROOT)

    async def remember_tool(self, appid: int, previous: str) -> None:
        """Record the tool a game used before Deck Doctor changed it, so the change can be undone.

        Only the first change is kept: undo always returns to how the game was
        before Deck Doctor touched it. An empty string means "Steam's default".
        """
        undo = _load_undo()
        undo.setdefault(str(appid), previous or "")
        _save_undo(undo)

    async def forget_tool(self, appid: int) -> None:
        undo = _load_undo()
        undo.pop(str(appid), None)
        _save_undo(undo)

    async def plugin_health(self) -> dict:
        report = plugin_health(decky.DECKY_USER_HOME, STEAM_ROOT)
        decky.logger.info("plugin health: %s", [f["id"] for f in report["findings"]])
        return report

    async def move_plugin(self, folder: str) -> str:
        """The one action that needs root: Decky's plugins folder is owned by root."""
        dest = move_plugin_to_backup(decky.DECKY_USER_HOME, folder)
        decky.logger.info("moved plugin %s to %s", folder, dest)
        return dest

    async def guide(self, finding_id: str) -> str:
        return _guide_text(finding_id)

    async def save_guide_to_desktop(self, finding_id: str) -> str:
        text = _guide_text(finding_id)
        title = text.splitlines()[0].lstrip("# ").strip()
        return save_steps_to_desktop(decky.DECKY_USER_HOME, decky.DECKY_USER, title, text)

    async def start_fix(self, appid: int, verb: str) -> dict:
        """Start a background Protontricks fix. Only one runs at a time."""
        appid = int(appid)
        if verb not in ALLOWED_VERBS:
            raise ValueError(f"not an allowed fix: {verb}")
        if self.job and self.job.status == "running":
            return self.job.as_dict()
        launches = [l for l in steam.parse_launches(steam.console_lines(STEAM_ROOT)) if l.appid == appid]
        manifest = steam.app_manifest(STEAM_ROOT, appid)
        log = os.path.join(decky.DECKY_PLUGIN_LOG_DIR, f"protontricks-{appid}-{verb}.log")
        self.job = Job(appid, verb, log)
        decky.logger.info("starting fix %s for %s", verb, appid)
        asyncio.get_event_loop().create_task(run_protontricks(
            self.job, decky.DECKY_USER, manifest and manifest["_library"],
            bool(launches) and launches[-1].running))
        return self.job.as_dict()

    async def fix_status(self):
        return self.job.as_dict() if self.job else None

    async def _main(self):
        decky.logger.info("Deck Doctor loaded")

    async def _unload(self):
        pass
