"""Scene detection for splitting compilation videos into individual commercials.

Uses PySceneDetect to find transition points (cuts, fades, black frames)
between individual commercials in compilation videos.
"""

import subprocess
import json
import shutil
from pathlib import Path


def detect_scenes(video_path: str, threshold: float = 27.0,
                  min_scene_length: float = 5.0,
                  max_scene_length: float = 120.0) -> list[dict]:
    """Detect scene boundaries in a video file.

    Uses PySceneDetect's ContentDetector for cut detection and
    filters results to likely individual commercial boundaries.

    Args:
        video_path: Path to the video file.
        threshold: Sensitivity for scene detection (lower = more splits).
                   Default 27.0 works well for commercial compilations.
        min_scene_length: Minimum scene duration in seconds (skip tiny fragments).
        max_scene_length: Maximum scene duration in seconds (force-split long segments).

    Returns:
        List of scene dicts with start_time, end_time, duration, and index.
    """
    if not shutil.which("scenedetect"):
        raise RuntimeError(
            "scenedetect not found. Install with: pip install scenedetect[opencv]"
        )

    # Run scenedetect CLI and capture the scene list as CSV
    cmd = [
        "scenedetect",
        "-i", video_path,
        "--output", "/dev/null",
        "detect-content",
        "--threshold", str(threshold),
        "list-scenes",
        "--no-output-file",
        "--quiet",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Scene detection timed out (10 min limit)")

    if result.returncode != 0:
        # Fallback: use ffprobe to detect black frames
        return _detect_scenes_ffprobe(video_path, min_scene_length, max_scene_length)

    return _parse_scenedetect_output(
        result.stdout, min_scene_length, max_scene_length
    )


def detect_scenes_ffprobe(video_path: str, min_scene_length: float = 5.0,
                          max_scene_length: float = 120.0) -> list[dict]:
    """Fallback scene detection using ffprobe's black frame detection."""
    return _detect_scenes_ffprobe(video_path, min_scene_length, max_scene_length)


def _detect_scenes_ffprobe(video_path: str, min_scene_length: float,
                           max_scene_length: float) -> list[dict]:
    """Detect scenes by finding black frames (common between commercials)."""
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found. Install ffmpeg.")

    # Get total duration
    duration = _get_duration(video_path)
    if not duration:
        return []

    # Detect black frames
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-vf", "blackdetect=d=0.3:pix_th=0.10",
        "-an", "-f", "null", "-",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return []

    # Parse black frame timestamps from stderr
    import re
    black_starts = []
    for match in re.finditer(
        r"black_start:([\d.]+)\s+black_end:([\d.]+)", result.stderr
    ):
        start = float(match.group(1))
        end = float(match.group(2))
        midpoint = (start + end) / 2
        black_starts.append(midpoint)

    # Build scene list from black frame boundaries
    scenes = []
    prev_time = 0.0

    for split_time in black_starts:
        scene_duration = split_time - prev_time
        if scene_duration >= min_scene_length:
            scenes.append({
                "index": len(scenes),
                "start_time": prev_time,
                "end_time": split_time,
                "duration": scene_duration,
            })
        prev_time = split_time

    # Add final scene
    if duration - prev_time >= min_scene_length:
        scenes.append({
            "index": len(scenes),
            "start_time": prev_time,
            "end_time": duration,
            "duration": duration - prev_time,
        })

    # Force-split scenes that exceed max length
    scenes = _force_split_long_scenes(scenes, max_scene_length, min_scene_length)

    return scenes


def _parse_scenedetect_output(output: str, min_scene_length: float,
                               max_scene_length: float) -> list[dict]:
    """Parse scenedetect text output into scene list."""
    scenes = []
    lines = output.strip().split("\n")

    for line in lines:
        # scenedetect outputs lines like:
        # Scene  1: 00:00:00.000 - 00:00:32.500
        import re
        match = re.search(
            r"Scene\s+\d+.*?(\d+:\d+:\d+\.\d+)\s*-\s*(\d+:\d+:\d+\.\d+)", line
        )
        if not match:
            continue

        start = _timecode_to_seconds(match.group(1))
        end = _timecode_to_seconds(match.group(2))
        duration = end - start

        if duration >= min_scene_length:
            scenes.append({
                "index": len(scenes),
                "start_time": start,
                "end_time": end,
                "duration": duration,
            })

    scenes = _force_split_long_scenes(scenes, max_scene_length, min_scene_length)
    return scenes


def _force_split_long_scenes(scenes: list[dict], max_length: float,
                              min_length: float) -> list[dict]:
    """Split any scene longer than max_length into roughly equal parts."""
    result = []
    for scene in scenes:
        if scene["duration"] <= max_length:
            scene["index"] = len(result)
            result.append(scene)
        else:
            # Split into ~30 second chunks
            chunk_target = 30.0
            n_chunks = max(2, round(scene["duration"] / chunk_target))
            chunk_duration = scene["duration"] / n_chunks
            for i in range(n_chunks):
                start = scene["start_time"] + i * chunk_duration
                end = start + chunk_duration
                if i == n_chunks - 1:
                    end = scene["end_time"]
                if end - start >= min_length:
                    result.append({
                        "index": len(result),
                        "start_time": start,
                        "end_time": end,
                        "duration": end - start,
                    })
    return result


def _get_duration(video_path: str) -> float | None:
    """Get video duration using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, ValueError):
        return None


def _timecode_to_seconds(tc: str) -> float:
    """Convert HH:MM:SS.mmm timecode to seconds."""
    parts = tc.split(":")
    h, m = int(parts[0]), int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s
