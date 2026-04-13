"""Generate a synthetic test video for pipeline testing."""

import subprocess
import os
import sys

def create_test_video(output_path: str, duration: int = 30):
    """Create a test video with color bars, audio tones, and text overlays."""
    print(f"Creating {duration}s test video: {output_path}")

    # Generate video: color bars with changing colors
    # Generate audio: alternating tones
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=blue:s=1280x720:r=30:d={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:d={duration}",
        "-f", "lavfi", "-i", f"color=c=red:s=200x150:r=30:d={duration}",
        "-filter_complex",
        f"[0:v]drawtext=text='TEST VIDEO {duration}s':fontsize=48:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:enable='lt(t,15)'"
        f"[bg];"
        f"[2:v]format=rgba,colorchannelmixer=aa=0.8[wc];"
        f"[bg][wc]overlay=50:50[outv]",
        "-map", "[outv]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr}")
        return False

    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        print(f"Created: {output_path} ({size / 1024 / 1024:.1f} MB)")
        return True
    return False


if __name__ == "__main__":
    path = os.path.join("temp", "test_video.mp4")
    os.makedirs("temp", exist_ok=True)
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    success = create_test_video(path, duration=dur)
    sys.exit(0 if success else 1)
