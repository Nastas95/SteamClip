# SteamClip

[![Total Downloads](https://img.shields.io/github/downloads/Nastas95/SteamClip/total?style=for-the-badge&color=orange)](https://github.com/Nastas95/SteamClip/releases)
[![Python Version](https://img.shields.io/badge/Python-3.8+-yellow?style=for-the-badge&logo=python)](https://python.org)
[![License](https://img.shields.io/github/license/Nastas95/SteamClip?style=for-the-badge&color=green)](LICENSE)
[![Platforms](https://img.shields.io/badge/Platforms-Windows%20%7C%20Linux-blue?style=for-the-badge&logo=platformdotsh)](https://github.com/Nastas95/SteamClip)

> A GUI converter for Steam game recordings

Steam stores recordings as segmented `.m4s` files (DASH format). The native export works, but often produces pixelation and stuttering. SteamClip converts those recordings to clean `.mp4` files using FFmpeg, with no artifacts and no length limits

---

## Features

+ **Clip browser** — your recordings are displayed in a thumbnail grid with page controls. Click one or more clips, hit convert, done. The output lands on your Desktop by default

+ **Automatic game names** — SteamClip identifies the game for each clip automatically, including non-Steam games added to your Steam library (emulators, EmuDeck, Epic, etc.). You can also assign custom names from the settings

+ **FFmpeg bundled** — no separate installation needed

+ **13 built-in themes** — Steam Dark, Cyberpunk, Neon Blue, Dracula, Nord, Gruvbox, Catppuccin, Pip-Boy, CRT Amber, and a few more. Follows your OS light/dark setting automatically if you prefer

+ **Privacy** — no data collection. Everything is stored locally. The only outbound connections are Steam API calls for game names and GitHub release checks for updates

---

## Installation

+ **Windows:** download `steamclip.exe` from the [Releases page](https://github.com/Nastas95/SteamClip/releases)

+ **Linux:** download the binary from the [Releases page](https://github.com/Nastas95/SteamClip/releases) 

+ **or run from source:**

```bash
git clone https://github.com/Nastas95/SteamClip
cd SteamClip
pip install PyQt6 imageio[ffmpeg] pillow requests pathvalidate
python steamclip.py
```


On first launch, select your Steam installation type: Standard, Flatpak, or Manual (if your `userdata` folder is somewhere non-standard)

---

## Building from source

```bash
pip install pyinstaller PyQt6 imageio[ffmpeg] pillow requests pathvalidate
pyinstaller --onefile --windowed steamclip.py
```

---

## Data storage

- **Windows:** `%LOCALAPPDATA%\SteamClip\`
- **Linux:** `~/.config/SteamClip\`

---

## Contributing

Bug reports and feature requests go in [Issues](https://github.com/Nastas95/SteamClip/issues)

---

*Developed with ❤️ and a little AI assistance for the Steam Deck and PC gaming community*
