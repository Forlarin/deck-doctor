# The game needs .NET Framework

The game (or a tool it starts) needs Microsoft .NET Framework, which isn't included in this game's Proton setup.

## Fix
1. Close the game, then tap **Install .NET Framework 4.8** in Deck Doctor. It runs Protontricks for you in the background (5-15 minutes), with no Desktop Mode needed. Keep the Deck plugged in.
2. When it says it's finished, launch the game.

## If that doesn't work
- Try a **GE-Proton** version. It sometimes includes what's needed.
- Doing it by hand: in Desktop Mode, install **Protontricks** from Discover, then run `flatpak run com.github.Matoking.protontricks <appid> -q dotnet48` in Konsole. Replace `<appid>` with the game's number from Deck Doctor.

---
Still stuck? [Ask for help](https://github.com/Forlarin/deck-doctor/issues/new?template=help.md) and include what Deck Doctor showed.
