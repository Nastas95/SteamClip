#!/bin/bash

# Function to show an error message and exit
error() {
  kdialog --error "$1"
  exit 1
}

# Function to check the validity of a userdata folder
is_valid_userdata() {
  local userdata_dir="$1"
  local steamid_dirs=("$userdata_dir"/*)
  for steamid_dir in "${steamid_dirs[@]}"; do
    local gamerecordings_dir="$steamid_dir/gamerecordings"
    local gamerecording_file="$gamerecordings_dir/gamerecording.pb"
    if [ -d "$gamerecordings_dir" ] && [ -f "$gamerecording_file" ]; then
      return 0
    fi
  done

  return 1
}

# Load the default userdata folder from a configuration file (if it exists)
config_file="$HOME/.config/SteamClip/SteamClip.conf"
if [ -f "$config_file" ]; then
  default_dir=$(cat "$config_file")
else
  default_dir="$HOME/.local/share/Steam/userdata"
fi
mkdir -p "$(dirname "$config_file")"

# Check if the default directory is valid, but only if it is not empty
if [ -n "$default_dir" ] && ! is_valid_userdata "$default_dir"; then
  default_dir=""
fi

# If default_dir is not valid, ask the user to select a directory
while [ -z "$default_dir" ]; do
  kdialog --msgbox "Please select the userdata folder."
  default_dir=$(kdialog --title "Select Directory" --getexistingdirectory "$HOME") || error "No directory selected."
  if is_valid_userdata "$default_dir"; then
    echo "$default_dir" > "$config_file"
  else
    kdialog --error "The selected directory is invalid. Please try again."
    default_dir=""
  fi
done

# Find all valid userdata folders with clips
available_ids=()
for dir in "$default_dir"/*; do
  if [ -d "$dir" ] && is_valid_userdata "$default_dir"; then

    # Check if there are clips in the folder
    clip_dir="$dir/gamerecordings/clips"
    if [ -d "$clip_dir" ] && find "$clip_dir" -name "thumbnail.jpg" -print -quit; then
      available_ids+=("$(basename "$dir")")
    fi
  fi
done

# If no valid folders are found, show an error and exit
if [ ${#available_ids[@]} -eq 0 ]; then
  error "No valid userdata folders with clips found. Please ensure the folder structure is correct."
fi

# Build the menu array for kdialog
menu_items=()
for id in "${available_ids[@]}"; do
  menu_items+=("$id" "$id")
done

# Use kdialog to select a Steam ID
steam_id=$(kdialog --title "Select Steam ID" --menu "Select Steam ID" "${menu_items[@]}")
if [ -z "$steam_id" ]; then
  error "No Steam ID selected."
fi

# Check if the clip directory exists
clip_dir="$default_dir/$steam_id/gamerecordings/clips"
if [ ! -d "$clip_dir" ]; then
  error "Clip directory not found: $clip_dir"
fi

# Show available clips
clip_folders=("$clip_dir"/*)
clip_names=()
for folder in "${clip_folders[@]}"; do
  if [ -f "$folder/thumbnail.jpg" ]; then
    clip_names+=("$(basename "$folder")")
  fi
done

# Build the array for clip selection
clip_items=()
for name in "${clip_names[@]}"; do
    clip_items+=("$name" "$name")
done

# Use kdialog to select a clip
selected_clip=$(kdialog --title "Select a Clip" --menu "Select a Clip" "${clip_items[@]}")
[ -z "$selected_clip" ] && error "No clip selected."

# Show the clip preview
thumbnail_path="$clip_dir/$selected_clip/thumbnail.jpg"
kde-open "$thumbnail_path" &
sleep 3

# Wait for user confirmation
kdialog --title "Confirmation" --yesno "Is this the correct clip?" || {
    # If the user says 'No', restart the script
    exec "$0"
}

# Terminate the viewer
pkill -f "thumbnail.jpg"

# Select the video folder for the clip
video_dir="$clip_dir/$selected_clip/video"

# Find all subdirectories in the video directory
subdirectories=("$video_dir"/*/)

# Iterate over each subdirectory to find session.mpd
for subdir in "${subdirectories[@]}"; do
    session_mpd="$subdir/session.mpd"
    if [ -f "$session_mpd" ]; then
        break
    fi
done

# Check if session.mpd was found
if [ -z "$session_mpd" ]; then
    error "session.mpd file not found in the selected clip."
fi

# Define the output directory and base filename
output_dir="$HOME/Desktop"
base_name="clip"
extension=".mp4"

# Generate the full file name, incrementing the number if necessary
output_file="$output_dir/$base_name$extension"
counter=1

while [ -f "$output_file" ]; do
    ((counter++))
    output_file="$output_dir/$base_name$counter$extension"
done

# Generate the final video using ffmpeg
ffmpeg -i "$session_mpd" -c copy "$output_file" && \
    kdialog --title "Conversion Completed" --msgbox "Conversion completed successfully: $output_file" || \
    error "Error during file conversion."

# Save the selected userdata folder to the configuration file
echo "$default_dir" > "$config_file"
