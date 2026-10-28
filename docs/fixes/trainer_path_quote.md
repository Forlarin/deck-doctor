# The trainer's file name stops the game from starting

CheatDeck starts a trainer with the game by adding `PROTON_REMOTE_DEBUG_CMD="<path to trainer>"` to the game's launch options. Proton splits that path the way a shell would, so an apostrophe in the file name (for example `Assassin's Creed Mirage Trainer - FLiNG.exe`) looks like the start of a quote that never ends. Proton stops before the game starts, and no log is written.

## Fix
Press **Fix the launch options** in Deck Doctor, then start the game again. It puts a backslash before the apostrophe (`Assassin\'s`), so Proton reads it as part of the name. The trainer file isn't changed.

## Fix it by hand instead
1. In the game's Properties → General → Launch Options, find the trainer path.
2. Put a `\` before each `'` in the file name, e.g. `Assassin\'s\ Creed`.
3. Or rename the trainer file to remove the apostrophe, and add it to CheatDeck again.

---
Still stuck? [Ask for help](https://github.com/Forlarin/deck-doctor/issues/new?template=help.md) and include what Deck Doctor showed.
