# Cemu has no key for this Wii U disc image

Wii U disc images (.wux or .wud) are encrypted. Cemu needs each disc's key in its keys.txt to read them, and yours only has the example key, so Cemu can't open the game and closes.

## Fix
1. Find the disc key from **your own** disc dump. It's usually a .key file or a 32-character code saved next to the image when you dumped it.
2. Add it to **~/.local/share/Cemu/keys.txt** as a new line, e.g. `0123...cdef # Mario Kart 8`.
3. Launch the game again.

## No key?
Dump the game again with **Dumpling** on a homebrew-enabled Wii U. Dumpling saves the game as a folder (code, content, meta) that Cemu runs without any key. Put that folder in **Emulation/roms/wiiu/roms** and re-run Steam ROM Manager.

---
Still stuck? [Ask for help](https://github.com/Forlarin/deck-doctor/issues/new?template=help.md) and include what Deck Doctor showed.
