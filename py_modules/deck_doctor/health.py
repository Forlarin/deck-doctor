"""Plugin health: problems that typically appear after a SteamOS or Steam client update.

- Two plugin folders registering the same name, so Decky loads one, unloads it
  and loads the other on every boot (what broke CheatDeck on our test Deck).
- Plugin folders with no built frontend (a GitHub "Download ZIP" of the source).
- Plugins whose backend crashed on startup.
- A Decky Loader older than the latest release, especially after Steam updated.
"""

import json
import os
import re
import subprocess
import urllib.request
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from .diagnose import Finding, Fix

LATEST_URL = "https://api.github.com/repos/SteamDeckHomebrew/decky-loader/releases/latest"
FAILED_RE = re.compile(r"Failed to start (.+) \(v[^)]*\)!")
LOADED_RE = re.compile(r"\]: Loaded (.+) \(v[^)]*\)\s*$")
ERROR_RE = re.compile(r"^\s*\w*(?:Error|Exception)\b.*")


def read_plugins(plugins_dir: str) -> list:
    """[{"folder", "name", "version", "built"}] for every folder in Decky's plugins directory."""
    out = []
    for folder in sorted(os.listdir(plugins_dir)) if os.path.isdir(plugins_dir) else []:
        path = os.path.join(plugins_dir, folder)
        try:
            with open(os.path.join(path, "plugin.json")) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        version = None
        try:
            with open(os.path.join(path, "package.json")) as f:
                version = json.load(f).get("version")
        except (OSError, ValueError):
            pass
        out.append({
            "folder": folder,
            "name": meta.get("name", folder),
            "version": version,
            "built": os.path.exists(os.path.join(path, "dist", "index.js")),
        })
    return out


def startup_failures(journal_text: str) -> dict:
    """{plugin name: last error line} for plugins whose most recent start this boot failed.

    Decky logs "Loaded X" when it picks a plugin up and "Failed to start X!" right
    after if its backend crashes, so a later "Loaded X" with no failure after it
    means the plugin has since started fine (e.g. after a fix and a Decky restart).
    """
    failures, lines = {}, journal_text.splitlines()
    for i, line in enumerate(lines):
        if loaded := LOADED_RE.search(line):
            failures.pop(loaded.group(1), None)
            continue
        m = FAILED_RE.search(line)
        if not m:
            continue
        error = ""
        for follow in lines[i + 1:i + 25]:
            text = re.sub(r"^.*?PluginLoader\[\d+\]: ", "", follow)
            if ERROR_RE.match(text):
                error = text.strip()
                break
        failures[m.group(1)] = error[:200]
    return failures


def _version_tuple(v: Optional[str]) -> Optional[tuple]:
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(int(x) for x in m.groups()) if m else None


