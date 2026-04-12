# 🎬 SteamClip
### The ultimate Steam Recording to MP4 Converter

[![Total Downloads](https://img.shields.io/github/downloads/Nastas95/SteamClip/total?style=for-the-badge&color=orange)](https://github.com/Nastas95/SteamClip/releases)
[![Python Version](https://img.shields.io/badge/Python-3.8+-yellow?style=for-the-badge&logo=python)](https://python.org)
[![License](https://img.shields.io/github/license/Nastas95/SteamClip?style=for-the-badge&color=green)](LICENSE)
[![Platforms](https://img.shields.io/badge/Platforms-Windows%20%7C%20Linux-blue?style=for-the-badge&logo=platformdotsh)](https://github.com/Nastas95/SteamClip)

**SteamClip** is a powerful yet lightweight graphical converter designed to transform your Steam game recordings into perfect, artifact-free `.mp4` files.

---

## 🚀 Why SteamClip?

Steam uses a segmented DASH format (`.m4s`) for recordings. While Steam offers a native export, it often introduces **heavy visual artifacts** and stuttering

**SteamClip fixes this:**
- ✅ **Glitch-Free Output:** No more pixelation or visual bugs
- ✅ **No Length Limits:** Handles long clips in seconds
- ✅ **User Friendly:** A complete GUI—no terminal commands required
- ✅ **Seamless Integration:** Automatically identifies game names, so you don't have to deal with random numerical ID
- ✅ Intuitive GUI — Export your clips in a few clicks

---

## ✨ Key Features

### 🛠️ User Experience
- **3x2 Interactive Grid:** Navigate your library easily with high-quality thumbnails and page controls
- **Batch Conversion:** Select multiple clips at once and let SteamClip do the heavy lifting
- **Automatic Naming:** SteamClip instantly finds the correct game name for every clip, so your files are always organized

### 🎮 Superior Game Recognition
- **Non-Steam Support:** Works perfectly with non-steam games (emulators, EmuDeck, Epic Games etc.) added to your Steam library
- **Custom Naming:** You can assign your own names to any app or game directly from the settings
- **Always Updated:** Uses official databases to ensure even the newest releases are correctly identified

### 🎨 Fully Customizable UI
Personalize your experience with **13 built-in themes**:
- **Gaming:** Steam Dark (Default), Cyberpunk, Neon Blue
- **Developer Favorites:** Dracula, Nord, Gruvbox, Catppuccin
- **Retro Vibes:** Pip-Boy, CRT Amber
- **System Aware:** Follows your OS Light/Dark settings automatically

---

## 🚀 Installation

1. Download the latest version from the [**Releases Page**](https://github.com/Nastas95/SteamClip/releases)
2. **Windows:** Download `steamclip.exe`
3. **Linux:** Download the binary or run the Python script directly
4. **No Dependencies Needed:** FFmpeg is built-in for the executable versions
>  💡 **Tip**: You can also clone the repository and build the executable manually (see below)

## 🎯 Usage Guide

1. **Initial Setup:** On the first launch, select your Steam installation:
   - `Standard`: Default paths for Windows and Linux
   - `Flatpak`: Specific for Linux Flatpak users
   - `Manual`: Browse and select your `userdata` folder manually
2. **Browse & Select:** Click on one or more clips in the 3x2 grid
3. **Convert:** Hit **"Convert Clip(s)"**. The final `.mp4` will be saved to your **Desktop** by default
4. **Customize:** Explore the settings to customize your experience

---

## 💻 System Requirements

### Windows
- **OS:** Windows 10 or 11
- **Connection:** Optional (only needed for GameID updates and version checks)

### Linux
- **Environment:** Any modern distro
- **Connection:** Optional (only needed for GameID updates and version checks)

> [!IMPORTANT]
> **FFmpeg is bundled** via `imageio-ffmpeg`. You do **not** need to install FFmpeg separately on your system

---

## 🔒 Privacy & Transparency
- **Zero Data Collection:** SteamClip does not collect, track, or share any personal data
- **Local Storage:** All configurations and cached GameIDs are stored locally:
  - **Windows:** `%LOCALAPPDATA%\SteamClip\`
  - **Linux:** `~/.config/SteamClip/`
- **Internet Usage:** Connection is used only to fetch game names from the Steam API and check for app updates on GitHub

---

## 🔨 Building from Source
If you want to build the executable yourself:
```bash
# 1. Install dependencies
pip install pyinstaller PyQt6 imageio[ffmpeg] pillow requests pathvalidate

# 2. Build the app
pyinstaller --onefile --windowed steamclip.py
```

---
## 🤝 Contributing & Support

- 💡 Have an idea for a new theme? Open a PR or suggest it in an issue!
- 🐛 Found a bug? [Open an issue](https://github.com/Nastas95/SteamClip/issues)

---

*Developed with ❤️ and a little AI assistance for the Steam Deck and PC Gaming community*

