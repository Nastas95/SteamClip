# SteamClip Changelog

## v3.0 - Major Overhaul

### New Features

#### System Recordings Support
- Added ability to set a custom Steam Recordings folder path (Settings > Recordings Folder)
- Supports Steam's new system-wide recordings location (e.g., `K:\Steam Recordings`)
- Scans both userdata clips and system recordings

#### Convert & Delete Option
- New "Convert & Delete" button that exports clips and removes the original Steam recordings
- Confirmation dialog to prevent accidental deletion

#### GPU Encoding (HEVC/H.265)
- Added hardware-accelerated encoding options in Settings:
  - **Fast Copy** - No re-encode, same file size (default)
  - **NVIDIA GPU (HEVC)** - Uses NVENC with CQ 28, 20Mbps max bitrate
  - **AMD GPU (HEVC)** - Uses AMF encoder
  - **Intel GPU (HEVC)** - Uses QuickSync
  - **CPU (HEVC)** - Software x265 fallback
- Auto-detects available GPU encoders on startup
- Significantly smaller file sizes (6GB -> ~500MB for 5 min clip)

#### Parallel Export System
- Export multiple clips simultaneously using ThreadPoolExecutor
- Dynamic **+/-** controls to adjust concurrent exports (1-16) during export
- Shows active job count in real-time
- Perfect for high-end GPUs like RTX 5090

#### Non-Blocking Export
- Export processing moved to background thread (QThread)
- UI remains fully responsive during export
- Cancel button to stop export (current jobs finish gracefully)

#### Detailed Progress Panel
- Shows current clip name being processed
- Displays clip count (e.g., "3 / 10")
- Shows current operation status (Extracting, Concatenating, Encoding)
- Shows selected encoding mode
- Active jobs indicator

#### Scrollable Clip Grid
- Replaced 6-clip pagination with infinite scrollable grid
- Shows ALL clips matching current filter at once
- 4-column layout with smaller thumbnails (220x140)
- Removed Previous/Next buttons

#### Select All Button
- New "Select All" button to select all clips in current filter
- Works with game and clip type filters

### UI Improvements

#### Modern Dark Theme
- Catppuccin-inspired dark theme
- Colors: #1e1e2e (background), #89b4fa (accent), #f38ba8 (danger)
- Consistent styling across all components

#### Improved Layout
- Labeled filter sections (ACCOUNT, GAME, CLIP TYPE)
- Status bar showing selection count
- Reorganized action buttons
- Larger window (1000x720)

#### Better File Naming
- New format: `Game Name YYYY.MM.DD - HH.MM.SS.00.DVR.mp4`
- Uses folder modification time for accurate timestamps
- Matches Steam's native naming convention

### Bug Fixes

#### Critical Export Crash Fix
- Fixed `exc_info=e` -> `exc_info=exc` (undefined variable causing NameError)

#### FFmpeg Error Logging
- Added stderr capture to all ffmpeg subprocess calls
- Errors now logged for debugging

#### Settings Window
- Fixed button text visibility (dark text on light buttons)
- Increased window height to accommodate encoding options

### Technical Changes

- Added `QScrollArea` for clip grid
- Added `QThread` and `pyqtSignal` for async export
- Added `ThreadPoolExecutor` for parallel processing
- Added `threading` module for locks and synchronization
- New `ExportWorker` class with parallel processing support
- New `detect_available_encoders()` function
- Config now saves `encoding_mode` setting

### Dependencies
- PyQt6
- imageio-ffmpeg
- PIL/Pillow
- requests

---

*Based on original SteamClip from Wyattech/SteamClip*
