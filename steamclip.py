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
from PyQt6.QtGui import QPixmap, QIcon, QDesktopServices, QColor, QGuiApplication
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
    log_dir = os.path.join(SteamClipApp.CONFIG_DIR, 'logs')
    os.makedirs(log_dir, exist_ok=True)

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
    CURRENT_VERSION = "v4.5"

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
        self.current_theme = self.config.get('theme', 'Steam Dark')

        first_run = not os.path.exists(self.CONFIG_FILE)
        if not self.default_dir:
            logger("No default directory configured. Prompting user.")
            self.default_dir = self.prompt_steam_version_selection()
            if not self.default_dir:
                logger("User cancelled folder selection or failed to find one. Exiting.")
                QMessageBox.critical(self, "Critical Error", "Failed to locate Steam userdata directory. Exiting.")
                sys.exit(1)
            self.save_config(self.default_dir, self.export_dir)

        self.load_game_ids()

        # UI Components
        self.steamid_combo = QComboBox()
        self.gameid_combo = QComboBox()
        self.media_type_combo = QComboBox()
        self.steamid_combo.setFixedSize(300, 40)
        self.gameid_combo.setFixedSize(300, 40)
        self.media_type_combo.setFixedSize(300, 40)

        self.media_type_combo.addItems(["All Clips", "Manual Clips", "Background Recordings"])
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

    # ============ NON-STEAM GAMES NAME EXTRACTION ============
    def find_steam_root(self):
        if self.default_dir and os.path.isdir(self.default_dir):
            steam_root = Path(self.default_dir).parent.parent
            if (steam_root / "userdata").exists():
                return steam_root.resolve()
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
                Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
                Path.home() / "snap" / "steam" / "common" / ".steam" / "steam",
            ]
            for path in candidates:
                if path.exists() and (path / "userdata").exists():
                    return path.resolve()
        if self.default_dir:
            return Path(self.default_dir).parent.parent.resolve()
        return None

    def parse_binary_vdf(self, data):
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
                if type_byte == 0x08:
                    return res, p
                if p >= len(d):
                    break
                try:
                    key, p = read_string(d, p)
                except ValueError:
                    break
                if type_byte == 0x00:
                    sub_map, p = parse_map(d, p)
                    res[key] = sub_map
                elif type_byte == 0x01:
                    val, p = read_string(d, p)
                    res[key] = val
                elif type_byte == 0x02:
                    if p + 4 > len(d):
                        break
                    val = struct.unpack('<I', d[p:p+4])[0]
                    p += 4
                    res[key] = val
                else:
                    continue
            return res, p

        items = []
        ptr = 0
        if not data:
            return items
        try:
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
                    raw_id = item.get("appid")
                    if raw_id is not None:
                        app_id_32 = raw_id & 0xffffffff
                        clip_id = (app_id_32 << 32) | 0x02000000
                        non_steam_games[str(clip_id)] = app_name
                        logger(f"Non-Steam game found (explicit ID): {app_name} -> {clip_id} (Raw: {app_id_32})")
                        continue
                    if exe_path:
                        crc_input = (exe_path + app_name).encode("utf-8")
                        crc = zlib.crc32(crc_input) & 0xffffffff
                        app_id_32 = crc | 0x80000000
                        clip_id = (app_id_32 << 32) | 0x02000000
                        non_steam_games[str(clip_id)] = app_name
                        logger(f"Non-Steam game found (calculated ID): {app_name} -> {clip_id} (Raw: {app_id_32})")
            except Exception as e:
                logger(f"Error reading shortcuts.vdf from {shortcuts_path}: {e}")
        logger(f"Found {len(non_steam_games)} non-Steam games")
        return non_steam_games

    def merge_non_steam_games(self):
        logger("Merging non-Steam games into GameIDs database...")
        if not self.game_ids:
            self.load_game_ids(load_non_steam=False)
        non_steam_games = self.load_non_steam_games()
        merged_count = 0
        for app_id, app_name in non_steam_games.items():
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

    def load_config(self):
        config = {
            'userdata_path': None,
            'export_path': os.path.normpath(os.path.join(os.path.expanduser("~"), "Desktop")),
            'theme': 'Steam Dark'
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
                        elif key == 'theme':
                            config['theme'] = value
                        else:
                            logger(f"Malformed config line skipped: {line}")
        else:
            logger("No config file found (Fresh Install or Deleted).")
        return config

    def save_config(self, userdata_path=None, export_path=None, theme=None):
            logger(f"Saving configuration. Userdata: {userdata_path}, Export: {export_path}, Theme: {theme}")

            if userdata_path is not None:
                self.config['userdata_path'] = os.path.normpath(userdata_path)
            if export_path is not None:
                self.config['export_path'] = os.path.normpath(export_path)
            if theme is not None:
                self.config['theme'] = theme

            with open(self.CONFIG_FILE, 'w') as f:
                for key, value in self.config.items():
                    if value is not None:
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
            headers = {'User-Agent': 'SteamClip-App'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            release_data = response.json()
            return {
                'version': release_data.get('tag_name', 'Unknown'),
                'changelog': release_data.get('body', 'No changelog available'),
                'html_url': release_data.get('html_url', '')
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
            dialog.setLayout(layout)
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
        if load_non_steam:
            self.merge_non_steam_games()

    def fetch_game_name_from_steam(self, game_id):
        url = f"{self.STEAM_APP_DETAILS_URL}?appids={game_id}&filters=basic"
        try:
            response = requests.get(url, timeout=5)
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
                logger("filter_media_type: no steamid selected, returning early.")
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
                logger(f"  Scanned clips_dir_default: {clips_dir_default} -> {len(clip_folders)} folders")
            else:
                logger(f"  clips_dir_default does not exist: {clips_dir_default}")
            if os.path.isdir(video_dir_default):
                video_folders.extend(folder.path for folder in os.scandir(video_dir_default) if folder.is_dir() and "_" in folder.name)
                logger(f"  Scanned video_dir_default: {video_dir_default} -> {len(video_folders)} folders")
            else:
                logger(f"  video_dir_default does not exist: {video_dir_default}")
            if clips_dir_custom and os.path.isdir(clips_dir_custom):
                clip_folders.extend(folder.path for folder in os.scandir(clips_dir_custom) if folder.is_dir() and "_" in folder.name)
                logger(f"  Scanned clips_dir_custom: {clips_dir_custom} -> {len(clip_folders)} folders")
            if video_dir_custom and os.path.isdir(video_dir_custom):
                video_folders.extend(folder.path for folder in os.scandir(video_dir_custom) if folder.is_dir() and "_" in folder.name)
                logger(f"  Scanned video_dir_custom: {video_dir_custom} -> {len(video_folders)} folders")
            if selected_media_type == "All Clips":
                self.clip_folders = clip_folders + video_folders
            elif selected_media_type == "Manual Clips":
                self.clip_folders = clip_folders
            elif selected_media_type == "Background Recordings":
                self.clip_folders = video_folders
            else:
                logger(f"WARNING: Unrecognized media type '{selected_media_type}', defaulting to all clips.")
                self.clip_folders = clip_folders + video_folders
            self.clip_folders = sorted(self.clip_folders, key=lambda x: self.extract_datetime_from_folder_name(x), reverse=True)
            self.original_clip_folders = list(self.clip_folders)
            logger(f"Media filter applied. Found {len(self.clip_folders)} clips total (type='{selected_media_type}').")
            self.populate_gameid_combo()
            self.display_clips()

    def on_steamid_selected(self):
        selected_steamid = self.steamid_combo.currentText()
        if selected_steamid != self.prev_steamid:
            logger(f"Selected SteamID user: {selected_steamid}")
            self.prev_steamid = selected_steamid
            self.filter_media_type()

    def clear_clip_grid(self):
        while self.clip_grid.count():
            item = self.clip_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
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
    def extract_datetime_from_folder_name(folder_path):
        folder_name = os.path.basename(folder_path)
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
        game_ids_in_clips = {os.path.basename(folder).split('_')[1] for folder in folders_source if '_' in os.path.basename(folder)}
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
            if not os.path.exists(thumbnail_path):
                try:
                    fallback_path = os.path.join(tempfile.gettempdir(), f"steamclip_thumb_{index}.jpg")
                    self.create_placeholder_thumbnail(fallback_path)
                    if os.path.exists(fallback_path):
                        thumbnail_path = fallback_path
                except Exception as exc:
                    logger(f"Last-resort placeholder also failed for {folder}: {exc}")
            if os.path.exists(thumbnail_path):
                self.add_thumbnail_to_grid(thumbnail_path, folder, index)
            else:
                logger(f"WARNING: Could not create any thumbnail for clip: {folder}")
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
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFormat("Initializing conversion...")
        self.toggle_interface(enabled=False)
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
        self.resize(360, 580)
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)

        # --- Appearance Group ---
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QVBoxLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(ThemeManager.THEMES.keys()))
        current_theme = parent.config.get('theme', 'Steam Dark')
        self.theme_combo.setCurrentText(current_theme)
        self.theme_combo.currentTextChanged.connect(self.on_theme_changed)
        appearance_layout.addWidget(self.theme_combo)
        appearance_group.setLayout(appearance_layout)

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
        game_data_layout.addWidget(self.edit_game_ids_button)
        game_data_layout.addWidget(self.update_game_ids_button)
        game_data_group.setLayout(game_data_layout)

        # --- Application Group ---
        app_group = QGroupBox("Application Settings")
        app_layout = QVBoxLayout()
        self.check_for_updates_button = self.create_button("Check for Updates", self.check_for_updates, "system-software-update", size=None)
        if DEBUG:
            self.check_for_updates_button.setDisabled(True)
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

        main_layout.addWidget(appearance_group)
        main_layout.addWidget(general_group)
        main_layout.addWidget(game_data_group)
        main_layout.addWidget(app_group)
        main_layout.addStretch()
        main_layout.addLayout(footer_layout)
        self.setLayout(main_layout)

    def on_theme_changed(self, theme_name):
        logger(f"Theme changed to: {theme_name}")
        ThemeManager.apply(theme_name)
        self.parent().config['theme'] = theme_name
        self.parent().current_theme = theme_name
        self.parent().save_config(theme=theme_name)

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
            default_export_path = os.path.normpath(os.path.normpath(os.path.join(os.path.expanduser("~"), "Desktop")))
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
            non_steam_updated = self.parent().merge_non_steam_games()
            steam_updated = False
            if self.parent().is_connected():
                game_ids = {os.path.basename(folder).split('_')[1] for folder in self.parent().original_clip_folders if '_' in os.path.basename(folder)}
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

STEAM_DARK_QSS = """
QWidget { background-color: #1b2838; color: #c7d5e0; font-family: "Segoe UI", "Roboto", "Helvetica Neue", sans-serif; font-size: 14px; }
QFrame { border: 2px solid #3A4451; border-radius: 6px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #233140, stop:1 #1b2838); }
QLabel { color: #c7d5e0; }
QGroupBox { border: 2px solid #66c0f4; border-radius: 6px; margin-top: 24px; font-weight: bold; background-color: #233140; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #66c0f4; }
QPushButton { background-color: #2a475e; color: #ffffff; border: 1px solid #3A4451; border-radius: 4px; padding: 8px 16px; font-size: 14px; }
QPushButton:hover { background-color: #66c0f4; color: #ffffff; border-color: #66c0f4; }
QPushButton:pressed { background-color: #171a21; }
QPushButton:disabled { background-color: #171a21; color: #505050; border-color: #2a3a4a; }
QPushButton[class="primary"] { background-color: #66c0f4; color: #ffffff; font-weight: bold; font-size: 15px; border: 2px solid #66c0f4; }
QPushButton[class="primary"]:hover { background-color: #419dc9; }
QPushButton[class="primary"]:disabled { background-color: #171a21; color: #505050; border-color: #2a3a4a; }
QPushButton[class="secondary"] { background-color: #3d4450; border: 1px solid #3A4451; }
QPushButton[class="secondary"]:hover { background-color: #4e5663; border-color: #66c0f4; }
QPushButton[class="danger"] { background-color: #8c2a2a; border: 1px solid #6a1a1a; }
QPushButton[class="danger"]:hover { background-color: #b53636; border-color: #ff4444; }
QComboBox { background-color: #171a21; color: #c7d5e0; border: 1px solid #3A4451; border-radius: 4px; padding: 5px 10px; min-height: 25px; }
QComboBox:hover, QComboBox:on { border-color: #66c0f4; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border-left: 1px solid #3A4451; border-top-right-radius: 4px; border-bottom-right-radius: 4px; background: #2a475e; }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #c7d5e0; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #4e5663; border: 1px solid #3A4451; selection-background-color: #66c0f4; selection-color: #ffffff; color: #c7d5e0; outline: 0px; }
QTableWidget { background-color: #171a21; color: #c7d5e0; gridline-color: #3A4451; border: 1px solid #3A4451; border-radius: 4px; }
QHeaderView::section { background-color: #2a475e; color: #ffffff; padding: 4px; border: none; border-bottom: 1px solid #3A4451; }
QProgressBar { border: 1px solid #3A4451; background-color: #101214; border-radius: 4px; text-align: center; color: #ffffff; }
QProgressBar::chunk { background-color: #66c0f4; border-radius: 3px; }
QScrollBar:vertical { background: #1b2838; width: 14px; margin: 0; border-radius: 4px; }
QScrollBar::handle:vertical { background: #3d4450; min-height: 20px; border-radius: 4px; border: 1px solid #66c0f4; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #233140; border: 2px solid #66c0f4; border-radius: 6px; }
"""

STEAM_LIGHT_QSS = """
QWidget { background-color: #f0f2f5; color: #1a1a1a; font-family: "Segoe UI", "Roboto", "Helvetica Neue", sans-serif; font-size: 14px; }
QFrame { border: 2px solid #c8c8c8; border-radius: 6px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #ffffff, stop:1 #f0f2f5); }
QLabel { color: #1a1a1a; }
QGroupBox { border: 2px solid #2a475e; border-radius: 6px; margin-top: 24px; font-weight: bold; background-color: #ffffff; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #2a475e; }
QPushButton { background-color: #e0e3e8; color: #1a1a1a; border: 1px solid #c8c8c8; border-radius: 4px; padding: 8px 16px; font-size: 14px; }
QPushButton:hover { background-color: #66c0f4; color: #ffffff; border-color: #419dc9; }
QPushButton:pressed { background-color: #d0d3d8; }
QPushButton:disabled { background-color: #e8e8e8; color: #999999; border-color: #d8d8d8; }
QPushButton[class="primary"] { background-color: #2a475e; color: #ffffff; font-weight: bold; font-size: 15px; border: 2px solid #2a475e; }
QPushButton[class="primary"]:hover { background-color: #1e3547; }
QPushButton[class="secondary"] { background-color: #d0d3d8; border: 1px solid #b0b3b8; }
QPushButton[class="secondary"]:hover { background-color: #c0c3c8; border-color: #66c0f4; }
QPushButton[class="danger"] { background-color: #d9534f; color: #fff; border: 1px solid #c0302c; }
QPushButton[class="danger"]:hover { background-color: #c9302c; border-color: #ff4444; }
QComboBox { background-color: #ffffff; color: #1a1a1a; border: 1px solid #c8c8c8; border-radius: 4px; padding: 5px 10px; min-height: 25px; }
QComboBox:hover, QComboBox:on { border-color: #2a475e; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border-left: 1px solid #c8c8c8; border-top-right-radius: 4px; border-bottom-right-radius: 4px; background: #f5f5f5; }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #1a1a1a; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #ffffff; border: 1px solid #c8c8c8; selection-background-color: #2a475e; selection-color: #ffffff; color: #1a1a1a; outline: 0px; }
QTableWidget { background-color: #ffffff; color: #1a1a1a; gridline-color: #e0e0e0; border: 1px solid #c8c8c8; border-radius: 4px; }
QHeaderView::section { background-color: #e8e8e8; color: #1a1a1a; padding: 4px; border: none; border-bottom: 1px solid #c8c8c8; }
QProgressBar { border: 1px solid #c8c8c8; background-color: #e8e8e8; border-radius: 4px; text-align: center; color: #1a1a1a; }
QProgressBar::chunk { background-color: #2a475e; border-radius: 3px; }
QScrollBar:vertical { background: #f0f2f5; width: 14px; margin: 0; border-radius: 4px; }
QScrollBar::handle:vertical { background: #c0c0c0; min-height: 20px; border-radius: 4px; border: 1px solid #2a475e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #ffffff; border: 2px solid #2a475e; border-radius: 6px; }
"""

MODERN_DARK_QSS = """
QWidget { background-color: #121212; color: #e0e0e0; font-family: "Inter", "Segoe UI", system-ui, sans-serif; font-size: 14px; }
QFrame { border: 2px solid #333333; border-radius: 8px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #1e1e1e, stop:1 #121212); }
QLabel { color: #e0e0e0; }
QGroupBox { border: 2px solid #bb86fc; border-radius: 8px; margin-top: 28px; font-weight: 500; background-color: #1e1e1e; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; color: #bb86fc; }
QPushButton { background-color: #2c2c2c; color: #e0e0e0; border: 1px solid #444444; border-radius: 6px; padding: 8px 16px; font-size: 14px; }
QPushButton:hover { background-color: #3a3a3a; border-color: #555555; }
QPushButton:pressed { background-color: #222222; }
QPushButton:disabled { background-color: #2a2a2a; color: #666666; border-color: #333333; }
QPushButton[class="primary"] { background-color: #bb86fc; color: #000000; font-weight: bold; font-size: 15px; border: 2px solid #bb86fc; }
QPushButton[class="primary"]:hover { background-color: #a370db; }
QPushButton[class="secondary"] { background-color: #333333; border-color: #444444; }
QPushButton[class="secondary"]:hover { background-color: #444444; border-color: #bb86fc; }
QPushButton[class="danger"] { background-color: #cf6679; color: #000000; border: 1px solid #b85569; }
QPushButton[class="danger"]:hover { background-color: #b85569; border-color: #ff6688; }
QComboBox { background-color: #1e1e1e; color: #e0e0e0; border: 1px solid #444444; border-radius: 6px; padding: 5px 10px; min-height: 28px; }
QComboBox:hover, QComboBox:on { border-color: #bb86fc; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 32px; border-left: 1px solid #444444; border-top-right-radius: 6px; border-bottom-right-radius: 6px; background: #2c2c2c; }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #e0e0e0; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #1e1e1e; border: 1px solid #444444; selection-background-color: #bb86fc; selection-color: #000000; color: #e0e0e0; outline: 0px; padding: 2px; }
QTableWidget { background-color: #1e1e1e; color: #e0e0e0; gridline-color: #333333; border: 1px solid #333333; border-radius: 6px; }
QHeaderView::section { background-color: #2c2c2c; color: #e0e0e0; padding: 6px; border: none; border-bottom: 1px solid #333333; }
QProgressBar { border: 1px solid #444444; background-color: #2c2c2c; border-radius: 6px; text-align: center; color: #e0e0e0; height: 16px; }
QProgressBar::chunk { background-color: #bb86fc; border-radius: 5px; }
QScrollBar:vertical { background: #121212; width: 12px; margin: 0; border-radius: 6px; }
QScrollBar::handle:vertical { background: #555555; min-height: 20px; border-radius: 6px; border: 1px solid #bb86fc; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #1e1e1e; border: 2px solid #bb86fc; border-radius: 8px; }
"""

NORD_QSS = """
QWidget { background-color: #2E3440; color: #D8DEE9; font-family: "Segoe UI", "Roboto", "Helvetica Neue", sans-serif; font-size: 14px; }
QFrame { border: 2px solid #4C566A; border-radius: 6px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #3B4252, stop:1 #2E3440); }
QLabel { color: #D8DEE9; }
QGroupBox { border: 2px solid #88C0D0; border-radius: 6px; margin-top: 24px; font-weight: bold; background-color: #3B4252; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #88C0D0; }
QPushButton { background-color: #3B4252; color: #D8DEE9; border: 1px solid #4C566A; border-radius: 4px; padding: 8px 16px; font-size: 14px; }
QPushButton:hover { background-color: #4C566A; color: #ECEFF4; border-color: #88C0D0; }
QPushButton:pressed { background-color: #2E3440; }
QPushButton:disabled { background-color: #363F4F; color: #6B7A8D; border-color: #434C5E; }
QPushButton[class="primary"] { background-color: #88C0D0; color: #2E3440; font-weight: bold; font-size: 15px; border: 2px solid #88C0D0; }
QPushButton[class="primary"]:hover { background-color: #8FBCBB; }
QPushButton[class="secondary"] { background-color: #434C5E; border-color: #4C566A; }
QPushButton[class="secondary"]:hover { background-color: #4C566A; border-color: #88C0D0; }
QPushButton[class="danger"] { background-color: #BF616A; color: #ECEFF4; border: 1px solid #a04444; }
QPushButton[class="danger"]:hover { background-color: #D08770; border-color: #ff6666; }
QComboBox { background-color: #3B4252; color: #D8DEE9; border: 1px solid #4C566A; border-radius: 4px; padding: 5px 10px; min-height: 25px; }
QComboBox:hover, QComboBox:on { border-color: #88C0D0; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border-left: 1px solid #4C566A; border-top-right-radius: 4px; border-bottom-right-radius: 4px; background: #4C566A; }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #D8DEE9; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #3B4252; border: 1px solid #4C566A; selection-background-color: #88C0D0; selection-color: #2E3440; color: #D8DEE9; outline: 0px; }
QTableWidget { background-color: #2E3440; color: #D8DEE9; gridline-color: #4C566A; border: 1px solid #4C566A; border-radius: 4px; }
QHeaderView::section { background-color: #3B4252; color: #ECEFF4; padding: 6px; border: none; border-bottom: 1px solid #4C566A; }
QProgressBar { border: 1px solid #4C566A; background-color: #2E3440; border-radius: 4px; text-align: center; color: #ECEFF4; }
QProgressBar::chunk { background-color: #88C0D0; border-radius: 3px; }
QScrollBar:vertical { background: #2E3440; width: 14px; margin: 0; border-radius: 6px; }
QScrollBar::handle:vertical { background: #4C566A; min-height: 20px; border-radius: 6px; border: 1px solid #88C0D0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #3B4252; border: 2px solid #88C0D0; border-radius: 6px; }
"""

DRACULA_QSS = """
QWidget { background-color: #282a36; color: #f8f8f2; font-family: "Segoe UI", "Roboto", "Helvetica Neue", sans-serif; font-size: 14px; }
QFrame { border: 2px solid #6272a4; border-radius: 8px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #44475a, stop:1 #282a36); }
QLabel { color: #f8f8f2; }
QGroupBox { border: 2px solid #bd93f9; border-radius: 8px; margin-top: 28px; font-weight: bold; background-color: #44475a; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; color: #bd93f9; }
QPushButton { background-color: #44475a; color: #f8f8f2; border: 1px solid #6272a4; border-radius: 6px; padding: 8px 16px; font-size: 14px; }
QPushButton:hover { background-color: #6272a4; color: #f8f8f2; border-color: #bd93f9; }
QPushButton:pressed { background-color: #1e1f29; }
QPushButton:disabled { background-color: #363845; color: #6272a4; border-color: #44475a; }
QPushButton[class="primary"] { background-color: #bd93f9; color: #282a36; font-weight: bold; font-size: 15px; border: 2px solid #bd93f9; }
QPushButton[class="primary"]:hover { background-color: #ff79c6; }
QPushButton[class="secondary"] { background-color: #363845; border-color: #44475a; }
QPushButton[class="secondary"]:hover { background-color: #44475a; border-color: #bd93f9; }
QPushButton[class="danger"] { background-color: #ff5555; color: #f8f8f2; border: 1px solid #cc3333; }
QPushButton[class="danger"]:hover { background-color: #ff6e6e; border-color: #ff8888; }
QComboBox { background-color: #44475a; color: #f8f8f2; border: 1px solid #6272a4; border-radius: 6px; padding: 5px 10px; min-height: 28px; }
QComboBox:hover, QComboBox:on { border-color: #bd93f9; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 32px; border-left: 1px solid #6272a4; border-top-right-radius: 6px; border-bottom-right-radius: 6px; background: #6272a4; }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #f8f8f2; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #44475a; border: 1px solid #6272a4; selection-background-color: #bd93f9; selection-color: #282a36; color: #f8f8f2; outline: 0px; padding: 2px; }
QTableWidget { background-color: #282a36; color: #f8f8f2; gridline-color: #44475a; border: 1px solid #6272a4; border-radius: 6px; }
QHeaderView::section { background-color: #44475a; color: #f8f8f2; padding: 6px; border: none; border-bottom: 1px solid #6272a4; }
QProgressBar { border: 1px solid #6272a4; background-color: #44475a; border-radius: 6px; text-align: center; color: #f8f8f2; height: 16px; }
QProgressBar::chunk { background-color: #50fa7b; border-radius: 5px; }
QScrollBar:vertical { background: #282a36; width: 12px; margin: 0; border-radius: 6px; }
QScrollBar::handle:vertical { background: #6272a4; min-height: 20px; border-radius: 6px; border: 1px solid #bd93f9; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #44475a; border: 2px solid #bd93f9; border-radius: 8px; }
"""

CATPPUCCIN_MOCHA_QSS = """
QWidget { background-color: #1e1e2e; color: #cdd6f4; font-family: "Inter", "Segoe UI", system-ui, sans-serif; font-size: 14px; }
QFrame { border: 2px solid #313244; border-radius: 8px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #181825, stop:1 #1e1e2e); }
QLabel { color: #cdd6f4; }
QGroupBox { border: 2px solid #89b4fa; border-radius: 8px; margin-top: 28px; font-weight: 500; background-color: #181825; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; color: #89b4fa; }
QPushButton { background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; border-radius: 6px; padding: 8px 16px; font-size: 14px; }
QPushButton:hover { background-color: #45475a; border-color: #585b70; }
QPushButton:pressed { background-color: #11111b; }
QPushButton:disabled { background-color: #313244; color: #585b70; border-color: #313244; }
QPushButton[class="primary"] { background-color: #89b4fa; color: #1e1e2e; font-weight: bold; font-size: 15px; border: 2px solid #89b4fa; }
QPushButton[class="primary"]:hover { background-color: #74c7ec; }
QPushButton[class="secondary"] { background-color: #45475a; border-color: #585b70; }
QPushButton[class="secondary"]:hover { background-color: #585b70; border-color: #89b4fa; }
QPushButton[class="danger"] { background-color: #f38ba8; color: #1e1e2e; border: 1px solid #d0667f; }
QPushButton[class="danger"]:hover { background-color: #eba0ac; border-color: #ff8899; }
QComboBox { background-color: #181825; color: #cdd6f4; border: 1px solid #45475a; border-radius: 6px; padding: 5px 10px; min-height: 28px; }
QComboBox:hover, QComboBox:on { border-color: #89b4fa; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 32px; border-left: 1px solid #45475a; border-top-right-radius: 6px; border-bottom-right-radius: 6px; background: #313244; }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #cdd6f4; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #181825; border: 1px solid #45475a; selection-background-color: #89b4fa; selection-color: #1e1e2e; color: #cdd6f4; outline: 0px; padding: 2px; }
QTableWidget { background-color: #1e1e2e; color: #cdd6f4; gridline-color: #313244; border: 1px solid #313244; border-radius: 6px; }
QHeaderView::section { background-color: #313244; color: #cdd6f4; padding: 6px; border: none; border-bottom: 1px solid #45475a; }
QProgressBar { border: 1px solid #45475a; background-color: #313244; border-radius: 6px; text-align: center; color: #cdd6f4; height: 16px; }
QProgressBar::chunk { background-color: #a6e3a1; border-radius: 5px; }
QScrollBar:vertical { background: #1e1e2e; width: 12px; margin: 0; border-radius: 6px; }
QScrollBar::handle:vertical { background: #585b70; min-height: 20px; border-radius: 6px; border: 1px solid #89b4fa; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #181825; border: 2px solid #89b4fa; border-radius: 8px; }
"""

HIGH_CONTRAST_LIGHT_QSS = """
QWidget { background-color: #ffffff; color: #000000; font-family: "Segoe UI", "Roboto", "Helvetica Neue", sans-serif; font-size: 14px; }
QFrame { border: 3px solid #000000; border-radius: 4px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #f8f8f8, stop:1 #ffffff); }
QLabel { color: #000000; }
QGroupBox { border: 3px solid #0000ee; border-radius: 6px; margin-top: 24px; font-weight: bold; background-color: #ffffff; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #0000ee; }
QPushButton { background-color: #f0f0f0; color: #000000; border: 2px solid #000000; border-radius: 4px; padding: 8px 16px; font-size: 14px; font-weight: 600; }
QPushButton:hover { background-color: #e0e0e0; border-color: #0000cc; }
QPushButton:pressed { background-color: #d0d0d0; }
QPushButton:disabled { background-color: #e0e0e0; color: #808080; border-color: #a0a0a0; }
QPushButton[class="primary"] { background-color: #0000ee; color: #ffffff; font-weight: bold; font-size: 15px; border: 3px solid #0000cc; }
QPushButton[class="primary"]:hover { background-color: #0000cc; }
QPushButton[class="secondary"] { background-color: #e0e0e0; border-color: #000000; }
QPushButton[class="secondary"]:hover { background-color: #d0d0d0; border-color: #0000cc; }
QPushButton[class="danger"] { background-color: #cc0000; color: #ffffff; border: 2px solid #aa0000; }
QPushButton[class="danger"]:hover { background-color: #aa0000; border-color: #ff3333; }
QComboBox { background-color: #ffffff; color: #000000; border: 2px solid #000000; border-radius: 4px; padding: 5px 10px; min-height: 28px; font-weight: 600; }
QComboBox:hover, QComboBox:on { border-color: #0000ee; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 32px; border-left: 2px solid #000000; border-top-right-radius: 4px; border-bottom-right-radius: 4px; background: #f0f0f0; }
QComboBox::down-arrow { border-left: 6px solid transparent; border-right: 6px solid transparent; border-top: 8px solid #000000; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #ffffff; border: 2px solid #000000; selection-background-color: #0000ee; selection-color: #ffffff; color: #000000; outline: 0px; font-weight: 600; }
QTableWidget { background-color: #ffffff; color: #000000; gridline-color: #000000; border: 2px solid #000000; border-radius: 4px; }
QHeaderView::section { background-color: #f0f0f0; color: #000000; padding: 6px; border: none; border-bottom: 2px solid #000000; font-weight: bold; }
QProgressBar { border: 2px solid #000000; background-color: #e0e0e0; border-radius: 4px; text-align: center; color: #000000; height: 18px; }
QProgressBar::chunk { background-color: #0000ee; border-radius: 2px; }
QScrollBar:vertical { background: #ffffff; width: 16px; margin: 0; border: 1px solid #000000; border-radius: 4px; }
QScrollBar::handle:vertical { background: #000000; min-height: 24px; border-radius: 4px; border: 2px solid #0000ee; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #ffffff; border: 3px solid #000000; border-radius: 6px; }
"""

CYBERPUNK_QSS = """
QWidget { background-color: #0b0c15; color: #d0d0e0; font-family: "Segoe UI", "Roboto", "Helvetica Neue", sans-serif; font-size: 14px; }
QFrame { border: 2px solid #00f3ff; border-radius: 6px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #131420, stop:1 #0b0c15); }
QLabel { color: #d0d0e0; }
QGroupBox { border: 2px solid #00f3ff; border-radius: 6px; margin-top: 24px; font-weight: bold; background-color: #131420; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #00f3ff; }
QPushButton { background-color: #1a1c2e; color: #d0d0e0; border: 1px solid #00f3ff; border-radius: 4px; padding: 8px 16px; font-size: 14px; }
QPushButton:hover { background-color: #2a2d4a; color: #ffffff; border-color: #00ffff; }
QPushButton:pressed { background-color: #00f3ff; color: #000000; }
QPushButton:disabled { background-color: #151620; color: #555566; border-color: #333344; }
QPushButton[class="primary"] { background-color: #ff00ff; color: #000000; font-weight: bold; font-size: 15px; border: 2px solid #ff00ff; }
QPushButton[class="primary"]:hover { background-color: #d900d9; }
QPushButton[class="secondary"] { background-color: #222436; border-color: #00f3ff; }
QPushButton[class="secondary"]:hover { background-color: #2a2d4a; border-color: #00ffff; }
QPushButton[class="danger"] { background-color: #ff3366; color: #000000; border: 1px solid #cc0033; }
QPushButton[class="danger"]:hover { background-color: #ff1a4d; border-color: #ff6688; }
QComboBox { background-color: #1a1c2e; color: #d0d0e0; border: 1px solid #00f3ff; border-radius: 4px; padding: 5px 10px; min-height: 25px; }
QComboBox:hover, QComboBox:on { border-color: #00ffff; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border-left: 1px solid #00f3ff; border-top-right-radius: 4px; border-bottom-right-radius: 4px; background: #222436; }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #00f3ff; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #131420; border: 1px solid #00f3ff; selection-background-color: #00f3ff; selection-color: #000000; color: #d0d0e0; outline: 0px; }
QTableWidget { background-color: #0b0c15; color: #d0d0e0; gridline-color: #333344; border: 1px solid #00f3ff; border-radius: 4px; }
QHeaderView::section { background-color: #1a1c2e; color: #00f3ff; padding: 6px; border: none; border-bottom: 1px solid #333344; }
QProgressBar { border: 1px solid #00f3ff; background-color: #1a1c2e; border-radius: 4px; text-align: center; color: #d0d0e0; }
QProgressBar::chunk { background-color: #00f3ff; border-radius: 3px; }
QScrollBar:vertical { background: #0b0c15; width: 14px; margin: 0; border-radius: 6px; }
QScrollBar::handle:vertical { background: #00f3ff; min-height: 20px; border-radius: 6px; border: 1px solid #00ffff; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #131420; border: 2px solid #00f3ff; border-radius: 6px; }
"""

GRUVBOX_QSS = """
QWidget { background-color: #282828; color: #ebdbb2; font-family: "Segoe UI", "Roboto", "Helvetica Neue", sans-serif; font-size: 14px; }
QFrame { border: 2px solid #504945; border-radius: 8px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #32302f, stop:1 #282828); }
QLabel { color: #ebdbb2; }
QGroupBox { border: 2px solid #fabd2f; border-radius: 8px; margin-top: 28px; font-weight: bold; background-color: #32302f; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; color: #fabd2f; }
QPushButton { background-color: #3c3836; color: #ebdbb2; border: 1px solid #504945; border-radius: 6px; padding: 8px 16px; font-size: 14px; }
QPushButton:hover { background-color: #504945; color: #ebdbb2; border-color: #665c54; }
QPushButton:pressed { background-color: #282828; }
QPushButton:disabled { background-color: #3c3836; color: #928374; border-color: #3c3836; }
QPushButton[class="primary"] { background-color: #b8bb26; color: #282828; font-weight: bold; font-size: 15px; border: 2px solid #b8bb26; }
QPushButton[class="primary"]:hover { background-color: #a1b01e; }
QPushButton[class="secondary"] { background-color: #504945; border-color: #665c54; }
QPushButton[class="secondary"]:hover { background-color: #665c54; border-color: #fabd2f; }
QPushButton[class="danger"] { background-color: #cc241d; color: #ebdbb2; border: 1px solid #991111; }
QPushButton[class="danger"]:hover { background-color: #b2221a; border-color: #ff4444; }
QComboBox { background-color: #3c3836; color: #ebdbb2; border: 1px solid #504945; border-radius: 6px; padding: 5px 10px; min-height: 28px; }
QComboBox:hover, QComboBox:on { border-color: #fabd2f; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 32px; border-left: 1px solid #504945; border-top-right-radius: 6px; border-bottom-right-radius: 6px; background: #504945; }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #ebdbb2; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #32302f; border: 1px solid #504945; selection-background-color: #fabd2f; selection-color: #282828; color: #ebdbb2; outline: 0px; padding: 2px; }
QTableWidget { background-color: #282828; color: #ebdbb2; gridline-color: #504945; border: 1px solid #504945; border-radius: 6px; }
QHeaderView::section { background-color: #3c3836; color: #fabd2f; padding: 6px; border: none; border-bottom: 1px solid #504945; }
QProgressBar { border: 1px solid #504945; background-color: #3c3836; border-radius: 6px; text-align: center; color: #ebdbb2; height: 16px; }
QProgressBar::chunk { background-color: #b8bb26; border-radius: 5px; }
QScrollBar:vertical { background: #282828; width: 12px; margin: 0; border-radius: 6px; }
QScrollBar::handle:vertical { background: #928374; min-height: 20px; border-radius: 6px; border: 1px solid #fabd2f; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #32302f; border: 2px solid #fabd2f; border-radius: 8px; }
"""

SYSTEM_QSS = """
QWidget { font-family: "Segoe UI", "Roboto", "Helvetica Neue", sans-serif; font-size: 14px; }
QFrame { border: 2px solid palette(mid); border-radius: 4px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 palette(light), stop:1 palette(window)); }
QGroupBox { border: 2px solid palette(highlight); border-radius: 4px; margin-top: 24px; font-weight: bold; background-color: palette(base); }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: palette(highlight); }
QPushButton { border: 1px solid palette(mid); border-radius: 4px; padding: 8px 16px; font-size: 14px; }
QPushButton:hover { background-color: palette(light); border-color: palette(highlight); }
QPushButton:pressed { background-color: palette(midlight); }
QPushButton:disabled { color: palette(disabled); border-color: palette(mid); }
QPushButton[class="primary"] { background-color: palette(highlight); color: palette(highlighted-text); font-weight: bold; font-size: 15px; border: 2px solid palette(highlight); }
QPushButton[class="primary"]:hover { background-color: palette(dark); }
QPushButton[class="secondary"] { background-color: palette(button); border-color: palette(mid); }
QPushButton[class="secondary"]:hover { background-color: palette(light); border-color: palette(highlight); }
QPushButton[class="danger"] { background-color: palette(error); color: palette(error-text); border: 1px solid palette(dark); }
QPushButton[class="danger"]:hover { border-color: palette(error); }
QComboBox { border: 1px solid palette(mid); border-radius: 4px; padding: 5px 10px; min-height: 25px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 30px; border-left: 1px solid palette(mid); border-top-right-radius: 4px; border-bottom-right-radius: 4px; background: palette(button); }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid palette(text); width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { selection-background-color: palette(highlight); selection-color: palette(highlighted-text); outline: 0px; }
QTableWidget { border: 1px solid palette(mid); border-radius: 4px; }
QHeaderView::section { background-color: palette(button); color: palette(text); padding: 4px; border: none; border-bottom: 1px solid palette(mid); }
QProgressBar { border: 1px solid palette(mid); background-color: palette(base); border-radius: 4px; text-align: center; color: palette(text); height: 16px; }
QProgressBar::chunk { background-color: palette(highlight); border-radius: 3px; }
QScrollBar:vertical { background: palette(window); width: 14px; margin: 0; border-radius: 4px; }
QScrollBar::handle:vertical { background: palette(mid); min-height: 20px; border-radius: 4px; border: 1px solid palette(highlight); }
QMessageBox { background-color: palette(window); border: 2px solid palette(highlight); border-radius: 4px; }
"""

PIP_BOY_QSS = """
QWidget { background-color: #000000; color: #00ff00; font-family: "Consolas", "Monaco", "Courier New", monospace; font-size: 14px; }
QFrame { border: 2px dashed #00aa00; border-radius: 4px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #001100, stop:1 #000000); }
QLabel { color: #00ff00; }
QGroupBox { border: 3px solid #00ff00; border-radius: 6px; margin-top: 28px; font-weight: bold; background-color: #001100; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; color: #00ff00; }
QPushButton { background-color: #002200; color: #00ff00; border: 2px solid #00aa00; border-radius: 4px; padding: 8px 16px; font-size: 14px; font-family: "Consolas", monospace; }
QPushButton:hover { background-color: #004400; color: #ffffff; border-color: #00ff00; }
QPushButton:pressed { background-color: #00ff00; color: #000000; }
QPushButton:disabled { background-color: #001100; color: #005500; border-color: #003300; }
QPushButton[class="primary"] { background-color: #00ff00; color: #000000; font-weight: bold; font-size: 15px; border: 3px solid #00ff00; }
QPushButton[class="primary"]:hover { background-color: #00dd00; }
QPushButton[class="secondary"] { background-color: #001a00; border-color: #00aa00; }
QPushButton[class="secondary"]:hover { background-color: #003300; border-color: #00ff00; }
QPushButton[class="danger"] { background-color: #ff0000; color: #ffffff; border: 2px solid #aa0000; }
QPushButton[class="danger"]:hover { background-color: #cc0000; border-color: #ff4444; }
QComboBox { background-color: #001100; color: #00ff00; border: 2px solid #00aa00; border-radius: 4px; padding: 5px 10px; min-height: 28px; font-family: "Consolas", monospace; }
QComboBox:hover, QComboBox:on { border-color: #00ff00; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 32px; border-left: 2px solid #00aa00; border-top-right-radius: 4px; border-bottom-right-radius: 4px; background: #002200; }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #00ff00; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #000000; border: 2px solid #00aa00; selection-background-color: #00ff00; selection-color: #000000; color: #00ff00; outline: 0px; font-family: "Consolas", monospace; }
QTableWidget { background-color: #000000; color: #00ff00; gridline-color: #003300; border: 2px solid #00aa00; border-radius: 4px; font-family: "Consolas", monospace; }
QHeaderView::section { background-color: #002200; color: #00ff00; padding: 6px; border: none; border-bottom: 2px solid #00aa00; font-family: "Consolas", monospace; }
QProgressBar { border: 2px solid #00aa00; background-color: #001100; border-radius: 4px; text-align: center; color: #00ff00; height: 16px; }
QProgressBar::chunk { background-color: #00ff00; border-radius: 3px; }
QScrollBar:vertical { background: #000000; width: 16px; margin: 0; border: 1px solid #003300; border-radius: 4px; }
QScrollBar::handle:vertical { background: #00aa00; min-height: 24px; border-radius: 4px; border: 2px solid #00ff00; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #001100; border: 3px solid #00ff00; border-radius: 6px; }
"""

CRT_AMBER_QSS = """
QWidget { background-color: #0a0a0a; color: #ffb000; font-family: "VT323", "Consolas", "Courier New", monospace; font-size: 15px; }
QFrame { border: 3px solid #553300; border-radius: 10px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.85, fx:0.5, fy:0.5, stop:0 #1a1200, stop:0.7 #0f0f00, stop:1 #0a0a0a); }
QLabel { color: #ffb000; }
QGroupBox { border: 3px solid #ffb000; border-radius: 10px; margin-top: 32px; font-weight: bold; background-color: #111100; }
QGroupBox::title { subcontrol-origin: margin; left: 16px; padding: 0 10px; color: #ffb000; }
QPushButton { background-color: #221800; color: #ffb000; border: 2px solid #886600; border-radius: 6px; padding: 10px 18px; font-size: 15px; font-family: "VT323", monospace; }
QPushButton:hover { background-color: #332200; color: #000000; border-color: #ffb000; }
QPushButton:pressed { background-color: #ffb000; color: #000000; }
QPushButton:disabled { background-color: #1a1400; color: #554400; border-color: #332200; }
QPushButton[class="primary"] { background-color: #ffb000; color: #000000; font-weight: bold; font-size: 16px; border: 3px solid #ffb000; }
QPushButton[class="primary"]:hover { background-color: #e69e00; }
QPushButton[class="secondary"] { background-color: #1a1400; border-color: #664400; }
QPushButton[class="secondary"]:hover { background-color: #2a1e00; border-color: #ffb000; }
QPushButton[class="danger"] { background-color: #ff4400; color: #000000; border: 2px solid #aa2200; }
QPushButton[class="danger"]:hover { background-color: #ff6633; border-color: #ff8855; }
QComboBox { background-color: #111100; color: #ffb000; border: 2px solid #886600; border-radius: 6px; padding: 6px 12px; min-height: 32px; font-family: "VT323", monospace; }
QComboBox:hover, QComboBox:on { border-color: #ffb000; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 36px; border-left: 2px solid #886600; border-top-right-radius: 6px; border-bottom-right-radius: 6px; background: #221800; }
QComboBox::down-arrow { border-left: 6px solid transparent; border-right: 6px solid transparent; border-top: 7px solid #ffb000; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #0a0a0a; border: 2px solid #886600; selection-background-color: #ffb000; selection-color: #000000; color: #ffb000; outline: 0px; font-family: "VT323", monospace; padding: 2px; }
QTableWidget { background-color: #0a0a0a; color: #ffb000; gridline-color: #332200; border: 2px solid #886600; border-radius: 6px; font-family: "VT323", monospace; }
QHeaderView::section { background-color: #221800; color: #ffb000; padding: 8px; border: none; border-bottom: 2px solid #886600; font-family: "VT323", monospace; }
QProgressBar { border: 2px solid #886600; background-color: #111100; border-radius: 6px; text-align: center; color: #ffb000; height: 20px; }
QProgressBar::chunk { background-color: #ffb000; border-radius: 5px; }
QScrollBar:vertical { background: #0a0a0a; width: 18px; margin: 0; border: 1px solid #332200; border-radius: 6px; }
QScrollBar::handle:vertical { background: #886600; min-height: 30px; border-radius: 6px; border: 2px solid #ffb000; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #111100; border: 4px solid #ffb000; border-radius: 10px; }
"""

NEON_BLUE_QSS = """
QWidget { background-color: #000000; color: #00ccff; font-family: "Share Tech Mono", "Consolas", "Courier New", monospace; font-size: 14px; }
QFrame { border: 2px solid #005566; border-radius: 4px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.9, fx:0.5, fy:0.5, stop:0 #000810, stop:1 #000000); }
QLabel { color: #00ccff; }
QGroupBox { border: 2px solid #00ccff; border-radius: 6px; margin-top: 28px; font-weight: bold; background-color: #000810; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 8px; color: #00ccff; }
QPushButton { background-color: #001122; color: #00ccff; border: 1px solid #006688; border-radius: 4px; padding: 8px 16px; font-size: 14px; font-family: "Share Tech Mono", monospace; }
QPushButton:hover { background-color: #002244; color: #000000; border-color: #00ccff; }
QPushButton:pressed { background-color: #00ccff; color: #000000; }
QPushButton:disabled { background-color: #000810; color: #004455; border-color: #002233; }
QPushButton[class="primary"] { background-color: #00ccff; color: #000000; font-weight: bold; font-size: 15px; border: 2px solid #00ccff; }
QPushButton[class="primary"]:hover { background-color: #00aacc; }
QPushButton[class="secondary"] { background-color: #000a15; border-color: #004466; }
QPushButton[class="secondary"]:hover { background-color: #001525; border-color: #00ccff; }
QPushButton[class="danger"] { background-color: #ff3366; color: #ffffff; border: 1px solid #aa0033; }
QPushButton[class="danger"]:hover { background-color: #ff5588; border-color: #ff88aa; }
QComboBox { background-color: #000810; color: #00ccff; border: 1px solid #006688; border-radius: 4px; padding: 5px 10px; min-height: 28px; font-family: "Share Tech Mono", monospace; }
QComboBox:hover, QComboBox:on { border-color: #00ccff; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 32px; border-left: 1px solid #006688; border-top-right-radius: 4px; border-bottom-right-radius: 4px; background: #001122; }
QComboBox::down-arrow { border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 6px solid #00ccff; width: 0; height: 0; margin: 0 auto; }
QComboBox QAbstractItemView { background-color: #00050a; border: 1px solid #006688; selection-background-color: #00ccff; selection-color: #000000; color: #00ccff; outline: 0px; font-family: "Share Tech Mono", monospace; padding: 2px; }
QTableWidget { background-color: #000000; color: #00ccff; gridline-color: #002233; border: 1px solid #006688; border-radius: 4px; font-family: "Share Tech Mono", monospace; }
QHeaderView::section { background-color: #001122; color: #00ccff; padding: 6px; border: none; border-bottom: 1px solid #006688; font-family: "Share Tech Mono", monospace; }
QProgressBar { border: 1px solid #006688; background-color: #000810; border-radius: 4px; text-align: center; color: #00ccff; height: 16px; }
QProgressBar::chunk { background-color: #00ccff; border-radius: 3px; }
QScrollBar:vertical { background: #000000; width: 14px; margin: 0; border: 1px solid #002233; border-radius: 4px; }
QScrollBar::handle:vertical { background: #006688; min-height: 22px; border-radius: 4px; border: 1px solid #00ccff; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox { background-color: #000810; border: 3px solid #00ccff; border-radius: 6px; }
"""
# ================= THEME MANAGER =================
class ThemeManager:
    THEMES = {
        "Follow System": SYSTEM_QSS,
        "Catppuccin Mocha": CATPPUCCIN_MOCHA_QSS,
        "CRT Amber": CRT_AMBER_QSS,
        "Cyberpunk": CYBERPUNK_QSS,
        "Dracula": DRACULA_QSS,
        "Gruvbox": GRUVBOX_QSS,
        "High Contrast": HIGH_CONTRAST_LIGHT_QSS,
        "Modern Dark": MODERN_DARK_QSS,
        "Neon Blue": NEON_BLUE_QSS,
        "Nord": NORD_QSS,
        "Pip Boy": PIP_BOY_QSS,
        "Steam Dark": STEAM_DARK_QSS,
        "Steam Light": STEAM_LIGHT_QSS,
    }

    _app_instance = None

    @classmethod
    def register_app(cls, app):
        cls._app_instance = app

    @classmethod
    def apply(cls, theme_name):
        if cls._app_instance is None:
            return

        if theme_name == "SYSTEM":
            theme_name = "Follow System"

        cls._app_instance.setStyleSheet(cls.THEMES.get(theme_name, ""))

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

    app.setStyleSheet("")

    window = SteamClipApp()
    saved_theme = window.config.get('theme', 'Steam Dark')
    window.current_theme = saved_theme

    ThemeManager.register_app(app)
    ThemeManager.apply(saved_theme)

    window.show()
    sys.exit(app.exec())
