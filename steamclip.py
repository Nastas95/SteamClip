#!/usr/bin/env python3
import os
import sys
import subprocess
import json
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

import imageio_ffmpeg as iio
import logging
import traceback
import shutil
import tempfile
import glob
import requests
import platform
import xml.etree.ElementTree as ElTree
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGridLayout,
    QFrame, QComboBox, QDialog, QTableWidget,
    QTableWidgetItem, QTextEdit, QMessageBox,
    QFileDialog, QLayout, QProgressBar, QGroupBox,
    QSizePolicy, QScrollArea
)
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtCore import Qt, QThread, pyqtSignal


DEBUG = os.path.basename(sys.executable).startswith('python')
IS_WINDOWS = sys.platform == 'win32'
EXECUTABLE_NAME = 'steamclip'

# GPU Encoding options
ENCODING_MODES = {
    'copy': {'name': 'Fast Copy (no re-encode)', 'args': ['-c', 'copy']},
    'nvenc': {'name': 'NVIDIA GPU (HEVC)', 'args': ['-c:v', 'hevc_nvenc', '-preset', 'p4', '-cq', '28', '-maxrate', '20M', '-bufsize', '40M', '-c:a', 'aac', '-b:a', '192k']},
    'amf': {'name': 'AMD GPU (HEVC)', 'args': ['-c:v', 'hevc_amf', '-quality', 'quality', '-rc', 'vbr_peak', '-qp_i', '28', '-qp_p', '28', '-c:a', 'aac', '-b:a', '192k']},
    'qsv': {'name': 'Intel GPU (HEVC)', 'args': ['-c:v', 'hevc_qsv', '-preset', 'medium', '-global_quality', '28', '-c:a', 'aac', '-b:a', '192k']},
    'software': {'name': 'CPU (HEVC, slow)', 'args': ['-c:v', 'libx265', '-preset', 'medium', '-crf', '26', '-c:a', 'aac', '-b:a', '192k']},
}
if DEBUG:
    CONFIG_PATH = os.path.join(os.getcwd(), 'runtime')
    os.makedirs(CONFIG_PATH, exist_ok=True)
elif IS_WINDOWS:
    CONFIG_PATH = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser("~")), 'SteamClip')
    EXECUTABLE_NAME += '.exe'
else:
    CONFIG_PATH = os.path.expanduser("~/.config/SteamClip")


UPDATE_BATCH_SCRIPT = '''
@echo off
setlocal
set "old_exe=%(current_executable)s"
set "new_exe=%(temp_download_path)s"

:: 1. Wait
:loop
tasklist | findstr /C:"%(executable_name)s" >nul 2>&1
if %ERRORLEVEL% == 0 (
    timeout /t 1
    goto loop
)

:: 2. Replace
move /Y "%new_exe%" "%old_exe%" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Failed to replace executable. Retrying...
    timeout /t 2
    goto loop
)

:: 3. Run
:: Use 'cmd /c start' to avoid temporary directory inheritance
start "" /D "%~dp0" "%old_exe%"

:: 4. Delete
del "%~f0%"
'''


user_actions = []

def setup_logging():
    log_dir = os.path.join(SteamClipApp.CONFIG_DIR, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_dir, f"{timestamp}.log")
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s'
    )

def logger(action, exc_info=None):
    user_actions.append(action)
    if exc_info:
        logging.error(f"Exception occurred: {action}", exc_info=exc_info)

def detect_available_encoders():
    """Detect which GPU encoders are available via ffmpeg"""
    available = ['copy']  # Always available
    try:
        ffmpeg_path = iio.get_ffmpeg_exe()
        result = subprocess.run(
            [ffmpeg_path, '-encoders'],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
        )
        encoders_output = result.stdout

        # Check for NVIDIA NVENC
        if 'hevc_nvenc' in encoders_output:
            available.append('nvenc')
            logger("GPU encoder detected: NVIDIA NVENC")

        # Check for AMD AMF
        if 'hevc_amf' in encoders_output:
            available.append('amf')
            logger("GPU encoder detected: AMD AMF")

        # Check for Intel QuickSync
        if 'hevc_qsv' in encoders_output:
            available.append('qsv')
            logger("GPU encoder detected: Intel QSV")

        # Software encoder always available
        if 'libx265' in encoders_output:
            available.append('software')

    except Exception as exc:
        logger(f"Error detecting GPU encoders: {exc}")

    return available


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
            windows_release = 11 if sys.getwindowsversion().build >= 22000 else platform.release()  # fix win11 detection
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

    with open(log_file, "w") as f:
        f.write("SteamClip Crash Log:\n")
        for action in user_actions:
            f.write(f"- {action}\n")
        f.write("\nError Details:\n")
        # noinspection PyTypeChecker
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
        f.write(system_info)
    QMessageBox.critical(None, "Critical Error",
        f"An unexpected error occurred:\n{exc_value}\n\n"
        "A crash report has been saved to:\n"
        f"{log_file}")


