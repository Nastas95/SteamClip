#!/usr/bin/env python3
import os
import sys
import subprocess
import json
from typing import Optional
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

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGridLayout,
    QFrame, QComboBox, QDialog, QTableWidget,
    QTableWidgetItem, QTextEdit, QMessageBox,
    QFileDialog, QLayout, QProgressBar
)
from PyQt6.QtGui import QPixmap, QIcon
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


class ThumbnailFrame(QFrame):
    def __init__(self, parent=None):
        super(ThumbnailFrame, self).__init__(parent)
        self.folder = None


class SteamClipApp(QWidget):
    CONFIG_DIR = CONFIG_PATH
    CONFIG_FILE = os.path.join(CONFIG_DIR, 'SteamClip.conf')
    GAME_IDS_FILE = os.path.join(CONFIG_DIR, 'GameIDs.json')
    STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
    GITHUB_RELEASES_URL = "https://github.com/Nastas95/SteamClip/releases/latest"
    CURRENT_VERSION = "v0.0"

    def __init__(self):
        super().__init__()
        logger("Application started")
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
        self.conversion_worker = None
        self.settings_window = None
        first_run = not os.path.exists(self.CONFIG_FILE)

        if not self.default_dir:
            self.default_dir = self.prompt_steam_version_selection()
            if not self.default_dir:
                QMessageBox.critical(self, "Critical Error", "Failed to locate Steam userdata directory. Exiting.")
                sys.exit(1)

        self.save_config(self.default_dir, self.export_dir)
        self.load_game_ids()

        self.setStyleSheet("QComboBox { combobox-popup: 0; }")
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
        self.clip_frame = QFrame()
        self.clip_frame.setLayout(self.clip_grid)

        self.clear_selection_button = self.create_button("Clear Selection", self.clear_selection, enabled=False, size=(150, 40))
        self.export_all_button = self.create_button("Export All", self.export_all, enabled=True, size=(150, 40))
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
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
        self.main_layout.addLayout(self.id_selection_layout)
        self.main_layout.addWidget(self.clip_frame)
        self.main_layout.addLayout(self.clear_selection_layout)
        # Bottom Layout
        self.convert_button = self.create_button("Convert Clip(s)", self.convert_clip, enabled=False)
        self.exit_button = self.create_button("Exit", self.close)
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

        if first_run:
            QMessageBox.information(self, "INFO",
                "Clips will be saved on the Desktop. You can change the export path in the settings.")

    def load_config(self):
        config = {
            'userdata_path': None,
            'export_path': os.path.normpath(os.path.join(os.path.expanduser("~"), "Desktop"))}
        if os.path.exists(self.CONFIG_FILE):
            logger("Loaded configuration")
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
                        logger(f"Malformed config line (missing '='): {line}")
        return config

    def save_config(self, userdata_path=None, export_path=None):
        logger(f"Saving configuration: userdata={userdata_path}, export={export_path}")
        config = {}
        if userdata_path:
            config['userdata_path'] = os.path.normpath(userdata_path)
        config['export_path'] = export_path or os.path.normpath(os.path.normpath(os.path.join(os.path.expanduser("~"), "Desktop")))
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
        dialog = SteamVersionSelectionDialog(self)
        while dialog.exec() == QDialog.DialogCode.Accepted:
            selected_option = dialog.get_selected_option()
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
                widget.setStyleSheet("border: none;")
        self.convert_button.setEnabled(False)
        self.clear_selection_button.setEnabled(False)

    def populate_steamid_dirs(self):
        if not os.path.isdir(self.default_dir):
            self.show_error("Default Steam userdata directory not found.")
            return
        self.steamid_combo.clear()
        steamid_found = False
        for entry in os.scandir(self.default_dir):
            if entry.is_dir() and entry.name.isdigit():
                local_vdf = os.path.join(self.default_dir, entry, 'config', 'localconfig.vdf')
                if os.path.isfile(local_vdf):
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
            folder for folder in self.clip_folders[self.clip_index:]
            if self.find_session_mpd(folder)
        ]
        clips_to_show = valid_clip_folders[:6]
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
                widget.setStyleSheet("border: 3px solid lightblue;")
        self.update_navigation_buttons()
        self.export_all_button.setEnabled(bool(self.clip_folders))

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
        container = ThumbnailFrame()
        container.setFixedSize(340, 200)
        container_layout = QVBoxLayout()
        container.setLayout(container_layout)
        pixmap = QPixmap(thumbnail_path).scaled(340, 200, Qt.AspectRatioMode.KeepAspectRatio)
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
        duration_label.setStyleSheet("font-size: 14px; color: white; background-color: rgba(0, 0, 0, 180); border-radius: 3px; border: none;")
        duration_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        duration_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        duration_label.adjustSize()

        duration_width = duration_label.width()
        duration_height = duration_label.height()
        x = 340 - duration_width - 20
        y = 200 - duration_height - 20
        duration_label.move(x, y)

        container.folder = folder
        self.clip_grid.addWidget(container, index // 3, index % 3)

    def select_clip(self, folder, container):
        if folder in self.selected_clips:
            logger(f"Deselected clip: {folder}")
            self.selected_clips.remove(folder)
            container.setStyleSheet("border: none;")
        else:
            logger(f"Selected clip: {folder}")
            self.selected_clips.add(folder)
            container.setStyleSheet("border: 3px solid lightblue;")
        self.convert_button.setEnabled(bool(self.selected_clips))
        self.clear_selection_button.setEnabled(len(self.selected_clips) >= 1)

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
        self.progress_bar.setFormat(f"{int(total_progress)}%")
        self.progress_bar.setValue(int(total_progress))
        QApplication.processEvents()

    def start_conversion(self, selected_clips=None, export_all=False):
        if self.conversion_worker and self.conversion_worker.isRunning():
            QMessageBox.warning(self, "Operation in Progress", "Another conversion is already in progress.")
            return
        self.status_label.setText("")
        self.convert_button.setEnabled(False)
        self.export_all_button.setEnabled(False)
        self.clear_selection_button.setEnabled(False)
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.steamid_combo.setEnabled(False)
        self.gameid_combo.setEnabled(False)
        self.media_type_combo.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Starting conversion...")
        self.conversion_worker = ConversionWorker(self, selected_clips, export_all)
        self.conversion_worker.progress_updated.connect(self.update_progress)
        self.conversion_worker.finished.connect(self.on_conversion_finished)
        self.conversion_worker.error_occurred.connect(self.on_conversion_error)
        self.conversion_worker.status_message.connect(self.update_status_message)
        self.conversion_worker.cancelled.connect(self.on_conversion_cancelled)
        self.conversion_worker.start()
        self.conversion_worker.start()

    def on_conversion_finished(self, success, export_all):
        self.convert_button.setEnabled(bool(self.selected_clips))
        self.export_all_button.setEnabled(True)
        self.clear_selection_button.setEnabled(len(self.selected_clips) >= 1)
        self.prev_button.setEnabled(self.clip_index > 0)
        self.next_button.setEnabled(self.clip_index + 6 < len(self.clip_folders))
        self.settings_button.setEnabled(True)
        self.steamid_combo.setEnabled(True)
        self.gameid_combo.setEnabled(True)
        self.media_type_combo.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.show_completion_message(export_all, not success)

    def on_conversion_cancelled(self):
        self.progress_bar.setFormat("Cancelled by user")
        logger("Conversion cancelled by user")

    def on_conversion_error(self, clip_folder, error_message):
        folder_name = os.path.basename(clip_folder) if clip_folder else "Unknown clip"
        QMessageBox.warning(self, "Conversion Error",
                        f"Error converting {folder_name}:\n{error_message}\n\nCheck logs for details.")
        logger(f"Conversion error for {folder_name}: {error_message}")

    def update_status_message(self, message):
        self.progress_bar.setFormat(message)
        QApplication.processEvents()

    def validate_export_directory(self):
        if self.export_dir is None or not os.path.isdir(self.export_dir):
            logger(f"Export directory '{self.export_dir}' not found.")
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
                logger("Export Path not found, defaulted to Desktop")
                return True
            else:
                QMessageBox.warning(self, "Operation Cancelled", "Export operation has been cancelled.")
                logger("Export Path not found, Export Cancelled")
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

    def find_session_mpd_files(self, clip_folder):
        session_mpd_files = self.find_session_mpd(clip_folder)
        if not session_mpd_files:
            raise FileNotFoundError(f"No session.mpd files found in {clip_folder}")
        return session_mpd_files

    def prepare_temp_media_files(self, session_mpd_files):
        temp_video_paths = []
        temp_audio_paths = []
        ffmpeg_path = iio.get_ffmpeg_exe()
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
            raise FileNotFoundError("Initialization files missing")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_video:
            with open(init_video, 'rb') as f:
                tmp_video.write(f.read())
            for chunk in sorted(glob.glob(os.path.join(data_dir, 'chunk-stream0-*.m4s'))):
                with open(chunk, 'rb') as f:
                    tmp_video.write(f.read())
            temp_video_path = tmp_video.name
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_audio:
            with open(init_audio, 'rb') as f:
                tmp_audio.write(f.read())
            for chunk in sorted(glob.glob(os.path.join(data_dir, 'chunk-stream1-*.m4s'))):
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
        subprocess.run([
            ffmpeg_path, '-i', video_path, '-i', audio_path, '-c', 'copy', output_file
        ], **subprocess_args)
        return output_file

    def generate_output_filename(self, clip_folder):
        folder_basename = os.path.basename(clip_folder)
        parts = folder_basename.split('_')
        formatted_date = self.extract_date_from_folder_name(parts)
        game_id = parts[1] if len(parts) > 1 else "UnknownGame"
        game_name = self.get_game_name(game_id) or "Clip"
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
                logger(f"Unable to parse date from folder name parts: {parts}. Using 'UnknownDate'.")
        logger(f"Not enough parts to extract date: {parts}. Using 'UnknownDate'.")
        return "UnknownDate"

    def closeEvent(self, event):
        self.cleanup_temp_files()
        super().closeEvent(event)

    def cleanup_temp_files(self):
        temp_dir = os.path.join(self.CONFIG_DIR, 'tmp')
        if not os.path.exists(temp_dir):
            return

        try:
            deleted_count = 0
            for item in os.listdir(temp_dir):
                item_path = os.path.join(temp_dir, item)
                try:
                    if os.path.isfile(item_path) or os.path.islink(item_path):
                        os.unlink(item_path)
                        deleted_count += 1
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        deleted_count += 1
                except Exception as e:
                    logger(f"Impossibile eliminare {item_path}: {str(e)}")

            if deleted_count > 0:
                logger(f"Puliti {deleted_count} file temporanei in {temp_dir}")
        except Exception as e:
            logger(f"Errore durante la pulizia dei file temporanei: {str(e)}")

    def cleanup_clip_temp_files(self, file_paths):
        for file_path in file_paths:
            if file_path and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                    logger(f"Cleaned up temporary file: {file_path}")
                except Exception as exc:
                    logger(f"Error cleaning up temp file {file_path}: {str(exc)}")

    def show_completion_message(self, export_all, errors):
        self.progress_bar.setVisible(False)

        if export_all:
            if errors:
                self.show_error("Some clips failed to convert. Check the logs for details.")
            else:
                self.show_info("All clips converted successfully")
        else:
            if not errors:
                self.selected_clips.clear()
                self.display_clips()
                self.show_info("Selected clips converted successfully")

    def convert_clip(self):
        if not self.selected_clips:
            return
        self.start_conversion(selected_clips=self.selected_clips)

    def export_all(self):
        self.start_conversion(export_all=True)

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
        self.setFixedSize(220, 400)
        layout = QVBoxLayout()
        self.open_config_button = self.create_button("Open Config Folder", self.open_config_folder, "folder-open")
        self.edit_game_ids_button = self.create_button("Edit Game Name", self.open_edit_game_ids, "edit-rename")
        self.update_game_ids_button = self.create_button("Update GameIDs", self.update_game_ids, "view-refresh")
        self.check_for_updates_button = self.create_button("Check for Updates", self.check_for_updates, "view-refresh")
        self.close_settings_button = self.create_button("Close Settings", self.close, "window-close")
        self.select_export_button = self.create_button("Set Export Path", self.select_export_path, "folder-open")
        self.delete_config_button = self.create_button("Delete Config Folder", self.delete_config_folder, "edit-delete")
        if DEBUG:
            self.check_for_updates_button.setDisabled(True)
        self.version_label = QLabel(f"Version: {parent.CURRENT_VERSION}")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setLayout(layout)
        layout.addWidget(self.open_config_button)
        layout.addWidget(self.select_export_button)
        layout.addWidget(self.edit_game_ids_button)
        layout.addWidget(self.update_game_ids_button)
        layout.addWidget(self.check_for_updates_button)
        layout.addWidget(self.delete_config_button)
        layout.addWidget(self.close_settings_button)
        layout.addWidget(self.version_label)

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
                self.parent().save_config(self.parent().default_dir, self.parent().export_dir)
                QMessageBox.information(self, "Info", f"Export path set to: {export_path}")
                logger(f"Export path changed to: {export_path}")
                return
            except Exception as exc:
                QMessageBox.warning(self, "Invalid Directory", f"The selected directory is not writable: {str(exc)}")
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
            self.parent().show_changelog(release_info['version'], release_info['changelog'])
            logger(f"Update available, showing changelog")

    def open_edit_game_ids(self):
        edit_window = EditGameIDWindow(self.parent())
        edit_window.exec()

    @staticmethod
    def open_config_folder():
        config_folder = SteamClipApp.CONFIG_DIR
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

class ConversionWorker(QThread):
    progress_updated = pyqtSignal(int, int, int, int)
    finished = pyqtSignal(bool, bool)
    error_occurred = pyqtSignal(str, str)
    status_message = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, app_instance, selected_clips=None, export_all=False):
        super().__init__()
        self.app = app_instance
        self.selected_clips = selected_clips or set()
        self.export_all = export_all
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True
        self.cancelled.emit()

    def run(self):
        try:
            success = self.process_clips()
            if not self.is_cancelled:
                self.finished.emit(success, self.export_all)
        except Exception as e:
            logger(f"Worker thread exception: {str(e)}", exc_info=True)
            self.error_occurred.emit("", str(e))
            self.finished.emit(False, self.export_all)

    def process_clips(self):
        if not self.app.validate_export_directory():
            self.error_occurred.emit("", "Export directory validation failed")
            return False

        clip_list = self.app.get_clips_to_process(self.selected_clips, self.export_all)
        if not clip_list:
            self.error_occurred.emit("", "No clips to process")
            return False

        self.status_message.emit(f"Starting conversion of {len(clip_list)} clip(s)...")

        errors = False
        for clip_idx, clip_folder in enumerate(clip_list):
            if self.is_cancelled:
                self.status_message.emit("Conversion cancelled by user")
                return False

            try:
                if not self.process_single_clip(clip_folder, clip_idx, len(clip_list)):
                    errors = True
            except Exception as exc:
                errors = True
                self.error_occurred.emit(clip_folder, str(exc))

        return not errors

    def process_single_clip(self, clip_folder, clip_idx, total_clips):
        temp_files = []
        try:
            self.progress_updated.emit(clip_idx, total_clips, 0, 3)
            self.status_message.emit(f"Processing clip {clip_idx + 1}/{total_clips}: {os.path.basename(clip_folder)}")

            session_mpd_files = self.app.find_session_mpd_files(clip_folder)
            video_files, audio_files = self.app.prepare_temp_media_files(session_mpd_files)
            temp_files.extend(video_files + audio_files)

            self.progress_updated.emit(clip_idx, total_clips, 1, 3)
            concatenated_video = self.app.concatenate_media_files(video_files, is_video=True)
            temp_files.append(concatenated_video)

            self.progress_updated.emit(clip_idx, total_clips, 2, 3)
            concatenated_audio = self.app.concatenate_media_files(audio_files, is_video=False)
            temp_files.append(concatenated_audio)

            output_file = self.app.generate_and_merge_final_file(
                concatenated_video, concatenated_audio, clip_folder
            )

            self.progress_updated.emit(clip_idx, total_clips, 3, 3)
            logger(f"Clip successfully processed: {output_file}")
            return True
        except Exception as exc:
            logger(f"Error processing clip {clip_folder}: {str(exc)}", exc_info=exc)
            raise
        finally:
            self.app.cleanup_clip_temp_files(temp_files)

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

    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QWidget {
            font-size: 16px;
        }
        QLabel {
            font-size: 18px;
        }
        QPushButton {
            font-size: 16px;
        }
        QComboBox {
            font-size: 16px;
            combobox-popup: 0;
        }
        QTableWidget {
            font-size: 16px;
        }
    """)
    try:
        window = SteamClipApp()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        handle_exception(type(e), e, e.__traceback__)
