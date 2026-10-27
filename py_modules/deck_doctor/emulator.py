"""Checks for EmuDeck shortcuts: which emulator failed, and the usual reasons why.

EmuDeck adds games to Steam as non-Steam shortcuts that run
Emulation/tools/launchers/<emulator>.sh with the game file as an argument.
Steam's console log records that command, so we can tell which emulator and
which game file were used, then check the files that emulator needs.
"""

import glob
import os
import re
from typing import Optional

from .diagnose import Finding

LAUNCHER_RE = re.compile(r"(/[^\"']*?/Emulation)/tools/launchers/(?:[\w.-]+/)?([\w.-]+)\.sh")
ROM_RE = re.compile(r"\"(/[^\"]*/Emulation/roms/[^\"]+)\"")

# launcher name -> (emulator, console, AppImage name in ~/Applications or None, flatpak id or None)
EMULATORS = {
    "cemu": ("Cemu", "Wii U", "Cemu.AppImage", "info.cemu.Cemu"),
    "ryujinx": ("Ryujinx", "Switch", "publish", None),
    "yuzu": ("yuzu", "Switch", "yuzu.AppImage", None),
    "duckstation": ("DuckStation", "PlayStation", "DuckStation.AppImage", "org.duckstation.DuckStation"),
    "pcsx2-qt": ("PCSX2", "PlayStation 2", "pcsx2-Qt.AppImage", "net.pcsx2.PCSX2"),
    "rpcs3": ("RPCS3", "PlayStation 3", "rpcs3.AppImage", "net.rpcs3.RPCS3"),
    "dolphin-emu": ("Dolphin", "GameCube / Wii", None, "org.DolphinEmu.dolphin-emu"),
    "primehack": ("PrimeHack", "Metroid Prime (Wii)", None, "io.github.shiiion.primehack"),
    "ppsspp": ("PPSSPP", "PSP", None, "org.ppsspp.PPSSPP"),
    "melonds": ("melonDS", "Nintendo DS", None, "net.kuribo64.melonDS"),
    "azahar": ("Azahar", "Nintendo 3DS", "azahar.AppImage", None),
    "citra": ("Citra", "Nintendo 3DS", None, None),
    "retroarch": ("RetroArch", "retro consoles", None, "org.libretro.RetroArch"),
    "xemu-emu": ("xemu", "Xbox", None, "app.xemu.xemu"),
    "vita3k": ("Vita3K", "PS Vita", "Vita3K", None),
    "scummvm": ("ScummVM", "point-and-click games", None, "org.scummvm.ScummVM"),
    "shadps4": ("shadPS4", "PlayStation 4", "Shadps4-qt.AppImage", None),
    "es-de": ("ES-DE", "your game library", "ES-DE.AppImage", None),
}

PS1_BIOS_SIZE = 512 * 1024          # every PS1 BIOS image is exactly 512 KiB
PS2_BIOS_SIZE = 4 * 1024 * 1024     # PS2 BIOS images are 4 MiB
CEMU_KEYS = (".local/share/Cemu/keys.txt", ".config/Cemu/keys.txt")
EXAMPLE_CEMU_KEY = "541b9889519b27d363cd21604b97c67a"


def parse_shortcut(command: str) -> Optional[dict]:
    """{"emulator", "name", "console", "emulation", "rom"} for an EmuDeck launch, else None."""
    m = LAUNCHER_RE.search(command)
    if not m:
        return None
    key = m.group(2)
    name, console = EMULATORS.get(key, (key, "this console", None, None))[:2]
    rom = ROM_RE.search(command)
    return {"emulator": key, "name": name, "console": console,
            "emulation": m.group(1), "rom": rom.group(1) if rom else None}


def _installed(home: str, key: str, flatpak_ids: set) -> Optional[bool]:
    """True/False if we know how this emulator is installed, None if we can't tell."""
    if key not in EMULATORS:
        return None
    _, _, appimage, flatpak = EMULATORS[key]
    if appimage and os.path.exists(os.path.join(home, "Applications", appimage)):
        return True
    if flatpak and flatpak in flatpak_ids:
        return True
    return False if (appimage or flatpak) else None


def _cemu_has_keys(home: str) -> bool:
    for rel in CEMU_KEYS:
        try:
            with open(os.path.join(home, rel), encoding="utf-8", errors="replace") as f:
                for line in f:
                    key = line.split("#", 1)[0].strip().lower()
                    if re.fullmatch(r"[0-9a-f]{32}", key) and key != EXAMPLE_CEMU_KEY:
                        return True
        except OSError:
            continue
    return False


