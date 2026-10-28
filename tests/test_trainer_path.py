"""An apostrophe in a CheatDeck trainer's file name crashes Proton (real case: Assassin's Creed Mirage)."""

import os
import shlex
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from deck_doctor import steam  # noqa: E402
from deck_doctor.diagnose import escape_trainer_quotes, run_rules, trainer_cmd  # noqa: E402

APPID = 3035570
OPTIONS = ('PROTON_REMOTE_DEBUG_CMD="/home/deck/Downloads/Assassin\'s\\ Creed\\ Mirage\\ Trainer\\ -\\ FLiNG.exe" '
           'PRESSURE_VESSEL_FILESYSTEMS_RW="/home/deck/Downloads" %command%')
WRAPPER = ("/home/deck/.local/share/Steam/ubuntu12_32/steam-launch-wrapper --oom-score-adjust 900 -- "
           "/home/deck/.local/share/Steam/ubuntu12_32/reaper SteamLaunch AppId=3035570 -- "
           "'/x/Proton 10.0'/proton waitforexitandrun  '/sd/steamapps/common/Assassin'\\''s Creed Mirage/ACMirage.exe' "
           "-uplay_steam_mode")


def launch(options=OPTIONS):
    cmd = options.replace(" %command%", " " + WRAPPER)
    return steam.parse_launches([
        f'[2026-10-27 21:34:27] Game process added : AppID {APPID} "{cmd}", ProcID 1, IP 0.0.0.0:0',
        f'[2026-10-27 21:34:29] Game process removed: AppID {APPID} "x", ProcID 1 ',
    ])[0]


class TrainerPath(unittest.TestCase):
    def test_proton_cannot_split_the_mirage_path(self):
        with self.assertRaises(ValueError):
            shlex.split(trainer_cmd(launch().launch_env))

    def test_finding_and_fix(self):
        f = run_rules(APPID, launch(), None, {}, [], None, options=OPTIONS)
        self.assertEqual([x.id for x in f], ["trainer_path_quote"])
        fixed = f[0].fixes[0].target
        self.assertIn("Assassin\\'s\\ Creed", fixed)
        self.assertTrue(fixed.endswith("%command%"))
        # After the fix, Proton gets the real file name
        self.assertEqual(shlex.split(trainer_cmd(fixed)),
                         ["/home/deck/Downloads/Assassin's Creed Mirage Trainer - FLiNG.exe"])
        # ...and the next checkup doesn't flag it again
        self.assertNotIn("trainer_path_quote", [x.id for x in run_rules(APPID, launch(fixed), None, {}, [], None)])

    def test_fix_is_idempotent(self):
        once = escape_trainer_quotes(OPTIONS)
        self.assertEqual(escape_trainer_quotes(once), once)

    def test_spider_man_style_path_is_fine(self):
        ok = 'PROTON_REMOTE_DEBUG_CMD="/home/deck/Downloads/Marvels\\ Spider-Man\\ 2\\ Trainer.exe" %command%'
        self.assertNotIn("trainer_path_quote", [x.id for x in run_rules(APPID, launch(ok), None, {}, [], None)])


class LaunchOptionsFile(unittest.TestCase):
    def test_reads_options_from_localconfig(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = os.path.join(root, "userdata", "1613731442", "config")
            os.makedirs(cfg)
            escaped = OPTIONS.replace("\\", "\\\\").replace('"', '\\"')
            with open(os.path.join(cfg, "localconfig.vdf"), "w") as f:
                f.write('"UserLocalConfigStore"\n{\n\t"apps"\n\t{\n\t\t"3035570"\n\t\t{\n'
                        '\t\t\t"LastPlayed"\t\t"1793151269"\n'
                        f'\t\t\t"LaunchOptions"\t\t"{escaped}"\n\t\t}}\n\t}}\n}}\n')
            self.assertEqual(steam.launch_options(root, APPID), OPTIONS)
            self.assertIsNone(steam.launch_options(root, 12345))


if __name__ == "__main__":
    unittest.main()
