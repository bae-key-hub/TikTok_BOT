import os
import subprocess
import imageio_ffmpeg

def extract_audio_from_video(video_path: str) -> str:
    """
    Extracts audio from a video file into a lightweight MP3.
    This makes uploading to Gemini 10x faster and saves internet bandwidth!
    If anything goes wrong, returns the original video path as fallback.
    """
    if not os.path.exists(video_path):
        return video_path

    base_name, _ = os.path.splitext(video_path)
    audio_path = f"{base_name}_audio.mp3"

    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        # -y: overwrite output
        # -i: input file
        # -vn: disable video recording (extract audio only)
        # -acodec libmp3lame: mp3 codec
        # -q:a 4: good quality, tiny file size
        command = [
            ffmpeg_exe,
            "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", "4",
            audio_path
        ]
        
        # Run ffmpeg silently
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=60
        )
        
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            return audio_path
    except Exception as e:
        print(f"Audio extraction fallback: {e}")

    # Fallback to the original video file if extraction fails
    return video_path

def cleanup_files(*file_paths):
    """Safely removes temporary files to keep computer storage clean."""
    for path in file_paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                print(f"Could not delete temp file {path}: {e}")
