SteamClip - Steam Recording to MP4 Converter

SteamClip is a simple PYTHON script that allows you to convert Steam game recordings into .mp4 files

# **WHY**

Steam uses m4s file format for video and audio that then are layered in a single video output.

Exporting to mp4 from Steam itself is possible, but that leads to heavy visual artifacts in my testing.

Those artifacts are not present when using ffmpeg to convert m4s files to mp4 (or other formats)

This script was created to save glitch-free .mp4 clips and share them to my phone via Kde connect, especially clips longer than 1 minute


# **FEATURES**

* Converts multiple Steam recordings to MP4 format at once
* Intuitive and user-friendly interface designed for effortless video conversion
* Works by selecting the clip via an interactive prompt
* Saves the final converted file to the Desktop
* Customize GameIDs with user-defined names. This is especially useful for Non-Steam apps like EmuDeck
* Checks for new releases and prompts the user to download the new release from GitHub after showing the Changelog

# **INSTALLATION**

1. Download SteamClip from the [Release page](https://github.com/Nastas95/SteamClip/releases), **steamclip.exe for Windows users** (or clone the repository, follow the build instructions below to set up the script)
2. Place the SteamClip file in any directory

Done

# **USAGE**

1. Run SteamClip by double clicking it. Upon launch the program will ask what Steam version you have installed: Standard (from your distro package manager/if you didn't change install directory **on Windows**) or Flatpak (**Linux Only**)
There is an option to manually select your userdata folder, default directory is **~/.local/share/Steam/userdata** on Linux, **C:\Program Files (x86)\Steam** on Windows

If you have multiple Steam profiles, SteamClip will show you a list with every (valid) SteamID
   
2. After selecting the SteamID, your clips will show up in a 3x2 grid with "Next" and "Previous" button to scroll through different Clips
3. Select one or more clips from the grid and click "Convert Clip(s)". SteamClip will convert the clip(s) to an MP4 file and save it to your Desktop

In case of missing **STEAM** Game Name (I.E. New Game release from Steam) you can manually update GameIDs in settings. 
**NOTE: You can now set a custom name for ANY app in SteamClip Settings, Non-Steam apps included.**

 Config file is located in **~/.config/SteamClip** on Linux, **C:\Users\YOURUSERNAME\AppData\Local\SteamClip** on Windows

# **WINDOWS REQUIREMENTS**
- Windows 10 or above
- (*Optional*) Internet connection (**upon launch SteamClip tries to download the Steam appID (GameID) from [this source](https://store.steampowered.com/api/appdetails) and save it to the config folder, it also tries to fetch the latest version of SteamClip from [GitHub Apis](https://api.github.com/repos/Nastas95/SteamClip/releases/latest)

# **LINUX REQUIREMENTS**
- (*Optional*) Internet connection (**upon launch SteamClip tries to download the Steam appID (GameID) from [this source](https://store.steampowered.com/api/appdetails) and save it to the config folder, it also tries to fetch the latest version of SteamClip from [GitHub Apis](https://api.github.com/repos/Nastas95/SteamClip/releases/latest)

  # DISCLAIMER
   SteamClip does **NOT** collect any data. Internet connection is **NOT** a hard requirement.

# **BUILD INSTRUCTIONS AND REQUIREMENTS**
SteamClip is a simple standalone Python script with Ffmpeg built-in.
Download this repo, put SteamClip.py in any same directory, then run
`pyinstaller --onefile --windowed steamclip.py `

Once the build is complete, you will find the executable inside the **dist** folder.

**You Can build the executables for Linux and Windows via the GitHub Actions!**

## Requirements
* Python 3.6 or above
* pyinstaller ( `pip install pyinstaller` )
* PyQt6  ( `pip install PyQt6` )
* imageio[ffmpeg] ( `pip install imageio[ffmpeg]` )
* pillow ( `pip install pillow` )
* requests ( `pip install requests` )
* pathvalidate ( `pip install pathvalidate` )