def _has_bios(bios_dir: str, size: int) -> bool:
    for path in glob.glob(os.path.join(bios_dir, "**", "*"), recursive=True):
        if path.lower().endswith((".bin", ".rom")) and os.path.isfile(path) and os.path.getsize(path) == size:
            return True
    return False


def _has_switch_keys(emulation: str, home: str) -> bool:
    candidates = glob.glob(os.path.join(emulation, "bios", "*", "keys", "prod.keys")) + [
        os.path.join(home, ".config", "Ryujinx", "system", "prod.keys"),
        os.path.join(home, ".local", "share", "yuzu", "keys", "prod.keys"),
    ]
    return any(os.path.isfile(p) and os.path.getsize(p) > 0 for p in candidates)


def check_emulator(info: dict, home: str, flatpak_ids: set) -> list:
    """Findings for one EmuDeck launch. Empty if nothing specific is wrong."""
    findings, name, console, key = [], info["name"], info["console"], info["emulator"]
    emulation, rom = info["emulation"], info["rom"]

    if _installed(home, key, flatpak_ids) is False:
        findings.append(Finding(
            "emu_missing", "problem", f"{name} isn't installed",
            f"This {console} game is set up to run with {name}, but {name} isn't installed. That often "
            "happens after a SteamOS reset, or when EmuDeck no longer ships an emulator (Nintendo had "
            "the Switch emulators taken down). Reinstall it from EmuDeck → Manage Emulators.",
            evidence=f"EmuDeck launcher: {key}.sh"))
        return findings

    if rom and not os.path.exists(rom):
        findings.append(Finding(
            "emu_rom_missing", "problem", "The game file is missing",
            "The shortcut points to a game file that isn't there anymore. It may have been moved, "
            "renamed, or be on an SD card that isn't inserted. Put it back, or re-run Steam ROM "
            "Manager so the shortcut points to the right place.",
            evidence=rom))
        return findings

    if key == "cemu" and rom and rom.lower().endswith((".wux", ".wud")) and not _cemu_has_keys(home):
        findings.append(Finding(
            "emu_cemu_keys", "problem", "Cemu has no key for this Wii U disc image",
            "Disc images (.wux / .wud) are encrypted, and Cemu needs the disc's key in keys.txt to "
            "read them. Cemu's keys.txt only has the example key, so it can't open the game and closes. "
            "The key comes from your own Wii U disc dump. A game dumped with Dumpling (a folder with "
            "code, content and meta) doesn't need a key at all.",
            evidence=f"{os.path.basename(rom)}: no keys in ~/.local/share/Cemu/keys.txt"))
    elif key == "duckstation" and not _has_bios(os.path.join(emulation, "bios"), PS1_BIOS_SIZE):
        findings.append(Finding(
            "emu_bios_missing", "problem", "No PlayStation BIOS found",
            "DuckStation needs a PlayStation BIOS file, dumped from your own console, in "
            "Emulation/bios. There isn't one, so games can't start.",
            evidence=f"No 512 KB BIOS file in {os.path.join(emulation, 'bios')}"))
    elif key == "pcsx2-qt" and not _has_bios(os.path.join(emulation, "bios"), PS2_BIOS_SIZE):
        findings.append(Finding(
            "emu_bios_missing", "problem", "No PlayStation 2 BIOS found",
            "PCSX2 needs a PS2 BIOS file, dumped from your own console, in Emulation/bios. There "
            "isn't one, so games can't start.",
            evidence=f"No 4 MB BIOS file in {os.path.join(emulation, 'bios')}"))
    elif key in ("ryujinx", "yuzu") and not _has_switch_keys(emulation, home):
        findings.append(Finding(
            "emu_bios_missing", "problem", "Switch keys are missing",
            f"{name} needs prod.keys (and firmware) from your own Switch. Without them, Switch games "
            "can't be decrypted and the emulator closes.",
            evidence=f"No prod.keys in {os.path.join(emulation, 'bios', key, 'keys')}"))
    return findings


def installed_flatpaks(run=None) -> set:
    import subprocess
    run = run or subprocess.run
    try:
        out = run(["flatpak", "list", "--app", "--columns=application"], capture_output=True, text=True, timeout=30)
        return set(out.stdout.split())
    except Exception:
        return set()
