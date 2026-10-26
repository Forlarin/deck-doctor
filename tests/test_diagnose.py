"""Tests for the checkup, using log lines captured from a real Steam Deck.

Run with:  python3 -m unittest discover -s tests
"""

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from deck_doctor import diagnose, recent_games, steam  # noqa: E402
from deck_doctor.diagnose import run_rules  # noqa: E402

SM2 = 2651280
SM2_CMD = (
    'PROTON_REMOTE_DEBUG_CMD="/home/deck/Downloads/Marvels\\ Spider-Man\\ 2\\ v1.130\\ Plus\\ 22\\ Trainer.exe" '
    'PRESSURE_VESSEL_FILESYSTEMS_RW="/home/deck/Downloads" '
    "/home/deck/.local/share/Steam/ubuntu12_32/steam-launch-wrapper --oom-score-adjust 900 -- "
    "/home/deck/.local/share/Steam/ubuntu12_32/reaper SteamLaunch AppId=2651280 -- "
    "'/home/deck/.local/share/Steam/steamapps/common/SteamLinuxRuntime_sniper'/_v2-entry-point "
    "--verb=waitforexitandrun -- '/home/deck/.local/share/Steam/steamapps/common/{tool}'/proton "
    "waitforexitandrun  '/home/deck/.local/share/Steam/steamapps/common/Marvel'\\''s Spider-Man 2/Spider-Man2.exe'"
)


def sm2_lines(tool="Proton 10.0", start="23:05:03", end="23:05:42"):
    cmd = SM2_CMD.format(tool=tool)
    return [
        f"[2026-10-22 {start}] GameAction [AppID 2651280, ActionID 3] : LaunchApp changed task to CreatingProcess with \"\"",
        f'[2026-10-22 {start}] Game process added : AppID 2651280 "{cmd}", ProcID 77809, IP 0.0.0.0:0',
        f'[2026-10-22 23:05:07] Game process updated : AppID 2651280 "{cmd}", ProcID 77909, IP 0.0.0.0:0',
        f'[2026-10-22 23:05:08] Game process updated : AppID 2651280 "{cmd}", ProcID 77995, IP 0.0.0.0:0',
        f'[2026-10-22 {end}] Game process removed: AppID 2651280 "{cmd}", ProcID 77995 ',
    ]


TOOLS = [
    {"name": "proton_experimental", "label": "Proton - Experimental"},
    {"name": "proton_10", "label": "Proton 10.0"},
    {"name": "proton_11", "label": "Proton 11.0"},
    {"name": "GE-Proton9-23", "label": "GE-Proton9-23"},
]


def ids(findings):
    return [f.id for f in findings]


class ParseLaunches(unittest.TestCase):
    def test_spiderman_launch_is_one_launch_of_39_seconds(self):
        launches = steam.parse_launches(sm2_lines())
        self.assertEqual(len(launches), 1)
        l = launches[0]
        self.assertEqual(l.appid, SM2)
        self.assertEqual(l.seconds, 39)
        self.assertEqual(l.proton, "Proton 10.0")
        self.assertIn("PROTON_REMOTE_DEBUG_CMD", l.launch_env)

    def test_native_shortcut_has_no_proton(self):
        lines = [
            '[2026-10-22 22:31:27] Game process added : AppID 3232836859 "/home/deck/.local/share/Steam/ubuntu12_32/steam-launch-wrapper --oom-score-adjust 900 -- /home/deck/.local/share/Steam/ubuntu12_32/reaper SteamLaunch AppId=3232836859 -- ""/run/media/deck/x/Emulation/tools/launchers/cemu.sh"" -f -g "/run/media/deck/x/roms/wiiu/roms/Mario Kart 8.wux"", ProcID 75159, IP 0.0.0.0:0',
            '[2026-10-22 22:32:08] Game process removed: AppID 3232836859 "x", ProcID 75159 ',
        ]
        l = steam.parse_launches(lines)[0]
        self.assertIsNone(l.proton)
        self.assertEqual(l.seconds, 41)
        self.assertEqual(l.launch_env, "")

    def test_unfinished_launch_is_running(self):
        l = steam.parse_launches(sm2_lines()[:2])[0]
        self.assertTrue(l.running)

    def test_two_launches_are_separate(self):
        lines = sm2_lines(start="20:00:00", end="20:00:30") + sm2_lines()
        self.assertEqual(len(steam.parse_launches(lines)), 2)


class ToolNames(unittest.TestCase):
    def test_valve_proton_names(self):
        self.assertEqual(steam.internal_tool_name("Proton 10.0"), "proton_10")
        self.assertEqual(steam.internal_tool_name("Proton 6.3"), "proton_63")
        self.assertEqual(steam.internal_tool_name("Proton 9.0 (Beta)"), "proton_9")
        self.assertEqual(steam.internal_tool_name("Proton - Experimental"), "proton_experimental")
        self.assertIsNone(steam.internal_tool_name("Proton EasyAntiCheat Runtime"))


