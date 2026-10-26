import json
import os

import decky

from deck_doctor import available_tools, diagnose, recent_games
from deck_doctor.health import move_plugin_to_backup, plugin_health

STEAM_ROOT = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "Steam")
UNDO_FILE = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "undo.json")


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

    async def _main(self):
        decky.logger.info("Deck Doctor loaded")

    async def _unload(self):
        pass