def check_plugins(plugins: list, failures: dict, decky_version: Optional[str],
                  latest_version: Optional[str], steam_updated_after_decky: bool) -> list:
    """Pure decision logic for plugin health, kept separate from file access for testing."""
    findings = []

    by_name, duplicated = {}, set()
    for p in plugins:
        by_name.setdefault(p["name"], []).append(p)
    for name, copies in by_name.items():
        if len(copies) < 2:
            continue
        duplicated.update(p["folder"] for p in copies)
        # Keep the built copy with the plain folder name; offer to move the rest.
        keep = sorted(copies, key=lambda p: (not p["built"], len(p["folder"]), p["folder"]))[0]
        extras = [p for p in copies if p is not keep]
        findings.append(Finding(
            "duplicate_plugin", "problem", f"{name} is installed {len(copies)} times",
            f"The folders {', '.join(p['folder'] for p in copies)} all register as \"{name}\", so "
            "Decky loads one, unloads it and loads another on every start. That can make the "
            f"plugin disappear or half-work. Keep \"{keep['folder']}\" and move the extra "
            "copies to a backup folder (nothing is deleted).",
            evidence=", ".join(f"{p['folder']} (v{p['version'] or '?'}{'' if p['built'] else ', not built'})"
                               for p in copies),
            fixes=[Fix("move_plugin", f"Move \"{p['folder']}\" to backup", target=p["folder"]) for p in extras]))

    for p in plugins:
        if not p["built"] and p["folder"] not in duplicated:
            findings.append(Finding(
                "unbuilt_plugin", "problem", f"{p['name']} is source code, not an installable plugin",
                f"The folder \"{p['folder']}\" has no built frontend (dist/index.js), which happens when "
                "a plugin is downloaded with GitHub's \"Download ZIP\" button. It can't show anything. "
                "Install it from the Decky store or its Releases page instead.",
                fixes=[Fix("move_plugin", f"Move \"{p['folder']}\" to backup", target=p["folder"]),
                       Fix("open_decky_store", "Open the Decky store")]))

    for name, error in failures.items():
        findings.append(Finding(
            "plugin_crashed", "problem", f"{name} crashed when Decky started",
            "Its background part failed to start, so its features won't work. This often happens "
            "after a SteamOS update until the plugin's author releases a fix. Check the Decky store "
            "for an update.",
            evidence=error or None, fixes=[Fix("open_decky_store", "Open the Decky store")]))

    current, latest = _version_tuple(decky_version), _version_tuple(latest_version)
    if current and latest and current < latest:
        why = ("Steam updated itself after Decky was installed, and Steam updates often break "
               "older Decky versions. " if steam_updated_after_decky else "")
        findings.append(Finding(
            "decky_outdated", "problem" if steam_updated_after_decky else "warning",
            f"Decky Loader is out of date ({decky_version} → {latest_version})",
            why + "Updating Decky keeps all your plugins and their settings.",
            fixes=[Fix("open_decky_settings", "Open Decky settings to update")]))

    if not findings:
        summary = f"{len(plugins)} plugins installed, no duplicates or crashes"
        if decky_version:
            summary += f", Decky {decky_version}" + (" (latest)" if latest and current == latest else "")
        findings.append(Finding("plugins_ok", "info", "All plugins look healthy", summary + "."))
    return findings


def latest_decky_version(timeout: float = 5) -> Optional[str]:
    try:
        req = urllib.request.Request(LATEST_URL, headers={"User-Agent": "deck-doctor"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r).get("tag_name")
    except Exception:
        return None


def plugin_health(home: str, steam_root: str) -> dict:
    homebrew = os.path.join(home, "homebrew")
    plugins = read_plugins(os.path.join(homebrew, "plugins"))
    try:
        journal = subprocess.run(["journalctl", "-u", "plugin_loader", "-b", "--no-pager", "-o", "cat"],
                                 capture_output=True, text=True, timeout=15).stdout
    except Exception:
        journal = ""
    try:
        with open(os.path.join(homebrew, "services", ".loader.version")) as f:
            decky_version = f.read().strip()
    except OSError:
        decky_version = None
    try:
        steam_mtime = os.path.getmtime(os.path.join(steam_root, "package",
                                                    "steam_client_steamdeck_stable_ubuntu12.manifest"))
        decky_mtime = os.path.getmtime(os.path.join(homebrew, "services", "PluginLoader"))
        steam_after = steam_mtime > decky_mtime
    except OSError:
        steam_after = False
    latest = latest_decky_version()
    findings = check_plugins(plugins, startup_failures(journal), decky_version, latest, steam_after)
    return {
        "decky_version": decky_version,
        "latest_version": latest,
        "plugin_count": len(plugins),
        "findings": [asdict(f) for f in findings],
    }


def move_plugin_to_backup(home: str, folder: str) -> str:
    """Move one plugin folder out of Decky's plugins directory. Returns the backup path.

    The folder name must be a direct child of ~/homebrew/plugins, so this can't be
    pointed anywhere else.
    """
    plugins_dir = os.path.realpath(os.path.join(home, "homebrew", "plugins"))
    src = os.path.realpath(os.path.join(plugins_dir, folder))
    if os.path.dirname(src) != plugins_dir or not os.path.isdir(src):
        raise ValueError(f"not a plugin folder: {folder}")
    backup_dir = os.path.join(home, "homebrew", "plugin-backups")
    os.makedirs(backup_dir, exist_ok=True)
    dest = os.path.join(backup_dir, f"{folder}-{datetime.now():%Y%m%d-%H%M%S}")
    os.rename(src, dest)
    return dest
