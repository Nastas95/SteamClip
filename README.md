SteamClip - Steam Recording to MP4 Converter

SteamClip is a simple PYTHON script that allows you to convert Steam game recordings into .mp4 files.

# **WHY**

Steam uses m4s file format for video and audio that then are layered in a single video output.
Exporting to mp4 from Steam itself is possible, but that leads to heavy visual artifacts in my testing.
Those artifacts are not present when using ffmpeg to convert m4s files to mp4 (or other formats)

This script was created to save glitch-free .mp4 clips and share them to my phone via Kde connect, especially clips longer than 1 minute


# **FEATURES**

* Converts Steam recordings to MP4 format.
* Intuitive and user-friendly interface designed for effortless video conversion.
* Works by selecting the clip via an interactive prompt.
* Saves the final converted file to the Desktop.
* Customize GameIDs with user-defined names. This is especially useful for Non-Steam apps like EmuDeck

# **INSTALLATION**

1. Download SteamClip from the Release page or clone the repository. Follow the build instructions below to set up the script.
2. Place the SteamClip file in any directory.

Done

# **USAGE**

1. Run SteamClip by double clicking it. Upon launch the program will check if the userdata folder containing your SteamID is in the default directory **(~/.local/share/Steam/userdata)**
 or previously selected custom directory. If for some reason the expected userdata folder is invalid, the program will prompt you to select a valid userdata folder. 
 **Config file is located in ~/.config/SteamClip**

If you have multiple Steam profiles, SteamClip will show you a list with every (valid) SteamID
   
2. After selecting the SteamID, your clips will show up in a 3x2 grid with "Next" and "Previous" button to scroll through different Clips.
3. Select a clip from the grid and click "Convert Clip". SteamClip will convert the clip to an MP4 file and save it to your Desktop.

In case of missing **STEAM** Game Name (I.E. New Game release from Steam) you can manually update GameIDs in settings. 
**NOTE: You can now set a custom name for ANY app in SteamClip Settings, Non-Steam apps included.**

# **REQUIREMENTS**

SteamClip should run out of the box on any Linux distro!

An internet connection is required for SteamClip to be able to download GameIds: upon launch SteamClip tries to download the Steam appID (GameID) from [this source](https://api.steampowered.com/ISteamApps/GetAppList/v2/) and save it to the config folder

# **BUILD INSTRUCTIONS AND REQUIREMENTS**
SteamClip is a simple standalone Python script with Ffmpeg built-in.
Download this repo, put SteamClip.py and SteamClip.spec in the same directory, then run
`pyinstaller SteamClip.spec`

Once the build is complete, you will find the executable in the dist folder.

## Requirements
* Python 3.6 or above
* pyinstaller ( `pip install pyinstaller` )
* PyQt5  ( `pip install PyQt5` )
* imageio[ffmpeg] ( `pip install imageio[ffmpeg]` )

# **LICENSE**

Distributed under the GPL-3 License. See LICENSE for more information.
