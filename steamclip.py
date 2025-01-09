#!/usr/bin/env python3

import os
import sys
import subprocess
import json
import bz2
import imageio_ffmpeg as iio
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QGridLayout,
                             QFrame, QListWidget, QMessageBox, QComboBox, QDialog, QTableWidget, QTableWidgetItem, QSizePolicy, QHeaderView, QFileDialog)
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import Qt


# Main application class for the SteamClip GUI
class SteamClipApp(QWidget):
    # Configuration constants
    CONFIG_DIR = os.path.expanduser("~/.config/SteamClip")
    CONFIG_FILE = os.path.join(CONFIG_DIR, 'SteamClip.conf')
    GAME_IDS_FILE = os.path.join(CONFIG_DIR, 'GameIDs.txt')
    GAME_IDS_BZ2_FILE = os.path.join(CONFIG_DIR, 'GameIDs.txt.bz2')
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

        # Load game IDs from file
        self.load_game_ids()

        # Set up the UI components
        self.setup_ui()
        # Populate the SteamID directories
        self.populate_steamid_dirs()

    def load_default_directory(self):
        # Create the configuration directory if it does not exist
        os.makedirs(self.CONFIG_DIR, exist_ok=True)

        # Check if the configuration file exists
        if os.path.exists(self.CONFIG_FILE):
            # Read the path from the configuration file
            default_dir = open(self.CONFIG_FILE, 'r').read().strip()
            # Check if the path exists
            if not os.path.isdir(default_dir):
                self.show_info("Please select a valid userdata folder")
                self.default_dir = self.select_userdata_folder()  # Opens folder selection dialog
                self.save_default_directory(self.default_dir)  # Save new path to the configuration file
                return self.default_dir
            return default_dir
        else:
            # If the file does not exist, create it and write the default path
            with open(self.CONFIG_FILE, 'w') as f:
                f.write(self.DEFAULT_USERDATA_DIR)
            return self.DEFAULT_USERDATA_DIR

    def select_userdata_folder(self):
        # Folder selection dialog
        folder = QFileDialog.getExistingDirectory(self, "Select Userdata Folder", "")
        return folder if folder else self.DEFAULT_USERDATA_DIR  # Return default path if not selected

    def save_default_directory(self, directory):
        # Save the selected path to the configuration file
        with open(self.CONFIG_FILE, 'w') as f:
            f.write(directory)

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

        # Create a button for Settings
        self.settings_button = QPushButton()
        self.settings_button.setIcon(QIcon.fromTheme("preferences-system"))
        self.settings_button.setToolTip("Settings")
        self.settings_button.setFixedSize(30, 30)  # Set fixed size for the button
        self.settings_button.clicked.connect(self.open_settings)

        # Create a horizontal layout for the dropdowns and the settings button
        self.id_selection_layout = QHBoxLayout()
        self.id_selection_layout.addWidget(self.settings_button)
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

    def is_connected(self):
        """Check internet connectivity by pinging a known address."""
        try:
            # Use the 'ping' command to check connectivity to 1.1.1.1
            output = subprocess.run(["ping", "-c", "1", "1.1.1.1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return output.returncode == 0
        except Exception as e:
            print(f"Ping failed: {e}")
            return False

    def fetch_game_ids(self):
        """Fetch game IDs from the Steam API using curl and save them to a compressed file."""
        command = ['curl', '-s', self.STEAM_API_URL]
        try:
            result = subprocess.run(command, capture_output=True, check=True)
            with bz2.open(self.GAME_IDS_BZ2_FILE, 'wt', encoding='utf-8') as f:
                f.write(result.stdout.decode('utf-8'))
            self.show_info("Game IDs Downloaded in config folder")
        except subprocess.CalledProcessError as e:
            self.show_error(f"Failed to fetch game names from Steam API: {e}")

    def load_game_ids(self):
        """Load game IDs from the saved compressed file, showing a message if download is needed."""
        if not os.path.exists(self.GAME_IDS_BZ2_FILE):
            QMessageBox.information(self, "Info", "SteamClip will now try to download the GameID database. Please, be patient.")
            self.fetch_game_ids()

        try:
            with bz2.open(self.GAME_IDS_BZ2_FILE, 'rt', encoding='utf-8') as f:
                data = json.load(f)
                self.game_ids = {str(game['appid']): game['name'] for game in data.get('applist', {}).get('apps', [])}

            # Load custom GameIDs
            custom_game_ids_file = os.path.join(self.CONFIG_DIR, 'CustomGameIDs.json')
            if os.path.exists(custom_game_ids_file):
                with open(custom_game_ids_file, 'r') as f:
                    custom_game_ids = json.load(f)
                    # Override the game names with custom GameIDs
                    for game_id, game_name in custom_game_ids.items():
                        self.game_ids[game_id] = game_name

        except (json.JSONDecodeError, KeyError) as e:
            self.show_error(f"Error loading Game IDs: {e}")
            self.game_ids = {}  # Reset game_ids to an empty dictionary

    def get_game_name(self, game_id):
        """Get the game name or return the GameID if not found."""
        if game_id == "downloaded":
            return "Downloaded"  # Handle case-sensitive exception
        return self.game_ids.get(game_id, f"GameID {game_id}")

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

    def show_clip_selection(self, userdata_dir):
        # Show available clips for the selected SteamID
        clips_dir = os.path.join(userdata_dir, 'gamerecordings', 'clips')
        if not os.path.isdir(clips_dir):
            self.show_error(f"Clip directory not found in {userdata_dir}")
            return

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
            game_name = self.get_game_name(game_id)
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
        pixmap = QPixmap(thumbnail_path).scaled(300, 180, Qt.KeepAspectRatio)  # Scale the thumbnail
        thumbnail_label = QLabel()
        thumbnail_label.setPixmap(pixmap)
        thumbnail_label.setAlignment(Qt.AlignCenter)
        thumbnail_label.setStyleSheet("border: none; padding: 0; margin: 0;")  # Remove padding and margins
        thumbnail_label.mousePressEvent = lambda event: self.select_clip(folder, thumbnail_label)
        self.clip_grid.addWidget(thumbnail_label, index // 3, index % 3)

    def update_navigation_buttons(self):
        # Enable or disable navigation buttons based on the current clip index
        self.prev_button.setEnabled(self.clip_index > 0)
        self.next_button.setEnabled(self.clip_index + 6 < len(self.clip_folders))

    def select_clip(self, folder, label):
        # Handle selecting a clip from the displayed thumbnails
        if hasattr(self, 'selected_clip_folder') and self.selected_clip_folder:
            self.selected_clip_folder.setStyleSheet("border: none; padding: 0; margin: 0;")  # Clear previous selection

        label.setStyleSheet("border: 3px solid lightblue; padding: 0; margin: 0;")  # Snug border style
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

    def open_settings(self):
        # Open the settings window as a modal dialog
        self.settings_window = SettingsWindow(self)
        self.settings_window.exec_()  # Execute the dialog


# Settings window class
class SettingsWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(300, 200)

        layout = QVBoxLayout()

        # Create buttons for settings actions with icons
        self.open_config_button = QPushButton("Open Config Folder")
        self.open_config_button.setIcon(QIcon.fromTheme("folder-open"))
        self.open_config_button.clicked.connect(self.open_config_folder)

        self.update_game_ids_button = QPushButton("Update GameIDs")
        self.update_game_ids_button.setIcon(QIcon.fromTheme("view-refresh"))
        self.update_game_ids_button.clicked.connect(self.update_game_ids)

        self.edit_game_id_button = QPushButton("Edit GameID")
        self.edit_game_id_button.setIcon(QIcon.fromTheme("edit-rename"))
        self.edit_game_id_button.clicked.connect(self.edit_game_ids)

        self.close_settings_button = QPushButton("Close Settings")
        self.close_settings_button.setIcon(QIcon.fromTheme("window-close"))
        self.close_settings_button.clicked.connect(self.close)

        # Add buttons to the layout without stretchable space
        layout.addWidget(self.open_config_button)
        layout.addWidget(self.update_game_ids_button)
        layout.addWidget(self.edit_game_id_button)  # Add Edit GameID button
        layout.addWidget(self.close_settings_button)

        self.setLayout(layout)

    def edit_game_ids(self):
        # Open a dialog window to edit GameIDs
        self.edit_window = EditGameIDWindow(self.parent())
        self.edit_window.exec_()  # Execute the dialog

    def open_config_folder(self):
        # Open the configuration folder in the system's file explorer
        config_folder = SteamClipApp.CONFIG_DIR
        if sys.platform.startswith('linux'):
            subprocess.run(['xdg-open', config_folder])
        elif sys.platform == 'darwin':
            subprocess.run(['open', config_folder])
        elif sys.platform == 'win32':
            subprocess.run(['explorer', config_folder])

    def update_game_ids(self):
        # Check internet connectivity and update GameIDs
        if not self.parent().is_connected():
            QMessageBox.warning(self, "Warning", "Download Failed, GameIDs not updated!")
            return

        self.parent().fetch_game_ids()
        self.parent().load_game_ids()

        # Refresh the GameID dropdown in the parent
        self.parent().populate_gameid_combo()


class EditGameIDWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Edit GameIDs")
        self.setFixedSize(400, 300)  # Set a fixed size for the window

        self.layout = QVBoxLayout()
        self.table_widget = QTableWidget()

        # Get the GameIDs from the GameID dropdown
        self.game_ids = {self.parent().gameid_combo.itemData(i): self.parent().gameid_combo.itemText(i)
                         for i in range(self.parent().gameid_combo.count())}

        # Filter out "All Games" from the GameIDs
        filtered_game_ids = {game_id: game_name for game_id, game_name in self.game_ids.items() if game_name != "All Games"}

        # Set the table
        self.table_widget.setRowCount(len(filtered_game_ids))
        self.table_widget.setColumnCount(2)
        self.table_widget.setHorizontalHeaderLabels(["GameID", "Game Name"])

        # Populate the table with filtered data
        row = 0  # Initialize row counter for the table
        for game_id, game_name in filtered_game_ids.items():
            # Create the GameID item (non-editable)
            game_id_item = QTableWidgetItem(game_id)
            game_id_item.setFlags(Qt.ItemIsEnabled)  # Make GameID non-editable
            self.table_widget.setItem(row, 0, game_id_item)

            # Create the Game Name item (editable)
            name_item = QTableWidgetItem(game_name) if game_name else QTableWidgetItem("")
            self.table_widget.setItem(row, 1, name_item)  # Game Name editable

            row += 1  # Increment row counter for the next item

        # Set header stretch to fit the window width
        header = self.table_widget.horizontalHeader()
        header.setStretchLastSection(True)  # The last column will stretch to fill available space
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Resize first column to contents
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Stretch the second column to fill remaining space

        self.layout.addWidget(self.table_widget)

        # Create a horizontal layout for the buttons
        button_layout = QHBoxLayout()

        # Add a cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # Set size policy
        self.cancel_button.clicked.connect(self.reject)  # Close the dialog without saving changes
        button_layout.addWidget(self.cancel_button)

        # Add a button to save changes
        self.save_button = QPushButton("Apply Changes")
        self.save_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # Set size policy
        self.save_button.clicked.connect(self.save_changes)
        button_layout.addWidget(self.save_button)

        # Add the button layout to the main layout
        self.layout.addLayout(button_layout)

        self.setLayout(self.layout)

    def save_changes(self):
        """Save the changes made in the table to CustomGameIDs.json and reload GameIDs."""
        custom_game_ids = {}
        for row in range(self.table_widget.rowCount()):
            game_id_item = self.table_widget.item(row, 0)
            name_item = self.table_widget.item(row, 1)

            if game_id_item is not None:
                game_id = game_id_item.text()
            else:
                continue  # Skip this row if there is no Game ID

            game_name = name_item.text() if name_item is not None else ""
            custom_game_ids[game_id] = game_name

        # Save to CustomGameIDs.json
        custom_game_ids_file = os.path.join(SteamClipApp.CONFIG_DIR, 'CustomGameIDs.json')
        with open(custom_game_ids_file, 'w') as f:
            json.dump(custom_game_ids, f, indent=4)

        QMessageBox.information(self, "Info", "Custom GameIDs saved successfully.")

        # Reload GameIDs in the parent SteamClipApp
        self.parent().load_game_ids()

        # Update the GameID dropdown in the parent
        self.parent().populate_gameid_combo()

        self.accept()  # Close the dialog after saving changes


# Application entry point
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SteamClipApp()
    window.show()
    if sys.stdout.isatty():  # Check if output is a terminal
        print("Starting SteamClip application...")
    sys.exit(app.exec_())
