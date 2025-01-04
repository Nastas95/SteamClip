SteamClip - Steam Recording to MP4 Converter

SteamClip is a simple BASH script that allows you to convert Steam game recordings into .mp4 files.

# **WHY**

Steam uses m4s file format for video and audio that then are layered in a single video output.
Exporting to mp4 from Steam itself is possible, but that leads to heavy visual artifacts in my testing.
Those artifacts are not present when using ffmpeg to convert m4s files to mp4 (or other formats)

I made this script just to be able to save non glitchy .mp4 clips and share them to my phone via Kde connect, especially clips longer than 1 minute


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

1. Run the script by double clicking it. Upon launch the program will check if the userdata folder containing your SteamID
is in the default directory **(~/.local/share/Steam/userdata)** or previusly selected custom directory.
If for some reason the expected userdata folder is invalid, the program will prompt you to select a valid userdata folder. Config file is located in ~/.config/SteamClip
If you have multiple Steam profiles, the script will ask you to select the correct SteamID
   
3. After selecting the SteamID, an available list of clips will be shown.
4. Select a clip and an interactive preview will be displayed.
5. Confirm and the script will convert the clip to an MP4 file.
   The converted file will be saved to your Desktop.

# **REQUIREMENTS**

SteamOs and Bazzite should run out of the box
in case of missing dependencies on immutable distros: SteamClip works fine under Boxbuddy/Distrobox

* Linux (Tested on SteamOS and Bazzite).
* ffmpeg (Make sure it is installed):

        sudo apt install ffmpeg    # On Ubuntu/Debian
  
        sudo dnf install ffmpeg    # On Fedora

        sudo pacman -S ffmpeg      #On Arch

* kdialog for dialog boxes (usually pre-installed on KDE environments, but can be installed if necessary):

        sudo apt install kdialog   # On Ubuntu/Debian
  
        sudo dnf install kdialog   # On Fedora

        sudo pacman -S kdialog     #On Arch

* Steam installed with recordings in the default folder ~/.local/share/Steam/userdata/<steamID>/gamerecordings/clips.

# **LICENSE**

Distributed under the MIT License. See LICENSE for more information.
