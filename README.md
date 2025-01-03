SteamClip - Steam Recording to MP4 Converter

SteamClip is a simple BASH script that allows you to convert Steam game recordings into .mp4 files.
Features

    Converts Steam recordings to MP4 format.
    Easy to use, with a simple user interface.
    Works by selecting the clip via an interactive prompt.
    Saves the final converted file to the Desktop.

Installation

    Download or clone the repository.
    Place the SteamClip.sh file in any directory.
    Grant execution permissions:

    chmod +x SteamClip.sh

Usage

    Run the script by double clicking it

    If you have multiple Steam profiles, the script will ask you to select the correct SteamID.
    After selecting the SteamID, an available list of clips will be shown.
    Select a clip and an interactive preview will be displayed.
    Confirm the preview and the script will convert the clip to an MP4 file.
    The converted file will be saved to your Desktop.

Requirements

    Linux (Tested on SteamOS and Bazzite).
    ffmpeg (Make sure it is installed):

sudo apt install ffmpeg    # On Ubuntu/Debian
sudo dnf install ffmpeg    # On Fedora

    kdialog for dialog boxes (usually pre-installed on KDE environments, but can be installed if necessary):

sudo apt install kdialog   # On Ubuntu/Debian
sudo dnf install kdialog   # On Fedora

    Steam installed with recordings in the default folder ~/.local/share/Steam/userdata/<steamID>/gamerecordings/clips.

License

Distributed under the MIT License. See LICENSE for more information.
