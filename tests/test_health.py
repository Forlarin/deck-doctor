"""Tests for the plugin health check, using situations from a real Steam Deck."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from deck_doctor.health import (  # noqa: E402
    check_plugins,
    move_plugin_to_backup,
    read_plugins,
    startup_failures,
)

# Journal lines from Deck Doctor's own first install, which crashed on a wrong constant name.
CRASH_JOURNAL = """\
Oct 25 21:16:06 steamdeck PluginLoader[12323]: [loader][INFO]: Loaded Deck Doctor (v0.1.0)
Oct 25 21:16:07 steamdeck PluginLoader[12514]: Failed to start Deck Doctor (v0.1.0)!
Oct 25 21:16:07 steamdeck PluginLoader[12514]: Traceback (most recent call last):
Oct 25 21:16:07 steamdeck PluginLoader[12514]:   File "/home/deck/homebrew/plugins/deck-doctor/main.py", line 9, in <module>
Oct 25 21:16:07 steamdeck PluginLoader[12514]:     UNDO_FILE = os.path.join(decky.DECKY_SETTINGS_DIR, "undo.json")
Oct 25 21:16:07 steamdeck PluginLoader[12514]: AttributeError: module 'decky_loader.plugin.imports.decky' has no attribute 'DECKY_SETTINGS_DIR'. Did you mean: 'DECKY_PLUGIN_DIR'?
Oct 25 21:16:07 steamdeck PluginLoader[12323]: [injector][WARNING]: The Tab SharedJSContext socket has been disconnected
"""

CHEATDECK = {"folder": "CheatDeck", "name": "CheatDeck", "version": "2.0.0", "built": True}
CHEATDECK_ZIP = {"folder": "CheatDeck-main", "name": "CheatDeck", "version": "2.0.0", "built": False}
GRIDDB = {"folder": "decky-steamgriddb", "name": "SteamGridDB", "version": "1.8.1", "built": True}


def ids(findings):
    return [f.id for f in findings]


class CheckPlugins(unittest.TestCase):
    def test_cheatdeck_duplicate_keeps_built_copy(self):
        f = check_plugins([CHEATDECK, CHEATDECK_ZIP, GRIDDB], {}, "v3.3.0", "v3.3.0", False)
        self.assertEqual(ids(f), ["duplicate_plugin"])
        self.assertEqual([x.target for x in f[0].fixes], ["CheatDeck-main"])
        self.assertIn("not built", f[0].evidence)

    def test_unbuilt_plugin_on_its_own(self):
        f = check_plugins([CHEATDECK_ZIP, GRIDDB], {}, None, None, False)
        self.assertEqual(ids(f), ["unbuilt_plugin"])
        self.assertEqual(f[0].fixes[0].target, "CheatDeck-main")

    def test_crash_is_reported_with_error_line(self):
        f = check_plugins([GRIDDB], startup_failures(CRASH_JOURNAL), "v3.3.0", "v3.3.0", False)
        self.assertEqual(ids(f), ["plugin_crashed"])
        self.assertTrue(f[0].evidence.startswith("AttributeError: module"))

    def test_crash_cleared_by_later_successful_start(self):
        # What the real Deck's journal looked like after the fix was deployed.
        later = CRASH_JOURNAL + (
            "Oct 25 21:17:03 steamdeck PluginLoader[13052]: [loader][INFO]: found plugin: deck-doctor\n"
            "Oct 25 21:17:03 steamdeck PluginLoader[13052]: [loader][INFO]: Loaded Deck Doctor (v0.1.0)\n"
            "Oct 25 21:17:03 steamdeck PluginLoader[13234]: Deck Doctor loaded\n")
        self.assertEqual(startup_failures(later), {})

    def test_unloaded_line_does_not_clear_a_crash(self):
        text = CRASH_JOURNAL + "Oct 25 21:18:00 steamdeck PluginLoader[1]: Unloaded Deck Doctor (v0.1.0)\n"
        self.assertIn("Deck Doctor", startup_failures(text))

    def test_old_decky_after_steam_update_is_a_problem(self):
        f = check_plugins([GRIDDB], {}, "v3.2.10", "v3.3.0", True)
        self.assertEqual(ids(f), ["decky_outdated"])
        self.assertEqual(f[0].severity, "problem")
        self.assertIn("Steam updated itself", f[0].detail)

    def test_old_decky_without_steam_update_is_a_warning(self):
        f = check_plugins([GRIDDB], {}, "v3.2.10", "v3.3.0", False)
        self.assertEqual(f[0].severity, "warning")

    def test_version_compare_is_numeric(self):
        # "v3.10.0" > "v3.9.0" even though it sorts lower as text.
        self.assertEqual(ids(check_plugins([GRIDDB], {}, "v3.10.0", "v3.9.0", True)), ["plugins_ok"])

    def test_offline_skips_version_check(self):
        f = check_plugins([GRIDDB], {}, "v3.2.10", None, True)
        self.assertEqual(ids(f), ["plugins_ok"])

    def test_healthy(self):
        f = check_plugins([CHEATDECK, GRIDDB], {}, "v3.3.0", "v3.3.0", False)
        self.assertEqual(ids(f), ["plugins_ok"])
        self.assertIn("(latest)", f[0].detail)


class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.plugins = os.path.join(self.home, "homebrew", "plugins")
        for folder, built in (("CheatDeck", True), ("CheatDeck-main", False)):
            path = os.path.join(self.plugins, folder)
            os.makedirs(os.path.join(path, "dist"))
            with open(os.path.join(path, "plugin.json"), "w") as f:
                json.dump({"name": "CheatDeck"}, f)
            with open(os.path.join(path, "package.json"), "w") as f:
                json.dump({"version": "2.0.0"}, f)
            if built:
                open(os.path.join(path, "dist", "index.js"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_plugins(self):
        got = {p["folder"]: p["built"] for p in read_plugins(self.plugins)}
        self.assertEqual(got, {"CheatDeck": True, "CheatDeck-main": False})

    def test_move_to_backup(self):
        dest = move_plugin_to_backup(self.home, "CheatDeck-main")
        self.assertFalse(os.path.exists(os.path.join(self.plugins, "CheatDeck-main")))
        self.assertTrue(os.path.exists(os.path.join(dest, "plugin.json")))
        self.assertIn(os.path.join("homebrew", "plugin-backups"), dest)

    def test_move_refuses_paths_outside_plugins(self):
        for bad in ("..", "../..", "/etc", "CheatDeck/dist", "missing"):
            with self.assertRaises(ValueError, msg=bad):
                move_plugin_to_backup(self.home, bad)


if __name__ == "__main__":
    unittest.main()
