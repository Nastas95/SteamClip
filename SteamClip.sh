#!/bin/bash

# Function to show an error message and exit
error() {
    kdialog --error "$1"
    exit 1
}

# Check if ffmpeg is installed
if ! command -v ffmpeg &>/dev/null; then
    error "ffmpeg is not installed. Please install it before running this script."
fi

# Select Steam ID
default_dir="$HOME/.local/share/Steam/userdata"
steam_ids=("$default_dir"/*)
available_ids=()

# Populate the Steam ID list
for dir in "${steam_ids[@]}"; do
    [ -d "$dir" ] && available_ids+=("$(basename "$dir")")
done

if [ ${#available_ids[@]} -eq 0 ]; then
    error "No Steam ID found in the userdata directory."
elif [ ${#available_ids[@]} -eq 1 ]; then
    steam_id="${available_ids[0]}"
else
    # Build the menu array for kdialog
    menu_items=()
    for id in "${available_ids[@]}"; do
        menu_items+=("$id" "$id")
    done

    # Use kdialog to select a Steam ID
    steam_id=$(kdialog --title "Select Steam ID" --menu "Select Steam ID" "${menu_items[@]}")
    [ -z "$steam_id" ] && error "No Steam ID selected."
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

[ ${#clip_names[@]} -eq 0 ] && error "No clips found."

# Build the array for clip selection
clip_items=()
for name in "${clip_names[@]}"; do
    clip_items+=("$name" "$name")
done

# Use kdialog to select a clip
selected_clip=$(kdialog --title "Select a clip" --menu "Select a clip" "${clip_items[@]}")
[ -z "$selected_clip" ] && error "No clip selected."

# Show the selected clip thumbnail for 3 seconds
thumbnail_path="$clip_dir/$selected_clip/thumbnail.jpg"
kde-open "$thumbnail_path" &  # Open the image in the default viewer
viewer_pid=$!  # Get the viewer's PID

sleep 3  # Wait for 3 seconds

# Ask for user confirmation if the clip is correct
kdialog --title "Confirm" --yesno "Is this the correct clip?" || {
    # If the user says 'No', re-run the script
    exec "$0"  # Restart the script
}

# Terminate the viewer
# Try to kill the viewer by process name instead of PID
killall -q -w "gwenview" || killall -q -w "okular" || killall -q -w "konqueror" || killall -q -w "xdg-open"

# Selected clip directory
video_dir="$clip_dir/$selected_clip/video"

# Check if the video directory exists
if [ ! -d "$video_dir" ]; then
    error "Video directory not found in the selected clip."
fi

# Locate the single subdirectory in the video directory
subdirs=("$video_dir"/*/)
if [ ${#subdirs[@]} -ne 1 ]; then
    error "Unexpected number of subdirectories in the video directory."
fi

data_dir="${subdirs[0]}"

# Concatenate video files
video_files=("$data_dir"chunk-stream0-*.m4s)
audio_files=("$data_dir"chunk-stream1-*.m4s)
init_video="$data_dir/init-stream0.m4s"
init_audio="$data_dir/init-stream1.m4s"
temp_video="$data_dir/tmp_video.mp4"
temp_audio="$data_dir/tmp_audio.mp4"

[ ! -f "$init_video" ] && error "init-stream0.m4s file not found."
[ ! -f "$init_audio" ] && error "init-stream1.m4s file not found."

cat "$init_video" "${video_files[@]}" > "$temp_video" || error "Error concatenating video files."
cat "$init_audio" "${audio_files[@]}" > "$temp_audio" || error "Error concatenating audio files."

# Set output directory to ~/Desktop
output_dir="$HOME/Desktop"
mkdir -p "$output_dir"  # Ensure the directory exists

# Output file name (default clip.mp4)
output_file="$output_dir/clip.mp4"

# Add a number to the file name if the file already exists
base_name=$(basename "$output_file" .mp4)
dir_name=$(dirname "$output_file")
counter=2
new_output_file="$output_file"

# Modify to avoid overwrite prompt
while [ -f "$new_output_file" ]; do
    new_output_file="$dir_name/$base_name$counter.mp4"
    ((counter++))
done

# Convert using ffmpeg
ffmpeg -i "$temp_video" -i "$temp_audio" -c copy "$new_output_file" && \
    kdialog --title "Conversion Completed" --msgbox "Conversion successful: $new_output_file" || \
    error "Error during file conversion."

# Remove temporary files
rm -f "$temp_video" "$temp_audio"
