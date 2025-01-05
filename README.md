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

1. Download SteamClip from the Release page or clone the repository and follow built instractions below
2. Place the SteamClip file in any directory.

Done

# **USAGE**

1. Run SteamClip by double clicking it. Upon launch the program will check if the userdata folder containing your SteamID is in the default directory **(~/.local/share/Steam/userdata)**
 or previusly selected custom directory. If for some reason the expected userdata folder is invalid, the program will prompt you to select a valid userdata folder. 
Config file is located in ~/.config/SteamClip. **Config file is located in ~/.config/SteamClip**

If you have multiple Steam profiles, SteamClip will show you a list with every (valid) SteamID
   
2. After selecting the SteamID, your clips will show up in a 3x2 grid with "Next" and "Previous" button to scroll through different Clips.
3. SSelect a clip on the grid and click on "Convert Clip". SteamClip will convert the clip to an MP4 file and save it to your Desktop.

# **REQUIREMENTS**

None! SteamClip should run out of the box on any Linux distro!

# **BUILD INSTRUCTIONS AND REQUIREMENTS**
SteamClip is a simple standalone Python script with Ffmpeg built-in.
Download this repo, put SteamClip.py and SteamClip.spec in the same directory, then run
`pyinstaller SteamClip.spec`

## Requirements
* Python 3.6 or above
* pyinstaller ( `pip install pyinstaller` )
* PyQt5  ( `pip install PyQt5` )
* imageio[ffmpeg] ( `pip install imageio[ffmpeg]` )

# **LICENSE**

Distributed under the MIT License. See LICENSE for more information.
