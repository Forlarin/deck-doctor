# The emulator's BIOS or keys are missing

Some emulators need a file from the original console before any game can start: a **BIOS** for PlayStation and PlayStation 2, or **prod.keys and firmware** for Switch. These files can't be included with emulators, and have to come from your own console.

## Fix
1. Dump the BIOS or keys from your own console.
2. Copy them into **Emulation/bios**. For Switch, keys go in **Emulation/bios/<emulator>/keys**.
3. In Desktop Mode, open **EmuDeck → BIOS Checker** to confirm they're recognised.
4. Launch the game again.

---
Still stuck? [Ask for help](https://github.com/Forlarin/deck-doctor/issues/new?template=help.md) and include what Deck Doctor showed.
