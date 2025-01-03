SteamClip - Steam Recording to MP4 Converter

SteamClip is a simple BASH script that allows you to convert Steam game recordings into .mp4 files.

# **FEATURES**

* Converts Steam recordings to MP4 format.
* Easy to use, with a simple user interface.
* Works by selecting the clip via an interactive prompt.
* Saves the final converted file to the Desktop.

# **INSTALLATION**

1. Download SteamClip.sh from the Release page or clone the repository.
2. Place the SteamClip.sh file in any directory.
3. Grant execution permissions:

        chmod +x SteamClip.sh

# **USAGE**

1. Run the script by double clicking it
   If you have multiple Steam profiles, the script will ask you to select the correct SteamID.
   
2. After selecting the SteamID, an available list of clips will be shown.
3. Select a clip and an interactive preview will be displayed.
4. Confirm and the script will convert the clip to an MP4 file.
   The converted file will be saved to your Desktop.

# **REQUIREMENTS**

* Linux (Tested on SteamOS and Bazzite).
* ffmpeg (Make sure it is installed):

        sudo apt install ffmpeg    # On Ubuntu/Debian
  
        sudo dnf install ffmpeg    # On Fedora

* kdialog for dialog boxes (usually pre-installed on KDE environments, but can be installed if necessary):

        sudo apt install kdialog   # On Ubuntu/Debian
  
        sudo dnf install kdialog   # On Fedora

* Steam installed with recordings in the default folder ~/.local/share/Steam/userdata/<steamID>/gamerecordings/clips.

# **LICENSE**

Distributed under the MIT License. See LICENSE for more information.
