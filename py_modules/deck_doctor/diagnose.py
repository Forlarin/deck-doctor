"""The "game won't launch" checkup.

diagnose() gathers evidence about a game's most recent launch (how long it
ran, which Proton it used, what its own log files said) and runs it through
a list of rules. Each rule that matches produces a Finding: a plain-English
explanation plus, where one exists, a fix the frontend can apply.
"""

import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Optional

from . import steam

# Games whose anti-cheat refuses to run on Linux / SteamOS. No setting fixes these.
ANTICHEAT_BLOCKED = {
    1938090: "Call of Duty",
    1962663: "Call of Duty: Warzone",
    1985810: "Call of Duty: Black Ops Cold War",
    1985820: "Call of Duty: Vanguard",
    2000950: "Call of Duty: Modern Warfare",
    2933620: "Call of Duty: Black Ops 6",
    3595270: "Call of Duty: Modern Warfare III",
    1085660: "Destiny 2",
    1172470: "Apex Legends",
    359550: "Tom Clancy's Rainbow Six Siege",
    578080: "PUBG: Battlegrounds",
}

# (finding id, pattern) checked against the game's own log files.
LOG_PATTERNS = [
    ("corrupt_files", re.compile(
        r"decompression failed|verify (?:the )?(?:game(?:'s)? )?(?:file )?integrity|"
        r"corrupt(?:ed)? (?:file|data|archive|pak)|checksum mismatch|crc (?:error|mismatch)|"
        r"failed to (?:read|open|mount) \S+\.(?:pak|ucas|utoc|archive|toc)", re.I)),
    ("gpu_device_lost", re.compile(
        r"vk_error_device_lost|dxgi_error_device_(?:removed|hung)|out of video memory|"
        r"vk_error_out_of_device_memory", re.I)),
    ("missing_dotnet", re.compile(r"mscoree\.dll|\.net framework (?:is )?(?:required|not found)|"
                                  r"clr (?:error|failed)", re.I)),
    ("missing_vcredist", re.compile(r"(?:vcruntime|msvcp)\d+(?:_\d)?\.dll.{0,40}(?:not found|missing)", re.I)),
    ("anticheat_error", re.compile(r"easyanticheat.{0,60}(?:error|fail|not installed)|"
                                   r"battleye.{0,60}(?:error|fail|not installed)|"
                                   r"anti-?cheat.{0,40}(?:error|fail)", re.I)),
]

LOG_SUFFIXES = (".log", ".txt")
PREFIX_LOG_DIRS = ("Documents", "AppData/Local", "AppData/Roaming", "AppData/LocalLow", "Saved Games")
QUICK_EXIT_SECONDS = 90
LOW_SPACE_BYTES = 3 * 1024**3


@dataclass
class Fix:
    action: str          # "verify_files" | "set_proton" | "open_protondb" | "protontricks" | "move_plugin" | "open_decky_store" | "open_decky_settings"
    label: str
    tool: Optional[str] = None     # set_proton: Steam's internal tool name
    target: Optional[str] = None   # move_plugin: plugin folder name; protontricks: winetricks verb


@dataclass
class Finding:
    id: str
    severity: str        # "problem" | "warning" | "info"
    title: str
    detail: str
    evidence: Optional[str] = None
    fixes: list = field(default_factory=list)


def _tail(path: str, limit: int = 256 * 1024) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - limit))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def game_logs(steam_root: str, launch: steam.Launch, install_dir: Optional[str]) -> list:
    """Log files the game wrote around its last launch, newest first."""
    lo = launch.start.timestamp() - 30
    hi = (launch.end or launch.start + timedelta(days=1)).timestamp() + 120
    roots = []
    for sa in steam.library_folders(steam_root):
        user = os.path.join(sa, "compatdata", str(launch.appid), "pfx", "drive_c", "users", "steamuser")
        roots += [os.path.join(user, d) for d in PREFIX_LOG_DIRS]
    if install_dir:
        roots.append(install_dir)
    found = []
    for root in roots:
        base_depth = root.rstrip("/").count("/")
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath.count("/") - base_depth >= 4:
                dirnames[:] = []
            for name in filenames:
                # dd_* files are logs from installers Steam runs (VC++, .NET), not the game.
                if not name.lower().endswith(LOG_SUFFIXES) or name.startswith("dd_"):
                    continue
                path = os.path.join(dirpath, name)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if lo <= mtime <= hi:
                    found.append((mtime, path))
    return [p for _, p in sorted(found, reverse=True)]


