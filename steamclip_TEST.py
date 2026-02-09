#!/usr/bin/env python3
import os
import sys
import subprocess
import json
from typing import Optional
import webbrowser
import imageio_ffmpeg as iio
import logging
import traceback
import shutil
import tempfile
import glob
import requests
import pathvalidate
import platform
import xml.etree.ElementTree as ElTree
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import getpass
import struct
import zlib
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGridLayout,
    QFrame, QComboBox, QDialog, QTableWidget,
    QTableWidgetItem, QTextEdit, QMessageBox,
    QFileDialog, QLayout, QProgressBar, QHeaderView,
    QGroupBox
)
from PyQt6.QtGui import QPixmap, QIcon, QDesktopServices, QColor
from PyQt6.QtCore import Qt, QUrl, QThread, pyqtSignal

DEBUG = '-debug' in sys.argv
IS_WINDOWS = sys.platform == 'win32'
EXECUTABLE_NAME = 'steamclip'

if DEBUG:
    CONFIG_PATH = os.path.join(os.getcwd(), 'runtime')
    os.makedirs(CONFIG_PATH, exist_ok=True)
elif IS_WINDOWS:
    CONFIG_PATH = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser("~")), 'SteamClip')
    EXECUTABLE_NAME += '.exe'
else:
    CONFIG_PATH = os.path.expanduser("~/.config/SteamClip")

user_actions = []

def setup_logging():
    pass

def logger(action, exc_info=None):
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted_action = f"[{timestamp}] {action}"
    user_actions.append(formatted_action)
    if exc_info:
        print(f"ERROR: {formatted_action}", file=sys.stderr)
        traceback.print_exception(type(exc_info), exc_info, exc_info.__traceback__)
    elif DEBUG:
        print(formatted_action)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log_dir = os.path.join(SteamClipApp.CONFIG_DIR, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_dir, f"crash_{timestamp}.log")

    if IS_WINDOWS:
        try:
            windows_version = platform.version()
            windows_release = 11 if sys.getwindowsversion().build >= 22000 else platform.release()
            windows_edition = getattr(platform, 'win32_edition', lambda: 'Unknown Edition')()
            windows_system = platform.system()
            windows_info = f"{windows_system} {windows_release} ({windows_version} - {windows_edition})"
        except (Exception,):
            windows_info = "Unknown Windows Version"
        system_info = (
            "\nSystem Information:\n"
            f"Python Version: {sys.version}\n"
            f"Platform: {sys.platform}\n"
            f"Windows Version: {windows_info}\n"
        )
    else:
        try:
            dist_info = {}
            if os.path.exists('/etc/os-release'):
                with open('/etc/os-release') as f:
                    for line in f:
                        if '=' in line:
                            k, v = line.split('=', 1)
                            dist_info[k.strip()] = v.strip().strip('"')
            linux_distro = dist_info.get('PRETTY_NAME', 'Unknown Linux Distribution')
            linux_version = dist_info.get('VERSION_ID', 'Unknown Version')
        except (Exception,):
            linux_distro = 'Unknown Linux Distribution'
            linux_version = 'Unknown Version'
        system_info = (
            "\nSystem Information:\n"
            f"Python Version: {sys.version}\n"
            f"Platform: {sys.platform}\n"
            f"Linux Distribution: {linux_distro}\n"
            f"Linux Version: {linux_version}\n"
        )

    log_buffer = []
    log_buffer.append("SteamClip Crash Log:\n")
    log_buffer.append("===================\n")
    for action in user_actions:
        log_buffer.append(f"{action}\n")
    log_buffer.append("\nError Details:\n")
    log_buffer.append("===================\n")
    tb_list = traceback.format_exception(exc_type, exc_value, exc_traceback)
    log_buffer.append("".join(tb_list))
    log_buffer.append(system_info)
    full_log_text = "".join(log_buffer)

    try:
        current_user = getpass.getuser()
        if current_user:
            full_log_text = full_log_text.replace(current_user, "USERNAME")
    except Exception:
        pass

    with open(log_file, "w", encoding='utf-8') as f:
        f.write(full_log_text)

    QMessageBox.critical(None, "Critical Error",
        f"An unexpected error occurred:\n{exc_value}\n"
        "A crash report has been saved to:\n"
        f"{log_file}")

class ThumbnailFrame(QFrame):
    def __init__(self, parent=None):
        super(ThumbnailFrame, self).__init__(parent)
        self.folder = None

