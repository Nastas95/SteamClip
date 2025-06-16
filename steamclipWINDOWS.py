#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import imageio_ffmpeg as iio
import logging
import traceback
import shutil
import tempfile
import glob
import requests
import time
import xml.etree.ElementTree as ET
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGridLayout,
    QFrame, QComboBox, QDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QTextEdit,
    QMessageBox, QFileDialog, QLayout, QProgressBar
)
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import Qt
from datetime import datetime

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

def log_user_action(action):
    user_actions.append(action)
    logging.info(f"User Action: {action}")

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log_dir = os.path.join(SteamClipApp.CONFIG_DIR, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_dir, f"crash_{timestamp}.log")
    with open(log_file, "w") as f:
        f.write("User Actions:\n")
        for action in user_actions:
            f.write(f"- {action}\n")
        f.write("\nError Details:\n")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    error_message = f"An unexpected error occurred:\n{exc_value}"
    QMessageBox.critical(None, "Critical Error", error_message)

class SteamClipApp(QWidget):
    CONFIG_DIR = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser("~")),
    'SteamClip'
)
    CONFIG_FILE = os.path.join(CONFIG_DIR, 'SteamClip.conf')
    GAME_IDS_FILE = os.path.join(CONFIG_DIR, 'GameIDs.json')
    STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
    CURRENT_VERSION = "v2.16.5"

    def __init__(self):
        super().__init__()
        self.cleanup_temp_files()
        log_user_action("Application started")
        self.setWindowTitle("SteamClip")
        self.setGeometry(100, 100, 900, 600)
        self.clip_index = 0
        self.clip_folders = []
        self.original_clip_folders = []
        self.game_ids = {}
        self.config = self.load_config()
        self.default_dir = self.config.get('userdata_path')
        self.export_dir = self.config.get('export_path', os.path.expanduser("~/Desktop"))
        first_run = not os.path.exists(self.CONFIG_FILE)

        if not self.default_dir:
            self.default_dir = self.prompt_steam_version_selection()
            if not self.default_dir:
                QMessageBox.critical(self, "Critical Error", "Failed to locate Steam userdata directory. Exiting.")
                sys.exit(1)

        self.save_config(self.default_dir, self.export_dir)
        self.load_game_ids()
        self.selected_clips = set()
        self.setup_ui()
        self.del_invalid_clips()
        self.populate_steamid_dirs()
        self.perform_update_check()

        if first_run:
            QMessageBox.information(self, "INFO",
                "Clips will be saved on the Desktop. You can change the export path in the settings")

    def cleanup_temp_files(self):
        temp_files = glob.glob(os.path.join(self.CONFIG_DIR, "steamclip_new*"))
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    logging.info(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                logging.error(f"Error cleaning temp file {temp_file}: {str(e)}")

    def load_config(self):
        config = {'userdata_path': None, 'export_path': os.path.expanduser("~/Desktop")}
        if os.path.exists(self.CONFIG_FILE):
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
                    else:
                        logging.warning(f"Malformed config line (missing '='): {line}")
        return config

    def save_config(self, userdata_path=None, export_path=None):
        config = {}
        if userdata_path:
            config['userdata_path'] = userdata_path
        config['export_path'] = export_path or os.path.expanduser("~/Desktop")
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
        self.wait_message = QDialog(self)
        self.wait_message.setWindowTitle("Updating SteamClip")
        self.wait_message.setFixedSize(400, 120)
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)
        self.progress_label = QLabel("Downloading update... 0.0%")
        self.progress_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.progress_label)
        progress_frame = QFrame()
        progress_frame.setFixedSize(300, 30)
        progress_frame.setStyleSheet("background-color: #e0e0e0; border-radius: 5px;")
        self.progress_inner = QFrame(progress_frame)
        self.progress_inner.setGeometry(0, 0, 0, 30)
        self.progress_inner.setStyleSheet("background-color: #4caf50; border-radius: 5px;")
        layout.addWidget(progress_frame)
        cancel_button = QPushButton("Cancel Download")
        cancel_button.clicked.connect(lambda: self.cancel_download(temp_download_path))
        layout.addWidget(cancel_button)
        self.wait_message.setLayout(layout)
        self.wait_message.show()
        self._is_cancelled = False
        download_url = f"https://github.com/Nastas95/SteamClip/releases/download/{latest_release}/steamclip.exe"
        temp_download_path = os.path.join(self.CONFIG_DIR, "steamclip_new.exe")
        current_executable = os.path.abspath(sys.argv[0])
        try:
            import requests
            response = requests.get(download_url, stream=True)
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
                            self.progress_label.setText(f"Downloading update... {percentage:.1f}%")
                            progress_width = int(300 * (percentage / 100))
                            self.progress_inner.setFixedWidth(progress_width)
                        QApplication.processEvents()
                        if self.wait_message.isHidden():
                            self.cancel_download(temp_download_path)
                            return
            batch_script = os.path.join(self.CONFIG_DIR, "update.bat")
            with open(batch_script, "w") as bat:
                bat.write(f'''
    @echo off
    setlocal
    set "old_exe={current_executable}"
    set "new_exe={temp_download_path}"

    :: 1. Wait
    :loop
    tasklist | findstr /C:"{os.path.basename(current_executable)}" >nul 2>&1
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
    :: Usa 'cmd /c start' per evitare l'ereditarietà della directory temporanea
    start "" /D "%~dp0" "%old_exe%"

    :: 4. Delete
    del "%~f0%"
    ''')
            subprocess.Popen([batch_script], shell=True)
            sys.exit(0)
        except Exception as e:
            self.wait_message.close()
            QMessageBox.critical(self, "Update Failed", f"Failed to update SteamClip: {e}")

    def cancel_download(self, temp_download_path):
        self._is_cancelled = True
        self.wait_message.close()
        if hasattr(self, '_response'):
            self._response.close()
        QMessageBox.information(self, "Download Cancelled", "The update has been cancelled.")
        self._is_cancelled = False

    def get_latest_release_from_github(self):
        url = "https://api.github.com/repos/Nastas95/SteamClip/releases/latest"
        try:
            import requests
            response = requests.get(url)
            response.raise_for_status()
            release_data = response.json()
            return {
                'version': release_data['tag_name'],
                'changelog': release_data.get('body', 'No changelog available')
            }
        except Exception as e:
            logging.error(f"Error fetching release info: {e}")
            return None

    def prompt_update(self, latest_version, changelog):
        message_box = QMessageBox(QMessageBox.Question, "Update Available",
                                f"A new update ({latest_version}) is available. Update now?")
        update_button = message_box.addButton("Update", QMessageBox.AcceptRole)
        changelog_button = message_box.addButton("View Changelog", QMessageBox.ActionRole)
        cancel_button = message_box.addButton("Cancel", QMessageBox.RejectRole)
        message_box.exec_()
        if message_box.clickedButton() == update_button:
            self.download_update(latest_version)
        elif message_box.clickedButton() == changelog_button:
            self.show_changelog(latest_version, changelog)

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
        dialog.exec_()

    def check_and_load_userdata_folder(self):
        if not os.path.exists(self.CONFIG_FILE):
            return self.prompt_steam_version_selection()
        with open(self.CONFIG_FILE, 'r') as f:
            userdata_path = f.read().strip()
        return userdata_path if os.path.isdir(userdata_path) else self.prompt_steam_version_selection()

    def prompt_steam_version_selection(self):
        dialog = SteamVersionSelectionDialog(self)
        while dialog.exec_() == QDialog.Accepted:
            selected_option = dialog.get_selected_option()
            if selected_option == "Standard":
                userdata_path = os.path.expanduser("C:/Program Files (x86)/Steam/userdata")
            #elif selected_option == "Flatpak":
            #    userdata_path = os.path.expanduser("~/.var/app/com.valvesoftware.Steam/data/Steam/userdata")
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
        with open(self.CONFIG_FILE, 'w') as f:
            f.write(directory)

    def load_game_ids(self):
        if not os.path.exists(self.GAME_IDS_FILE):
            QMessageBox.information(self, "Info", "SteamClip will now try to download the GameID database. Please, be patient.")
            self.game_ids = {}
        else:
            with open(self.GAME_IDS_FILE, 'r') as f:
                self.game_ids = json.load(f)

    def fetch_game_name_from_steam(self, game_id):
        url = f"{self.STEAM_APP_DETAILS_URL}?appids={game_id}&filters=basic"
        try:
            response = requests.get(url)
            response.raise_for_status()  # Controlla errori HTTP
            data = response.json()
            if str(game_id) in data and data[str(game_id)]['success']:
                return data[str(game_id)]['data']['name']
        except Exception as e:
            logging.error(f"Error fetching game name for {game_id}: {e}")
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

    def setup_ui(self):
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
        self.clip_frame, self.clip_grid = self.create_clip_layout()
        self.clear_selection_button = self.create_button("Clear Selection", self.clear_selection, enabled=False, size=(150, 40))
        self.export_all_button = self.create_button("Export All", self.export_all, enabled=True, size=(150, 40))
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
###        self.debug_button = self.create_button("Debug Crash", self.debug_crash, enabled=True, size=(150, 40)) #DEBUG ONLY
        self.clear_selection_layout = QHBoxLayout()
        self.clear_selection_layout.addStretch()
        self.clear_selection_layout.addWidget(self.clear_selection_button)
        self.clear_selection_layout.addWidget(self.export_all_button)
        self.clear_selection_layout.addStretch()