class ExportWorker(QThread):
    """Parallel background worker for exporting clips without freezing UI"""
    progress = pyqtSignal(int, int, str)  # completed_clips, total_clips, status_text
    finished_signal = pyqtSignal(bool, str)  # success, message
    clip_started = pyqtSignal(str, str)  # clip_name, encoding_mode
    active_jobs_changed = pyqtSignal(int)  # current number of active jobs

    def __init__(self, clip_list, output_dir, encoding_mode, delete_after=False, max_workers=1):
        super().__init__()
        self.clip_list = list(clip_list)
        self.output_dir = output_dir
        self.encoding_mode = encoding_mode
        self.delete_after = delete_after
        self._cancelled = False
        self._max_workers = max_workers
        self._lock = threading.Lock()
        self._active_jobs = 0
        self._completed = 0
        self._errors = 0
        self._filename_lock = threading.Lock()
        self.game_ids = {}

    def cancel(self):
        self._cancelled = True

    def set_max_workers(self, count):
        """Dynamically adjust max workers (takes effect for new jobs)"""
        self._max_workers = max(1, min(count, 16))  # Clamp between 1-16

    def get_max_workers(self):
        return self._max_workers

    def get_game_name(self, game_id):
        if game_id in self.game_ids:
            return self.game_ids[game_id]
        return game_id

    def _export_single_clip(self, clip_folder):
        """Export a single clip - runs in thread pool"""
        if self._cancelled:
            return False

        with self._lock:
            self._active_jobs += 1
        self.active_jobs_changed.emit(self._active_jobs)

        ffmpeg_path = iio.get_ffmpeg_exe()
        temp_video_paths = []
        temp_audio_paths = []
        concatenated_video = None
        concatenated_audio = None
        video_list_file = None
        audio_list_file = None
        success = False

        try:
            folder_basename = os.path.basename(clip_folder)
            parts = folder_basename.split('_')
            game_id = parts[1] if len(parts) > 1 else "Unknown"
            game_name = self.get_game_name(game_id)

            encoding_name = ENCODING_MODES.get(self.encoding_mode, ENCODING_MODES['copy'])['name']
            self.clip_started.emit(game_name, encoding_name)

            session_mpd_files = []
            for root, _, files in os.walk(clip_folder):
                if 'session.mpd' in files:
                    session_mpd_files.append(os.path.join(root, 'session.mpd'))

            if not session_mpd_files:
                raise FileNotFoundError("No session.mpd files found")

            for session_mpd in session_mpd_files:
                if self._cancelled:
                    break
                data_dir = os.path.dirname(session_mpd)
                init_video = os.path.join(data_dir, 'init-stream0.m4s')
                init_audio = os.path.join(data_dir, 'init-stream1.m4s')

                if not (os.path.exists(init_video) and os.path.exists(init_audio)):
                    raise FileNotFoundError("Initialization files missing")

                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_video:
                    with open(init_video, 'rb') as f:
                        tmp_video.write(f.read())
                    for chunk in sorted(glob.glob(os.path.join(data_dir, 'chunk-stream0-*.m4s'))):
                        with open(chunk, 'rb') as f:
                            tmp_video.write(f.read())
                    temp_video_paths.append(tmp_video.name)

                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_audio:
                    with open(init_audio, 'rb') as f:
                        tmp_audio.write(f.read())
                    for chunk in sorted(glob.glob(os.path.join(data_dir, 'chunk-stream1-*.m4s'))):
                        with open(chunk, 'rb') as f:
                            tmp_audio.write(f.read())
                    temp_audio_paths.append(tmp_audio.name)

            if self._cancelled:
                return False

            # Use unique temp file names with thread id
            thread_id = threading.get_ident()
            concatenated_video = os.path.join(tempfile.gettempdir(), f"concat_video_{thread_id}_{hash(clip_folder)}.mp4")
            concatenated_audio = os.path.join(tempfile.gettempdir(), f"concat_audio_{thread_id}_{hash(clip_folder)}.mp4")
            video_list_file = os.path.join(tempfile.gettempdir(), f"video_list_{thread_id}_{hash(clip_folder)}.txt")
            audio_list_file = os.path.join(tempfile.gettempdir(), f"audio_list_{thread_id}_{hash(clip_folder)}.txt")

            with open(video_list_file, 'w') as f:
                for temp_video in temp_video_paths:
                    f.write(f"file '{temp_video}'\n")

            with open(audio_list_file, 'w') as f:
                for temp_audio in temp_audio_paths:
                    f.write(f"file '{temp_audio}'\n")

            subprocess.run([
                ffmpeg_path, '-y',
                '-f', 'concat', '-safe', '0',
                '-i', video_list_file,
                '-c', 'copy', '-movflags', '+faststart',
                '-max_muxing_queue_size', '1024',
                concatenated_video
            ], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)

            if self._cancelled:
                return False

            subprocess.run([
                ffmpeg_path, '-y',
                '-f', 'concat', '-safe', '0',
                '-i', audio_list_file,
                '-c', 'copy',
                concatenated_audio
            ], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)

            if self._cancelled:
                return False

            # Get timestamp from folder modification time
            try:
                folder_mtime = os.path.getmtime(clip_folder)
                dt_obj = datetime.fromtimestamp(folder_mtime)
                # Format: "Game Name YYYY.MM.DD - HH.MM.SS.00.DVR"
                formatted_date = dt_obj.strftime("%Y.%m.%d - %H.%M.%S")
                formatted_date += f".{int(dt_obj.microsecond / 10000):02d}"  # centiseconds
            except Exception:
                formatted_date = datetime.now().strftime("%Y.%m.%d - %H.%M.%S.00")

            base_filename = f"{game_name} {formatted_date}.DVR"
            with self._filename_lock:
                output_file = self._get_unique_filename(self.output_dir, f"{base_filename}.mp4")

            encoding_args = ENCODING_MODES.get(self.encoding_mode, ENCODING_MODES['copy'])['args']
            mux_cmd = [ffmpeg_path, '-y', '-i', concatenated_video, '-i', concatenated_audio] + encoding_args + [output_file]

            subprocess.run(mux_cmd, check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)

            if self.delete_after:
                try:
                    shutil.rmtree(clip_folder)
                    logger(f"Deleted source clip folder: {clip_folder}")
                except Exception as del_exc:
                    logger(f"Failed to delete clip folder {clip_folder}: {str(del_exc)}")

            success = True
            logger(f"Successfully exported: {game_name}")

        except Exception as exc:
            logger(f"Error processing clip {clip_folder}: {str(exc)}", exc_info=exc)

        finally:
            # Cleanup temp files
            for temp_file in temp_video_paths + temp_audio_paths:
                try:
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                except Exception:
                    pass
            for f in [concatenated_video, concatenated_audio, video_list_file, audio_list_file]:
                try:
                    if f and os.path.exists(f):
                        os.unlink(f)
                except Exception:
                    pass

            with self._lock:
                self._active_jobs -= 1
                if success:
                    self._completed += 1
                else:
                    self._errors += 1
            self.active_jobs_changed.emit(self._active_jobs)

        return success

    def run(self):
        total_clips = len(self.clip_list)
        clip_queue = list(self.clip_list)

        try:
            # Dynamic executor - we'll manually manage submission based on current max_workers
            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = {}
                submitted = 0

                while (submitted < total_clips or futures) and not self._cancelled:
                    # Submit new jobs up to current max_workers limit
                    while submitted < total_clips and len(futures) < self._max_workers:
                        if self._cancelled:
                            break
                        clip = clip_queue[submitted]
                        future = executor.submit(self._export_single_clip, clip)
                        futures[future] = clip
                        submitted += 1

                    # Check for completed futures
                    completed_futures = []
                    for future in list(futures.keys()):
                        if future.done():
                            completed_futures.append(future)

                    for future in completed_futures:
                        del futures[future]

                    # Update progress
                    self.progress.emit(self._completed, total_clips,
                        f"{self._active_jobs} active, {self._completed}/{total_clips} done")

                    # Small sleep to prevent busy loop
                    if futures:
                        self.msleep(100)

                # Wait for remaining futures if cancelled
                if self._cancelled:
                    # Let current jobs finish
                    for future in futures:
                        try:
                            future.result(timeout=60)
                        except Exception:
                            pass

            if self._cancelled:
                self.finished_signal.emit(False, f"Export cancelled. {self._completed}/{total_clips} clips processed.")
            elif self._errors > 0:
                self.finished_signal.emit(False, f"Completed with {self._errors} error(s). {self._completed}/{total_clips} exported.")
            else:
                self.finished_signal.emit(True, f"Successfully exported {self._completed} clip(s)")

        except Exception as exc:
            self.finished_signal.emit(False, f"Export failed: {str(exc)}")

    @staticmethod
    def _get_unique_filename(directory, filename):
        base_name, ext = os.path.splitext(filename)
        counter = 1
        unique_filename = os.path.join(directory, filename)
        while os.path.exists(unique_filename):
            unique_filename = os.path.join(directory, f"{base_name}_{counter}{ext}")
            counter += 1
        return unique_filename


class ThumbnailFrame(QFrame):
    def __init__(self, parent=None):
        super(ThumbnailFrame, self).__init__(parent)
        self.folder = None  # This is set in add_thumbnail_to_grid