def _match_logs(paths: list) -> dict:
    """{finding id: (log file, matching line)} for the first hit of each pattern."""
    hits = {}
    for path in paths:
        for line in _tail(path).splitlines():
            for fid, pattern in LOG_PATTERNS:
                if fid not in hits and pattern.search(line):
                    hits[fid] = (os.path.basename(path), line.strip()[:200])
    return hits


def _is_new_proton(label: Optional[str]) -> bool:
    if not label:
        return False
    if "Experimental" in label:
        return True
    m = re.search(r"Proton (\d+)", label)
    return bool(m) and int(m.group(1)) >= 11


def _tool(tools: list, name: str) -> Optional[dict]:
    return next((t for t in tools if t["name"] == name), None)


def is_steam_game(appid: int) -> bool:
    """Non-Steam shortcuts (emulators, Heroic games) get IDs above 2^31."""
    return appid < 2**31


def run_rules(appid: int, launch: Optional[steam.Launch], manifest: Optional[dict],
              log_hits: dict, tools: list, free_bytes: Optional[int],
              forced_tool: Optional[str] = None, emu: Optional[dict] = None,
              emu_findings: Optional[list] = None) -> list:
    """Pure decision logic, kept separate from file access so it can be tested."""
    findings = []
    protondb = Fix("open_protondb", "See ProtonDB reports")

    if appid in ANTICHEAT_BLOCKED:
        findings.append(Finding(
            "anticheat_blocked", "problem", "This game's anti-cheat blocks the Steam Deck",
            f"{ANTICHEAT_BLOCKED[appid]} uses anti-cheat that refuses to run on SteamOS. "
            "No Proton version or setting can change that. Cloud gaming (e.g. Xbox Cloud Gaming) "
            "or streaming from a PC are the only ways to play it on the Deck."))
        return findings

    if manifest is not None and manifest.get("StateFlags") not in (None, "4"):
        findings.append(Finding(
            "not_fully_installed", "problem", "The game isn't fully installed or updated",
            "Steam still has a download or update pending for this game. Let it finish in the "
            "Downloads page, then try again."))

    if free_bytes is not None and free_bytes < LOW_SPACE_BYTES:
        findings.append(Finding(
            "low_disk", "warning", "Internal storage is almost full",
            f"Only {free_bytes / 1024**3:.1f} GB is free. Games keep their Proton data and shader "
            "cache on internal storage, even when installed to the SD card, and can fail to start "
            "when it runs out. Free up some space and try again."))

    if launch is None:
        findings.append(Finding(
            "no_launch", "info", "No recent launch found",
            "Steam's log doesn't show this game being started recently. Launch it once (even if it "
            "fails), then run the checkup again so Deck Doctor has something to look at."))
        return findings

    if launch.running:
        findings.append(Finding(
            "running", "info", "The game is running right now",
            "Deck Doctor checks the last finished launch. Close the game, then run the checkup."))
        return findings

    if "corrupt_files" in log_hits:
        file, line = log_hits["corrupt_files"]
        findings.append(Finding(
            "corrupt_files", "problem", "Some game files are damaged",
            "The game's own log says it couldn't read part of its data. That usually means a "
            "download was interrupted. Verifying the files makes Steam re-download only the "
            "broken parts.",
            evidence=f"{file}: {line}", fixes=[Fix("verify_files", "Verify game files")]))

    if "anticheat_error" in log_hits:
        file, line = log_hits["anticheat_error"]
        findings.append(Finding(
            "anticheat_error", "problem", "The anti-cheat failed to start",
            "The game's anti-cheat reported an error. Some games only support it on certain Proton "
            "versions; others block Linux entirely. Check ProtonDB to see which.",
            evidence=f"{file}: {line}", fixes=[protondb]))

    for fid, title, detail in (
        ("missing_dotnet", "The game needs .NET Framework",
         "The log mentions .NET, which isn't included in this game's Proton setup. Deck Doctor can "
         "install it with Protontricks for you, right here in Game Mode."),
        ("missing_vcredist", "A Visual C++ runtime is missing",
         "The log says a Microsoft C++ runtime file is missing. Verifying the files usually "
         "reinstalls it; if not, Deck Doctor can install the runtimes with Protontricks."),
        ("gpu_device_lost", "The graphics driver crashed",
         "The game lost its connection to the GPU. A different Proton version, lower graphics "
         "settings, or DX11 mode (if the game offers it) often fixes this."),
    ):
        if fid in log_hits:
            file, line = log_hits[fid]
            fixes = {
                "missing_dotnet": [Fix("protontricks", "Install .NET Framework 4.8", target="dotnet48"), protondb],
                "missing_vcredist": [Fix("verify_files", "Verify game files"),
                                     Fix("protontricks", "Install Visual C++ runtimes", target="vcrun2022")],
            }.get(fid, [protondb])
            findings.append(Finding(fid, "problem", title, detail, evidence=f"{file}: {line}", fixes=fixes))

    # EmuDeck shortcuts: specific emulator problems (missing keys, BIOS, emulator) come first.
    findings.extend(emu_findings or [])

    proton = launch.proton
    forced = _tool(tools, forced_tool) if forced_tool else None
    if proton and forced and forced["label"] != proton:
        findings.append(Finding(
            "changed_since_launch", "info", f"Already switched to {forced['label']}",
            f"The last launch used {proton}, but the game has been set to {forced['label']} since "
            "then. Launch it again to test the new setting, then re-run the checkup."))
        return findings

    if "PROTON_REMOTE_DEBUG_CMD" in launch.launch_env and _is_new_proton(proton):
        fixes = [Fix("set_proton", "Switch to Proton 10", "proton_10")] if _tool(tools, "proton_10") else []
        findings.append(Finding(
            "trainer_new_proton", "problem", "Trainers don't open on this Proton version",
            f"This game launches a trainer (through CheatDeck), but it ran on {proton}. Trainer "
            "windows don't appear on Proton 11 or Experimental because of a Proton bug. Proton 10 "
            "works.", evidence=f"Ran on {proton}", fixes=fixes))

    quick = launch.seconds is not None and launch.seconds < QUICK_EXIT_SECONDS
    if quick and not any(f.severity == "problem" for f in findings):
        if proton:
            fixes = []
            for name, label in (("proton_experimental", "Try Proton Experimental"), ("proton_10", "Try Proton 10")):
                t = _tool(tools, name)
                if t and t["label"] != proton:
                    fixes.append(Fix("set_proton", label, name))
            ge = next((t for t in tools if t["label"].startswith("GE-Proton")), None)
            if ge:
                fixes.append(Fix("set_proton", f"Try {ge['label']}", ge["name"]))
            fixes.append(protondb)
            detail = (f"It ran for only {int(launch.seconds)} seconds on {proton}, and its logs "
                      "don't name a cause. The most common fix is a different Proton version. "
                      "Change one thing at a time, and avoid switching repeatedly on games with "
                      "Denuvo, which can lock you out for 24 hours.")
        elif emu:
            fixes = []
            detail = (f"It ran for only {int(launch.seconds)} seconds in {emu['name']} ({emu['console']}). "
                      f"Deck Doctor didn't find a missing BIOS, key or emulator, so open {emu['name']} "
                      "from Desktop Mode and load the game there to see its error message. Also check "
                      "that the game file isn't damaged or only partly copied.")
        elif not is_steam_game(appid):
            fixes = []
            detail = (f"It ran for only {int(launch.seconds)} seconds. This is a non-Steam shortcut "
                      "(for example an emulator or another launcher), so the problem is usually in "
                      "that program: a missing BIOS, keys or firmware file, or a game file it can't "
                      "read. Open the emulator directly to see its error message.")
        else:
            fixes = [Fix("verify_files", "Verify game files"), protondb]
            detail = (f"It ran for only {int(launch.seconds)} seconds and its logs don't name a "
                      "cause. Try verifying the game files.")
        findings.append(Finding(
            "quick_exit", "problem", "The game closed right after starting", detail,
            evidence=f"Last launch lasted {int(launch.seconds)}s", fixes=fixes))

    if not findings:
        findings.append(Finding(
            "looks_ok", "info", "No problems found in the last launch",
            f"The last launch ran for {int(launch.seconds or 0)} seconds and its logs look normal. "
            "If something still goes wrong, launch the game again, then re-run the checkup."))
    return findings


