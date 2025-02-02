#!/usr/bin/env python3

import os
import sys
import subprocess
import json
import bz2
import imageio_ffmpeg as iio
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QGridLayout,
                             QFrame, QComboBox, QDialog, QTableWidget,
                             QTableWidgetItem, QSizePolicy, QHeaderView,
                             QMessageBox, QFileDialog)
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import Qt
from datetime import datetime
import webbrowser

class SteamClipApp(QWidget):
    CONFIG_DIR = os.path.expanduser("~/.config/SteamClip")
    CONFIG_FILE = os.path.join(CONFIG_DIR, 'SteamClip.conf')
    GAME_IDS_FILE = os.path.join(CONFIG_DIR, 'GameIDs.txt')
    GAME_IDS_BZ2_FILE = os.path.join(CONFIG_DIR, 'GameIDs.txt.bz2')
    STEAM_API_URL = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
    CURRENT_VERSION = "v2.7.1"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SteamClip")
        self.setGeometry(100, 100, 900, 600)

        self.clip_index = 0
        self.clip_folders = []
        self.original_clip_folders = []
        self.game_ids = {}

        self.default_dir = self.check_and_load_userdata_folder()
        self.load_game_ids()
        self.setup_ui()
        self.populate_steamid_dirs()
        self.check_for_updates_at_startup()

    def check_for_updates_at_startup(self):
        version_file_path = os.path.join(self.CONFIG_DIR, 'Version.txt')

        if not os.path.exists(version_file_path):
            with open(version_file_path, 'w') as version_file:
                version_file.write(self.CURRENT_VERSION)
        else:
            with open(version_file_path, 'r') as version_file:
                file_version = version_file.read().strip()

            if file_version != self.CURRENT_VERSION:
                with open(version_file_path, 'w') as version_file:
                    version_file.write(self.CURRENT_VERSION)

        self.check_for_updates()  # Call check for updates at startup

    def check_for_updates(self):
        version_file_path = os.path.join(self.CONFIG_DIR, 'Version.txt')
        with open(version_file_path, 'r') as version_file:
            file_version = version_file.read().strip()

        latest_release = self.get_latest_release_from_github()

        if latest_release and latest_release != file_version:
            self.prompt_update()
        elif latest_release == file_version:
            # Removed this line to prevent showing the message at startup
            pass

    def get_latest_release_from_github(self):
        url = "https://api.github.com/repos/Nastas95/SteamClip/releases/latest"
        command = ['curl', '-s', url]

        try:
            result = subprocess.run(command, capture_output=True, check=True, text=True)
            latest_release_info = json.loads(result.stdout)
            return latest_release_info['tag_name']
        except subprocess.CalledProcessError as e:
            print(f"Error fetching latest release: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")
            return None

    def prompt_update(self):
        reply = QMessageBox.question(self, "Update Available",
                                     "A new update is available. Update now?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            webbrowser.open("https://github.com/Nastas95/SteamClip/releases/latest")

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
                userdata_path = os.path.expanduser("~/.local/share/Steam/userdata")
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
        with open(self.CONFIG_FILE, 'w') as f:
            f.write(directory)

    def load_game_ids(self):
        if not os.path.exists(self.GAME_IDS_BZ2_FILE):
            QMessageBox.information(self, "Info", "SteamClip will now try to download the GameID database. Please, be patient.")
            self.fetch_game_ids()

        try:
            with bz2.open(self.GAME_IDS_BZ2_FILE, 'rt', encoding='utf-8') as f:
                data = json.load(f)
                self.game_ids = {str(game['appid']): game['name'] for game in data.get('applist', {}).get('apps', [])}

            self.load_custom_game_ids()
        except (json.JSONDecodeError, KeyError) as e:
            self.show_error(f"Error loading Game IDs: {e}")
            self.game_ids = {}

    def load_custom_game_ids(self):
        custom_game_ids_file = os.path.join(self.CONFIG_DIR, 'CustomGameIDs.json')
        if os.path.exists(custom_game_ids_file):
            with open(custom_game_ids_file, 'r') as f:
                custom_game_ids = json.load(f)
                self.game_ids.update(custom_game_ids)

    def get_game_name(self, game_id):
        return self.game_ids.get(game_id, f"GameID {game_id}")

    def setup_ui(self):
        self.steamid_combo = QComboBox()
        self.steamid_combo.currentIndexChanged.connect(self.on_steamid_selected)

        self.gameid_combo = QComboBox()
        self.gameid_combo.currentIndexChanged.connect(self.filter_clips_by_gameid)

        self.clip_frame, self.clip_grid = self.create_clip_layout()
        self.bottom_layout = self.create_bottom_layout()

        self.settings_button = self.create_button("", self.open_settings, icon="preferences-system", size=(30, 30))

        self.id_selection_layout = QHBoxLayout()
        self.id_selection_layout.addWidget(self.settings_button)
        self.id_selection_layout.addWidget(self.steamid_combo)
        self.id_selection_layout.addWidget(self.gameid_combo)

        self.main_layout = QVBoxLayout()
        self.main_layout.addLayout(self.id_selection_layout)
        self.main_layout.addWidget(self.clip_frame)
        self.main_layout.addLayout(self.bottom_layout)

        self.setLayout(self.main_layout)

    def create_clip_layout(self):
        clip_grid = QGridLayout()
        clip_frame = QFrame()
        clip_frame.setLayout(clip_grid)
        return clip_frame, clip_grid

    def create_bottom_layout(self):
        self.convert_button = self.create_button("Convert Clip", self.convert_clip, enabled=False)
        self.exit_button = self.create_button("Exit", self.close)
        self.prev_button = self.create_button("<< Previous", self.show_previous_clips)
        self.next_button = self.create_button("Next >>", self.show_next_clips)

        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self.prev_button)
        bottom_layout.addWidget(self.next_button)
        bottom_layout.addWidget(self.convert_button)
        bottom_layout.addWidget(self.exit_button)

        return bottom_layout

    def create_button(self, text, slot, enabled=True, icon=None, size=None):
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
            output = subprocess.run(["ping", "-c", "1", "1.1.1.1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return output.returncode == 0
        except Exception as e:
            print(f"Ping failed: {e}")
            return False

    def fetch_game_ids(self):
        command = ['curl', '-s', self.STEAM_API_URL]
        try:
            result = subprocess.run(command, capture_output=True, check=True)
            with bz2.open(self.GAME_IDS_BZ2_FILE, 'wt', encoding='utf-8') as f:
                f.write(result.stdout.decode('utf-8'))
            self.show_info("Game IDs Downloaded in config folder")
        except subprocess.CalledProcessError as e:
            self.show_error(f"Failed to fetch game names from Steam API: {e}")

    def populate_steamid_dirs(self):
        if not os.path.isdir(self.default_dir):
            self.show_error("Default Steam userdata directory not found.")
            return

        self.steamid_combo.clear()
        for entry in os.scandir(self.default_dir):
            if entry.is_dir() and entry.name.isdigit():
                clips_dir = os.path.join(self.default_dir, entry.name, 'gamerecordings', 'clips')
                if os.path.isdir(clips_dir):
                    self.steamid_combo.addItem(entry.name)

    def on_steamid_selected(self):
        selected_steamid = self.steamid_combo.currentText()
        userdata_dir = os.path.join(self.default_dir, selected_steamid)
        self.show_clip_selection(userdata_dir)

    def clear_clip_grid(self):
        for i in range(self.clip_grid.count()):
            widget = self.clip_grid.itemAt(i).widget()
            if widget:
                widget.deleteLater()

    def show_clip_selection(self, userdata_dir):
        clips_dir = os.path.join(userdata_dir, 'gamerecordings', 'clips')
        if not os.path.isdir(clips_dir):
            self.show_error(f"Clip directory not found in {userdata_dir}")
            return

        clip_folders = [folder.path for folder in os.scandir(clips_dir) if folder.is_dir() and "_" in folder.name]
        self.clip_folders = sorted(clip_folders, key=lambda x: self.extract_datetime_from_folder_name(x), reverse=True)
        self.original_clip_folders = list(self.clip_folders)
        self.populate_gameid_combo()
        self.display_clips()

    def extract_datetime_from_folder_name(self, folder_name):
        parts = folder_name.split('_')
        if len(parts) >= 3:
            datetime_str = parts[-2] + parts[-1]
            return datetime.strptime(datetime_str, "%Y%m%d%H%M%S")
        return datetime.min

    def populate_gameid_combo(self):
        game_ids_in_clips = {folder.split('_')[1] for folder in self.clip_folders}
        sorted_game_ids = sorted(game_ids_in_clips)
        self.gameid_combo.clear()
        self.gameid_combo.addItem("All Games")
        for game_id in sorted_game_ids:
            self.gameid_combo.addItem(self.get_game_name(game_id), game_id)

    def filter_clips_by_gameid(self):
        selected_index = self.gameid_combo.currentIndex()
        if selected_index == 0:
            self.clip_folders = self.original_clip_folders
        else:
            selected_game_id = self.gameid_combo.itemData(selected_index)
            self.clip_index = 0
            self.clip_folders = [folder for folder in self.original_clip_folders if f'_{selected_game_id}_' in folder]
        self.display_clips()

    def display_clips(self):
        self.selected_clip_folder = None
        self.clear_clip_grid()
        clips_to_show = self.clip_folders[self.clip_index:self.clip_index + 6]

        for index, folder in enumerate(clips_to_show):
            thumbnail_path = os.path.join(folder, 'thumbnail.jpg')
            if os.path.exists(thumbnail_path):
                self.add_thumbnail_to_grid(thumbnail_path, folder, index)

        self.update_navigation_buttons()

    def add_thumbnail_to_grid(self, thumbnail_path, folder, index):
        pixmap = QPixmap(thumbnail_path).scaled(300, 180, Qt.KeepAspectRatio)
        thumbnail_label = QLabel()
        thumbnail_label.setPixmap(pixmap)
        thumbnail_label.setAlignment(Qt.AlignCenter)
        thumbnail_label.setStyleSheet("border: none; padding: 0; margin: 0;")
        thumbnail_label.mousePressEvent = lambda event: self.select_clip(folder, thumbnail_label)
        self.clip_grid.addWidget(thumbnail_label, index // 3, index % 3)

    def update_navigation_buttons(self):
        self.prev_button.setEnabled(self.clip_index > 0)
        self.next_button.setEnabled(self.clip_index + 6 < len(self.clip_folders))

    def select_clip(self, folder, label):
        if hasattr(self, 'selected_clip_folder') and self.selected_clip_folder:
            self.selected_clip_folder.setStyleSheet("border: none; padding: 0; margin: 0;")

        label.setStyleSheet("border: 3px solid lightblue; padding: 0; margin: 0;")
        self.selected_clip_folder = label
        self.selected_clip = folder
        self.convert_button.setEnabled(True)

    def show_previous_clips(self):
        if self.clip_index - 6 >= 0:
            self.clip_index -= 6
            self.display_clips()

    def show_next_clips(self):
        if self.clip_index + 6 < len(self.clip_folders):
            self.clip_index += 6
            self.display_clips()

    def convert_clip(self):
        if not hasattr(self, 'selected_clip_folder'):
            self.show_error("No valid clip selected for conversion.")
            return

        session_mpd_file = self.find_session_mpd(self.selected_clip)
        if not session_mpd_file:
            self.show_error("session.mpd file not found in selected clip.")
            return

        output_file = self.get_unique_filename(os.path.expanduser("~/Desktop"), "clip.mp4")
        ffmpeg_path = iio.get_ffmpeg_exe()

        try:
            subprocess.run([ffmpeg_path, '-i', session_mpd_file, '-c', 'copy', output_file], check=True)
            self.show_info(f"Conversion completed successfully: {output_file}")
        except subprocess.CalledProcessError:
            self.show_error("Error during file conversion.")

    def find_session_mpd(self, clip_folder):
        video_dir = os.path.join(clip_folder, 'video')
        for root, _, files in os.walk(video_dir):
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

class SteamVersionSelectionDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Select Steam Version")
        self.setFixedSize(300, 150)

        layout = QVBoxLayout()

        self.standard_button = QPushButton("Standard")
        self.flatpak_button = QPushButton("Flatpak")
        self.manual_button = QPushButton("Select the userdata folder manually")

        self.standard_button.clicked.connect(lambda: self.accept_and_set("Standard"))
        self.flatpak_button.clicked.connect(lambda: self.accept_and_set("Flatpak"))
        self.manual_button.clicked.connect(self.select_userdata_folder)

        layout.addWidget(QLabel("What version of Steam are you using?"))
        layout.addWidget(self.standard_button)
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

    def is_valid_userdata_folder(self, folder):
        if not os.path.basename(folder) == "userdata":
            print(f"Invalid: Folder name is not 'userdata'. Found: {os.path.basename(folder)}")
            return False

        valid_user_data = False
        steam_id_dirs = [d for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d)) and d.isdigit()]

        if not steam_id_dirs:
            print("Invalid: No numeric SteamID directories found.")
            return False

        for steam_id in steam_id_dirs:
            clips_path = os.path.join(folder, steam_id, 'gamerecordings', 'clips')
            if os.path.isdir(clips_path):
                valid_user_data = True
                print(f"Valid: Found 'gamerecordings/clips' for SteamID {steam_id}.")
                break

        if not valid_user_data:
            print("Invalid: No 'gamerecordings/clips' found in any SteamID.")
        return valid_user_data

    def get_selected_option(self):
        return self.selected_version

class SettingsWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(300, 200)

        layout = QVBoxLayout()

        self.open_config_button = self.create_button("Open Config Folder", self.open_config_folder, "folder-open")
        self.update_game_ids_button = self.create_button("Update GameIDs", self.update_game_ids, "view-refresh")
        self.check_for_updates_button = self.create_button("Check for Updates", self.check_for_updates, "view-refresh")
        self.close_settings_button = self.create_button("Close Settings", self.close, "window-close")

        layout.addWidget(self.open_config_button)
        layout.addWidget(self.update_game_ids_button)
        layout.addWidget(self.check_for_updates_button)
        layout.addWidget(self.close_settings_button)

        self.setLayout(layout)

    def create_button(self, text, slot, icon=None):
        button = QPushButton(text)
        button.clicked.connect(slot)
        if icon:
            button.setIcon(QIcon.fromTheme(icon))
        return button

    def check_for_updates(self):
        self.parent().check_for_updates()

    def open_config_folder(self):
        config_folder = SteamClipApp.CONFIG_DIR
        if sys.platform.startswith('linux'):
            subprocess.run(['xdg-open', config_folder])
        elif sys.platform == 'darwin':
            subprocess.run(['open', config_folder])
        elif sys.platform == 'win32':
            subprocess.run(['explorer', config_folder])

    def update_game_ids(self):
        if not self.parent().is_connected():
            QMessageBox.warning(self, "Warning", "Download Failed, GameIDs not updated!")
            return

        self.parent().fetch_game_ids()
        self.parent().load_game_ids()
        self.parent().populate_gameid_combo()

class EditGameIDWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Edit GameIDs")
        self.setFixedSize(400, 300)

        self.layout = QVBoxLayout()
        self.table_widget = QTableWidget()
        self.populate_table()

        self.layout.addWidget(self.table_widget)
        self.layout.addLayout(self.create_button_layout())
        self.setLayout(self.layout)

    def populate_table(self):
        self.game_ids = {self.parent().gameid_combo.itemData(i): self.parent().gameid_combo.itemText(i)
                         for i in range(self.parent().gameid_combo.count())}
        filtered_game_ids = {game_id: game_name for game_id, game_name in self.game_ids.items() if game_name != "All Games"}

        self.table_widget.setRowCount(len(filtered_game_ids))
        self.table_widget.setColumnCount(2)
        self.table_widget.setHorizontalHeaderLabels(["GameID", "Game Name"])

        for row, (game_id, game_name) in enumerate(filtered_game_ids.items()):
            self.table_widget.setItem(row, 0, QTableWidgetItem(game_id))
            name_item = QTableWidgetItem(game_name)
            self.table_widget.setItem(row, 1, name_item)

        self.table_widget.horizontalHeader().setStretchLastSection(True)
        self.table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_widget.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

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
        custom_game_ids = {self.table_widget.item(row, 0).text(): self.table_widget.item(row, 1).text()
                           for row in range(self.table_widget.rowCount()) if self.table_widget.item(row, 0)}

        custom_game_ids_file = os.path.join(SteamClipApp.CONFIG_DIR, 'CustomGameIDs.json')
        with open(custom_game_ids_file, 'w') as f:
            json.dump(custom_game_ids, f, indent=4)

        QMessageBox.information(self, "Info", "Custom GameIDs saved successfully.")
        self.parent().load_game_ids()
        self.parent().populate_gameid_combo()
        self.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SteamClipApp()
    window.show()
    print("Starting SteamClip application..." if sys.stdout.isatty() else "")
    sys.exit(app.exec_())