class SteamClipApp(QWidget):
    CONFIG_DIR = CONFIG_PATH
    CONFIG_FILE = os.path.join(CONFIG_DIR, 'SteamClip.conf')
    GAME_IDS_FILE = os.path.join(CONFIG_DIR, 'GameIDs.json')
    STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
    CURRENT_VERSION = "v3.0"

    def __init__(self):
        super().__init__()
        self.cleanup_temp_files()
        logger("Application started")
        self.setWindowIcon(QIcon('SteamClip.ico'))
        self.setWindowTitle("SteamClip")
        self.setGeometry(100, 100, 1000, 720)
        self._is_cancelled = False
        self.clip_index = 0
        self.clip_folders = []
        self.original_clip_folders = []
        self.game_ids = {}
        self._custom_record_cache = {}
        self.config = self.load_config()
        self.default_dir = self.config.get('userdata_path')
        self.export_dir = self.config.get('export_path', os.path.expanduser("~/Desktop"))
        self.system_recordings_path = self.config.get('system_recordings_path')
        self.encoding_mode = self.config.get('encoding_mode', 'copy')
        self.available_encoders = detect_available_encoders()
        self.prev_steamid = None
        self.prev_media_type = None
        self.wait_message = None
        self.settings_window = None
        first_run = not os.path.exists(self.CONFIG_FILE)

        if not self.default_dir:
            self.default_dir = self.prompt_steam_version_selection()
            if not self.default_dir:
                QMessageBox.critical(self, "Critical Error", "Failed to locate Steam userdata directory. Exiting.")
                sys.exit(1)

        self.save_config(self.default_dir, self.export_dir, self.system_recordings_path, self.encoding_mode)
        self.load_game_ids()

        # Main layout
        self.main_layout = QVBoxLayout()
        self.main_layout.setSpacing(15)
        self.main_layout.setContentsMargins(20, 20, 20, 20)

        # Header with title and settings
        header_layout = QHBoxLayout()
        title_label = QLabel("Steam Clip Converter")
        title_label.setObjectName("titleLabel")
        self.settings_button = QPushButton("Settings")
        self.settings_button.setObjectName("navButton")
        self.settings_button.clicked.connect(self.open_settings)
        self.settings_button.setFixedWidth(80)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.settings_button)
        self.main_layout.addLayout(header_layout)

        # Filter section with labels
        filter_frame = QFrame()
        filter_frame.setObjectName("filterFrame")
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setSpacing(20)

        # Account filter
        account_layout = QVBoxLayout()
        account_label = QLabel("ACCOUNT")
        account_label.setObjectName("sectionLabel")
        self.steamid_combo = QComboBox()
        self.steamid_combo.setFixedSize(200, 36)
        self.steamid_combo.currentIndexChanged.connect(self.on_steamid_selected)
        account_layout.addWidget(account_label)
        account_layout.addWidget(self.steamid_combo)
        filter_layout.addLayout(account_layout)

        # Game filter
        game_layout = QVBoxLayout()
        game_label = QLabel("GAME")
        game_label.setObjectName("sectionLabel")
        self.gameid_combo = QComboBox()
        self.gameid_combo.setFixedSize(200, 36)
        self.gameid_combo.currentIndexChanged.connect(self.filter_clips_by_gameid)
        game_layout.addWidget(game_label)
        game_layout.addWidget(self.gameid_combo)
        filter_layout.addLayout(game_layout)

        # Type filter
        type_layout = QVBoxLayout()
        type_label = QLabel("CLIP TYPE")
        type_label.setObjectName("sectionLabel")
        self.media_type_combo = QComboBox()
        self.media_type_combo.setFixedSize(180, 36)
        self.media_type_combo.addItems(["All Clips", "Manual Clips", "Background Clips"])
        self.media_type_combo.setCurrentIndex(0)
        self.media_type_combo.currentIndexChanged.connect(self.filter_media_type)
        type_layout.addWidget(type_label)
        type_layout.addWidget(self.media_type_combo)
        filter_layout.addLayout(type_layout)

        filter_layout.addStretch()
        self.main_layout.addWidget(filter_frame)

        # Clip grid area with scroll
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #181825; }")

        self.clip_frame = QFrame()
        self.clip_frame.setObjectName("clipFrame")
        self.clip_grid = QGridLayout()
        self.clip_grid.setSpacing(10)
        self.clip_frame.setLayout(self.clip_grid)

        self.scroll_area.setWidget(self.clip_frame)
        self.scroll_area.setMinimumHeight(400)
        self.main_layout.addWidget(self.scroll_area)

        # Status bar
        self.status_label = QLabel("Select clips to convert")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.status_label)

        # Progress section (hidden by default)
        self.progress_frame = QFrame()
        self.progress_frame.setObjectName("progressFrame")
        self.progress_frame.setVisible(False)
        progress_layout = QVBoxLayout(self.progress_frame)
        progress_layout.setContentsMargins(15, 10, 15, 10)
        progress_layout.setSpacing(8)

        # Progress header with clip info
        progress_header = QHBoxLayout()
        self.progress_clip_label = QLabel("Processing...")
        self.progress_clip_label.setStyleSheet("font-weight: bold; color: #89b4fa;")
        self.progress_count_label = QLabel("0 / 0")
        self.progress_count_label.setStyleSheet("color: #a6adc8;")
        progress_header.addWidget(self.progress_clip_label)
        progress_header.addStretch()
        progress_header.addWidget(self.progress_count_label)
        progress_layout.addLayout(progress_header)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.progress_bar)

        # Progress details row
        progress_details = QHBoxLayout()
        self.progress_status_label = QLabel("Starting...")
        self.progress_status_label.setStyleSheet("font-size: 12px; color: #6c7086;")
        self.progress_encoding_label = QLabel("")
        self.progress_encoding_label.setStyleSheet("font-size: 12px; color: #a6e3a1;")
        progress_details.addWidget(self.progress_status_label)
        progress_details.addStretch()
        progress_details.addWidget(self.progress_encoding_label)
        progress_layout.addLayout(progress_details)

        # Concurrent exports control row
        concurrent_layout = QHBoxLayout()
        concurrent_label = QLabel("Simultaneous Exports:")
        concurrent_label.setStyleSheet("font-size: 12px; color: #cdd6f4;")
        concurrent_layout.addWidget(concurrent_label)

        self.concurrent_minus_btn = QPushButton("-")
        self.concurrent_minus_btn.setFixedSize(30, 30)
        self.concurrent_minus_btn.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.concurrent_minus_btn.clicked.connect(self.decrease_concurrent)
        concurrent_layout.addWidget(self.concurrent_minus_btn)

        self.concurrent_count_label = QLabel("1")
        self.concurrent_count_label.setFixedWidth(30)
        self.concurrent_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.concurrent_count_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #89b4fa;")
        concurrent_layout.addWidget(self.concurrent_count_label)

        self.concurrent_plus_btn = QPushButton("+")
        self.concurrent_plus_btn.setFixedSize(30, 30)
        self.concurrent_plus_btn.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.concurrent_plus_btn.clicked.connect(self.increase_concurrent)
        concurrent_layout.addWidget(self.concurrent_plus_btn)

        self.active_jobs_label = QLabel("(0 active)")
        self.active_jobs_label.setStyleSheet("font-size: 11px; color: #6c7086;")
        concurrent_layout.addWidget(self.active_jobs_label)

        concurrent_layout.addStretch()

        # Cancel button on the same row
        self.cancel_export_button = QPushButton("Cancel Export")
        self.cancel_export_button.setObjectName("dangerButton")
        self.cancel_export_button.clicked.connect(self.cancel_export)
        self.cancel_export_button.setFixedWidth(120)
        concurrent_layout.addWidget(self.cancel_export_button)

        progress_layout.addLayout(concurrent_layout)

        # Default concurrent count
        self._concurrent_count = 1

        self.main_layout.addWidget(self.progress_frame)

        # Worker reference
        self.export_worker = None

        # Selection row
        nav_layout = QHBoxLayout()
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.clicked.connect(self.select_all_filtered)
        self.clear_selection_button = QPushButton("Clear Selection")
        self.clear_selection_button.clicked.connect(self.clear_selection)
        self.clear_selection_button.setEnabled(False)
        nav_layout.addWidget(self.select_all_button)
        nav_layout.addWidget(self.clear_selection_button)
        nav_layout.addStretch()
        self.main_layout.addLayout(nav_layout)

        # Action buttons row
        action_layout = QHBoxLayout()
        action_layout.setSpacing(12)

        self.export_all_button = QPushButton("Export All Clips")
        self.export_all_button.clicked.connect(self.export_all)

        self.convert_button = QPushButton("Convert Selected")
        self.convert_button.setObjectName("primaryButton")
        self.convert_button.clicked.connect(self.convert_clip)
        self.convert_button.setEnabled(False)

        self.convert_delete_button = QPushButton("Convert && Delete")
        self.convert_delete_button.setObjectName("dangerButton")
        self.convert_delete_button.clicked.connect(self.convert_and_delete_clip)
        self.convert_delete_button.setEnabled(False)

        action_layout.addWidget(self.export_all_button)
        action_layout.addStretch()
        action_layout.addWidget(self.convert_button)
        action_layout.addWidget(self.convert_delete_button)

        if DEBUG:
            self.debug_button = QPushButton("Debug Crash")
            self.debug_button.clicked.connect(self.debug_crash)
            action_layout.addWidget(self.debug_button)

        self.main_layout.addLayout(action_layout)

        self.setLayout(self.main_layout)

        self.selected_clips = set()
        self.del_invalid_clips()
        self.populate_steamid_dirs()
        # self.perform_update_check()  # Disabled temporarily

        if first_run:
            QMessageBox.information(self, "INFO",
                "Clips will be saved on the Desktop. You can change the export path in the settings.")

    def cleanup_temp_files(self):
        temp_files = glob.glob(os.path.join(self.CONFIG_DIR, "steamclip_new*"))
        if IS_WINDOWS:  # cleanup the batch script
            temp_files += [os.path.join(self.CONFIG_DIR, "update.bat")]
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    logging.info(f"Cleaned up temp file: {temp_file}")
            except Exception as exc:
                logging.error(f"Error cleaning temp file {temp_file}: {str(exc)}")

    def load_config(self):
        config = {'userdata_path': None, 'export_path': os.path.expanduser("~/Desktop"), 'system_recordings_path': None, 'encoding_mode': 'copy'}
        if os.path.exists(self.CONFIG_FILE):
            logger(f"Loaded configuration")
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
                            config['userdata_path'] = value
                        elif key == 'export_path':
                            config['export_path'] = value
                        elif key == 'system_recordings_path':
                            config['system_recordings_path'] = value if value else None
                        elif key == 'encoding_mode':
                            config['encoding_mode'] = value if value in ENCODING_MODES else 'copy'
                    else:
                        logger(f"Malformed config line (missing '='): {line}")
        return config

    def save_config(self, userdata_path=None, export_path=None, system_recordings_path=None, encoding_mode=None):
        logger(f"Saving configuration: userdata={userdata_path}, export={export_path}, system_recordings={system_recordings_path}, encoding={encoding_mode}")
        config = {}
        if userdata_path:
            config['userdata_path'] = userdata_path
        config['export_path'] = export_path or os.path.expanduser("~/Desktop")
        if system_recordings_path:
            config['system_recordings_path'] = system_recordings_path
        config['encoding_mode'] = encoding_mode or 'copy'
        with open(self.CONFIG_FILE, 'w') as f:
            for key, value in config.items():
                f.write(f"{key}={value}\n")

    def moveEvent(self, event):
        super().moveEvent(event)
        for combo_box in [self.steamid_combo, self.gameid_combo, self.media_type_combo]:
            if combo_box.view().isVisible():
                combo_box.hidePopup()

    def perform_update_check(self, show_message=True):
        release_info = self.get_latest_release_from_github()
        if not release_info:
            return None
        latest_version = release_info['version']
        if latest_version != self.CURRENT_VERSION and show_message:
            self.prompt_update(latest_version, release_info['changelog'])
        return release_info

    def download_update(self, latest_release):
        logger(f"Update download initiated for version {latest_release}")
        self.wait_message = QDialog(self)
        self.wait_message.setWindowTitle("Updating SteamClip")
        self.wait_message.setFixedSize(400, 120)
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_label = QLabel("Downloading update... 0.0%")
        progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(progress_label)
        progress_frame = QFrame()
        progress_frame.setFixedSize(300, 30)
        progress_frame.setStyleSheet("background-color: #e0e0e0; border-radius: 5px;")
        progress_inner = QFrame(progress_frame)
        progress_inner.setGeometry(0, 0, 0, 30)
        progress_inner.setStyleSheet("background-color: #4caf50; border-radius: 5px;")
        layout.addWidget(progress_frame)
        cancel_button = QPushButton("Cancel Download")
        cancel_button.clicked.connect(lambda: self.cancel_download(temp_download_path))
        layout.addWidget(cancel_button)
        self.wait_message.setLayout(layout)
        self.wait_message.show()
        self._is_cancelled = False
        download_url = f"https://github.com/Nastas95/SteamClip/releases/download/{latest_release}/{EXECUTABLE_NAME}"
        temp_download_path = os.path.join(self.CONFIG_DIR, EXECUTABLE_NAME.replace('steamclip', 'steamclip_new'))
        current_executable = os.path.abspath(sys.argv[0])
        try:

            with requests.get(download_url, stream=True, timeout=120) as response:
                response.raise_for_status()
                total_size = int(response.headers.get('content-length', 0))
                downloaded_size = 0
                with open(temp_download_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._is_cancelled:
                            break
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if total_size > 0:
                                percentage = (downloaded_size / total_size) * 100
                                progress_label.setText(f"Downloading update... {percentage:.1f}%")
                                progress_width = int(300 * (percentage / 100))
                                progress_inner.setFixedWidth(progress_width)
                            QApplication.processEvents()
                            if self.wait_message.isHidden():
                                self.cancel_download(temp_download_path)
                                return

            if IS_WINDOWS:
                batch_script = os.path.join(self.CONFIG_DIR, "update.bat")
                with open(batch_script, "w") as bat:
                    bat.write(UPDATE_BATCH_SCRIPT % {'current_executable': current_executable,
                                                     'temp_download_path': temp_download_path,
                                                     'executable_name': os.path.basename(current_executable)})
                subprocess.Popen([batch_script], shell=True)
            else:
                os.replace(temp_download_path, current_executable)
                self.wait_message.close()

            sys.exit(0)
        except Exception as exc:
            self.wait_message.close()
            if os.path.exists(temp_download_path):
                os.remove(temp_download_path)
            QMessageBox.critical(self, "Update Failed", f"Failed to update SteamClip: {exc}")

    def cancel_download(self, temp_download_path):
        if hasattr(self, '_is_cancelled') and self._is_cancelled:
            return
        self._is_cancelled = True
        if os.path.exists(temp_download_path):
            os.remove(temp_download_path)
        if self.wait_message is not None:
            self.wait_message.close()
        QMessageBox.information(self, "Download Cancelled", "The update has been cancelled.")
        logger("Update download cancelled by user")

    @staticmethod
    def get_latest_release_from_github():
        url = "https://api.github.com/repos/Nastas95/SteamClip/releases/latest"
        try:
            response = requests.get(url)
            response.raise_for_status()
            release_data = response.json()
            return {
                'version': release_data['tag_name'],
                'changelog': release_data.get('body', 'No changelog available')
            }
        except requests.exceptions.RequestException as exc:
            logger(f"Error fetching release info: {exc}")
            return None

    def prompt_update(self, latest_version, changelog):
        message_box = QMessageBox(QMessageBox.Icon.Question, "Update Available",
                                f"A new update ({latest_version}) is available. Update now?")
        update_button = message_box.addButton("Update", QMessageBox.ButtonRole.AcceptRole)
        changelog_button = message_box.addButton("View Changelog", QMessageBox.ButtonRole.ActionRole)
        cancel_button = message_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        message_box.exec()
        if message_box.clickedButton() == update_button:
            self.download_update(latest_version)
        elif message_box.clickedButton() == changelog_button:
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
        update_button = QPushButton("Update Now")
        update_button.clicked.connect(lambda: (dialog.close(), self.download_update(latest_version)))
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        button_layout.addWidget(update_button)
        button_layout.addWidget(close_button)
        layout.addWidget(text_edit)
        layout.addLayout(button_layout)
        dialog.setLayout(layout)
        dialog.exec()

    def check_and_load_userdata_folder(self):
        if not os.path.exists(self.CONFIG_FILE):
            return self.prompt_steam_version_selection()
        with open(self.CONFIG_FILE, 'r') as f:
            userdata_path = f.read().strip()
        return userdata_path if os.path.isdir(userdata_path) else self.prompt_steam_version_selection()

    def prompt_steam_version_selection(self):
        dialog = SteamVersionSelectionDialog(self)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            selected_option = dialog.get_selected_option()
            if selected_option == "Standard":
                if IS_WINDOWS:
                    userdata_path = "C:/Program Files (x86)/Steam/userdata"
                else:
                    userdata_path = "~/.local/share/Steam/userdata"
                userdata_path = os.path.expanduser(userdata_path)
            elif selected_option == "Flatpak":
               userdata_path = os.path.expanduser("~/.var/app/com.valvesoftware.Steam/data/Steam/userdata")
            elif os.path.isdir(selected_option):
                userdata_path = selected_option
            else:
                continue
            if os.path.isdir(userdata_path):
                self.save_default_directory(userdata_path)
                return userdata_path
            else:
                QMessageBox.warning(self, "Invalid Directory", "The selected directory is not valid. Please select again.")
        return None

    def save_default_directory(self, directory):
        os.makedirs(self.CONFIG_DIR, exist_ok=True)
        if not IS_WINDOWS:
            tmp_dir = os.path.join(self.CONFIG_DIR, 'tmp')
            os.makedirs(tmp_dir, exist_ok=True)
        with open(self.CONFIG_FILE, 'w') as f:
            f.write(directory)

    def load_game_ids(self):
        if not os.path.exists(self.GAME_IDS_FILE):
            QMessageBox.information(self, "Info", "SteamClip will now download the GameID database. Please, be patient.")
            self.game_ids = {}
        else:
            with open(self.GAME_IDS_FILE, 'r') as f:
                self.game_ids = json.load(f)

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
            logger("No custom record path found - localconfig.vdf not found")
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
            logger("No custom record path found - BackgroundRecordPath not set")
            self._custom_record_cache[userdata_dir] = None
            return None
        except Exception as exc:
            logger(f"Error reading custom record path: {str(exc)}")
            self._custom_record_cache[userdata_dir] = None
            return None

    def del_invalid_clips(self):
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
        # Also check system recordings path
        if self.system_recordings_path and os.path.isdir(self.system_recordings_path):
            for subdir in ['clips', 'video']:
                sys_dir = os.path.join(self.system_recordings_path, subdir)
                if os.path.isdir(sys_dir):
                    for folder_entry in os.scandir(sys_dir):
                        if folder_entry.is_dir() and "_" in folder_entry.name:
                            folder_path = folder_entry.path
                            if not self.find_session_mpd(folder_path):
                                invalid_folders.append(folder_path)
        if invalid_folders:
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

    def filter_media_type(self):
        selected_media_type = self.media_type_combo.currentText()
        if selected_media_type != self.prev_media_type:
            logger(f"Selected media type: {selected_media_type}")
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
        # Include system recordings path if configured
        if self.system_recordings_path and os.path.isdir(self.system_recordings_path):
            sys_clips = os.path.join(self.system_recordings_path, 'clips')
            sys_video = os.path.join(self.system_recordings_path, 'video')
            if os.path.isdir(sys_clips):
                clip_folders.extend(folder.path for folder in os.scandir(sys_clips) if folder.is_dir() and "_" in folder.name)
            if os.path.isdir(sys_video):
                video_folders.extend(folder.path for folder in os.scandir(sys_video) if folder.is_dir() and "_" in folder.name)
        if selected_media_type == "All Clips":
            self.clip_folders = clip_folders + video_folders
        elif selected_media_type == "Manual Clips":
            self.clip_folders = clip_folders
        elif selected_media_type == "Background Recordings":
            self.clip_folders = video_folders
        self.clip_folders = sorted(self.clip_folders, key=lambda x: self.extract_datetime_from_folder_name(x), reverse=True)
        self.original_clip_folders = list(self.clip_folders)
        self.populate_gameid_combo()
        self.display_clips()

    def on_steamid_selected(self):
        selected_steamid = self.steamid_combo.currentText()
        if selected_steamid != self.prev_steamid:
            logger(f"Selected SteamID: {selected_steamid}")
            self.prev_steamid = selected_steamid
        self.filter_media_type()

    def clear_clip_grid(self):
        for i in range(self.clip_grid.count()):
            widget = self.clip_grid.itemAt(i).widget()
            if widget:
                widget.deleteLater()

    def clear_selection(self):
        logger("Cleared selection of clips")
        self.selected_clips.clear()
        for i in range(self.clip_grid.count()):
            widget = self.clip_grid.itemAt(i).widget()
            if widget and hasattr(widget, 'folder'):
                widget.setStyleSheet("border: none; border-radius: 6px; background-color: #181825;")
        self.convert_button.setEnabled(False)
        self.convert_delete_button.setEnabled(False)
        self.clear_selection_button.setEnabled(False)
        self.update_status_bar()

    def select_all_filtered(self):
        """Select all clips in current filter"""
        logger("Selecting all filtered clips")
        # Add all clip folders to selected_clips
        for folder in self.clip_folders:
            if self.find_session_mpd(folder):
                self.selected_clips.add(folder)
        # Update visual styling for all displayed clips
        for i in range(self.clip_grid.count()):
            widget = self.clip_grid.itemAt(i).widget()
            if widget and hasattr(widget, 'folder'):
                widget.setStyleSheet("border: 3px solid #89b4fa; border-radius: 6px;")
        # Enable buttons
        self.convert_button.setEnabled(bool(self.selected_clips))
        self.convert_delete_button.setEnabled(bool(self.selected_clips))
        self.clear_selection_button.setEnabled(bool(self.selected_clips))
        self.update_status_bar()

    def update_status_bar(self):
        count = len(self.selected_clips)
        total = len(self.clip_folders)
        if count == 0:
            self.status_label.setText(f"{total} clips available - Click to select")
        elif count == 1:
            self.status_label.setText(f"1 clip selected")
        else:
            self.status_label.setText(f"{count} clips selected")

    def populate_steamid_dirs(self):
        if not os.path.isdir(self.default_dir):
            self.show_error("Default Steam userdata directory not found.")
            return
        self.steamid_combo.clear()
        steamid_found = False
        for entry in os.scandir(self.default_dir):
            if entry.is_dir() and entry.name.isdigit():
                clips_dir = os.path.join(self.default_dir, entry.name, 'gamerecordings', 'clips')
                video_dir = os.path.join(self.default_dir, entry.name, 'gamerecordings', 'video')
                if os.path.isdir(clips_dir) or os.path.isdir(video_dir):
                    self.steamid_combo.addItem(entry.name)
                    steamid_found = True
        if not steamid_found:
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
        game_ids_in_clips = {folder.split('_')[1] for folder in self.clip_folders}
        sorted_game_ids = sorted(game_ids_in_clips)
        self.gameid_combo.clear()
        self.gameid_combo.addItem("All Games")
        for game_id in sorted_game_ids:
            self.gameid_combo.addItem(self.get_game_name(game_id), game_id)

    # noinspection PyTypeChecker
    def save_game_ids(self):
        with open(self.GAME_IDS_FILE, 'w') as f_obj:
            json.dump(self.game_ids, f_obj, indent=4)

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
            logger(f"Selected Game: {game_name} (ID: {selected_game_id})")
            self.clip_folders = [
                folder for folder in self.original_clip_folders
                if f'_{selected_game_id}_' in folder and self.find_session_mpd(folder)
            ]
        self.clip_index = 0
        self.display_clips()

    def display_clips(self):
        self.clear_clip_grid()
        valid_clip_folders = [
            folder for folder in self.clip_folders
            if self.find_session_mpd(folder)
        ]
        # Display ALL clips in a 4-column grid
        for index, folder in enumerate(valid_clip_folders):
            session_mpd_files = self.find_session_mpd(folder)
            if not session_mpd_files:
                continue
            first_session_mpd = session_mpd_files[0]
            thumbnail_path = os.path.join(folder, 'thumbnail.jpg')
            if first_session_mpd and not os.path.exists(thumbnail_path):
                self.extract_first_frame(first_session_mpd, thumbnail_path)
            if os.path.exists(thumbnail_path):
                self.add_thumbnail_to_grid(thumbnail_path, folder, index)
        # Re-apply selection styling
        for i in range(self.clip_grid.count()):
            widget: Optional[ThumbnailFrame] = self.clip_grid.itemAt(i).widget()
            if widget and hasattr(widget, 'folder') and widget.folder in self.selected_clips:
                widget.setStyleSheet("border: 3px solid #89b4fa; border-radius: 8px;")
        self.export_all_button.setEnabled(bool(self.clip_folders))
        self.update_status_bar()

    # noinspection PyTypeChecker
    def extract_first_frame(self, session_mpd_path, output_thumbnail_path):
        temp_video_path = None
        try:
            ffmpeg_path = iio.get_ffmpeg_exe()
            data_dir = os.path.dirname(session_mpd_path)
            init_video = os.path.join(data_dir, 'init-stream0.m4s')
            chunk_video_pattern = os.path.join(data_dir, 'chunk-stream0-*.m4s')
            chunk_video_list = sorted(glob.glob(chunk_video_pattern))

            if not os.path.exists(init_video) or not chunk_video_list:
                logger(f"Missing video files: {data_dir}")
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
                    logger(f"First Chunk missing: {first_chunk}")
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
                logger(f"Thumbnail extracted: {output_thumbnail_path}")
            else:
                logger(f"FFMPEG Failed to extract: {session_mpd_path}: {result.stderr}")
                self.create_placeholder_thumbnail(output_thumbnail_path)

        except Exception as exc:
            logger(f"Error extracting thumbnail {session_mpd_path}: {exc}", exc_info=True)
            self.create_placeholder_thumbnail(output_thumbnail_path)
        finally:
            if temp_video_path and os.path.exists(temp_video_path):
                try:
                    os.unlink(temp_video_path)
                except OSError as exc:
                    logger(f"Error removing temp files: {temp_video_path}: {exc}")

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
            logging.info(f"Thumbnail placeholder created: {output_path}")
        except Exception as exc:
            logging.error(f"Error creating placeholder thumbnail {output_path}: {exc}")

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
                logger(f"Error parsing {session_mpd_path}: {exc}")
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        return f"{minutes}:{seconds:02d}"

    def add_thumbnail_to_grid(self, thumbnail_path, folder, index):
        # Smaller thumbnails for 4-column layout
        THUMB_WIDTH = 220
        THUMB_HEIGHT = 124

        container = ThumbnailFrame()
        container.setFixedSize(THUMB_WIDTH, THUMB_HEIGHT)
        container.setStyleSheet("border-radius: 6px; background-color: #181825;")
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0, 0, 0, 0)
        container.setLayout(container_layout)
        pixmap = QPixmap(thumbnail_path).scaled(THUMB_WIDTH, THUMB_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio)
        thumbnail_label = QLabel()
        thumbnail_label.setPixmap(pixmap)
        thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumbnail_label.setStyleSheet("border: none;")

        def select_clip_event(_event):
            self.select_clip(folder, container)

        thumbnail_label.mousePressEvent = select_clip_event
        container_layout.addWidget(thumbnail_label)

        duration = self.get_clip_duration(folder)
        duration_label = QLabel(f"{duration}", container)
        duration_label.setStyleSheet("font-size: 11px; color: #cdd6f4; background-color: rgba(30, 30, 46, 200); border-radius: 3px; padding: 2px 4px; border: none;")
        duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        duration_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        duration_label.adjustSize()

        duration_width = duration_label.width()
        duration_height = duration_label.height()
        x = THUMB_WIDTH - duration_width - 8
        y = THUMB_HEIGHT - duration_height - 8
        duration_label.move(x, y)

        container.folder = folder
        # 4-column grid
        self.clip_grid.addWidget(container, index // 4, index % 4)

    def select_clip(self, folder, container):
        if folder in self.selected_clips:
            logger(f"Deselected clip: {folder}")
            self.selected_clips.remove(folder)
            container.setStyleSheet("border: none; border-radius: 8px; background-color: #181825;")
        else:
            logger(f"Selected clip: {folder}")
            self.selected_clips.add(folder)
            container.setStyleSheet("border: 3px solid #89b4fa; border-radius: 8px;")
        self.convert_button.setEnabled(bool(self.selected_clips))
        self.convert_delete_button.setEnabled(bool(self.selected_clips))
        self.clear_selection_button.setEnabled(len(self.selected_clips) >= 1)
        self.update_status_bar()

    def update_navigation_buttons(self):
        self.prev_button.setEnabled(self.clip_index > 0)
        self.next_button.setEnabled(self.clip_index + 6 < len(self.clip_folders))

    def show_previous_clips(self):
        if self.clip_index - 6 >= 0:
            logger("Navigated to previous clips")
            self.clip_index -= 6
            self.display_clips()

    def show_next_clips(self):
        if self.clip_index + 6 < len(self.clip_folders):
            logger("Navigated to next clips")
            self.clip_index += 6
            self.display_clips()

    def update_progress(self, current_clip, total_clips, step, total_steps):
        clip_segment = 100 / total_clips
        step_progress = (step / total_steps) * clip_segment
        total_progress = (current_clip * clip_segment) + step_progress
        self.progress_bar.setValue(int(total_progress))
        QApplication.processEvents()

    def process_clips(self, selected_clips=None, export_all=False, delete_after=False):
        """Start export process in background thread"""
        if self.export_worker and self.export_worker.isRunning():
            self.show_error("Export already in progress")
            return

        if self.export_dir is None or not os.path.isdir(self.export_dir):
            logger(f"Export directory '{self.export_dir}' not found.")
            reply = QMessageBox.critical(
                self,
                "!WARNING!",
                f"Directory '{self.export_dir}' not found.\n"
                "Use Desktop as export directory?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.export_dir = os.path.expanduser("~/Desktop")
                self.save_config(self.default_dir, self.export_dir, self.system_recordings_path, self.encoding_mode)
                QMessageBox.information(self, "Info", f"Export path set to: {self.export_dir}")
                logger("Export Path not found, defaulted to Desktop")
            else:
                QMessageBox.warning(self, "Operation Cancelled", "Export operation has been cancelled.")
                logger("Export Path not found, Export Cancelled")
                return

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
            clip_list = filtered_clips
        else:
            clip_list = list(selected_clips) if selected_clips else []

        if not clip_list:
            self.show_error("No clips to process")
            return

        output_dir = self.export_dir or os.path.expanduser("~/Desktop")

        # Show progress UI
        self.progress_frame.setVisible(True)
        self.progress_bar.setRange(0, len(clip_list))
        self.progress_bar.setValue(0)
        self.progress_clip_label.setText("Starting export...")
        self.progress_count_label.setText(f"0 / {len(clip_list)}")
        self.progress_status_label.setText("Initializing...")
        self.progress_encoding_label.setText(ENCODING_MODES.get(self.encoding_mode, ENCODING_MODES['copy'])['name'])

        # Disable action buttons during export
        self.convert_button.setEnabled(False)
        self.convert_delete_button.setEnabled(False)
        self.export_all_button.setEnabled(False)
        self.select_all_button.setEnabled(False)

        # Create and start worker with concurrent count
        self.export_worker = ExportWorker(clip_list, output_dir, self.encoding_mode, delete_after, self._concurrent_count)
        self.export_worker.game_ids = self.game_ids.copy()
        self.export_worker.progress.connect(self.on_export_progress)
        self.export_worker.clip_started.connect(self.on_clip_started)
        self.export_worker.finished_signal.connect(self.on_export_finished)
        self.export_worker.active_jobs_changed.connect(self.on_active_jobs_changed)
        self.export_worker.start()
        logger(f"Started export of {len(clip_list)} clips with {self._concurrent_count} simultaneous workers")

    def on_export_progress(self, current_clip, total_clips, status_text):
        """Handle progress updates from worker"""
        self.progress_bar.setValue(current_clip)
        self.progress_count_label.setText(f"{current_clip + 1} / {total_clips}")
        self.progress_status_label.setText(status_text)

    def on_clip_started(self, clip_name, encoding_mode):
        """Handle clip started signal"""
        self.progress_clip_label.setText(f"Converting: {clip_name}")
        self.progress_encoding_label.setText(encoding_mode)

    def on_export_finished(self, success, message):
        """Handle export completion"""
        self.progress_frame.setVisible(False)

        # Reset cancel button state
        self.cancel_export_button.setEnabled(True)
        self.cancel_export_button.setText("Cancel Export")
        self.active_jobs_label.setText("(0 active)")

        # Re-enable buttons
        self.convert_button.setEnabled(bool(self.selected_clips))
        self.convert_delete_button.setEnabled(bool(self.selected_clips))
        self.export_all_button.setEnabled(bool(self.clip_folders))
        self.select_all_button.setEnabled(True)

        if success:
            self.selected_clips.clear()
            self.display_clips()
            self.show_info(message)
        else:
            if "cancelled" in message.lower():
                self.show_info(message)
            else:
                self.show_error(message)

        self.export_worker = None
        logger(f"Export finished: {message}")

    def cancel_export(self):
        """Cancel the current export"""
        if self.export_worker and self.export_worker.isRunning():
            self.export_worker.cancel()
            self.cancel_export_button.setEnabled(False)
            self.cancel_export_button.setText("Cancelling...")
            self.progress_status_label.setText("Cancelling... please wait")
            logger("Export cancel requested")

    def increase_concurrent(self):
        """Increase simultaneous export count"""
        if self._concurrent_count < 16:
            self._concurrent_count += 1
            self.concurrent_count_label.setText(str(self._concurrent_count))
            if self.export_worker and self.export_worker.isRunning():
                self.export_worker.set_max_workers(self._concurrent_count)
            logger(f"Concurrent exports increased to {self._concurrent_count}")

    def decrease_concurrent(self):
        """Decrease simultaneous export count"""
        if self._concurrent_count > 1:
            self._concurrent_count -= 1
            self.concurrent_count_label.setText(str(self._concurrent_count))
            if self.export_worker and self.export_worker.isRunning():
                self.export_worker.set_max_workers(self._concurrent_count)
            logger(f"Concurrent exports decreased to {self._concurrent_count}")

    def on_active_jobs_changed(self, count):
        """Update active jobs display"""
        self.active_jobs_label.setText(f"({count} active)")

    def convert_clip(self):
        self.process_clips(selected_clips=self.selected_clips)

    def convert_and_delete_clip(self):
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            "This will convert the selected clip(s) and DELETE the original Steam recordings.\n\n"
            "This action cannot be undone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.process_clips(selected_clips=self.selected_clips, delete_after=True)

    def export_all(self):
        self.process_clips(export_all=True)

    @staticmethod
    def find_session_mpd(clip_folder):
        session_mpd_files = []
        for root, _, files in os.walk(clip_folder):
            if 'session.mpd' in files:
                session_mpd_files.append(os.path.join(root, 'session.mpd'))
        return session_mpd_files

    @staticmethod
    def get_unique_filename(directory, filename):
        base_name, ext = os.path.splitext(filename)
        counter = 1
        unique_filename = os.path.join(directory, filename)
        while os.path.exists(unique_filename):
            logger(f"File already exists: {unique_filename}")
            unique_filename = os.path.join(directory, f"{base_name}_{counter}{ext}")
            counter += 1
        logger(f"Generated unique filename: {unique_filename}")
        return unique_filename

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)

    def show_info(self, message):
        QMessageBox.information(self, "Info", message)

    def open_settings(self):
        if not self.settings_window:
            self.settings_window = SettingsWindow(self)
        self.settings_window.exec()

    @staticmethod
    def debug_crash():
        logger("Debug button pressed - Simulating crash")
        raise Exception("Test crash")


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
            clips_path = os.path.join(folder, steam_id, 'gamerecordings')
            if os.path.isdir(clips_path):
                return True
        return False

    def get_selected_option(self):
        return self.selected_version


class SettingsWindow(QDialog):
    BUTTON_STYLE = "color: #1e1e2e; background-color: #cdd6f4; padding: 10px; border-radius: 6px; font-size: 13px;"
    BUTTON_DANGER = "color: #1e1e2e; background-color: #f38ba8; padding: 10px; border-radius: 6px; font-size: 13px;"

    def __init__(self, parent: SteamClipApp):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(300, 560)
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title = QLabel("Settings")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #89b4fa;")
        layout.addWidget(title)
        self.select_export_button = self.create_button("Export Location", self.select_export_path)
        self.select_system_recordings_button = self.create_button("Recordings Folder", self.select_system_recordings_path)
        self.edit_game_ids_button = self.create_button("Edit Game Names", self.open_edit_game_ids)
        self.update_game_ids_button = self.create_button("Refresh Game Names", self.update_game_ids)
        self.open_config_button = self.create_button("Open Config Folder", self.open_config_folder)
        self.check_for_updates_button = self.create_button("Check for Updates", self.check_for_updates)
        self.delete_config_button = self.create_button("Reset All Settings", self.delete_config_folder, danger=True)
        self.close_settings_button = self.create_button("Close", self.close)
        if DEBUG:
            self.check_for_updates_button.setDisabled(True)
        
        # Paths section
        paths_label = QLabel("PATHS")
        paths_label.setStyleSheet("font-size: 11px; color: #6c7086; font-weight: bold;")
        layout.addWidget(paths_label)
        layout.addWidget(self.select_export_button)
        layout.addWidget(self.select_system_recordings_button)

        layout.addSpacing(10)

        # Encoding section
        encoding_label = QLabel("ENCODING")
        encoding_label.setStyleSheet("font-size: 11px; color: #6c7086; font-weight: bold;")
        layout.addWidget(encoding_label)

        self.encoding_combo = QComboBox()
        self.encoding_combo.setFixedHeight(36)
        # Populate with available encoders
        for mode_key in parent.available_encoders:
            if mode_key in ENCODING_MODES:
                self.encoding_combo.addItem(ENCODING_MODES[mode_key]['name'], mode_key)
        # Set current selection
        current_idx = self.encoding_combo.findData(parent.encoding_mode)
        if current_idx >= 0:
            self.encoding_combo.setCurrentIndex(current_idx)
        self.encoding_combo.currentIndexChanged.connect(self.on_encoding_changed)
        layout.addWidget(self.encoding_combo)

        layout.addSpacing(10)

        # Game names section
        games_label = QLabel("GAME NAMES")
        games_label.setStyleSheet("font-size: 11px; color: #6c7086; font-weight: bold;")
        layout.addWidget(games_label)
        layout.addWidget(self.edit_game_ids_button)
        layout.addWidget(self.update_game_ids_button)
        
        layout.addSpacing(10)
        
        # Other section
        other_label = QLabel("OTHER")
        other_label.setStyleSheet("font-size: 11px; color: #6c7086; font-weight: bold;")
        layout.addWidget(other_label)
        layout.addWidget(self.open_config_button)
        layout.addWidget(self.check_for_updates_button)
        layout.addWidget(self.delete_config_button)
        
        layout.addStretch()
        layout.addWidget(self.close_settings_button)
        
        self.version_label = QLabel(f"v{parent.CURRENT_VERSION}")
        self.version_label.setStyleSheet("font-size: 11px; color: #6c7086;")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.version_label)
        
        self.setLayout(layout)

    def parent(self) -> Optional[SteamClipApp]:  # to silence PyCharm inspection
        return super().parent()

    def select_export_path(self):
        export_path = QFileDialog.getExistingDirectory(self, "Set Export Folder")
        if export_path and os.path.isdir(export_path):
            try:
                test_file = os.path.join(export_path, ".test_write_permission")
                with open(test_file, 'w') as f:
                    f.write("test")
                os.remove(test_file)
                self.parent().export_dir = export_path
                self.parent().save_config(self.parent().default_dir, self.parent().export_dir, self.parent().system_recordings_path, self.parent().encoding_mode)
                QMessageBox.information(self, "Info", f"Export path set to: {export_path}")
                logger(f"Export path changed to: {export_path}")
                return
            except Exception as exc:
                QMessageBox.warning(self, "Invalid Directory", f"The selected directory is not writable: {str(exc)}")
        default_export_path = os.path.expanduser("~/Desktop")
        self.parent().export_dir = default_export_path
        self.parent().save_config(self.parent().default_dir, default_export_path, self.parent().system_recordings_path, self.parent().encoding_mode)
        QMessageBox.warning(self, "Invalid Directory",
                            f"Selected export directory is invalid. Using default: {default_export_path}")

    def select_system_recordings_path(self):
        recordings_path = QFileDialog.getExistingDirectory(self, "Set System Recordings Folder")
        if recordings_path and os.path.isdir(recordings_path):
            clips_dir = os.path.join(recordings_path, 'clips')
            video_dir = os.path.join(recordings_path, 'video')
            if os.path.isdir(clips_dir) or os.path.isdir(video_dir):
                self.parent().system_recordings_path = recordings_path
                self.parent().save_config(
                    self.parent().default_dir,
                    self.parent().export_dir,
                    recordings_path,
                    self.parent().encoding_mode
                )
                QMessageBox.information(self, "Info", f"System recordings path set to: {recordings_path}")
                logger(f"System recordings path changed to: {recordings_path}")
                self.parent().filter_media_type()
            else:
                QMessageBox.warning(self, "Invalid Directory",
                    "The selected directory does not contain 'clips' or 'video' subfolders.\n"
                    "Please select a valid Steam recordings folder.")
        elif recordings_path:
            QMessageBox.warning(self, "Invalid Directory", "The selected directory is not valid.")

    def on_encoding_changed(self, index):
        mode_key = self.encoding_combo.itemData(index)
        if mode_key:
            self.parent().encoding_mode = mode_key
            self.parent().save_config(
                self.parent().default_dir,
                self.parent().export_dir,
                self.parent().system_recordings_path,
                mode_key
            )
            logger(f"Encoding mode changed to: {mode_key}")

    def create_button(self, text, slot, size=None, danger=False):
        button = QPushButton(text)
        button.clicked.connect(slot)
        button.setStyleSheet(self.BUTTON_DANGER if danger else self.BUTTON_STYLE)
        if size:
            button.setFixedSize(*size)
        return button

    def check_for_updates(self):
        logger(f"User Check for Update")
        release_info = self.parent().perform_update_check(show_message=False)
        if release_info is None:
            QMessageBox.critical(self, "Error", "Failed to fetch the latest release information.")
            logger(f"Update Check Failed")
            return
        if release_info['version'] == self.parent().CURRENT_VERSION:
            QMessageBox.information(self, "No Updates Available", "You are already using the latest version of SteamClip.")
            logger(f"Latest Version Already installed")
        else:
            self.parent().prompt_update(release_info['version'], release_info['changelog'])
            logger(f"Manual Update Cancelled")

    def open_edit_game_ids(self):
        edit_window = EditGameIDWindow(self.parent())
        edit_window.exec()

    @staticmethod
    def open_config_folder():
        config_folder = SteamClipApp.CONFIG_DIR
        os.makedirs(config_folder, exist_ok=True)
        if sys.platform.startswith('linux'):
            subprocess.run(['xdg-open', config_folder])
        elif sys.platform == 'darwin':
            subprocess.run(['open', config_folder])
        elif sys.platform == 'win32':
            subprocess.run(['explorer', os.path.normpath(config_folder)])

    def update_game_ids(self):
        try:
            if not self.parent().is_connected():
                return QMessageBox.warning(self, "Warning", "No internet connection")

            game_ids = {folder.split('_')[1] for folder in self.parent().original_clip_folders}
            updated = False

            for game_id in game_ids:
                if game_id not in self.parent().game_ids:
                    try:
                        name = self.parent().fetch_game_name_from_steam(game_id)
                        if name:
                            self.parent().game_ids[game_id] = name
                            updated = True
                    except Exception as exc:
                        logging.error(f"Failed to fetch name for {game_id}: {exc}")

            if updated:
                self.parent().save_game_ids()
                self.parent().populate_gameid_combo()
                QMessageBox.information(self, "Success", "Game ID database updated")
            else:
                QMessageBox.information(self, "Info", "No updates needed")

        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Update failed: {str(exc)}")

    def delete_config_folder(self):
        logger("Config folder deletion requested")
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete the entire configuration folder?\n\n{SteamClipApp.CONFIG_DIR}\n\nThis action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                shutil.rmtree(SteamClipApp.CONFIG_DIR)
                QMessageBox.information(self, "Deletion Complete", "Configuration folder has been deleted.\nThe application will now close.")
                QApplication.quit()
            except Exception as exc:
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

    def parent(self) -> Optional[SteamClipApp]:  # to silence PyCharm inspection
        return super().parent()

    def save_changes(self):
        updated_game_names = {}
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 0)
            if item:
                game_id = item.data(Qt.ItemDataRole.UserRole)
                new_name = item.text()
                updated_game_names[game_id] = new_name
        game_ids_file = os.path.join(SteamClipApp.CONFIG_DIR, 'GameIDs.json')
        with open(game_ids_file, 'w') as f:
            # noinspection PyTypeChecker
            json.dump(updated_game_names, f, indent=4)
        QMessageBox.information(self, "Info", "Game names saved successfully.")
        logger("Game ID names edited")
        self.parent().load_game_ids()
        self.parent().populate_gameid_combo()


