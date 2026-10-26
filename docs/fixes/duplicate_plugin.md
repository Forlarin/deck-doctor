# A plugin is installed more than once

Two plugin folders register the same name, so Decky loads one, unloads it and loads the other on every start. The plugin may disappear or only half work.

This often happens after installing a plugin twice: once from the store and once from a downloaded ZIP.

## Fix
1. Tap **Move to backup** for each extra copy. Deck Doctor keeps the working copy and moves the others to `~/homebrew/plugin-backups`. Nothing is deleted.
2. Restart the Deck.

To undo, move the folder back from `~/homebrew/plugin-backups` into `~/homebrew/plugins` (it needs `sudo`).

---
Still stuck? [Ask for help](https://github.com/Forlarin/deck-doctor/issues/new?template=help.md) and include what Deck Doctor showed.
