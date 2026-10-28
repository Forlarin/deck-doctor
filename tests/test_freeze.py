"""Tests for freeze detection: kernel log messages, launches that never ended, force close."""

import os
import signal
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from deck_doctor import steam  # noqa: E402
from deck_doctor.diagnose import run_rules  # noqa: E402
from deck_doctor.freeze import force_close, game_processes, kernel_hits, kernel_log  # noqa: E402

GPU_HANG = [
    "2026-10-22T23:41:02-04:00 steamdeck kernel: [drm:amdgpu_job_timedout [amdgpu]] *ERROR* ring gfx_0.0.0 "
    "timeout, signaled seq=1234, emitted seq=1236",
    "2026-10-22T23:41:02-04:00 steamdeck kernel: amdgpu 0000:04:00.0: amdgpu: GPU reset begin!",
]
OOM = [
    "2026-10-22T23:50:10-04:00 steamdeck kernel: GameThread invoked oom-killer: gfp_mask=0x140cca, order=0",
    "2026-10-22T23:50:10-04:00 steamdeck kernel: Out of memory: Killed process 81234 (Cyberpunk2077.e) "
    "total-vm:25165824kB, anon-rss:14680064kB",
]
NORMAL = ["2026-10-27T20:39:18-04:00 steamdeck kernel: amdgpu 0000:04:00.0: amdgpu: ring sdma0 uses VM inv eng 13 on hub 0"]
APPID = 2651280


def launch(ended=True):
    lines = [f'[2026-10-22 23:30:00] Game process added : AppID {APPID} "x", ProcID 77809, IP 0.0.0.0:0']
    if ended:
        lines.append(f'[2026-10-22 23:45:00] Game process removed: AppID {APPID} "x", ProcID 77809 ')
    return steam.parse_launches(lines)[0]


def ids(findings):
    return [f.id for f in findings]


class Kernel(unittest.TestCase):
    def test_gpu_hang_and_oom(self):
        hits = kernel_hits(NORMAL + GPU_HANG + OOM)
        self.assertIn("ring gfx_0.0.0 timeout", hits["gpu_hang"])
        self.assertIn("Cyberpunk2077.e", hits["out_of_memory"])

    def test_normal_ring_setup_is_not_a_hang(self):
        self.assertEqual(kernel_hits(NORMAL), {})

    def test_journalctl_window(self):
        calls = []

        class Out:
            stdout = "\n".join(GPU_HANG)

        def run(cmd, **kw):
            calls.append(cmd)
            return Out()
        lines = kernel_log(datetime(2026, 10, 22, 23, 30), datetime(2026, 10, 22, 23, 45), run)
        self.assertEqual(len(lines), 2)
        self.assertEqual(calls[0][-4:], ["--since", "2026-10-22 23:30:00", "--until", "2026-10-22 23:45:00"])

    def test_journalctl_missing(self):
        def run(cmd, **kw):
            raise FileNotFoundError
        self.assertEqual(kernel_log(datetime(2026, 10, 22), None, run), [])


class Rules(unittest.TestCase):
    def test_gpu_hang_during_finished_launch(self):
        f = run_rules(APPID, launch(), None, {}, [], None, kernel={"gpu_hang": GPU_HANG[0]})
        self.assertEqual(ids(f), ["gpu_hang"])

    def test_launch_that_never_ended(self):
        f = run_rules(APPID, launch(ended=False), None, {}, [], None, alive=False)
        self.assertEqual(ids(f), ["game_froze"])
        self.assertEqual(f[0].severity, "problem")

    def test_never_ended_with_out_of_memory(self):
        f = run_rules(APPID, launch(ended=False), None, {}, [], None,
                      kernel={"out_of_memory": OOM[1]}, alive=False)
        self.assertEqual(ids(f), ["out_of_memory", "game_froze"])
        self.assertIn("Cyberpunk2077.e", f[0].detail)

    def test_after_force_close_the_game_is_not_blamed(self):
        forced = datetime(2026, 10, 22, 23, 44, 58)  # launch() ends at 23:45:00
        f = run_rules(APPID, launch(), None, {}, [], None, forced_at=forced)
        self.assertEqual(ids(f), ["force_closed"])
        # An older force close doesn't hide a later problem
        f = run_rules(APPID, launch(), None, {}, [], None, forced_at=datetime(2026, 10, 21))
        self.assertNotIn("force_closed", ids(f))

    def test_running_game_offers_force_close(self):
        f = run_rules(APPID, launch(ended=False), None, {}, [], None, alive=True)
        self.assertEqual(ids(f), ["running"])
        self.assertEqual(f[0].fixes[0].action, "force_close")


class FakeProc(unittest.TestCase):
    """A fake /proc: reaper 100 (the game's) -> wine 101 -> game.exe 102, plus an unrelated 200."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proc = self.tmp.name
        self.add("100", "1", f"reaper\0SteamLaunch\0AppId={APPID}\0")
        self.add("101", "100", "wine64\0game.exe\0", env=f"SteamGameId={APPID}\0")
        self.add("102", "101", "game.exe\0")
        self.add("200", "1", "firefox\0")
        # A trainer started by CheatDeck: not a child of the game, but in the game's environment
        self.add("300", "1", "trainer.exe\0", env=f"SteamGameId={APPID}\0")

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, pid, ppid, cmdline, env=""):
        d = os.path.join(self.proc, pid)
        os.makedirs(d)
        with open(os.path.join(d, "stat"), "w") as f:
            f.write(f"{pid} (name with) spaces) S {ppid} 1 1\n")
        with open(os.path.join(d, "cmdline"), "w") as f:
            f.write(cmdline)
        with open(os.path.join(d, "environ"), "w") as f:
            f.write(env)

    def test_finds_every_process_of_this_game_only(self):
        self.assertEqual(sorted(game_processes(APPID, self.proc)), ["100", "101", "300"])
        self.assertEqual(game_processes(12345, self.proc), [])
        self.assertEqual(game_processes(265128, self.proc), [])   # a prefix of the ID isn't a match

    def test_force_close_kills_the_whole_game_only(self):
        killed = []
        n = force_close(APPID, self.proc, kill=lambda pid, sig: killed.append((pid, sig)))
        self.assertEqual(n, 4)  # reaper, wine, game.exe (a child with no ID of its own), trainer
        self.assertEqual(sorted(p for p, _ in killed), [100, 101, 102, 300])
        self.assertTrue(all(sig == signal.SIGKILL for _, sig in killed))

    def test_force_close_with_nothing_running(self):
        killed = []
        self.assertEqual(force_close(12345, self.proc, kill=lambda p, s: killed.append(p)), 0)
        self.assertEqual(killed, [])


if __name__ == "__main__":
    unittest.main()
