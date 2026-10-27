"""Tests for the Game Mode fixes (Protontricks) and saving guides to the Desktop."""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from deck_doctor import fixes  # noqa: E402
from deck_doctor.diagnose import run_rules  # noqa: E402
from deck_doctor.fixes import Job, needs_sd_access, run_protontricks, save_steps_to_desktop  # noqa: E402

ME = os.environ.get("USER") or "root"


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "logs", "pt.log")
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_job(self, verb="dotnet48", library="/home/deck/.local/share/Steam/steamapps",
                installed=True, running=False, codes=None):
        codes = list(codes or [])

        async def fake_run(cmd, log, timeout):
            self.calls.append(cmd)
            return codes.pop(0) if codes else 0

        job = Job(2651280, verb, self.log)
        with mock.patch.object(fixes, "_run", fake_run), \
                mock.patch.object(fixes, "protontricks_installed", return_value=installed):
            asyncio.run(run_protontricks(job, ME, library, running))
        return job

    def test_happy_path_runs_only_the_verb(self):
        job = self.run_job()
        self.assertEqual(job.status, "done")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][-4:], ["com.github.Matoking.protontricks", "2651280", "-q", "dotnet48"])

    def test_installs_protontricks_and_grants_sd_access(self):
        job = self.run_job(library="/run/media/deck/abc/steamapps", installed=False)
        self.assertEqual(job.status, "done")
        self.assertIn("install", self.calls[0])
        self.assertIn("--filesystem=/run/media", self.calls[1])
        self.assertIn("dotnet48", self.calls[2])

    def test_refuses_unknown_verbs(self):
        job = self.run_job(verb="rm -rf")
        self.assertEqual(job.status, "failed")
        self.assertEqual(self.calls, [])

    def test_refuses_while_game_is_running(self):
        job = self.run_job(running=True)
        self.assertEqual(job.status, "failed")
        self.assertIn("Close the game", job.message)
        self.assertEqual(self.calls, [])

    def test_protontricks_error_is_reported(self):
        job = self.run_job(codes=[1])
        self.assertEqual(job.status, "failed")
        self.assertIn("Protontricks reported an error", job.message)

    def test_status_shows_last_log_line(self):
        job = self.run_job()
        with open(self.log, "w") as f:
            f.write("Executing w_do_call dotnet48\n\nExecuting cabextract\n")
        self.assertEqual(job.as_dict()["last_line"], "Executing cabextract")


class Helpers(unittest.TestCase):
    def test_sd_access_only_for_external_libraries(self):
        self.assertTrue(needs_sd_access("/run/media/deck/cb8ca546/steamapps"))
        self.assertFalse(needs_sd_access("/home/deck/.local/share/Steam/steamapps"))
        self.assertFalse(needs_sd_access(None))

    def test_user_command_sets_session_environment(self):
        cmd = fixes.user_command(ME, ["flatpak", "run", "x"])
        self.assertIn("flatpak", cmd)
        self.assertTrue(any(c.startswith("XDG_RUNTIME_DIR=/run/user/") for c in cmd))

    def test_save_steps_to_desktop(self):
        with tempfile.TemporaryDirectory() as home:
            path = save_steps_to_desktop(home, ME, "The game needs .NET Framework!",
                                         "# The game needs .NET\n\n1. Run `protontricks` **now**")
            self.assertTrue(path.endswith("Desktop/Deck Doctor - The game needs NET Framework.txt"))
            with open(path) as f:
                self.assertEqual(f.read(), "# The game needs .NET\n\n1. Run protontricks now")

    def test_dotnet_finding_offers_protontricks(self):
        f = run_rules(2651280, None, None, {}, [], None)  # no launch -> only no_launch
        self.assertEqual([x.id for x in f], ["no_launch"])
        from deck_doctor import steam
        launch = steam.parse_launches([
            '[2026-10-26 10:00:00] Game process added : AppID 2651280 "x/steam-launch-wrapper -- y", ProcID 1, IP 0',
            '[2026-10-26 10:00:20] Game process removed: AppID 2651280 "x", ProcID 1 ',
        ])[0]
        f = run_rules(2651280, launch, {"StateFlags": "4"}, {"missing_dotnet": ("game.log", "mscoree.dll not found")}, [], None)
        self.assertEqual(f[0].id, "missing_dotnet")
        self.assertEqual((f[0].fixes[0].action, f[0].fixes[0].target), ("protontricks", "dotnet48"))


if __name__ == "__main__":
    unittest.main()
