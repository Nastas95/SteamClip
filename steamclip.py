#!/usr/bin/env python3
import os
import sys
import subprocess
import imageio_ffmpeg as iio
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QLabel, QGridLayout, QFrame, QListWidget, QMessageBox
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt

class SteamClipApp(QWidget):
    CONFIG_DIR = os.path.expanduser("~/.config/SteamClip")
    CONFIG_FILE = os.path.join(CONFIG_DIR, 'SteamClip.conf')
    DEFAULT_USERDATA_DIR = os.path.expanduser("~/.local/share/Steam/userdata")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SteamClip")
        self.setGeometry(100, 100, 900, 600)

        self.layout = QHBoxLayout()
        self.default_dir = self.load_default_directory()
        self.clip_index = 0
        self.clip_folders = []

        self.setup_ui()
        self.populate_steamid_dirs()

    def setup_ui(self):
        self.steamid_list = QListWidget()
        self.steamid_label = QLabel("Select SteamID")
        self.left_layout = self.create_left_layout()
        self.clip_frame, self.clip_grid = self.create_clip_layout()
        self.bottom_layout = self.create_bottom_layout()

        self.clip_navigation_layout = QVBoxLayout()
        self.clip_navigation_layout.addWidget(self.clip_frame)
        self.clip_navigation_layout.addLayout(self.bottom_layout)

        self.main_layout = QHBoxLayout()
        self.main_layout.addLayout(self.left_layout)
        self.main_layout.addLayout(self.clip_navigation_layout)
        self.setLayout(self.main_layout)

    def create_left_layout(self):
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.steamid_label)
        left_layout.addWidget(self.steamid_list)
        return left_layout

    def create_clip_layout(self):
        clip_grid = QGridLayout()
        clip_frame = QFrame()
        clip_frame.setLayout(clip_grid)
        return clip_frame, clip_grid

    def create_bottom_layout(self):
        self.convert_button = self.create_button("Convert Clip", self.convert_clip, False)
        self.exit_button = self.create_button("Exit", self.close)
        self.prev_button = self.create_button("Previous", self.show_previous_clips)
        self.next_button = self.create_button("Next", self.show_next_clips)

        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self.prev_button)
        bottom_layout.addWidget(self.next_button)
        bottom_layout.addWidget(self.convert_button)
        bottom_layout.addWidget(self.exit_button)
        return bottom_layout

    def create_button(self, text, slot, enabled=True):
        button = QPushButton(text)
        button.clicked.connect(slot)
        button.setEnabled(enabled)
        return button

    def load_default_directory(self):
        os.makedirs(self.CONFIG_DIR, exist_ok=True)
        if os.path.exists(self.CONFIG_FILE):
            with open(self.CONFIG_FILE, 'r') as file:
                default_dir = file.read().strip()
                if self.is_valid_userdata(default_dir):
                    return default_dir
                else:
                    self.show_error("Invalid directory in configuration.")
                    return self.ask_for_directory()
        else:
            with open(self.CONFIG_FILE, 'w') as file:
                file.write(self.DEFAULT_USERDATA_DIR)
            return self.DEFAULT_USERDATA_DIR

    def ask_for_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Userdata Directory", os.path.expanduser("~"))
        if directory and self.is_valid_userdata(directory):
            with open(self.CONFIG_FILE, 'w') as file:
                file.write(directory)
            return directory
        else:
            self.show_error("No valid directory selected. Exiting.")
            sys.exit(1)

    def is_valid_userdata(self, directory):
        return os.path.isdir(directory) and any(
            f.is_dir() and os.path.isdir(os.path.join(f.path, 'gamerecordings'))
            for f in os.scandir(directory)
        )

    def populate_steamid_dirs(self):
        if os.path.isdir(self.default_dir):
            valid_userdirs = [
                f.path for f in os.scandir(self.default_dir) if f.is_dir() and os.path.isdir(os.path.join(f.path, 'gamerecordings'))
            ]
            self.steamid_list.addItems([os.path.basename(dir) for dir in valid_userdirs])
            self.steamid_list.currentItemChanged.connect(self.on_steamid_selected)

    def on_steamid_selected(self):
        selected_item = self.steamid_list.currentItem()
        if selected_item:
            steamid_dir = selected_item.text()
            self.clear_clip_grid()
            self.show_clip_selection(os.path.join(self.default_dir, steamid_dir))

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

        self.clip_folders = [f.path for f in os.scandir(clips_dir) if f.is_dir()]
        if not self.clip_folders:
            self.show_error("No clips found.")
            return

        self.display_clips()

    def display_clips(self):
        clips_to_show = self.clip_folders[self.clip_index:self.clip_index + 6]
        for index, folder in enumerate(clips_to_show):
            thumbnail_path = os.path.join(folder, 'thumbnail.jpg')
            if os.path.exists(thumbnail_path):
                self.add_thumbnail_to_grid(thumbnail_path, folder, index)

        self.update_navigation_buttons()

    def add_thumbnail_to_grid(self, thumbnail_path, folder, index):
        pixmap = QPixmap(thumbnail_path).scaled(280, 160, Qt.KeepAspectRatio)
        thumbnail_label = QLabel()
        thumbnail_label.setPixmap(pixmap)
        thumbnail_label.setAlignment(Qt.AlignCenter)
        thumbnail_label.setStyleSheet("border: none;")
        thumbnail_label.mousePressEvent = lambda event: self.select_clip(folder, thumbnail_label)
        self.clip_grid.addWidget(thumbnail_label, index // 3, index % 3)

    def update_navigation_buttons(self):
        self.prev_button.setEnabled(self.clip_index > 0)
        self.next_button.setEnabled(self.clip_index + 6 < len(self.clip_folders))

    def select_clip(self, folder, label):
        if hasattr(self, 'selected_clip_folder') and self.selected_clip_folder:
            self.selected_clip_folder.setStyleSheet("border: none;")

        label.setStyleSheet("border: 3px solid lightblue;")
        self.selected_clip_folder = label
        self.selected_clip = folder
        self.convert_button.setEnabled(True)

    def show_previous_clips(self):
        self.clip_index = max(0, self.clip_index - 6)
        self.display_clips()

    def show_next_clips(self):
        self.clip_index = min(len(self.clip_folders) - 6, self.clip_index + 6)
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

        # Use the FFmpeg executable from imageio-ffmpeg
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SteamClipApp()
    window.show()
    sys.exit(app.exec_())