def diagnose(steam_root: str, appid: int, home: str) -> dict:
    launches = [l for l in steam.parse_launches(steam.console_lines(steam_root)) if l.appid == appid]
    launch = launches[-1] if launches else None
    manifest = steam.app_manifest(steam_root, appid)
    install_dir = None
    if manifest and manifest.get("installdir"):
        install_dir = os.path.join(manifest["_library"], "common", manifest["installdir"])
    logs = game_logs(steam_root, launch, install_dir) if launch and not launch.running else []
    tools = steam.installed_tools(steam_root)
    try:
        free = shutil.disk_usage(home).free
    except OSError:
        free = None

    forced_tool = steam.compat_tool_for(steam_root, appid)
    emu, emu_findings = None, []
    if launch and not launch.running and not is_steam_game(appid):
        from . import emulator  # imported here: emulator.py builds on this module's Finding
        emu = emulator.parse_shortcut(launch.command)
        if emu:
            emu_findings = emulator.check_emulator(emu, home, emulator.installed_flatpaks())
    findings = run_rules(appid, launch, manifest, _match_logs(logs), tools, free, forced_tool, emu, emu_findings)
    return {
        "appid": appid,
        "last_launch": None if launch is None else {
            "start": launch.start.isoformat(sep=" "),
            "seconds": launch.seconds,
            "proton": launch.proton,
        },
        "forced_tool": forced_tool,
        "emulator": emu,
        "logs_checked": [os.path.basename(p) for p in logs[:10]],
        "findings": [asdict(f) for f in findings],
    }


def game_name(steam_root: str, launch) -> Optional[str]:
    """A name for the game list when Steam's own library hasn't got one (uninstalled games, demos)."""
    manifest = steam.app_manifest(steam_root, launch.appid)
    if manifest and manifest.get("name"):
        return manifest["name"]
    # The command also names the Steam runtime and Proton folders; the game's folder comes last.
    command = launch.command.replace("'\\''", "'")  # Steam shell-quotes apostrophes as '\''
    folders = re.findall(r"steamapps/common/([^/\"]+?)'?/", command)
    return folders[-1] if folders else None


def recent_games(steam_root: str, limit: int = 8) -> list:
    """App IDs of the most recently launched games, newest first, with how the last launch went."""
    seen, out = set(), []
    for launch in reversed(steam.parse_launches(steam.console_lines(steam_root))):
        if launch.appid in seen:
            continue
        seen.add(launch.appid)
        out.append({"appid": launch.appid, "name": game_name(steam_root, launch),
                    "seconds": launch.seconds, "start": launch.start.isoformat(sep=" ")})
        if len(out) >= limit:
            break
    return out


def available_tools(steam_root: str) -> list:
    return steam.installed_tools(steam_root)