class ConversionThread(QThread):
    progress_update = pyqtSignal(str, int)
    finished_signal = pyqtSignal(bool, str, bool)
    error_signal = pyqtSignal(str)

    def __init__(self, clip_list, export_dir, game_ids, export_all=False):
        super().__init__()
        self.clip_list = clip_list
        self.export_dir = export_dir
        self.game_ids = game_ids
        self.export_all = export_all
        self._is_cancelled = False

    def cancel(self):
        logger("Conversion thread cancellation requested.")
        self._is_cancelled = True

    def run(self):
        total_clips = len(self.clip_list)
        errors = False
        logger(f"Starting conversion thread. Total clips to process: {total_clips}")
        self.progress_update.emit("Starting Conversion...", 0)

        for clip_idx, clip_folder in enumerate(self.clip_list):
            if self._is_cancelled:
                logger("Conversion cancelled by user.")
                break

            try:
                self.update_progress(clip_idx, total_clips, 0, 3)
                if not self.process_single_clip(clip_folder, clip_idx, total_clips):
                    errors = True
                    logger(f"Failed to convert clip: {clip_folder}")
            except Exception as e:
                logger(f"Critical error in thread for clip {clip_folder}: {e}", exc_info=e)
                errors = True

        msg = "All clips converted successfully" if not errors else "Some clips failed to convert"
        logger(f"Conversion thread finished. Result: {msg}")
        self.finished_signal.emit(not errors, msg, self.export_all)

    def update_progress(self, current_clip, total_clips, step, total_steps):
        clip_segment = 100 / total_clips
        step_progress = (step / total_steps) * clip_segment
        total_progress = (current_clip * clip_segment) + step_progress
        display_clip_num = current_clip + 1
        msg = f"Processing Clip {display_clip_num}/{total_clips} - {int(total_progress)}%"
        self.progress_update.emit(msg, int(total_progress))

    def process_single_clip(self, clip_folder, clip_idx, total_clips):
        logger(f"Processing clip [{clip_idx+1}/{total_clips}]: {os.path.basename(clip_folder)}")
        temp_files = []
        try:
            session_mpd_files = self.find_session_mpd_files(clip_folder)
            logger(f"Found {len(session_mpd_files)} session files in {clip_folder}")
            video_files, audio_files = self.prepare_temp_media_files(session_mpd_files)
            temp_files.extend(video_files + audio_files)

            logger("Concatenating video segments...")
            concatenated_video = self.concatenate_media_files(video_files, is_video=True)
            temp_files.append(concatenated_video)
            self.update_progress(clip_idx, total_clips, 1, 3)

            logger("Concatenating audio segments...")
            concatenated_audio = self.concatenate_media_files(audio_files, is_video=False)
            temp_files.append(concatenated_audio)
            self.update_progress(clip_idx, total_clips, 2, 3)

            logger("Merging video and audio...")
            output_file = self.generate_and_merge_final_file(
                concatenated_video, concatenated_audio, clip_folder
            )
            self.update_progress(clip_idx, total_clips, 3, 3)
            logger(f"Clip successfully generated: {output_file}")
            return True
        except Exception as exc:
            logger(f"Error processing clip {clip_folder}: {str(exc)}", exc_info=exc)
            return False
        finally:
            self.cleanup_clip_temp_files(temp_files)

    def find_session_mpd_files(self, clip_folder):
        session_mpd_files = []
        for root, _, files in os.walk(clip_folder):
            if 'session.mpd' in files:
                session_mpd_files.append(os.path.join(root, 'session.mpd'))
        if not session_mpd_files:
            raise FileNotFoundError(f"No session.mpd files found in {clip_folder}")
        return session_mpd_files

    def prepare_temp_media_files(self, session_mpd_files):
        temp_video_paths = []
        temp_audio_paths = []
        for session_mpd in session_mpd_files:
            data_dir = os.path.dirname(session_mpd)
            video_path, audio_path = self.create_temp_media_file(data_dir)
            temp_video_paths.append(video_path)
            temp_audio_paths.append(audio_path)
        return temp_video_paths, temp_audio_paths

    def create_temp_media_file(self, data_dir):
        init_video = os.path.join(data_dir, 'init-stream0.m4s')
        init_audio = os.path.join(data_dir, 'init-stream1.m4s')
        if not (os.path.exists(init_video) and os.path.exists(init_audio)):
            raise FileNotFoundError(f"Initialization files missing in {data_dir}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_video:
            with open(init_video, 'rb') as f:
                tmp_video.write(f.read())
            chunks = sorted(glob.glob(os.path.join(data_dir, 'chunk-stream0-*.m4s')))
            for chunk in chunks:
                with open(chunk, 'rb') as f:
                    tmp_video.write(f.read())
            temp_video_path = tmp_video.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_audio:
            with open(init_audio, 'rb') as f:
                tmp_audio.write(f.read())
            chunks = sorted(glob.glob(os.path.join(data_dir, 'chunk-stream1-*.m4s')))
            for chunk in chunks:
                with open(chunk, 'rb') as f:
                    tmp_audio.write(f.read())
            temp_audio_path = tmp_audio.name

        return temp_video_path, temp_audio_path

    def concatenate_media_files(self, media_paths, is_video=True):
        ffmpeg_path = iio.get_ffmpeg_exe()
        output_file = os.path.join(tempfile.gettempdir(), f"concat_{'video' if is_video else 'audio'}_{os.getpid()}_{hash(str(media_paths))}.mp4")
        list_file = tempfile.NamedTemporaryFile(delete=False, mode='w', suffix=".txt")
        for media_path in media_paths:
            list_file.write(f"file '{media_path}'\n")
        list_file.close()

        try:
            subprocess_args = {'check': True, 'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE}
            if IS_WINDOWS:
                subprocess_args['creationflags'] = subprocess.CREATE_NO_WINDOW

            command = [
                ffmpeg_path, '-f', 'concat', '-safe', '0', '-i', list_file.name,
                '-c', 'copy'
            ]
            if is_video:
                command.extend(['-movflags', '+faststart', '-max_muxing_queue_size', '1024'])
            command.append(output_file)

            subprocess.run(command, **subprocess_args)
            return output_file
        finally:
            os.unlink(list_file.name)

    def generate_and_merge_final_file(self, video_path, audio_path, clip_folder):
        output_file = self.generate_output_filename(clip_folder)
        ffmpeg_path = iio.get_ffmpeg_exe()
        subprocess_args = {'check': True}
        if IS_WINDOWS:
            subprocess_args['creationflags'] = subprocess.CREATE_NO_WINDOW

        logger(f"Merging to output file: {output_file}")
        subprocess.run([
            ffmpeg_path, '-i', video_path, '-i', audio_path, '-c', 'copy', output_file
        ], **subprocess_args)
        return output_file

    def generate_output_filename(self, clip_folder):
        folder_basename = os.path.basename(clip_folder)
        parts = folder_basename.split('_')
        formatted_date = self.extract_date_from_folder_name(parts)
        game_id = parts[1] if len(parts) > 1 else "UnknownGame"
        game_name = self.game_ids.get(game_id)
        if not game_name:
            game_name = game_id
        sanitized_game_name = pathvalidate.sanitize_filename(game_name)
        base_filename_with_date = f"{sanitized_game_name}_{formatted_date}"
        return self.get_unique_filename(self.export_dir, f"{base_filename_with_date}.mp4")

    def extract_date_from_folder_name(self, parts):
        if len(parts) >= 3:
            try:
                datetime_str = parts[-2] + parts[-1]
                dt_obj = datetime.strptime(datetime_str, "%Y%m%d%H%M%S")
                return dt_obj.strftime("%Y-%m-%d_%H-%M-%S")
            except ValueError:
                pass
        return "UnknownDate"

    def cleanup_clip_temp_files(self, file_paths):
        count = 0
        for file_path in file_paths:
            if file_path and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                    count += 1
                except Exception as exc:
                    logger(f"Error cleaning up temp file {file_path}: {str(exc)}")
        if count > 0:
            logger(f"Cleaned up {count} temporary files.")

    @staticmethod
    def get_unique_filename(directory, filename):
        base_name, ext = os.path.splitext(filename)
        counter = 1
        unique_filename = os.path.join(directory, filename)
        while os.path.exists(unique_filename):
            unique_filename = os.path.join(directory, f"{base_name}_{counter}{ext}")
            counter += 1
        return unique_filename

class SteamClipApp(QWidget):
    CONFIG_DIR = CONFIG_PATH
    CONFIG_FILE = os.path.join(CONFIG_DIR, 'SteamClip.conf')
    GAME_IDS_FILE = os.path.join(CONFIG_DIR, 'GameIDs.json')
    STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
    GITHUB_RELEASES_URL = "https://github.com/Nastas95/SteamClip/releases"
    CURRENT_VERSION = "v0.0"

    def __init__(self):
        super().__init__()
        logger("Initializing SteamClipApp UI...")
        self.setWindowIcon(QIcon('SteamClip.ico'))
        self.setWindowTitle("SteamClip")
        self.setGeometry(100, 100, 900, 600)
        self._is_cancelled = False
        self.clip_index = 0
        self.clip_folders = []
        self.original_clip_folders = []
        self.game_ids = {}
        self._custom_record_cache = {}
        self.config = self.load_config()
        self.default_dir = self.config.get('userdata_path')
        self.export_dir = self.config.get('export_path', os.path.normpath(os.path.join(os.path.expanduser("~"), "Desktop")))
        self.prev_steamid = None
        self.prev_media_type = None
        self.wait_message = None
        self.settings_window = None
        self.conversion_thread = None

        first_run = not os.path.exists(self.CONFIG_FILE)
        if not self.default_dir:
            logger("No default directory configured. Prompting user.")
            self.default_dir = self.prompt_steam_version_selection()
            if not self.default_dir:
                logger("User cancelled folder selection or failed to find one. Exiting.")
                QMessageBox.critical(self, "Critical Error", "Failed to locate Steam userdata directory. Exiting.")
                sys.exit(1)

        self.save_config(self.default_dir, self.export_dir)
        self.load_game_ids()  # Ora include automaticamente i giochi non-Steam

        # UI Components (identici all'originale)
        self.steamid_combo = QComboBox()
        self.gameid_combo = QComboBox()
        self.media_type_combo = QComboBox()
        self.steamid_combo.setFixedSize(300, 40)
        self.gameid_combo.setFixedSize(300, 40)
        self.media_type_combo.setFixedSize(300, 40)
        self.media_type_combo.addItems(["All Clips", "Manual Clips", "Background Clips"])
        self.media_type_combo.setCurrentIndex(0)

        self.steamid_combo.currentIndexChanged.connect(self.on_steamid_selected)
        self.gameid_combo.currentIndexChanged.connect(self.filter_clips_by_gameid)
        self.media_type_combo.currentIndexChanged.connect(self.filter_media_type)

        self.clip_grid = QGridLayout()
        self.clip_grid.setSpacing(15)
        self.clip_frame = QFrame()
        self.clip_frame.setLayout(self.clip_grid)

        self.clear_selection_button = self.create_button("Clear Selection", self.clear_selection, enabled=False, size=(150, 40))
        self.export_all_button = self.create_button("Export All", self.export_all, enabled=True, size=(150, 40))

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(25)
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.clear_selection_layout = QHBoxLayout()
        self.clear_selection_layout.addStretch()
        self.clear_selection_layout.addWidget(self.clear_selection_button)
        self.clear_selection_layout.addWidget(self.export_all_button)
        self.clear_selection_layout.addStretch()

        if DEBUG:
            self.debug_button = self.create_button("Debug Crash", self.debug_crash, enabled=True, size=(150, 40))
            self.clear_selection_layout.addWidget(self.debug_button)

        self.settings_button = self.create_button("", self.open_settings, icon=QIcon.ThemeIcon.DocumentProperties, size=(40, 40))

        self.id_selection_layout = QHBoxLayout()
        self.id_selection_layout.addWidget(self.settings_button)
        self.id_selection_layout.addWidget(self.steamid_combo)
        self.id_selection_layout.addWidget(self.gameid_combo)
        self.id_selection_layout.addWidget(self.media_type_combo)

        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.addLayout(self.id_selection_layout)
        self.main_layout.addWidget(self.clip_frame)
        self.main_layout.addLayout(self.clear_selection_layout)

        # Bottom Layout
        self.convert_button = self.create_button("Convert Clip(s)", self.convert_clip, enabled=False)
        self.convert_button.setProperty("class", "primary")
        self.exit_button = self.create_button("Exit", self.close)
        self.exit_button.setProperty("class", "secondary")
        self.prev_button = self.create_button("<< Previous", self.show_previous_clips)
        self.next_button = self.create_button("Next >>", self.show_next_clips)

        self.bottom_layout = QHBoxLayout()
        self.bottom_layout.addWidget(self.prev_button)
        self.bottom_layout.addWidget(self.next_button)
        self.bottom_layout.addWidget(self.convert_button)
        self.bottom_layout.addWidget(self.exit_button)

        self.main_layout.addLayout(self.bottom_layout)
        self.setLayout(self.main_layout)
        self.main_layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.progress_bar)

        self.selected_clips = set()
        self.del_invalid_clips()
        self.populate_steamid_dirs()
        self.perform_update_check()
        logger("Application UI Setup Complete.")

        if first_run:
            logger("First run detected. Info message displayed.")
            QMessageBox.information(self, "INFO",
                "Clips will be saved on the Desktop. You can change the export path in the settings.")

    # ============ METODI AGGIUNTI PER NON-STEAM GAMES ============

    def find_steam_root(self):
        """Locate Steam installation directory based on platform and configuration."""
        # Try to get from existing config first
        if self.default_dir and os.path.isdir(self.default_dir):
            steam_root = Path(self.default_dir).parent.parent
            if (steam_root / "userdata").exists():
                return steam_root.resolve()

        # Platform-specific fallbacks
        if IS_WINDOWS:
            candidates = [
                Path(r"C:\Program Files (x86)\Steam"),
                Path(r"C:\Program Files\Steam"),
            ]
            for path in candidates:
                if path.exists() and (path / "userdata").exists():
                    return path.resolve()
        else:
            candidates = [
                Path.home() / ".steam" / "steam",
                Path.home() / ".local" / "share" / "Steam",
                Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",  # Flatpak
                Path.home() / "snap" / "steam" / "common" / ".steam" / "steam",  # Snap
            ]
            for path in candidates:
                if path.exists() and (path / "userdata").exists():
                    return path.resolve()

        # Last resort: try to infer from default_dir
        if self.default_dir:
            return Path(self.default_dir).parent.parent.resolve()

        return None

    def parse_binary_vdf(self, data):
        """Parser for Steam's binary VDF format used in shortcuts.vdf."""
        def read_string(d, p):
            end = d.find(b'\x00', p)
            if end == -1:
                raise ValueError("Unterminated string")
            s = d[p:end].decode('utf-8', 'replace')
            return s, end + 1

        def parse_map(d, p):
            res = {}
            while p < len(d):
                type_byte = d[p]
                p += 1
                if type_byte == 0x08:  # End of map
                    return res, p
                if p >= len(d):
                    break
                try:
                    key, p = read_string(d, p)
                except ValueError:
                    break

                if type_byte == 0x00:  # Nested map
                    sub_map, p = parse_map(d, p)
                    res[key] = sub_map
                elif type_byte == 0x01:  # String
                    val, p = read_string(d, p)
                    res[key] = val
                elif type_byte == 0x02:  # Int32 (treated as unsigned)
                    if p + 4 > len(d):
                        break
                    val = struct.unpack('<I', d[p:p+4])[0]
                    p += 4
                    res[key] = val
                else:
                    # Skip unknown types to avoid breaking parsing
                    continue
            return res, p

        items = []
        ptr = 0
        if not data:
            return items

        try:
            # Standard format: starts with 0x00 + "shortcuts"
            if data[ptr] == 0x00:
                ptr += 1
                key, ptr = read_string(data, ptr)
                if key == "shortcuts":
                    root_map, ptr = parse_map(data, ptr)
                    for k, v in root_map.items():
                        if isinstance(v, dict):
                            items.append(v)
                    return items
        except Exception as e:
            logger(f"Error parsing VDF header: {e}")

        # Fallback: try parsing directly as a map
        try:
            root_map, ptr = parse_map(data, 0)
            for k, v in root_map.items():
                if isinstance(v, dict):
                    items.append(v)
            return items
        except Exception as e:
            logger(f"Error in VDF fallback parsing: {e}")
            return items

    def load_non_steam_games(self):
        """Scan Steam userdata for non-Steam shortcuts and return AppID -> Name mapping."""
        non_steam_games = {}
        steam_root = self.find_steam_root()

        if not steam_root:
            logger("Could not locate Steam root directory for non-Steam games scan")
            return non_steam_games

        userdata_path = steam_root / "userdata"
        if not userdata_path.exists():
            logger(f"No userdata folder found at {userdata_path}")
            return non_steam_games

        logger(f"Scanning for non-Steam games in: {userdata_path}")

        # Scan all user directories
        for user_dir in userdata_path.iterdir():
            if not user_dir.is_dir():
                continue

            shortcuts_path = user_dir / "config" / "shortcuts.vdf"
            if not shortcuts_path.exists():
                continue

            logger(f"Found shortcuts.vdf for user {user_dir.name}")
            try:
                with open(shortcuts_path, "rb") as f:
                    data = f.read()

                items = self.parse_binary_vdf(data)
                for item in items:
                    app_name = item.get("AppName", "").strip()
                    exe_path = item.get("Exe", "").strip()

                    if not app_name:
                        continue

                    # Method 1: Use explicit appid if available (modern Steam)
                    raw_id = item.get("appid")
                    if raw_id is not None:
                        app_id_32 = raw_id & 0xffffffff
                        # CONVERSIONE: Shift 32 bit a sinistra e OR con 0x02000000
                        clip_id = (app_id_32 << 32) | 0x02000000
                        non_steam_games[str(clip_id)] = app_name
                        logger(f"Non-Steam game found (explicit ID): {app_name} -> {clip_id} (Raw: {app_id_32})")
                        continue

                    # Method 2: Calculate legacy ID using CRC32 algorithm
                    if exe_path:
                        crc_input = (exe_path + app_name).encode("utf-8")
                        crc = zlib.crc32(crc_input) & 0xffffffff
                        app_id_32 = crc | 0x80000000
                        # CONVERSIONE: Shift 32 bit a sinistra e OR con 0x02000000
                        clip_id = (app_id_32 << 32) | 0x02000000
                        non_steam_games[str(clip_id)] = app_name
                        logger(f"Non-Steam game found (calculated ID): {app_name} -> {clip_id} (Raw: {app_id_32})")

            except Exception as e:
                logger(f"Error reading shortcuts.vdf from {shortcuts_path}: {e}")

        logger(f"Found {len(non_steam_games)} non-Steam games")
        return non_steam_games

    def merge_non_steam_games(self):
        """Merge non-Steam games into the main game_ids dictionary."""
        logger("Merging non-Steam games into GameIDs database...")

        # Load existing game IDs first if not already loaded
        if not self.game_ids:
            self.load_game_ids(load_non_steam=False)

        # Get non-Steam games
        non_steam_games = self.load_non_steam_games()

        # Merge with existing games (preserve manual edits)
        merged_count = 0
        for app_id, app_name in non_steam_games.items():
            # Only add if not already present OR if current value is just the ID (placeholder)
            if app_id not in self.game_ids or self.game_ids[app_id] == app_id:
                self.game_ids[app_id] = app_name
                merged_count += 1

        if merged_count > 0:
            self.save_game_ids()
            logger(f"Merged {merged_count} non-Steam games into GameIDs.json")
            return True
        else:
            logger("No new non-Steam games to merge")
            return False

    # ============ METODI ESISTENTI MODIFICATI ============

    def load_config(self):
        config = {
            'userdata_path': None,
            'export_path': os.path.normpath(os.path.join(os.path.expanduser("~"), "Desktop"))
        }
        if os.path.exists(self.CONFIG_FILE):
            logger("Loading configuration file...")
            with open(self.CONFIG_FILE, 'r') as f:
                lines = f.readlines()
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if key == 'userdata_path':
                            config['userdata_path'] = os.path.normpath(value) if value else None
                        elif key == 'export_path':
                            config['export_path'] = os.path.normpath(value)
                    else:
                        logger(f"Malformed config line skipped: {line}")
        else:
            logger("No config file found (Fresh Install or Deleted).")
        return config

    def save_config(self, userdata_path=None, export_path=None):
        logger(f"Saving configuration. Userdata: {userdata_path}, Export: {export_path}")
        config = {}
        if userdata_path:
            config['userdata_path'] = os.path.normpath(userdata_path)
        config['export_path'] = export_path or os.path.normpath(os.path.join(os.path.expanduser("~"), "Desktop"))
        with open(self.CONFIG_FILE, 'w') as f:
            for key, value in config.items():
                f.write(f"{key}={value}\n")

    def moveEvent(self, event):
        super().moveEvent(event)
        for combo_box in [self.steamid_combo, self.gameid_combo, self.media_type_combo]:
            if combo_box.view().isVisible():
                combo_box.hidePopup()

    def closeEvent(self, event):
        if self.conversion_thread and self.conversion_thread.isRunning():
            logger("Exit attempted while conversion running.")
            reply = QMessageBox.question(
                self,
                "Conversion in Progress",
                "A conversion is currently in progress. Are you sure you want to exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                logger("User confirmed exit during conversion. Stopping thread.")
                self.conversion_thread.cancel()
                self.conversion_thread.wait(3000)
                event.accept()
            else:
                logger("User cancelled exit.")
                event.ignore()
        else:
            logger("Application closing normally.")
            event.accept()

    def perform_update_check(self, show_message=True):
        release_info = self.get_latest_release_from_github()
        if not release_info:
            return None
        latest_version = release_info['version']
        if latest_version != self.CURRENT_VERSION and show_message:
            logger(f"Update available: {latest_version}")
            self.prompt_update(latest_version, release_info['changelog'])
        return release_info

    @staticmethod
    def get_latest_release_from_github():
        url = "https://api.github.com/repos/Nastas95/SteamClip/releases/latest"
        try:
            response = requests.get(url)
            response.raise_for_status()
            release_data = response.json()
            return {
                'version': release_data['tag_name'],
                'changelog': release_data.get('body', 'No changelog available'),
                'html_url': release_data['html_url']
            }
        except requests.exceptions.RequestException as exc:
            logger(f"Error fetching release info: {exc}")
            return None

    def prompt_update(self, latest_version, changelog):
        message_box = QMessageBox(QMessageBox.Icon.Question, "Update Available",
            f"A new update ({latest_version}) is available. View changelog?")
        changelog_button = message_box.addButton("View Changelog", QMessageBox.ButtonRole.ActionRole)
        cancel_button = message_box.addButton("Maybe Later", QMessageBox.ButtonRole.RejectRole)
        message_box.exec()
        if message_box.clickedButton() == changelog_button:
            self.show_changelog(latest_version, changelog)
        elif message_box.clickedButton() == cancel_button:
            message_box.close()

    def show_changelog(self, latest_version, changelog_text):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Changelog - {latest_version}")
        dialog.setGeometry(100, 100, 600, 400)
        layout = QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setMarkdown(changelog_text)
        button_layout = QHBoxLayout()
        download_button = QPushButton("Go to Download Page")
        download_button.clicked.connect(lambda: self.handle_download_click(dialog))
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(download_button)
        button_layout.addWidget(close_button)
        layout.addWidget(text_edit)
        layout.addLayout(button_layout)
        dialog.exec()

    def open_download_page(self):
        clean_env = os.environ.copy()
        clean_env.pop("LD_LIBRARY_PATH", None)
        clean_env.pop("QT_PLUGIN_PATH", None)
        clean_env.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
        clean_env.pop("QML2_IMPORT_PATH", None)
        clean_env.pop("QML_IMPORT_PATH", None)
        if "_MEIPASS" in clean_env:
            meipass = clean_env["_MEIPASS"]
            for key in list(clean_env.keys()):
                if meipass in clean_env[key]:
                    clean_env.pop(key, None)
        try:
            if sys.platform.startswith('linux'):
                subprocess.Popen(['xdg-open', self.GITHUB_RELEASES_URL], env=clean_env)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', self.GITHUB_RELEASES_URL], env=clean_env)
            elif sys.platform == 'win32':
                subprocess.Popen(['explorer', self.GITHUB_RELEASES_URL], env=clean_env)
            logger("Opened download page in browser")
        except Exception as e:
            logger(f"Failed to open download page: {e}")
            self.show_error(f"Could not open your default browser. Please visit the release page manually:\n{self.GITHUB_RELEASES_URL}")

    def handle_download_click(self, dialog):
        dialog.close()
        self.open_download_page()

    def check_and_load_userdata_folder(self):
        if not os.path.exists(self.CONFIG_FILE):
            return self.prompt_steam_version_selection()
        with open(self.CONFIG_FILE, 'r') as f:
            userdata_path = f.read().strip()
        return userdata_path if os.path.isdir(userdata_path) else self.prompt_steam_version_selection()

    def prompt_steam_version_selection(self):
        logger("Prompting for Steam Version Selection...")
        dialog = SteamVersionSelectionDialog(self)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            selected_option = dialog.get_selected_option()
            logger(f"User selected steam version option: {selected_option}")
            if selected_option == "Standard":
                if IS_WINDOWS:
                    userdata_path = os.path.normpath(r"C:\Program Files (x86)\Steam\userdata")
                else:
                    userdata_path = os.path.expanduser("~/.local/share/Steam/userdata")
                userdata_path = os.path.expanduser(userdata_path)
            elif selected_option == "Flatpak":
                userdata_path = os.path.expanduser("~/.var/app/com.valvesoftware.Steam/data/Steam/userdata")
            elif os.path.isdir(selected_option):
                userdata_path = selected_option
            else:
                logger("Invalid option selected in dialog.")
                continue
            if os.path.isdir(userdata_path):
                self.save_default_directory(userdata_path)
                logger(f"Valid userdata path found: {userdata_path}")
                return userdata_path
            else:
                logger(f"Path not found: {userdata_path}")
                QMessageBox.warning(self, "Invalid Directory", "The selected directory is not valid. Please select again.")
        return None

    def save_default_directory(self, directory):
        os.makedirs(self.CONFIG_DIR, exist_ok=True)
        if not IS_WINDOWS:
            tmp_dir = os.path.join(self.CONFIG_DIR, 'tmp')
            os.makedirs(tmp_dir, exist_ok=True)
        with open(self.CONFIG_FILE, 'w') as f:
            f.write(directory)

    def load_game_ids(self, load_non_steam=True):
        """Load game IDs from GameIDs.json and optionally merge non-Steam shortcuts."""
        if not os.path.exists(self.GAME_IDS_FILE):
            if load_non_steam:
                QMessageBox.information(self, "Info", "SteamClip will now download the GameID database and scan for non-Steam games. Please, be patient.")
            logger("GameID DB missing. Initializing empty dict.")
            self.game_ids = {}
        else:
            try:
                with open(self.GAME_IDS_FILE, 'r', encoding='utf-8') as f:
                    self.game_ids = json.load(f)
                logger(f"Loaded {len(self.game_ids)} entries from GameIDs.json")
            except Exception as e:
                logger(f"Error loading GameIDs.json: {e}")
                self.game_ids = {}

        # Always merge non-Steam games on load (fast operation)
        if load_non_steam:
            self.merge_non_steam_games()

    def fetch_game_name_from_steam(self, game_id):
        url = f"{self.STEAM_APP_DETAILS_URL}?appids={game_id}&filters=basic"
        try:
            response = requests.get(url)
            response.raise_for_status()
            logger(f"Fetched game name for ID {game_id}")
            data = response.json()
            if str(game_id) in data and data[str(game_id)]['success']:
                return data[str(game_id)]['data']['name']
        except Exception as exc:
            logger(f"Network error fetching game {game_id}: {str(exc)}")
        return f"{game_id}"

    def get_game_name(self, game_id):
        if game_id in self.game_ids:
            return self.game_ids[game_id]
        if not game_id.isdigit():
            default_name = f"{game_id}"
            self.game_ids[game_id] = default_name
            self.save_game_ids()
            return default_name
        name = self.fetch_game_name_from_steam(game_id)
        if name:
            self.game_ids[game_id] = name
            self.save_game_ids()
            return name
        default_name = f"{game_id}"
        self.game_ids[game_id] = default_name
        self.save_game_ids()
        return default_name

    @staticmethod
    def create_button(text, slot, enabled=True, icon=None, size=(240, 40)):
        button = QPushButton(text)
        button.clicked.connect(slot)
        button.setEnabled(enabled)
        if icon:
            button.setIcon(QIcon.fromTheme(icon))
        if size:
            button.setFixedSize(*size)
        return button

    @staticmethod
    def is_connected():
        try:
            if IS_WINDOWS:
                response = requests.get("https://www.google.com", timeout=5)
                return response.status_code == 200
            else:
                output = subprocess.run(["ping", "-c", "1", "1.1.1.1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return output.returncode == 0
        except requests.ConnectionError:
            return False
        except Exception as exc:
            print(f"Connection check failed: {exc}")
            return False

    def get_custom_record_path(self, userdata_dir):
        if userdata_dir in self._custom_record_cache:
            return self._custom_record_cache[userdata_dir]
        localconfig_path = os.path.join(userdata_dir, 'config', 'localconfig.vdf')
        if not os.path.exists(localconfig_path):
            logger(f"No custom record path found - localconfig.vdf missing in {userdata_dir}")
            self._custom_record_cache[userdata_dir] = None
            return None
        try:
            with open(localconfig_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                for i, line in enumerate(lines):
                    line = line.strip()
                    if '"BackgroundRecordPath"' in line:
                        parts = line.split('"BackgroundRecordPath"')
                        if len(parts) > 1:
                            path_line = parts[1].strip()
                            path_line = path_line.strip('" ')
                            if path_line:
                                logger(f"Custom record path detected: {path_line}")
                                self._custom_record_cache[userdata_dir] = path_line
                                return path_line
            logger(f"No custom record path found in localconfig for {userdata_dir}")
            self._custom_record_cache[userdata_dir] = None
            return None
        except Exception as exc:
            logger(f"Error reading custom record path: {str(exc)}")
            self._custom_record_cache[userdata_dir] = None
            return None

    def del_invalid_clips(self):
        logger("Checking for invalid clips...")
        invalid_folders = []
        for steamid_entry in os.scandir(self.default_dir):
            if steamid_entry.is_dir() and steamid_entry.name.isdigit():
                userdata_dir = steamid_entry.path
                clips_dirs = []
                default_clips = os.path.join(userdata_dir, 'gamerecordings', 'clips')
                default_video = os.path.join(userdata_dir, 'gamerecordings', 'video')
                if os.path.isdir(default_clips):
                    clips_dirs.append(default_clips)
                if os.path.isdir(default_video):
                    clips_dirs.append(default_video)
                custom_path = self.get_custom_record_path(userdata_dir)
                if custom_path:
                    custom_clips = os.path.join(custom_path, 'clips')
                    custom_video = os.path.join(custom_path, 'video')
                    if os.path.isdir(custom_clips):
                        clips_dirs.append(custom_clips)
                    if os.path.isdir(custom_video):
                        clips_dirs.append(custom_video)
                for clip_dir in clips_dirs:
                    for folder_entry in os.scandir(clip_dir):
                        if folder_entry.is_dir() and "_" in folder_entry.name:
                            folder_path = folder_entry.path
                            if not self.find_session_mpd(folder_path):
                                invalid_folders.append(folder_path)
        if invalid_folders:
            logger(f"Found {len(invalid_folders)} invalid clip folders.")
            reply = QMessageBox.question(
                self,
                "Invalid Clips Found",
                f"Found {len(invalid_folders)} invalid clip(s). Delete them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                success = 0
                for folder in invalid_folders:
                    try:
                        shutil.rmtree(folder)
                        logger(f"Deleted invalid clip folder: {folder}")
                        success += 1
                    except Exception as exc:
                        self.show_error(f"Failed to delete {folder}: {str(exc)}")
                        logger(f"Failed to delete {folder}: {str(exc)}")
                self.show_info(f"Deleted {success} invalid clip(s).")
                self.populate_steamid_dirs()
        else:
            logger("No invalid clips found.")

    def filter_media_type(self):
        selected_media_type = self.media_type_combo.currentText()
        if selected_media_type != self.prev_media_type:
            logger(f"Filtering media type: {selected_media_type}")
            self.prev_media_type = selected_media_type
            selected_steamid = self.steamid_combo.currentText()
            if not selected_steamid:
                return
            userdata_dir = os.path.join(self.default_dir, selected_steamid)
            custom_record_path = self.get_custom_record_path(userdata_dir)
            clips_dir_default = os.path.join(userdata_dir, 'gamerecordings', 'clips')
            video_dir_default = os.path.join(userdata_dir, 'gamerecordings', 'video')
            clips_dir_custom = os.path.join(custom_record_path, 'clips') if custom_record_path else None
            video_dir_custom = os.path.join(custom_record_path, 'video') if custom_record_path else None
            clip_folders = []
            video_folders = []
            if os.path.isdir(clips_dir_default):
                clip_folders.extend(folder.path for folder in os.scandir(clips_dir_default) if folder.is_dir() and "_" in folder.name)
            if os.path.isdir(video_dir_default):
                video_folders.extend(folder.path for folder in os.scandir(video_dir_default) if folder.is_dir() and "_" in folder.name)
            if clips_dir_custom and os.path.isdir(clips_dir_custom):
                clip_folders.extend(folder.path for folder in os.scandir(clips_dir_custom) if folder.is_dir() and "_" in folder.name)
            if video_dir_custom and os.path.isdir(video_dir_custom):
                video_folders.extend(folder.path for folder in os.scandir(video_dir_custom) if folder.is_dir() and "_" in folder.name)
            if selected_media_type == "All Clips":
                self.clip_folders = clip_folders + video_folders
            elif selected_media_type == "Manual Clips":
                self.clip_folders = clip_folders
            elif selected_media_type == "Background Recordings":
                self.clip_folders = video_folders
            self.clip_folders = sorted(self.clip_folders, key=lambda x: self.extract_datetime_from_folder_name(x), reverse=True)
            self.original_clip_folders = list(self.clip_folders)
            logger(f"Media filter applied. Found {len(self.clip_folders)} clips total.")
            self.populate_gameid_combo()
            self.display_clips()

    def on_steamid_selected(self):
        selected_steamid = self.steamid_combo.currentText()
        if selected_steamid != self.prev_steamid:
            logger(f"Selected SteamID user: {selected_steamid}")
            self.prev_steamid = selected_steamid
            self.filter_media_type()

    def clear_clip_grid(self):
        for i in range(self.clip_grid.count()):
            widget = self.clip_grid.itemAt(i).widget()
            if widget:
                widget.deleteLater()

    def clear_selection(self):
        logger("User cleared all selected clips.")
        self.selected_clips.clear()
        for i in range(self.clip_grid.count()):
            widget = self.clip_grid.itemAt(i).widget()
            if widget and hasattr(widget, 'folder'):
                widget.setStyleSheet("border: none;")
        self.convert_button.setEnabled(False)
        self.clear_selection_button.setEnabled(False)

    def populate_steamid_dirs(self):
        if not os.path.isdir(self.default_dir):
            self.show_error("Default Steam userdata directory not found.")
            return
        self.steamid_combo.clear()
        steamid_found = False
        count = 0
        for entry in os.scandir(self.default_dir):
            if entry.is_dir() and entry.name.isdigit():
                local_vdf = os.path.join(self.default_dir, entry, 'config', 'localconfig.vdf')
                if os.path.isfile(local_vdf):
                    self.steamid_combo.addItem(entry.name)
                    steamid_found = True
                    count += 1
        logger(f"Populated SteamID list with {count} accounts.")
        if not steamid_found:
            logger("No Steam accounts found in userdata.")
            QMessageBox.warning(
                self,
                "No Clips Found",
                "Clips folder is empty. Record at least one clip to use SteamClip."
            )
            sys.exit()
        self.update_media_type_combo()

    def update_media_type_combo(self):
        self.media_type_combo.blockSignals(True)
        try:
            selected_steamid = self.steamid_combo.currentText()
            if not selected_steamid:
                return
            userdata_dir = os.path.join(self.default_dir, selected_steamid)
            clips_dir = os.path.join(userdata_dir, 'gamerecordings', 'clips')
            video_dir = os.path.join(userdata_dir, 'gamerecordings', 'video')
            self.media_type_combo.clear()
            if os.path.isdir(clips_dir) and os.path.isdir(video_dir):
                self.media_type_combo.addItems(["All Clips", "Manual Clips", "Background Recordings"])
            elif os.path.isdir(clips_dir):
                self.media_type_combo.addItems(["Manual Clips"])
            elif os.path.isdir(video_dir):
                self.media_type_combo.addItems(["Background Recordings"])
            self.media_type_combo.setCurrentIndex(0)
        finally:
            self.media_type_combo.blockSignals(False)
            self.filter_media_type()

    @staticmethod
    def extract_datetime_from_folder_name(folder_name):
        parts = folder_name.split('_')
        if len(parts) >= 3:
            try:
                datetime_str = parts[-2] + parts[-1]
                return datetime.strptime(datetime_str, "%Y%m%d%H%M%S")
            except ValueError:
                pass
        return datetime.min

    def populate_gameid_combo(self):
        folders_source = self.original_clip_folders if self.original_clip_folders else self.clip_folders
        game_ids_in_clips = {folder.split('_')[1] for folder in folders_source}
        sorted_game_ids = sorted(game_ids_in_clips)
        current_id = self.gameid_combo.currentData()
        self.gameid_combo.blockSignals(True)
        self.gameid_combo.clear()
        self.gameid_combo.addItem("All Games")
        for game_id in sorted_game_ids:
            self.gameid_combo.addItem(self.get_game_name(game_id), game_id)
        if current_id:
            index = self.gameid_combo.findData(current_id)
            if index >= 0:
                self.gameid_combo.setCurrentIndex(index)
        logger(f"Populated GameID combo. Found {len(sorted_game_ids)} unique games.")
        self.gameid_combo.blockSignals(False)

    def save_game_ids(self):
        with open(self.GAME_IDS_FILE, 'w', encoding='utf-8') as f_obj:
            json.dump(self.game_ids, f_obj, indent=4, ensure_ascii=False)

    def filter_clips_by_gameid(self):
        selected_index = self.gameid_combo.currentIndex()
        if selected_index == 0:
            self.clip_folders = [
                folder for folder in self.original_clip_folders
                if self.find_session_mpd(folder)
            ]
        else:
            selected_game_id = self.gameid_combo.itemData(selected_index)
            if not selected_game_id:
                return
            game_name = self.get_game_name(selected_game_id)
            logger(f"Filtering clips by Game: {game_name} (ID: {selected_game_id})")
            self.clip_folders = [
                folder for folder in self.original_clip_folders
                if f'_{selected_game_id}_' in folder and self.find_session_mpd(folder)
            ]
        self.clip_index = 0
        self.display_clips()

    def display_clips(self):
        self.clear_clip_grid()
        valid_clip_folders = [
            folder for folder in self.clip_folders[self.clip_index:]
            if self.find_session_mpd(folder)
        ]
        clips_to_show = valid_clip_folders[:6]
        logger(f"Displaying clips {self.clip_index+1}-{self.clip_index+len(clips_to_show)} of {len(self.clip_folders)}")
        for index, folder in enumerate(clips_to_show):
            session_mpd_files = self.find_session_mpd(folder)
            if not session_mpd_files:
                continue
            first_session_mpd = session_mpd_files[0]
            thumbnail_path = os.path.join(folder, 'thumbnail.jpg')
            if first_session_mpd and not os.path.exists(thumbnail_path):
                self.extract_first_frame(first_session_mpd, thumbnail_path)
            if os.path.exists(thumbnail_path):
                self.add_thumbnail_to_grid(thumbnail_path, folder, index)
        placeholders_needed = 6 - len(clips_to_show)
        for i in range(placeholders_needed):
            placeholder = QFrame()
            placeholder.setFixedSize(300, 180)
            placeholder.setStyleSheet("border: none; background-color: transparent;")
            self.clip_grid.addWidget(placeholder, (len(clips_to_show) + i) // 3, (len(clips_to_show) + i) % 3)
        for i in range(self.clip_grid.count()):
            widget: Optional[ThumbnailFrame] = self.clip_grid.itemAt(i).widget()
            if widget and hasattr(widget, 'folder') and widget.folder in self.selected_clips:
                widget.setStyleSheet("border: 3px solid #66c0f4; border-radius: 4px;")
        self.update_navigation_buttons()
        self.export_all_button.setEnabled(bool(self.clip_folders))

    def extract_first_frame(self, session_mpd_path, output_thumbnail_path):
        temp_video_path = None
        try:
            ffmpeg_path = iio.get_ffmpeg_exe()
            data_dir = os.path.dirname(session_mpd_path)
            init_video = os.path.join(data_dir, 'init-stream0.m4s')
            chunk_video_pattern = os.path.join(data_dir, 'chunk-stream0-*.m4s')
            chunk_video_list = sorted(glob.glob(chunk_video_pattern))
            if not os.path.exists(init_video) or not chunk_video_list:
                logger(f"Missing video files for thumbnail generation in: {data_dir}")
                self.create_placeholder_thumbnail(output_thumbnail_path)
                return
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_video:
                temp_video_path = tmp_video.name
                with open(init_video, 'rb') as f_init:
                    shutil.copyfileobj(f_init, tmp_video)
                first_chunk = chunk_video_list[0]
                if os.path.exists(first_chunk) and os.access(first_chunk, os.R_OK):
                    with open(first_chunk, 'rb') as f_chunk:
                        shutil.copyfileobj(f_chunk, tmp_video)
                else:
                    logger(f"First Chunk missing for thumbnail: {first_chunk}")
                    raise FileNotFoundError(f"First Chunk missing: {first_chunk}")
            command = [
                ffmpeg_path, '-y',
                '-ss', '00:00:00.000',
                '-i', temp_video_path,
                '-vframes', '1',
                '-q:v', '2',
                output_thumbnail_path
            ]
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode == 0 and os.path.exists(output_thumbnail_path):
                if DEBUG: logger(f"Thumbnail extracted: {output_thumbnail_path}")
                pass
            else:
                logger(f"FFMPEG Failed to extract thumbnail: {session_mpd_path}: {result.stderr}")
                self.create_placeholder_thumbnail(output_thumbnail_path)
        except Exception as exc:
            logger(f"Error extracting thumbnail {session_mpd_path}: {exc}", exc_info=True)
            self.create_placeholder_thumbnail(output_thumbnail_path)
        finally:
            if temp_video_path and os.path.exists(temp_video_path):
                try:
                    os.unlink(temp_video_path)
                except OSError as exc:
                    logger(f"Error removing thumbnail temp files: {temp_video_path}: {exc}")

    @staticmethod
    def create_placeholder_thumbnail(output_path, width=320, height=180, text="Missing Thumbnail"):
        try:
            image = Image.new('RGB', (width, height), color='black')
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (width - text_width) / 2
            y = (height - text_height) / 2
            draw.text((x, y), text, fill='white', font=font)
            image.save(output_path, 'JPEG')
            logger(f"Thumbnail placeholder created: {output_path}")
        except Exception as exc:
            logger(f"Error creating placeholder thumbnail {output_path}: {exc}")

    def get_clip_duration(self, clip_folder):
        total_seconds = 0.0
        session_mpd_files = self.find_session_mpd(clip_folder)
        for session_mpd_path in session_mpd_files:
            try:
                tree = ElTree.parse(session_mpd_path)
                root = tree.getroot()
                _ns = {'dash': 'urn:mpeg:dash:schema:mpd:2011'}
                mpd_element = root
                if 'mediaPresentationDuration' in mpd_element.attrib:
                    duration_str = mpd_element.attrib['mediaPresentationDuration']
                    duration_str = duration_str[2:]
                    if 'H' in duration_str:
                        hours, rest = duration_str.split('H')
                        minutes, seconds = rest.split('M') if 'M' in rest else (rest[:-1], '0S')
                        seconds = seconds.split('S')[0]
                        total_seconds += int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                    elif 'M' in duration_str:
                        minutes, seconds = duration_str.split('M')
                        seconds = seconds.split('S')[0]
                        total_seconds += int(minutes) * 60 + float(seconds)
                    else:
                        total_seconds += float(duration_str.split('S')[0])
                else:
                    logger(f"Attribute 'mediaPresentationDuration' not found in {session_mpd_path}")
            except Exception as exc:
                logger(f"Error parsing mpd for duration {session_mpd_path}: {exc}")
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        return f"{minutes}:{seconds:02d}"

    def add_thumbnail_to_grid(self, thumbnail_path, folder, index):
        container = ThumbnailFrame()
        container.setFixedSize(340, 200)
        container_layout = QVBoxLayout()
        container.setLayout(container_layout)
        pixmap = QPixmap(thumbnail_path).scaled(340, 200, Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        thumbnail_label = QLabel()
        thumbnail_label.setPixmap(pixmap)
        thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumbnail_label.setStyleSheet("border: none; border-radius: 4px;")
        thumbnail_label.setScaledContents(True)
        def select_clip_event(_event):
            self.select_clip(folder, container)
        thumbnail_label.mousePressEvent = select_clip_event
        container_layout.addWidget(thumbnail_label)
        container_layout.setContentsMargins(0,0,0,0)
        duration = self.get_clip_duration(folder)
        duration_label = QLabel(f"{duration}", container)
        duration_label.setStyleSheet("""
            font-size: 13px;
            font-weight: bold;
            color: #e1e1e1;
            background-color: rgba(0, 0, 0, 0.7);
            border-radius: 4px;
            padding: 2px 5px;
        """)
        duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        duration_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        duration_label.adjustSize()
        duration_width = duration_label.width()
        duration_height = duration_label.height()
        x = 340 - duration_width - 10
        y = 200 - duration_height - 10
        duration_label.move(x, y)
        container.folder = folder
        self.clip_grid.addWidget(container, index // 3, index % 3)

    def select_clip(self, folder, container):
        if folder in self.selected_clips:
            self.selected_clips.remove(folder)
            container.setStyleSheet("border: none;")
        else:
            self.selected_clips.add(folder)
            container.setStyleSheet("border: 3px solid #66c0f4; border-radius: 4px;")
        self.convert_button.setEnabled(bool(self.selected_clips))
        self.clear_selection_button.setEnabled(len(self.selected_clips) >= 1)

    def update_navigation_buttons(self):
        self.prev_button.setEnabled(self.clip_index > 0)
        self.next_button.setEnabled(self.clip_index + 6 < len(self.clip_folders))

    def show_previous_clips(self):
        if self.clip_index - 6 >= 0:
            logger("User navigated to previous page.")
            self.clip_index -= 6
            self.display_clips()

    def show_next_clips(self):
        if self.clip_index + 6 < len(self.clip_folders):
            logger("User navigated to next page.")
            self.clip_index += 6
            self.display_clips()

    def on_progress_update(self, message, value):
        self.progress_bar.setFormat(message)
        self.progress_bar.setValue(value)

    def on_conversion_finished(self, success, message, export_all):
        self.progress_bar.setVisible(False)
        self.toggle_interface(enabled=True)
        self.show_info(message)
        if not export_all:
            self.selected_clips.clear()
            self.display_clips()

    def on_thread_finished(self):
        logger("Conversion thread terminated.")
        self.conversion_thread = None

    def toggle_interface(self, enabled):
        self.convert_button.setEnabled(enabled and bool(self.selected_clips))
        self.export_all_button.setEnabled(enabled and bool(self.clip_folders))
        self.clear_selection_button.setEnabled(enabled and bool(self.selected_clips))
        self.prev_button.setEnabled(enabled and self.clip_index > 0)
        self.next_button.setEnabled(enabled and (self.clip_index + 6 < len(self.clip_folders)))
        self.steamid_combo.setEnabled(enabled)
        self.gameid_combo.setEnabled(enabled)
        self.media_type_combo.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)

    def process_clips(self, selected_clips=None, export_all=False):
        logger(f"Initiating process_clips. ExportAll: {export_all}")
        if not self.validate_export_directory():
            return False
        clip_list = self.get_clips_to_process(selected_clips, export_all)
        if not clip_list:
            logger("Process cancelled: No clips to process.")
            self.show_error("No clips to process")
            return False
        # Setup Progress Bar
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFormat("Initializing conversion...")
        # Disable UI
        self.toggle_interface(enabled=False)
        # Start Thread
        self.conversion_thread = ConversionThread(
            clip_list,
            self.export_dir,
            self.game_ids,
            export_all
        )
        self.conversion_thread.progress_update.connect(self.on_progress_update)
        self.conversion_thread.finished_signal.connect(self.on_conversion_finished)
        self.conversion_thread.finished.connect(self.on_thread_finished)
        self.conversion_thread.start()
        return True

    def validate_export_directory(self):
        if self.export_dir is None or not os.path.isdir(self.export_dir):
            logger(f"Export directory invalid or missing: '{self.export_dir}'")
            reply = QMessageBox.critical(
                self, "!WARNING!",
                f"Directory '{self.export_dir}' not found.\nUse Desktop as export directory?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.export_dir = os.path.normpath(os.path.join(os.path.expanduser("~"), "Desktop"))
                self.save_config(self.default_dir, self.export_dir)
                QMessageBox.information(self, "Info", f"Export path set to: {self.export_dir}")
                logger(f"Export Path defaulted to Desktop: {self.export_dir}")
                return True
            else:
                QMessageBox.warning(self, "Operation Cancelled", "Export operation has been cancelled.")
                logger("Export Path validation failed. User cancelled.")
                return False
        return True

    def get_clips_to_process(self, selected_clips, export_all):
        if export_all:
            selected_game_index = self.gameid_combo.currentIndex()
            selected_media_type = self.media_type_combo.currentText()
            filtered_clips = self.original_clip_folders.copy()
            if selected_media_type == "Manual Clips":
                filtered_clips = [c for c in filtered_clips if "clips" in c]
            elif selected_media_type == "Background Recordings":
                filtered_clips = [c for c in filtered_clips if "video" in c]
            if selected_game_index > 0:
                game_id = self.gameid_combo.itemData(selected_game_index)
                filtered_clips = [c for c in filtered_clips if f"_{game_id}_" in c]
            return filtered_clips
        return list(selected_clips) if selected_clips else []

    def convert_clip(self):
        logger(f"User clicked Convert. {len(self.selected_clips)} clips selected.")
        self.process_clips(selected_clips=self.selected_clips)

    def export_all(self):
        logger("User clicked Export All.")
        self.process_clips(export_all=True)

    @staticmethod
    def find_session_mpd(clip_folder):
        session_mpd_files = []
        for root, _, files in os.walk(clip_folder):
            if 'session.mpd' in files:
                session_mpd_files.append(os.path.join(root, 'session.mpd'))
        return session_mpd_files

    def show_error(self, message):
        logger(f"Showing Error Dialog: {message}")
        QMessageBox.critical(self, "Error", message)

    def show_info(self, message):
        logger(f"Showing Info Dialog: {message}")
        QMessageBox.information(self, "Info", message)

    def open_settings(self):
        logger("Opening Settings Window.")
        if not self.settings_window:
            self.settings_window = SettingsWindow(self)
            self.settings_window.exec()

    @staticmethod
    def debug_crash():
        logger("Debug button pressed - Simulating crash")
        raise Exception("Test crash simulated by user")

class SteamVersionSelectionDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Select Steam Version")
        self.setFixedSize(350, 150)
        layout = QVBoxLayout()
        self.standard_button = QPushButton("Standard")
        self.manual_button = QPushButton("Select the userdata folder manually")
        self.standard_button.clicked.connect(lambda: self.accept_and_set("Standard"))
        self.manual_button.clicked.connect(self.select_userdata_folder)
        layout.addWidget(QLabel("What version of Steam are you using?"))
        layout.addWidget(self.standard_button)
        if not IS_WINDOWS:
            self.flatpak_button = QPushButton("Flatpak")
            self.flatpak_button.clicked.connect(lambda: self.accept_and_set("Flatpak"))
            layout.addWidget(self.flatpak_button)
        layout.addWidget(self.manual_button)
        self.setLayout(layout)
        self.selected_version = None

    def accept_and_set(self, version):
        self.selected_version = version
        self.accept()

    def select_userdata_folder(self):
        userdata_path = QFileDialog.getExistingDirectory(self, "Select userdata folder")
        if userdata_path:
            if self.is_valid_userdata_folder(userdata_path):
                self.selected_version = userdata_path
                self.accept()
            else:
                QMessageBox.warning(self, "Invalid Directory", "The selected directory is not a valid userdata folder.")

    @staticmethod
    def is_valid_userdata_folder(folder):
        if not os.path.basename(folder) == "userdata":
            return False
        steam_id_dirs = [d for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d)) and d.isdigit()]
        if not steam_id_dirs:
            return False
        for steam_id in steam_id_dirs:
            local_vdf = os.path.join(folder, steam_id, 'config', 'localconfig.vdf')
            if os.path.isfile(local_vdf):
                return True
        return False

    def get_selected_option(self):
        return self.selected_version

class SettingsWindow(QDialog):
    def __init__(self, parent: SteamClipApp):
        super().__init__(parent)
        self.setWindowIcon(QIcon.fromTheme(QIcon.ThemeIcon.DocumentProperties))
        self.setWindowTitle("Settings")
        self.resize(360, 560)  # Aumentato per il nuovo pulsante

        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)

        # --- General Settings Group ---
        general_group = QGroupBox("General Settings")
        general_layout = QVBoxLayout()
        self.open_config_button = self.create_button("Open Config Folder", self.open_config_folder, "folder-open", size=None)
        self.select_export_button = self.create_button("Set Export Path", self.select_export_path, "folder-open", size=None)
        general_layout.addWidget(self.open_config_button)
        general_layout.addWidget(self.select_export_button)
        general_group.setLayout(general_layout)

        # --- Game Data Group ---
        game_data_group = QGroupBox("Game Settings")
        game_data_layout = QVBoxLayout()
        self.edit_game_ids_button = self.create_button("Edit Game Name", self.open_edit_game_ids, "edit-rename", size=None)
        self.update_game_ids_button = self.create_button("Update GameIDs", self.update_game_ids, "view-refresh", size=None)
        # Scan Non-Steam Games button removed
        game_data_layout.addWidget(self.edit_game_ids_button)
        game_data_layout.addWidget(self.update_game_ids_button)
        game_data_group.setLayout(game_data_layout)

        # --- Application Group ---
        app_group = QGroupBox("Application Settings")
        app_layout = QVBoxLayout()
        self.check_for_updates_button = self.create_button("Check for Updates", self.check_for_updates, "system-software-update", size=None)
        if DEBUG:
            self.check_for_updates_button.setDisabled(True)
        # Danger Zone / Maintenance
        self.delete_config_button = self.create_button("Delete Config Folder", self.delete_config_folder, "edit-delete", size=None)
        self.delete_config_button.setProperty("class", "danger")
        app_layout.addWidget(self.check_for_updates_button)
        app_layout.addWidget(self.delete_config_button)
        app_group.setLayout(app_layout)

        # --- Footer ---
        footer_layout = QHBoxLayout()
        self.version_label = QLabel(f"Version: {parent.CURRENT_VERSION}")
        self.close_settings_button = self.create_button("Close", self.close, "window-close", size=(100, 35))
        footer_layout.addWidget(self.version_label)
        footer_layout.addStretch()
        footer_layout.addWidget(self.close_settings_button)

        main_layout.addWidget(general_group)
        main_layout.addWidget(game_data_group)
        main_layout.addWidget(app_group)
        main_layout.addStretch()
        main_layout.addLayout(footer_layout)
        self.setLayout(main_layout)

    def close(self):
        logger("Settings window closed.")
        super().close()

    def parent(self) -> Optional[SteamClipApp]:
        return super().parent()

    def select_export_path(self):
        logger("User clicked Set Export Path.")
        export_path = QFileDialog.getExistingDirectory(self, "Set Export Folder")
        if export_path and os.path.isdir(export_path):
            try:
                test_file = os.path.join(export_path, ".test_write_permission")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
                self.parent().export_dir = export_path
                self.parent().save_config(self.parent().default_dir, self.parent().export_dir)
                QMessageBox.information(self, "Info", f"Export path set to: {export_path}")
                logger(f"Export path successfully changed to: {export_path}")
                return
            except Exception as exc:
                logger(f"Failed to set export path {export_path}: {exc}")
                QMessageBox.warning(self, "Invalid Directory", f"The selected directory is not writable: {str(exc)}")
        else:
            logger("Export path selection cancelled or invalid.")
            default_export_path = os.path.normpath(os.path.join(os.path.expanduser("~"), "Desktop"))
            self.parent().export_dir = default_export_path
            self.parent().save_config(self.parent().default_dir, default_export_path)
            QMessageBox.warning(self, "Invalid Directory",
                f"Selected export directory is invalid. Using default: {default_export_path}")

    @staticmethod
    def create_button(text, slot, icon=None, size=(200, 45)):
        button = QPushButton(text)
        button.clicked.connect(slot)
        if icon:
            button.setIcon(QIcon.fromTheme(icon))
        if size:
            button.setFixedSize(*size)
        return button

    def check_for_updates(self):
        logger(f"User explicitly clicked Check for Update.")
        release_info = self.parent().perform_update_check(show_message=False)
        if release_info is None:
            QMessageBox.critical(self, "Error", "Failed to fetch the latest release information.")
            logger(f"Update Check Failed: Could not fetch info.")
            return
        if release_info['version'] == self.parent().CURRENT_VERSION:
            QMessageBox.information(self, "No Updates Available", "You are already using the latest version of SteamClip.")
            logger(f"Update Check: Already on latest version ({self.parent().CURRENT_VERSION}).")
        else:
            self.parent().show_changelog(release_info['version'], release_info['changelog'])
            logger(f"Update Check: New version available ({release_info['version']}). showing changelog.")

    def open_edit_game_ids(self):
        logger("Opening Edit Game IDs window.")
        edit_window = EditGameIDWindow(self.parent())
        edit_window.exec()

    @staticmethod
    def open_config_folder():
        config_folder = SteamClipApp.CONFIG_DIR
        logger(f"User requested to open config folder: {config_folder}")
        os.makedirs(config_folder, exist_ok=True)
        clean_env = os.environ.copy()
        clean_env.pop("LD_LIBRARY_PATH", None)
        clean_env.pop("QT_PLUGIN_PATH", None)
        clean_env.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
        clean_env.pop("QML2_IMPORT_PATH", None)
        clean_env.pop("QML_IMPORT_PATH", None)
        if "_MEIPASS" in clean_env:
            meipass = clean_env["_MEIPASS"]
            for key in list(clean_env.keys()):
                if meipass in clean_env[key]:
                    clean_env.pop(key, None)
        try:
            if sys.platform.startswith('linux'):
                subprocess.Popen(['xdg-open', config_folder], env=clean_env)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', config_folder], env=clean_env)
            elif sys.platform == 'win32':
                subprocess.Popen(['explorer', os.path.normpath(config_folder)], env=clean_env)
        except Exception as e:
            logger(f"Failed to open config folder: {e}")
            QMessageBox.critical(None, "Error", f"Could not open config folder:\n{e}")

    def update_game_ids(self):
        logger("User clicked Update GameIDs (including non-Steam games).")
        try:
            # First merge non-Steam games (works offline)
            non_steam_updated = self.parent().merge_non_steam_games()

            # Then update Steam games (requires internet)
            steam_updated = False
            if self.parent().is_connected():
                game_ids = {folder.split('_')[1] for folder in self.parent().original_clip_folders}
                logger(f"Checking GameIDs for {len(game_ids)} games...")
                for game_id in game_ids:
                    if game_id not in self.parent().game_ids or self.parent().game_ids[game_id] == game_id:
                        try:
                            name = self.parent().fetch_game_name_from_steam(game_id)
                            if name:
                                self.parent().game_ids[game_id] = name
                                steam_updated = True
                        except Exception as exc:
                            logger(f"Failed to fetch name for {game_id}: {exc}")
            else:
                logger("Update GameIDs: No internet connection. Skipping Steam game updates.")

            if non_steam_updated or steam_updated:
                self.parent().save_game_ids()
                self.parent().populate_gameid_combo()
                logger("Game ID database updated successfully (Steam + non-Steam).")
                QMessageBox.information(self, "Success",
                    "Game ID database updated successfully!\n"
                    f"{'✓ Non-Steam games merged' if non_steam_updated else '• Non-Steam games already up to date'}\n"
                    f"{'✓ Steam games updated' if steam_updated else '• Steam games already up to date'}")
            else:
                logger("Game ID database is already up to date.")
                QMessageBox.information(self, "Info", "No updates needed - database is already up to date.")

        except Exception as exc:
            logger(f"Update GameIDs failed with exception: {exc}")
            QMessageBox.critical(self, "Error", f"Update failed: {str(exc)}")

    def delete_config_folder(self):
        logger("DANGER: User requested Config folder deletion.")
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete the entire configuration folder?\n{SteamClipApp.CONFIG_DIR}\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                shutil.rmtree(SteamClipApp.CONFIG_DIR)
                logger("Configuration folder deleted. Exiting application.")
                QMessageBox.information(self, "Deletion Complete", "Configuration folder has been deleted.\nThe application will now close.")
                QApplication.quit()
            except Exception as exc:
                logger(f"Failed to delete configuration folder: {exc}")
                QMessageBox.critical(self, "Error", f"Failed to delete configuration folder:\n{str(exc)}")

class EditGameIDWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Edit Game Names")
        self.setFixedSize(400, 300)
        self.layout = QVBoxLayout()
        self.table_widget = QTableWidget()
        self.game_names = {}
        self.populate_table()
        self.layout.addWidget(self.table_widget)
        button_layout = QHBoxLayout()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("Apply Changes")
        apply_button.clicked.connect(self.save_changes)
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(apply_button)
        self.layout.addLayout(button_layout)
        self.setLayout(self.layout)

    def populate_table(self):
        self.game_names = {
            self.parent().gameid_combo.itemData(i): self.parent().gameid_combo.itemText(i)
            for i in range(1, self.parent().gameid_combo.count())
        }
        self.table_widget.setRowCount(len(self.game_names))
        self.table_widget.setColumnCount(1)
        self.table_widget.setHorizontalHeaderLabels(["Game Name"])
        for row, (game_id, game_name) in enumerate(self.game_names.items()):
            name_item = QTableWidgetItem(game_name)
            name_item.setData(Qt.ItemDataRole.UserRole, game_id)
            self.table_widget.setItem(row, 0, name_item)
        self.table_widget.horizontalHeader().setStretchLastSection(True)

    def parent(self) -> Optional[SteamClipApp]:
        return super().parent()

    def save_changes(self):
        logger("Saving changes to Game IDs manual edit.")
        updated_game_names = {}
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 0)
            if item:
                game_id = item.data(Qt.ItemDataRole.UserRole)
                new_name = item.text()
                updated_game_names[game_id] = new_name
        game_ids_file = os.path.join(SteamClipApp.CONFIG_DIR, 'GameIDs.json')
        with open(game_ids_file, 'w', encoding='utf-8') as f:
            json.dump(updated_game_names, f, indent=4, ensure_ascii=False)
        QMessageBox.information(self, "Info", "Game names saved successfully.")
        logger("Game ID names edited and saved.")
        self.parent().load_game_ids()
        self.parent().populate_gameid_combo()
        self.accept()

if __name__ == "__main__":
    sys.excepthook = handle_exception
    logger(f"Process Started. Platform: {sys.platform}, Python: {sys.version}")
    logger(f"Working Directory: {os.getcwd()}")
    logger(f"Config Path: {CONFIG_PATH}")

    if not IS_WINDOWS:
        tempfile.tempdir = os.path.expanduser(os.path.join(SteamClipApp.CONFIG_DIR, 'tmp'))
        os.makedirs(tempfile.gettempdir(), exist_ok=True)
        os.environ["REQUESTS_CA_BUNDLE"] = "/etc/ssl/certs/ca-certificates.crt"

    app = QApplication(sys.argv)
    app.setStyleSheet("""
    /* Global Reset & Colors */
    QWidget {
        background-color: #1b2838; /* Steam Main Dark Blue */
        color: #c7d5e0; /* Steam Light Gray Text */
        font-family: "Segoe UI", "Roboto", "Helvetica Neue", sans-serif;
        font-size: 14px;
    }
    QFrame {
        border: none;
    }
    /* Labels */
    QLabel {
        color: #c7d5e0;
    }
    /* Group Boxes */
    QGroupBox {
        border: 1px solid #3A4451;
        border-radius: 2px;
        margin-top: 20px;
        font-weight: bold;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
        color: #66c0f4; /* Steam Blue */
    }
    /* Buttons */
    QPushButton {
        background-color: #2a475e; /* Button Dark Blue */
        color: #ffffff;
        border: none;
        border-radius: 2px;
        padding: 8px 16px;
        font-size: 14px;
    }
    QPushButton:hover {
        background-color: #66c0f4; /* Steam Blue Hover */
        color: #ffffff;
    }
    QPushButton:pressed {
        background-color: #171a21; /* Darker on press */
    }
    QPushButton:disabled {
        background-color: #171a21;
        color: #505050;
    }
    /* Special Buttons (Primary/Action) */
    QPushButton[class="primary"] {
        background-color: #66c0f4;
        color: #ffffff;
        font-weight: bold;
        font-size: 15px;
    }
    QPushButton[class="primary"]:hover {
        background-color: #419dc9;
    }
    QPushButton[class="primary"]:disabled {
        background-color: #171a21;
        color: #505050;
    }
    QPushButton[class="secondary"] {
        background-color: #3d4450;
    }
    QPushButton[class="secondary"]:hover {
        background-color: #4e5663;
    }
    QPushButton[class="danger"] {
        background-color: #8c2a2a;
    }
    QPushButton[class="danger"]:hover {
        background-color: #b53636;
    }
    /* Combo Boxes */
    QComboBox {
        background-color: #171a21;
        color: #c7d5e0;
        border: 1px solid #3A4451;
        border-radius: 2px;
        padding: 5px;
        padding-left: 10px;
        min-height: 25px;
    }
    QComboBox:hover, QComboBox:on {
        border: 1px solid #66c0f4;
    }
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 30px;
        border-left-width: 1px;
        border-left-color: #3A4451;
        border-left-style: solid;
        border-top-right-radius: 2px;
        border-bottom-right-radius: 2px;
        background: #2a475e;
    }
    QComboBox::drop-down:hover {
        background-color: #66c0f4;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid #c7d5e0;
        width: 0;
        height: 0;
        margin: 0 auto;
    }
    QComboBox QAbstractItemView {
        background-color: #4e5663;
        border: 1px solid #3A4451;
        selection-background-color: #66c0f4;
        selection-color: #ffffff;
        color: #c7d5e0;
        outline: 0px;
    }
    QComboBox QAbstractItemView::item {
        min-height: 25px;
        padding: 2px;
    }
    QComboBox QAbstractItemView::item:hover,
    QComboBox QAbstractItemView::item:selected {
        background-color: #66c0f4;
        color: #ffffff;
    }
    /* Input Fields */
    QLineEdit, QTextEdit {
        background-color: #0e1114;
        color: #ffffff;
        border: 1px solid #3A4451;
        border-radius: 2px;
        padding: 4px;
    }
    /* Table Widget */
    QTableWidget {
        background-color: #171a21;
        color: #c7d5e0;
        gridline-color: #3A4451;
        border: none;
    }
    QHeaderView::section {
        background-color: #2a475e;
        color: #ffffff;
        padding: 4px;
        border: 1px solid #171a21;
    }
    /* Scrollbars */
    QScrollBar:vertical {
        background: #171a21;
        width: 12px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: #3d4450;
        min-height: 20px;
        border-radius: 2px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: none;
    }
    /* Progress Bar */
    QProgressBar {
        border: 1px solid #3A4451;
        background-color: #101214;
        border-radius: 2px;
        text-align: center;
        color: #ffffff;
    }
    QProgressBar::chunk {
        background-color: #66c0f4;
    }
    /* Message Box */
    QMessageBox {
        background-color: #1b2838;
    }
    """)

    try:
        window = SteamClipApp()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        handle_exception(type(e), e, e.__traceback__)