if __name__ == "__main__":
    sys.excepthook = handle_exception
    if not IS_WINDOWS:
        tempfile.tempdir = os.path.expanduser(os.path.join(SteamClipApp.CONFIG_DIR, 'tmp'))
        os.makedirs(tempfile.gettempdir(), exist_ok=True)
        os.environ["REQUESTS_CA_BUNDLE"] = "/etc/ssl/certs/ca-certificates.crt"

    setup_logging()
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QWidget {
            font-size: 14px;
            font-family: 'Segoe UI', Arial, sans-serif;
        }
        QMainWindow, QDialog, QWidget#mainWidget {
            background-color: #1e1e2e;
        }
        QLabel {
            color: #cdd6f4;
            font-size: 14px;
        }
        QLabel#titleLabel {
            font-size: 20px;
            font-weight: bold;
            color: #89b4fa;
        }
        QLabel#sectionLabel {
            font-size: 12px;
            color: #6c7086;
            font-weight: bold;
            text-transform: uppercase;
        }
        QLabel#statusLabel {
            font-size: 13px;
            color: #a6adc8;
            padding: 8px;
            background-color: #313244;
            border-radius: 6px;
        }
        QPushButton {
            font-size: 14px;
            padding: 10px 20px;
            border-radius: 8px;
            border: none;
            background-color: #45475a;
            color: #cdd6f4;
        }
        QPushButton:hover {
            background-color: #585b70;
        }
        QPushButton:pressed {
            background-color: #313244;
        }
        QPushButton:disabled {
            background-color: #313244;
            color: #6c7086;
        }
        QPushButton#primaryButton {
            background-color: #89b4fa;
            color: #1e1e2e;
            font-weight: bold;
        }
        QPushButton#primaryButton:hover {
            background-color: #b4befe;
        }
        QPushButton#primaryButton:disabled {
            background-color: #45475a;
            color: #6c7086;
        }
        QPushButton#dangerButton {
            background-color: #f38ba8;
            color: #1e1e2e;
            font-weight: bold;
        }
        QPushButton#dangerButton:hover {
            background-color: #eba0ac;
        }
        QPushButton#dangerButton:disabled {
            background-color: #45475a;
            color: #6c7086;
        }
        QPushButton#navButton {
            background-color: transparent;
            color: #89b4fa;
            padding: 8px 16px;
        }
        QPushButton#navButton:hover {
            background-color: #313244;
        }
        QPushButton#navButton:disabled {
            color: #45475a;
        }
        QComboBox {
            font-size: 14px;
            padding: 8px 12px;
            border-radius: 8px;
            border: 2px solid #45475a;
            background-color: #313244;
            color: #cdd6f4;
            combobox-popup: 0;
        }
        QComboBox:hover {
            border-color: #89b4fa;
        }
        QComboBox::drop-down {
            border: none;
            padding-right: 10px;
        }
        QComboBox QAbstractItemView {
            background-color: #313244;
            color: #cdd6f4;
            selection-background-color: #45475a;
            border: 1px solid #45475a;
            border-radius: 8px;
        }
        QFrame#clipFrame {
            background-color: #181825;
            border-radius: 12px;
            padding: 10px;
        }
        QFrame#filterFrame {
            background-color: #313244;
            border-radius: 10px;
            padding: 15px;
        }
        QFrame#progressFrame {
            background-color: #313244;
            border-radius: 10px;
            padding: 10px;
            margin: 5px 0;
        }
        QProgressBar {
            border: none;
            border-radius: 6px;
            background-color: #313244;
            text-align: center;
            color: #cdd6f4;
        }
        QProgressBar::chunk {
            background-color: #89b4fa;
            border-radius: 6px;
        }
        QTableWidget {
            font-size: 14px;
            background-color: #313244;
            color: #cdd6f4;
            gridline-color: #45475a;
            border-radius: 8px;
        }
        QTableWidget::item:selected {
            background-color: #45475a;
        }
        QHeaderView::section {
            background-color: #1e1e2e;
            color: #cdd6f4;
            padding: 8px;
            border: none;
        }
        QMessageBox {
            background-color: #1e1e2e;
        }
        QMessageBox QLabel {
            color: #cdd6f4;
        }
        QScrollBar:vertical {
            background-color: #1e1e2e;
            width: 12px;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background-color: #45475a;
            border-radius: 6px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #585b70;
        }
    """)
    try:
        window = SteamClipApp()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        handle_exception(type(e), e, e.__traceback__)