class Rules(unittest.TestCase):
    def launch(self, **kw):
        return steam.parse_launches(sm2_lines(**kw))[0]

    def test_corrupt_files_offers_verify(self):
        hits = {"corrupt_files": ("Marvel's Spider-Man 2.log", "[NxStorage] Decompression failed @ 0x1, Format=0x81")}
        f = run_rules(SM2, self.launch(), {"StateFlags": "4"}, hits, TOOLS, 50 * 1024**3)
        self.assertEqual(ids(f), ["corrupt_files"])
        self.assertEqual(f[0].fixes[0].action, "verify_files")

    def test_trainer_on_proton_11_offers_proton_10(self):
        f = run_rules(SM2, self.launch(tool="Proton 11.0", end="23:15:00"), {"StateFlags": "4"}, {}, TOOLS, None)
        self.assertEqual(ids(f), ["trainer_new_proton"])
        self.assertEqual(f[0].fixes[0].tool, "proton_10")

    def test_trainer_on_proton_10_is_fine(self):
        f = run_rules(SM2, self.launch(end="23:15:00"), {"StateFlags": "4"}, {}, TOOLS, None)
        self.assertEqual(ids(f), ["looks_ok"])

    def test_quick_exit_without_cause_suggests_other_protons(self):
        f = run_rules(SM2, self.launch(), {"StateFlags": "4"}, {}, TOOLS, None)
        self.assertEqual(ids(f), ["quick_exit"])
        tools = [x.tool for x in f[0].fixes if x.action == "set_proton"]
        self.assertEqual(tools, ["proton_experimental", "GE-Proton9-23"])  # not the one it already used

    def test_anticheat_game_stops_early(self):
        f = run_rules(1938090, None, None, {}, TOOLS, None)
        self.assertEqual(ids(f), ["anticheat_blocked"])
        self.assertEqual(f[0].fixes, [])

    def test_pending_update_and_low_disk(self):
        f = run_rules(SM2, self.launch(end="23:15:00"), {"StateFlags": "1026"}, {}, TOOLS, 1 * 1024**3)
        self.assertEqual(ids(f), ["not_fully_installed", "low_disk"])

    def test_trainer_already_switched_since_launch(self):
        # Ace Combat 7 on the real Deck: last run on Proton 11, then pinned to Proton 10.
        f = run_rules(SM2, self.launch(tool="Proton 11.0"), {"StateFlags": "4"}, {}, TOOLS, None, "proton_10")
        self.assertEqual(ids(f), ["changed_since_launch"])

    def test_non_steam_shortcut_quick_exit_points_at_emulator(self):
        mk8 = steam.parse_launches([
            '[2026-10-22 22:31:27] Game process added : AppID 3232836859 "/x/steam-launch-wrapper -- cemu.sh", ProcID 1, IP 0.0.0.0:0',
            '[2026-10-22 22:32:08] Game process removed: AppID 3232836859 "x", ProcID 1 ',
        ])[0]
        f = run_rules(3232836859, mk8, None, {}, TOOLS, None)
        self.assertEqual(ids(f), ["quick_exit"])
        self.assertEqual(f[0].fixes, [])
        self.assertIn("emulator", f[0].detail)

    def test_never_launched(self):
        self.assertEqual(ids(run_rules(SM2, None, {"StateFlags": "4"}, {}, TOOLS, None)), ["no_launch"])


class EndToEnd(unittest.TestCase):
    """Build a fake Steam folder that mirrors the Spider-Man 2 crash and check the full checkup."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = os.path.join(self.tmp.name, "Steam")
        sa = os.path.join(root, "steamapps")
        os.makedirs(os.path.join(root, "logs"))
        os.makedirs(os.path.join(root, "config"))
        os.makedirs(os.path.join(sa, "common", "Proton 10.0"))
        os.makedirs(os.path.join(sa, "common", "Proton - Experimental"))
        os.makedirs(os.path.join(sa, "common", "Marvel's Spider-Man 2"))
        with open(os.path.join(root, "logs", "console_log.txt"), "w") as f:
            f.write("\n".join(sm2_lines()) + "\n")
        with open(os.path.join(sa, f"appmanifest_{SM2}.acf"), "w") as f:
            f.write('"AppState"\n{\n\t"appid"\t\t"2651280"\n\t"StateFlags"\t\t"4"\n'
                    '\t"installdir"\t\t"Marvel\'s Spider-Man 2"\n}\n')
        with open(os.path.join(root, "config", "config.vdf"), "w") as f:
            f.write('"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
                    '\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n\t\t\t\t\t"2651280"\n\t\t\t\t\t{\n'
                    '\t\t\t\t\t\t"name"\t\t"proton_10"\n\t\t\t\t\t\t"config"\t\t""\n\t\t\t\t\t}\n\t\t\t\t}\n'
                    '\t\t\t}\n\t\t}\n\t}\n}\n')
        logdir = os.path.join(sa, "compatdata", str(SM2), "pfx", "drive_c", "users", "steamuser",
                              "Documents", "Marvel's Spider-Man 2")
        os.makedirs(logdir)
        log = os.path.join(logdir, "Marvel's Spider-Man 2.log")
        with open(log, "w") as f:
            f.write("23:05:10:529 (00000356) > [NxStorage] DirectStorage initialization succeeded\n"
                    "23:05:16:212 (00000660) > [NxStorage] Decompression failed @ 0x00000001109AAC70, "
                    "Format=0x81, SrcSize=43739, DstSize=99568.\n")
        t = time.mktime(datetime(2026, 10, 22, 23, 5, 20).timetuple())
        os.utime(log, (t, t))

    def tearDown(self):
        self.tmp.cleanup()

    def test_spiderman_checkup(self):
        report = diagnose(self.root, SM2, self.tmp.name)
        self.assertEqual(report["last_launch"]["seconds"], 39)
        self.assertEqual(report["forced_tool"], "proton_10")
        self.assertEqual(report["logs_checked"], ["Marvel's Spider-Man 2.log"])
        self.assertEqual([f["id"] for f in report["findings"]], ["corrupt_files"])
        self.assertIn("Decompression failed", report["findings"][0]["evidence"])

    def test_recent_games(self):
        self.assertEqual([g["appid"] for g in recent_games(self.root)], [SM2])


if __name__ == "__main__":
    unittest.main()
