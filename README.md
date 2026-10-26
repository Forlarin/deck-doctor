# Deck Doctor 🩺

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that tells you **why a Steam Deck game won't launch**, in plain English, and fixes it with one tap. No Desktop Mode, no terminal.

It reads the same things an experienced Linux user would check (Steam's launch log, the Proton version the game ran on, and the game's own log files) and turns them into a short explanation with a fix button.

## What it checks

### Game won't launch
Pick any recently launched game in the Quick Access menu:

| Problem | Fix button |
|---|---|
| Damaged game files (e.g. `Decompression failed` in the game's log) | Verify game files |
| A CheatDeck trainer running on Proton 11 / Experimental, where trainer windows don't appear | Switch to Proton 10 |
| Game closes within a minute with no clear cause | Try Proton Experimental / Proton 10 / GE-Proton, ProtonDB |
| Anti-cheat that blocks SteamOS (Call of Duty, Destiny 2, Apex…) | Explains why and suggests cloud gaming |
| Missing .NET or Visual C++ runtime, GPU crash, anti-cheat error | Fix or guide for each |
| Update still pending, internal storage almost full | Explains what to do |
| Non-Steam shortcut (emulator) that crashes | Points you to the emulator |

Every Proton change can be undone with **Undo Deck Doctor's Proton change**.

### Plugin health
For when plugins disappear after a SteamOS update:

| Problem | Fix button |
|---|---|
| The same plugin installed twice, so Decky keeps unloading it | Move the extra copy to `~/homebrew/plugin-backups` (nothing is deleted) |
| A GitHub "Download ZIP" source folder instead of a built plugin | Move to backup, open the Decky store |
| A plugin that crashed on startup, with its error | Open the Decky store |
| Decky Loader out of date (flagged more strongly if Steam updated since) | Open Decky settings |

Every problem has a **How to fix this** guide ([docs/fixes](docs/fixes)) and a **Still stuck? Get help** button that opens a pre-filled help request here on GitHub.

## Install

Deck Doctor isn't in the Decky store yet. Until then:

1. Download `deck-doctor.zip` from [Releases](https://github.com/Forlarin/deck-doctor/releases) (the first release is coming soon).
2. On the Deck: Quick Access → Decky (plug icon) → ⚙ → **Developer** → **Install plugin from ZIP**.

## Permissions

Deck Doctor only **reads** files, with two exceptions:
- **Proton changes and file verification** go through Steam's own client API, the same calls the game's Properties menu makes.
- **Moving a duplicate plugin** to backup needs root, because Decky's plugins folder is owned by root. That's the only reason the plugin uses Decky's `root` flag, and the move is restricted to folders directly inside `~/homebrew/plugins`.

## Development

```bash
pnpm install
pnpm build            # frontend -> dist/index.js
npm test              # Python tests, built from real Steam Deck logs
scripts/deploy.sh deck@steamdeck.local   # copy to a Deck over SSH and verify checksums
```

- `py_modules/deck_doctor/steam.py` reads Steam's files (launch log, manifests, Proton installs).
- `py_modules/deck_doctor/diagnose.py` holds the "game won't launch" rules.
- `py_modules/deck_doctor/health.py` holds the plugin health rules.
- `src/index.tsx` is the Quick Access panel.

To add a check: add a rule that returns a `Finding`, a test for it, and a guide in `docs/fixes/<id>.md`. The tests fail if a problem has no guide.

## License

BSD-3-Clause. Built from the [Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template).
