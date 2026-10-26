# Trainers don't open on this Proton version

Trainers started through CheatDeck use a Proton feature (`PROTON_REMOTE_DEBUG_CMD`). On Proton 11 and Proton Experimental, a bug stops the trainer's window from appearing.

## Fix
1. Tap **Switch to Proton 10** in Deck Doctor. Or: ⚙ → **Properties** → **Compatibility** → tick **Force the use of a specific Steam Play compatibility tool** → **Proton 10.0**.
2. Launch the game. The trainer window can take 10–20 seconds and may open behind the game.

## If the trainer still doesn't open
- FLiNG trainers made after mid-2023 often need .NET Framework 4.8 in the game's Proton setup: install it with Protontricks (`protontricks <appid> dotnet48`).
- Make sure the trainer matches your game version.
- Only use trainers in single-player games.

---
Still stuck? [Ask for help](https://github.com/Forlarin/deck-doctor/issues/new?template=help.md) and include what Deck Doctor showed.
