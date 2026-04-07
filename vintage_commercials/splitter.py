"""Video splitter — cuts compilation videos into individual clips using FFmpeg.

Uses hardware-accelerated decoding on Pi 5 (V4L2 M2M) when available.
"""

import os
import subprocess
import shutil
from pathlib import Path


def split_video(video_path: str, scenes: list[dict],
                output_dir: str = None,
                use_hw_accel: bool = True) -> list[str]:
    """Split a video into individual clips at scene boundaries.

    Args:
        video_path: Path to the source compilation video.
        scenes: List of scene dicts from scene_detect (start_time, end_time, index).
        output_dir: Directory for output clips. Defaults to a subdirectory
                    next to the source file.
        use_hw_accel: Try Pi 5 hardware acceleration (V4L2 M2M).

    Returns:
        List of paths to the split clip files.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found. Install with: sudo apt install ffmpeg")

    video_path = os.path.abspath(video_path)
    base_name = Path(video_path).stem

    if not output_dir:
        output_dir = os.path.join(os.path.dirname(video_path), f"{base_name}_clips")

    os.makedirs(output_dir, exist_ok=True)

    hw_available = use_hw_accel and _has_v4l2m2m()
    clip_paths = []

    for scene in scenes:
        idx = scene["index"]
        start = scene["start_time"]
        duration = scene["duration"]

        clip_filename = f"{base_name}_clip{idx:03d}.mp4"
        clip_path = os.path.join(output_dir, clip_filename)

        cmd = _build_ffmpeg_cmd(
            video_path, clip_path, start, duration, hw_available
        )

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0 and os.path.exists(clip_path):
                clip_paths.append(clip_path)
            elif hw_available:
                # Retry without hardware acceleration
                cmd = _build_ffmpeg_cmd(
                    video_path, clip_path, start, duration, False
                )
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300
                )
                if result.returncode == 0 and os.path.exists(clip_path):
                    clip_paths.append(clip_path)
                else:
                    print(f"[splitter] Failed to split clip {idx}: {result.stderr[:200]}")
            else:
                print(f"[splitter] Failed to split clip {idx}: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            print(f"[splitter] Clip {idx} timed out")

    return clip_paths


def extract_thumbnail(video_path: str, timestamp: float = None,
                      output_path: str = None) -> str | None:
    """Extract a thumbnail frame from a video.

    Args:
        video_path: Path to the video.
        timestamp: Time in seconds to grab the frame. Defaults to 25% through.
        output_path: Output path for the thumbnail. Defaults to video_name_thumb.jpg.

    Returns:
        Path to the thumbnail, or None on failure.
    """
    if not output_path:
        output_path = str(Path(video_path).with_suffix(".jpg"))

    if timestamp is None:
        # Grab a frame ~25% through the video
        from .scene_detect import _get_duration
        duration = _get_duration(video_path)
        timestamp = (duration or 10) * 0.25

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "3",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
    except subprocess.TimeoutExpired:
        pass

    return None


def _build_ffmpeg_cmd(input_path: str, output_path: str,
                      start: float, duration: float,
                      use_hw: bool) -> list[str]:
    """Build an ffmpeg command for splitting a clip."""
    cmd = ["ffmpeg", "-y"]

    if use_hw:
        # Pi 5 hardware-accelerated decode
        cmd.extend(["-hwaccel", "v4l2m2m"])

    # Seek before input (fast seek)
    cmd.extend(["-ss", f"{start:.3f}"])
    cmd.extend(["-i", input_path])
    cmd.extend(["-t", f"{duration:.3f}"])

    if use_hw:
        # Try hardware encode
        cmd.extend(["-c:v", "h264_v4l2m2m"])
    else:
        # Software encode — use copy when possible, re-encode if needed
        cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "23"])

    cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    cmd.extend(["-movflags", "+faststart"])
    cmd.append(output_path)

    return cmd


def _has_v4l2m2m() -> bool:
    """Check if Pi 5 V4L2 M2M hardware codec is available."""
    if not shutil.which("ffmpeg"):
        return False
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders"], capture_output=True, text=True, timeout=10
        )
        return "h264_v4l2m2m" in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False