###        self.clear_selection_layout.addWidget(self.debug_button) #DEBUG ONLY
        self.settings_button = self.create_button("", self.open_settings, icon="preferences-system", size=(40, 40))
        self.id_selection_layout = QHBoxLayout()
        self.id_selection_layout.addWidget(self.settings_button)
        self.id_selection_layout.addWidget(self.steamid_combo)
        self.id_selection_layout.addWidget(self.gameid_combo)
        self.id_selection_layout.addWidget(self.media_type_combo)
        self.main_layout = QVBoxLayout()
        self.main_layout.addLayout(self.id_selection_layout)
        self.main_layout.addWidget(self.clip_frame)
        self.main_layout.addLayout(self.clear_selection_layout)
        self.bottom_layout = self.create_bottom_layout()
        self.main_layout.addLayout(self.bottom_layout)
        self.setLayout(self.main_layout)
        self.main_layout.setSizeConstraint(QLayout.SetFixedSize)
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.main_layout.addWidget(self.progress_bar)

    def create_clip_layout(self):
        clip_grid = QGridLayout()
        clip_frame = QFrame()
        clip_frame.setLayout(clip_grid)
        return clip_frame, clip_grid

    def create_bottom_layout(self):
        self.convert_button = self.create_button("Convert Clip(s)", self.convert_clip, enabled=False)
        self.exit_button = self.create_button("Exit", self.close)
        self.prev_button = self.create_button("<< Previous", self.show_previous_clips)
        self.next_button = self.create_button("Next >>", self.show_next_clips)
        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self.prev_button)
        bottom_layout.addWidget(self.next_button)
        bottom_layout.addWidget(self.convert_button)
        bottom_layout.addWidget(self.exit_button)
        return bottom_layout

    def create_button(self, text, slot, enabled=True, icon=None, size=(240, 40)):
        button = QPushButton(text)
        button.clicked.connect(slot)
        button.setEnabled(enabled)
        if icon:
            button.setIcon(QIcon.fromTheme(icon))
        if size:
            button.setFixedSize(*size)
        return button

    def is_connected(self):
        try:
            response = requests.get("http://www.google.com", timeout=5)
            return response.status_code == 200
        except requests.ConnectionError:
            return False
        except Exception as e:
            print(f"Connection check failed: {e}")
            return False

    def get_custom_record_path(self, userdata_dir):
        localconfig_path = os.path.join(userdata_dir, 'config', 'localconfig.vdf')
        if not os.path.exists(localconfig_path):
            return None
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
                        return path_line
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
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                success = 0
                for folder in invalid_folders:
                    try:
                        shutil.rmtree(folder)
                        log_user_action(f"Deleted invalid clip folder: {folder}")
                        success += 1
                    except Exception as e:
                        self.show_error(f"Failed to delete {folder}: {str(e)}")
                self.show_info(f"Deleted {success} invalid clip(s).")
                self.populate_steamid_dirs()

    def filter_media_type(self):
        selected_media_type = self.media_type_combo.currentText()
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
        log_user_action(f"Selected SteamID: {selected_steamid}")
        userdata_dir = os.path.join(self.default_dir, selected_steamid)
        self.filter_media_type()

    def clear_clip_grid(self):
        for i in range(self.clip_grid.count()):
            widget = self.clip_grid.itemAt(i).widget()
            if widget:
                widget.deleteLater()

    def clear_selection(self):
        log_user_action("Cleared selection of clips")
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

    def extract_datetime_from_folder_name(self, folder_name):
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

    def save_game_ids(self):
        with open(self.GAME_IDS_FILE, 'w') as f:
            json.dump(self.game_ids, f, indent=4)

    def filter_clips_by_gameid(self):
        selected_index = self.gameid_combo.currentIndex()
        if selected_index == 0:
            log_user_action("Selected All Games")
            self.clip_folders = [
                folder for folder in self.original_clip_folders
                if self.find_session_mpd(folder)
            ]
        else:
            selected_game_id = self.gameid_combo.itemData(selected_index)
            if not selected_game_id:
                return
            game_name = self.get_game_name(selected_game_id)
            log_user_action(f"Selected Game: {game_name} (ID: {selected_game_id})")
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
            widget = self.clip_grid.itemAt(i).widget()
            if widget and hasattr(widget, 'folder') and widget.folder in self.selected_clips:
                widget.setStyleSheet("border: 3px solid lightblue;")
        self.update_navigation_buttons()
        self.export_all_button.setEnabled(bool(self.clip_folders))

    def extract_first_frame(self, session_mpd_path, output_thumbnail_path):
        ffmpeg_path = iio.get_ffmpeg_exe()
        data_dir = os.path.dirname(session_mpd_path)
        init_video = os.path.join(data_dir, 'init-stream0.m4s')
        chunk_video = glob.glob(os.path.join(data_dir, 'chunk-stream0-*.m4s'))
        if not os.path.exists(init_video) or not chunk_video:
            logging.error(f"Error extracting thumbnail: {e}")
            return
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_video:
                with open(init_video, 'rb') as f:
                    tmp_video.write(f.read())
                for chunk in sorted(chunk_video):
                    with open(chunk, 'rb') as f:
                        tmp_video.write(f.read())
                temp_video_path = tmp_video.name
            command = [
                ffmpeg_path,
                '-i', temp_video_path,
                '-ss', '00:00:00.000',
                '-vframes', '1',
                output_thumbnail_path
            ]
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"Error extracting thumbnail: {e}")
        finally:
            if 'temp_video_path' in locals() and os.path.exists(temp_video_path):
                os.unlink(temp_video_path)

    def get_clip_duration(self, clip_folder):
        total_seconds = 0.0
        session_mpd_file = self.find_session_mpd(clip_folder)
        if not session_mpd_file:
            return "0:00"
        if os.path.exists(session_mpd_file):
            try:
                import xml.etree.ElementTree as ET
                tree = ET.parse(session_mpd_file)
                root = tree.getroot()
                ns = {'dash': 'urn:mpeg:dash:schema:mpd:2011'}
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
                    logging.warning(f"Attribute 'mediaPresentationDuration' not found in {session_mpd_file}")
            except Exception as e:
                logging.error(f"Error parsing {session_mpd_file}: {e}")
        else:
            logging.error(f"File {session_mpd_file} does not exist")

        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        return f"{minutes}:{seconds:02d}"

    def add_thumbnail_to_grid(self, thumbnail_path, folder, index):
        container = QFrame()
        container.setFixedSize(340, 200)
        container_layout = QVBoxLayout()
        container.setLayout(container_layout)
        pixmap = QPixmap(thumbnail_path).scaled(340, 200, Qt.KeepAspectRatio)
        thumbnail_label = QLabel()
        thumbnail_label.setPixmap(pixmap)
        thumbnail_label.setAlignment(Qt.AlignCenter)
        thumbnail_label.setStyleSheet("border: none;")

        def select_clip_event(event):
            self.select_clip(folder, container)

        thumbnail_label.mousePressEvent = select_clip_event
        container_layout.addWidget(thumbnail_label)

        duration = self.get_clip_duration(folder)
        duration_label = QLabel(f"{duration}", container)
        duration_label.setStyleSheet("font-size: 14px; color: white; background-color: rgba(0, 0, 0, 180); border-radius: 3px; border: none;")
        duration_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        duration_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
            log_user_action(f"Deselected clip: {folder}")
            self.selected_clips.remove(folder)
            container.setStyleSheet("border: none;")
        else:
            log_user_action(f"Selected clip: {folder}")
            self.selected_clips.add(folder)
            container.setStyleSheet("border: 3px solid lightblue;")
        self.convert_button.setEnabled(bool(self.selected_clips))
        self.clear_selection_button.setEnabled(len(self.selected_clips) >= 1)

    def update_navigation_buttons(self):
        self.prev_button.setEnabled(self.clip_index > 0)
        self.next_button.setEnabled(self.clip_index + 6 < len(self.clip_folders))

    def show_previous_clips(self):
        if self.clip_index - 6 >= 0:
            log_user_action("Navigated to previous clips")
            self.clip_index -= 6
            self.display_clips()

    def show_next_clips(self):
        if self.clip_index + 6 < len(self.clip_folders):
            log_user_action("Navigated to next clips")
            self.clip_index += 6
            self.display_clips()

    def update_progress(self, current_clip, total_clips, step, total_steps):
        clip_segment = 100 / total_clips
        step_progress = (step / total_steps) * clip_segment
        total_progress = (current_clip * clip_segment) + step_progress
        self.progress_bar.setValue(int(total_progress))
        QApplication.processEvents()

    def process_clips(self, selected_clips=None, export_all=False):
        if self.export_dir is None or not os.path.isdir(self.export_dir):
            logging.warning(f"Export directory '{self.export_dir}' not found.")
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
                self.save_config(self.default_dir, self.export_dir)
                QMessageBox.information(self, "Info", f"Export path set to: {self.export_dir}")
            else:
                QMessageBox.warning(self, "Operation Cancelled", "Export operation has been cancelled.")
                return
        QApplication.processEvents()

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
        ffmpeg_path = iio.get_ffmpeg_exe()
        errors = False

        total_clips = len(clip_list)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)

        try:
            for clip_idx, clip_folder in enumerate(clip_list):
                try:
                    session_mpd_files = []
                    for root, _, files in os.walk(clip_folder):
                        if 'session.mpd' in files:
                            session_mpd_files.append(os.path.join(root, 'session.mpd'))

                    if not session_mpd_files:
                        raise FileNotFoundError("No session.mpd files found")
                    temp_video_paths = []
                    temp_audio_paths = []

                    for session_mpd in session_mpd_files:
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

                    concatenated_video = os.path.join(tempfile.gettempdir(), f"concat_video_{hash(clip_folder)}.mp4")
                    concatenated_audio = os.path.join(tempfile.gettempdir(), f"concat_audio_{hash(clip_folder)}.mp4")
                    video_list_file = os.path.join(tempfile.gettempdir(), f"video_list_{hash(clip_folder)}.txt")
                    audio_list_file = os.path.join(tempfile.gettempdir(), f"audio_list_{hash(clip_folder)}.txt")

                    with open(video_list_file, 'w') as f:
                        for temp_video in temp_video_paths:
                            f.write(f"file '{temp_video}'\n")

                    with open(audio_list_file, 'w') as f:
                        for temp_audio in temp_audio_paths:
                            f.write(f"file '{temp_audio}'\n")

                    subprocess.run([
                        ffmpeg_path,
                        '-f', 'concat',
                        '-safe', '0',
                        '-i', video_list_file,
                        '-c', 'copy',
                        concatenated_video
                    ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.update_progress(clip_idx, total_clips, 1, 3)

                    subprocess.run([
                        ffmpeg_path,
                        '-f', 'concat',
                        '-safe', '0',
                        '-i', audio_list_file,
                        '-c', 'copy',
                        concatenated_audio
                    ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.update_progress(clip_idx, total_clips, 2, 3)

                    game_id = os.path.basename(clip_folder).split('_')[1]
                    game_name = self.get_game_name(game_id) or "Clip"
                    output_file = self.get_unique_filename(output_dir, f"{game_name}.mp4")

                    subprocess.run([
                        ffmpeg_path,
                        '-i', concatenated_video,
                        '-i', concatenated_audio,
                        '-c', 'copy',
                        output_file
                    ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.update_progress(clip_idx, total_clips, 3, 3)

                except Exception as e:
                    errors = True
                    logging.error(f"Error processing {clip_folder}: {str(e)}")
                finally:
                    for temp_video in temp_video_paths + temp_audio_paths:
                        try:
                            if os.path.exists(temp_video):
                                os.unlink(temp_video)
                        except Exception as e:
                            logging.warning(f"Error cleaning up temp files: {str(e)}")
                    try:
                        if 'concatenated_video' in locals() and os.path.exists(concatenated_video):
                            os.unlink(concatenated_video)
                        if 'concatenated_audio' in locals() and os.path.exists(concatenated_audio):
                            os.unlink(concatenated_audio)
                        if 'video_list_file' in locals() and os.path.exists(video_list_file):
                            os.unlink(video_list_file)
                        if 'audio_list_file' in locals() and os.path.exists(audio_list_file):
                            os.unlink(audio_list_file)
                    except Exception as e:
                        logging.warning(f"Error cleaning up concatenated files: {str(e)}")

            if export_all:
                msg = "All clips converted successfully" if not errors else "Some clips failed"
                self.show_info(msg)
            else:
                self.selected_clips.clear()
                self.display_clips()
                self.show_info("Selected clips converted successfully")
            return not errors
        finally:
            self.progress_bar.setVisible(False)

#       Thanks to User /u/vanokhin for the suggestions!

    def convert_clip(self):
        QApplication.processEvents()
        self.process_clips(selected_clips=self.selected_clips)

    def export_all(self):
        QApplication.processEvents()
        self.process_clips(export_all=True)

    def find_session_mpd(self, clip_folder):
        for root, _, files in os.walk(clip_folder):
            if 'session.mpd' in files:
                return os.path.join(root, 'session.mpd')
        return None

    def get_unique_filename(self, directory, filename):
        base_name, ext = os.path.splitext(filename)
        counter = 1
        unique_filename = os.path.join(directory, filename)
        while os.path.exists(unique_filename):
            unique_filename = os.path.join(directory, f"{base_name}_{counter}{ext}")
            counter += 1
        return unique_filename

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)

    def show_info(self, message):
        QMessageBox.information(self, "Info", message)

    def open_settings(self):
        self.settings_window = SettingsWindow(self)
        self.settings_window.exec_()

    def debug_crash(self):
        log_user_action("Debug button pressed - Simulating crash")
        raise Exception("Test crash")


class SteamVersionSelectionDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Select Steam Version")
        self.setFixedSize(350, 150)
        layout = QVBoxLayout()
        self.standard_button = QPushButton("Standard")
        #self.flatpak_button = QPushButton("Flatpak")
        self.manual_button = QPushButton("Select the userdata folder manually")
        self.standard_button.clicked.connect(lambda: self.accept_and_set("Standard"))
        #self.flatpak_button.clicked.connect(lambda: self.accept_and_set("Flatpak"))
        self.manual_button.clicked.connect(self.select_userdata_folder)
        layout.addWidget(QLabel("What version of Steam are you using?"))
        layout.addWidget(self.standard_button)
        #layout.addWidget(self.flatpak_button)
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

    def is_valid_userdata_folder(self, folder):
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
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(220, 400)
        layout = QVBoxLayout()
        self.open_config_button = self.create_button("Open Config Folder", self.open_config_folder, "folder-open")
        self.edit_game_ids_button = self.create_button("Edit Game Name", self.open_edit_game_ids, "edit-rename")
        self.update_game_ids_button = self.create_button("Update GameIDs", self.update_game_ids, "view-refresh")
        self.check_for_updates_button = self.create_button("Check for Updates", self.check_for_updates_in_settings, "view-refresh")
        self.close_settings_button = self.create_button("Close Settings", self.close, "window-close")
        self.select_export_button = self.create_button("Set Export Path", self.select_export_path, "folder-open")
        self.delete_config_button = self.create_button("Delete Config Folder", self.delete_config_folder, "edit-delete")
        self.version_label = QLabel(f"Version: {parent.CURRENT_VERSION}")
        self.version_label.setAlignment(Qt.AlignLeft)
        self.setLayout(layout)
        layout.addWidget(self.open_config_button)
        layout.addWidget(self.select_export_button)
        layout.addWidget(self.edit_game_ids_button)
        layout.addWidget(self.update_game_ids_button)
        layout.addWidget(self.check_for_updates_button)
        layout.addWidget(self.delete_config_button)
        layout.addWidget(self.close_settings_button)
        layout.addWidget(self.version_label)

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
                return
            except Exception as e:
                QMessageBox.warning(self, "Invalid Directory",
                                    f"The selected directory is not writable: {str(e)}")
        default_export_path = os.path.expanduser("~/Desktop")
        self.parent().export_dir = default_export_path
        self.parent().save_config(self.parent().default_dir, default_export_path)
        QMessageBox.warning(self, "Invalid Directory",
                            f"Selected export directory is invalid. Using default: {default_export_path}")

    def create_button(self, text, slot, icon=None, size=(200, 45)):
        button = QPushButton(text)
        button.clicked.connect(slot)
        if icon:
            button.setIcon(QIcon.fromTheme(icon))
        if size:
            button.setFixedSize(*size)
        return button

    def check_for_updates_in_settings(self):
        release_info = self.parent().perform_update_check(show_message=False)
        if release_info is None:
            QMessageBox.critical(self, "Error", "Failed to fetch the latest release information.")
            return
        if release_info['version'] == self.parent().CURRENT_VERSION:
            QMessageBox.information(self, "No Updates Available", "You are already using the latest version of SteamClip.")
        else:
            self.parent().prompt_update(release_info['version'], release_info['changelog'])

    def open_edit_game_ids(self):
        edit_window = EditGameIDWindow(self.parent())
        edit_window.exec_()

    def open_config_folder(self):
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
                    except Exception as e:
                        logging.error(f"Failed to fetch name for {game_id}: {e}")

            if updated:
                self.parent().save_game_ids()
                self.parent().populate_gameid_combo()
                QMessageBox.information(self, "Success", "Game ID database updated")
            else:
                QMessageBox.information(self, "Info", "No updates needed")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Update failed: {str(e)}")

    def delete_config_folder(self):
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete the entire configuration folder?\n\n{SteamClipApp.CONFIG_DIR}\n\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                shutil.rmtree(SteamClipApp.CONFIG_DIR)
                QMessageBox.information(self, "Deletion Complete", "Configuration folder has been deleted.\nThe application will now close.")
                QApplication.quit()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete configuration folder:\n{str(e)}")

class EditGameIDWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Edit Game Names")
        self.setFixedSize(400, 300)
        self.layout = QVBoxLayout()
        self.table_widget = QTableWidget()
        self.populate_table()
        self.layout.addWidget(self.table_widget)
        self.layout.addLayout(self.create_button_layout())
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
            name_item.setData(Qt.UserRole, game_id)
            self.table_widget.setItem(row, 0, name_item)
        self.table_widget.horizontalHeader().setStretchLastSection(True)

    def create_button_layout(self):
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.create_button("Cancel", self.reject))
        button_layout.addWidget(self.create_button("Apply Changes", self.save_changes))
        return button_layout

    def create_button(self, text, slot):
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def save_changes(self):
        updated_game_names = {}
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 0)
            if item:
                game_id = item.data(Qt.UserRole)
                new_name = item.text()
                updated_game_names[game_id] = new_name
        game_ids_file = os.path.join(SteamClipApp.CONFIG_DIR, 'GameIDs.json')
        with open(game_ids_file, 'w') as f:
            json.dump(updated_game_names, f, indent=4)
        QMessageBox.information(self, "Info", "Game names saved successfully.")
        self.parent().load_game_ids()
        self.parent().populate_gameid_combo()


if __name__ == "__main__":
    sys.excepthook = handle_exception
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
        sys.exit(app.exec_())
    except Exception as e:
        handle_exception(type(e), e, e.__traceback__)
