#!/usr/bin/env python3

import os
import sys
import subprocess
import requests
import imageio_ffmpeg as iio
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QGridLayout,
                             QFrame, QListWidget, QMessageBox, QComboBox)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt

# Main application class for the SteamClip GUI
class SteamClipApp(QWidget):
    # Configuration constants
    CONFIG_DIR = os.path.expanduser("~/.config/SteamClip")
    CONFIG_FILE = os.path.join(CONFIG_DIR, 'SteamClip.conf')
    DEFAULT_USERDATA_DIR = os.path.expanduser("~/.local/share/Steam/userdata")
    STEAM_API_URL = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"

    def __init__(self):
        super().__init__()
        # Set up the main window properties
        self.setWindowTitle("SteamClip")
        self.setGeometry(100, 100, 900, 600)
        # Load default directory and initialize variables
        self.default_dir = self.load_default_directory()
        self.clip_index = 0
        self.clip_folders = []
        self.original_clip_folders = []
        self.game_ids = {}
        # Set up the UI components
        self.setup_ui()
        # Populate the SteamID directories
        self.populate_steamid_dirs()

    def setup_ui(self):
        # Create dropdown for SteamID selection
        self.steamid_combo = QComboBox()
        self.steamid_combo.currentIndexChanged.connect(self.on_steamid_selected)

        # Create dropdown for GameID selection
        self.gameid_combo = QComboBox()
        self.gameid_combo.currentIndexChanged.connect(self.filter_clips_by_gameid)

        # Create layout for clip thumbnails
        self.clip_frame, self.clip_grid = self.create_clip_layout()
        # Create layout for navigation and action buttons
        self.bottom_layout = self.create_bottom_layout()

        # Create a horizontal layout for the dropdowns
        self.id_selection_layout = QHBoxLayout()
        self.id_selection_layout.addWidget(self.steamid_combo)
        self.id_selection_layout.addWidget(self.gameid_combo)

        # Set the main layout of the window
        self.main_layout = QVBoxLayout()
        self.main_layout.addLayout(self.id_selection_layout)
        self.main_layout.addWidget(self.clip_frame)
        self.main_layout.addLayout(self.bottom_layout)

        self.setLayout(self.main_layout)

    def create_clip_layout(self):
        # Create a grid layout for displaying clips
        clip_grid = QGridLayout()
        clip_frame = QFrame()
        clip_frame.setLayout(clip_grid)
        return clip_frame, clip_grid

    def create_bottom_layout(self):
        # Create buttons for actions (Convert, Exit, Previous, Next)
        self.convert_button = self.create_button("Convert Clip", self.convert_clip, False)
        self.exit_button = self.create_button("Exit", self.close)
        self.prev_button = self.create_button("<< Previous", self.show_previous_clips)
        self.next_button = self.create_button("Next >>", self.show_next_clips)

        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self.prev_button)
        bottom_layout.addWidget(self.next_button)
        bottom_layout.addWidget(self.convert_button)
        bottom_layout.addWidget(self.exit_button)

        return bottom_layout

    def create_button(self, text, slot, enabled=True):
        # Create a button with specified text and action
        button = QPushButton(text)
        button.clicked.connect(slot)
        button.setEnabled(enabled)
        return button

    def load_default_directory(self):
        # Load the default directory from config or use the default path
        os.makedirs(self.CONFIG_DIR, exist_ok=True)
        if os.path.exists(self.CONFIG_FILE):
            return open(self.CONFIG_FILE, 'r').read().strip()
        return self.DEFAULT_USERDATA_DIR

    def populate_steamid_dirs(self):
        # Populate the SteamID dropdown with directories found in the userdata directory
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
        # Handle selection of SteamID and show corresponding clips
        selected_steamid = self.steamid_combo.currentText()
        userdata_dir = os.path.join(self.default_dir, selected_steamid)
        self.show_clip_selection(userdata_dir)

    def clear_clip_grid(self):
        # Clear the grid layout of any existing clip widgets
        for i in range(self.clip_grid.count()):
            widget = self.clip_grid.itemAt(i).widget()
            if widget:
                widget.deleteLater()

    def fetch_game_names(self):
        # Fetch game names from the Steam API
        try:
            response = requests.get(self.STEAM_API_URL)
            response.raise_for_status()
            games = response.json().get('applist', {}).get('apps', [])
            self.game_ids = {str(game['appid']): game['name'] for game in games}
        except requests.RequestException:
            self.show_error("Failed to fetch game names from Steam API.")

    def show_clip_selection(self, userdata_dir):
        # Show available clips for the selected SteamID
        clips_dir = os.path.join(userdata_dir, 'gamerecordings', 'clips')
        if not os.path.isdir(clips_dir):
            self.show_error(f"Clip directory not found in {userdata_dir}")
            return

        self.fetch_game_names()

        clip_folders = []
        for folder in os.scandir(clips_dir):
            if folder.is_dir() and "_" in folder.name:
                clip_folders.append(folder.path)

        self.clip_folders = sorted(clip_folders, key=lambda x: x.split('_')[-1], reverse=True)
        self.original_clip_folders = list(self.clip_folders)
        self.populate_gameid_combo()
        self.display_clips()

    def populate_gameid_combo(self):
        # Populate the GameID dropdown with available game IDs from the clips
        game_ids_in_clips = {folder.split('_')[1] for folder in self.clip_folders}
        sorted_game_ids = sorted(game_ids_in_clips)
        self.gameid_combo.clear()
        self.gameid_combo.addItem("All Games")
        for game_id in sorted_game_ids:
            game_name = self.game_ids.get(game_id, f"GameID {game_id}")
            self.gameid_combo.addItem(game_name, game_id)

    def filter_clips_by_gameid(self):
        # Filter the clips based on the selected GameID
        selected_index = self.gameid_combo.currentIndex()
        if selected_index == 0:
            self.clip_folders = self.original_clip_folders
        else:
            selected_game_id = self.gameid_combo.itemData(selected_index)
            self.clip_index = 0
            self.clip_folders = [folder for folder in self.original_clip_folders if f'_{selected_game_id}_' in folder]
        self.display_clips()

    def display_clips(self):
        # Display the clips in the grid layout
        self.selected_clip_folder = None
        self.clear_clip_grid()
        clips_to_show = self.clip_folders[self.clip_index:self.clip_index + 6]

        for index, folder in enumerate(clips_to_show):
            thumbnail_path = os.path.join(folder, 'thumbnail.jpg')
            if os.path.exists(thumbnail_path):
                self.add_thumbnail_to_grid(thumbnail_path, folder, index)

        self.update_navigation_buttons()

    def add_thumbnail_to_grid(self, thumbnail_path, folder, index):
        # Add a thumbnail image to the grid layout
        pixmap = QPixmap(thumbnail_path).scaled(300, 180, Qt.KeepAspectRatio)
        thumbnail_label = QLabel()
        thumbnail_label.setPixmap(pixmap)
        thumbnail_label.setAlignment(Qt.AlignCenter)
        thumbnail_label.setStyleSheet("border: none;")
        thumbnail_label.mousePressEvent = lambda event: self.select_clip(folder, thumbnail_label)
        self.clip_grid.addWidget(thumbnail_label, index // 3, index % 3)

    def update_navigation_buttons(self):
        # Enable or disable navigation buttons based on the current clip index
        self.prev_button.setEnabled(self.clip_index > 0)
        self.next_button.setEnabled(self.clip_index + 6 < len(self.clip_folders))

    def select_clip(self, folder, label):
        # Handle selecting a clip from the displayed thumbnails
        if hasattr(self, 'selected_clip_folder') and self.selected_clip_folder:
            self.selected_clip_folder.setStyleSheet("border: none;")

        label.setStyleSheet("border: 3px solid lightblue;")
        self.selected_clip_folder = label
        self.selected_clip = folder
        self.convert_button.setEnabled(True)

    def show_previous_clips(self):
        # Navigate to the previous set of clips
        if self.clip_index - 6 >= 0:
            self.clip_index -= 6
            self.display_clips()

    def show_next_clips(self):
        # Navigate to the next set of clips
        if self.clip_index + 6 < len(self.clip_folders):
            self.clip_index += 6
            self.display_clips()

    def convert_clip(self):
        # Convert the selected clip to an MP4 format
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
        # Search for the session.mpd file within the clip folder
        video_dir = os.path.join(clip_folder, 'video')
        for root, _, files in os.walk(video_dir):
            if 'session.mpd' in files:
                return os.path.join(root, 'session.mpd')
        return None

    def get_unique_filename(self, directory, filename):
        # Generate a unique filename in the specified directory
        base_name, ext = os.path.splitext(filename)
        counter = 1
        unique_filename = os.path.join(directory, filename)

        while os.path.exists(unique_filename):
            unique_filename = os.path.join(directory, f"{base_name}_{counter}{ext}")
            counter += 1

        return unique_filename

    def show_error(self, message):
        # Display an error message to the user
        QMessageBox.critical(self, "Error", message)

    def show_info(self, message):
        # Display an info message to the user
        QMessageBox.information(self, "Info", message)

# Application entry point
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SteamClipApp()
    window.show()
    if sys.stdout.isatty():  # Check if output is a terminal
        print("Starting SteamClip application...")
    sys.exit(app.exec_())
