# SteamClip - Steam Recording to MP4 Converter

SteamClip is a Python application that converts Steam game recordings into MP4 files with GPU-accelerated encoding support.

## Why SteamClip?

Steam uses m4s file format for video and audio that are layered together. Exporting to MP4 from Steam itself can produce visual artifacts.

SteamClip uses FFmpeg to convert recordings cleanly, with optional GPU encoding for significantly smaller file sizes.

## Features

### Core Features
- Convert multiple Steam recordings to MP4 at once
- **GPU-accelerated encoding** (NVIDIA NVENC, AMD AMF, Intel QuickSync)
- **Parallel exports** - process multiple clips simultaneously (1-16 concurrent jobs)
- **System Recordings support** - works with Steam's new system-wide recordings folder
- **Convert & Delete** option to export and remove originals
- Non-blocking export with detailed progress tracking

### User Interface
- Modern dark theme (Catppuccin-inspired)
- Scrollable grid showing ALL clips (no pagination limits)
- Filter by account, game, and clip type
- **Select All** button for batch operations
- Cancel button to stop exports gracefully

### Encoding Options
| Mode | Description |
|------|-------------|
| Fast Copy | No re-encode, same file size (default) |
| NVIDIA GPU (HEVC) | Uses NVENC, ~10x smaller files |
| AMD GPU (HEVC) | Uses AMF encoder |
| Intel GPU (HEVC) | Uses QuickSync |
| CPU (HEVC) | Software x265 fallback |

### File Naming
Exports use Steam's naming convention:
```
Game Name YYYY.MM.DD - HH.MM.SS.00.DVR.mp4
```

## Installation

1. Download SteamClip from the [Releases page](https://github.com/Wyattech/SteamClip/releases)
2. Run `SteamClip.exe` - no installation required

## Usage

1. **First Launch**: Select your Steam userdata folder (or use auto-detect)
2. **System Recordings**: Optionally set a custom recordings folder in Settings (e.g., `K:\Steam Recordings`)
3. **Select Clips**: Click thumbnails to select clips (use Select All for batch)
4. **Choose Encoding**: Set your preferred encoding mode in Settings
5. **Export**: Click "Convert" or "Convert & Delete"

### Settings
- **Steam Path**: Your Steam userdata folder
- **Recordings Folder**: Optional system-wide recordings location
- **Output Path**: Where exported MP4s are saved
- **Encoding Mode**: Choose between Fast Copy or GPU encoding
- **Custom Game Names**: Add names for non-Steam apps

Config location: `C:\Users\USERNAME\AppData\Local\SteamClip`

## Requirements

### Windows
- Windows 10 or above
- Optional: Internet connection (for fetching game names from Steam API)

### For GPU Encoding
- **NVIDIA**: GTX 10-series or newer with latest drivers
- **AMD**: RX 400 series or newer
- **Intel**: 6th gen Core or newer with integrated graphics

## Building from Source

### Requirements
- Python 3.8+
- PyQt6 (`pip install PyQt6`)
- imageio-ffmpeg (`pip install imageio-ffmpeg`)
- Pillow (`pip install pillow`)
- requests (`pip install requests`)

### Build Command
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=SteamClip.ico steamclip.py
```

The executable will be in the `dist` folder.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Credits

Based on original SteamClip by [Nastas95](https://github.com/Nastas95/SteamClip)

## Disclaimer

SteamClip does **NOT** collect any data. Internet connection is only used to fetch game names from Steam's public API.
