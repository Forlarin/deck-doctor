"""Tests for EmuDeck shortcut checks, based on a real Mario Kart 8 (Cemu) launch."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py_modules"))

from deck_doctor import steam  # noqa: E402
from deck_doctor.diagnose import run_rules  # noqa: E402
from deck_doctor.emulator import check_emulator, parse_shortcut  # noqa: E402

SD = "/run/media/deck/cb8ca546-a448-496c-b49d-e302ebec2947"
MK8_CMD = (
    '/home/deck/.local/share/Steam/ubuntu12_32/steam-launch-wrapper --oom-score-adjust 900 -- '
    '/home/deck/.local/share/Steam/ubuntu12_32/reaper SteamLaunch AppId=3232836859 -- '
    f'""{SD}/Emulation/tools/launchers/cemu.sh"" -f -g "{SD}/Emulation/roms/wiiu/roms/Mario Kart 8 (USA) (En,Fr,Es).wux"'
)
EXAMPLE_KEYS = (
    "# this file contains keys needed for decryption of disc file system data (WUD/WUX)\n"
    "# 1 key per line, any text after a '#' character is considered a comment\n"
    "541b9889519b27d363cd21604b97c67a # example key (can be deleted)\n"
)


def ids(findings):
    return [f.id for f in findings]


class Parse(unittest.TestCase):
    def test_mario_kart_shortcut(self):
        info = parse_shortcut(MK8_CMD)
        self.assertEqual((info["emulator"], info["name"], info["console"]), ("cemu", "Cemu", "Wii U"))
        self.assertEqual(info["emulation"], f"{SD}/Emulation")
        self.assertTrue(info["rom"].endswith("Mario Kart 8 (USA) (En,Fr,Es).wux"))

    def test_es_de_launcher_in_subfolder(self):
        cmd = ('/x/steam-launch-wrapper -- /x/reaper SteamLaunch AppId=4025932087 -- '
               f'"{SD}/Emulation/tools/launchers/es-de/es-de.sh""')
        info = parse_shortcut(cmd)
        self.assertEqual((info["emulator"], info["name"]), ("es-de", "ES-DE"))
        self.assertIsNone(info["rom"])

    def test_steam_game_is_not_an_emulator(self):
        self.assertIsNone(parse_shortcut("/x/steam-launch-wrapper -- '/x/Proton 10.0'/proton waitforexitandrun 'game.exe'"))


class Checks(unittest.TestCase):
    """A fake home and Emulation folder, laid out like EmuDeck's."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.emulation = os.path.join(self.tmp.name, "sd", "Emulation")
        os.makedirs(os.path.join(self.home, "Applications"))
        os.makedirs(os.path.join(self.home, ".local", "share", "Cemu"))
        os.makedirs(os.path.join(self.emulation, "roms", "wiiu", "roms"))
        os.makedirs(os.path.join(self.emulation, "bios", "ryujinx", "keys"))
        self.rom = os.path.join(self.emulation, "roms", "wiiu", "roms", "Mario Kart 8.wux")
        open(self.rom, "wb").close()
        open(os.path.join(self.home, "Applications", "Cemu.AppImage"), "w").close()
        self.write_keys(EXAMPLE_KEYS)

    def tearDown(self):
        self.tmp.cleanup()

    def write_keys(self, text):
        with open(os.path.join(self.home, ".local", "share", "Cemu", "keys.txt"), "w") as f:
            f.write(text)

    def info(self, emulator="cemu", rom=None):
        name, console = {"cemu": ("Cemu", "Wii U"), "duckstation": ("DuckStation", "PlayStation"),
                         "pcsx2-qt": ("PCSX2", "PlayStation 2"), "ryujinx": ("Ryujinx", "Switch")}[emulator]
        return {"emulator": emulator, "name": name, "console": console,
                "emulation": self.emulation, "rom": rom or self.rom}

    def test_mario_kart_missing_cemu_key(self):
        f = check_emulator(self.info(), self.home, set())
        self.assertEqual(ids(f), ["emu_cemu_keys"])

    def test_real_key_is_enough(self):
        self.write_keys(EXAMPLE_KEYS + "0123456789abcdef0123456789abcdef # Mario Kart 8\n")
        self.assertEqual(check_emulator(self.info(), self.home, set()), [])

    def test_dumpling_folder_needs_no_key(self):
        game = os.path.join(self.emulation, "roms", "wiiu", "roms", "Mario Kart 8", "code", "Turbo.rpx")
        os.makedirs(os.path.dirname(game))
        open(game, "w").close()
        self.assertEqual(check_emulator(self.info(rom=game), self.home, set()), [])

    def test_missing_rom(self):
        f = check_emulator(self.info(rom=self.rom + ".gone"), self.home, set())
        self.assertEqual(ids(f), ["emu_rom_missing"])

    def test_missing_emulator(self):
        os.remove(os.path.join(self.home, "Applications", "Cemu.AppImage"))
        self.assertEqual(ids(check_emulator(self.info(), self.home, set())), ["emu_missing"])
        # ...but a Flatpak install counts
        self.assertEqual(ids(check_emulator(self.info(), self.home, {"info.cemu.Cemu"})), ["emu_cemu_keys"])

    def test_ps1_and_ps2_bios_by_size(self):
        open(os.path.join(self.home, "Applications", "DuckStation.AppImage"), "w").close()
        open(os.path.join(self.home, "Applications", "pcsx2-Qt.AppImage"), "w").close()
        self.assertEqual(ids(check_emulator(self.info("duckstation"), self.home, set())), ["emu_bios_missing"])
        with open(os.path.join(self.emulation, "bios", "scph5501.bin"), "wb") as f:
            f.write(b"\0" * 512 * 1024)
        self.assertEqual(check_emulator(self.info("duckstation"), self.home, set()), [])
        # A PS1 BIOS doesn't satisfy PCSX2
        self.assertEqual(ids(check_emulator(self.info("pcsx2-qt"), self.home, set())), ["emu_bios_missing"])

    def test_switch_keys(self):
        os.makedirs(os.path.join(self.home, "Applications", "publish"))
        self.assertEqual(ids(check_emulator(self.info("ryujinx"), self.home, set())), ["emu_bios_missing"])
        with open(os.path.join(self.emulation, "bios", "ryujinx", "keys", "prod.keys"), "w") as f:
            f.write("header_key = 00\n")
        self.assertEqual(check_emulator(self.info("ryujinx"), self.home, set()), [])


class InCheckup(unittest.TestCase):
    def launch(self):
        return steam.parse_launches([
            f'[2026-10-22 22:31:27] Game process added : AppID 3232836859 "{MK8_CMD}", ProcID 75159, IP 0.0.0.0:0',
            '[2026-10-22 22:32:08] Game process removed: AppID 3232836859 "x", ProcID 75159 ',
        ])[0]

    def test_emulator_finding_replaces_generic_quick_exit(self):
        from deck_doctor.diagnose import Finding
        emu = parse_shortcut(MK8_CMD)
        key = Finding("emu_cemu_keys", "problem", "Cemu has no key", "...")
        f = run_rules(3232836859, self.launch(), None, {}, [], None, None, emu, [key])
        self.assertEqual(ids(f), ["emu_cemu_keys"])

    def test_quick_exit_names_the_emulator_when_no_cause_found(self):
        f = run_rules(3232836859, self.launch(), None, {}, [], None, None, parse_shortcut(MK8_CMD), [])
        self.assertEqual(ids(f), ["quick_exit"])
        self.assertIn("in Cemu (Wii U)", f[0].detail)


if __name__ == "__main__":
    unittest.main()
