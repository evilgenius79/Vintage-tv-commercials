"""Download engine — handles downloading videos from various sources."""

import os
import subprocess
import shutil
import requests
from pathlib import Path
from typing import Optional

from .sources import archive_org
from .ytdlp_utils import get_js_runtime_args


DEFAULT_DOWNLOAD_DIR = "downloads"


def download(source_url: str, output_dir: str = DEFAULT_DOWNLOAD_DIR,
             filename: str = None) -> Optional[str]:
    """Download a video from any supported source.

    Args:
        source_url: URL of the video to download.
        output_dir: Directory to save the file in.
        filename: Optional filename override (without extension).

    Returns:
        Path to the downloaded file, or None on failure.
    """
    os.makedirs(output_dir, exist_ok=True)

    if "archive.org" in source_url:
        return _download_archive(source_url, output_dir, filename)
    else:
        return _download_ytdlp(source_url, output_dir, filename)


def _download_ytdlp(url: str, output_dir: str, filename: str = None) -> Optional[str]:
    """Download using yt-dlp (works for YouTube and many other sites)."""
    if not shutil.which("yt-dlp"):
        print("[downloader] yt-dlp not found. Install with: pip install yt-dlp")
        return None

    output_template = os.path.join(output_dir, f"{_sanitize(filename)}.%(ext)s" if filename else "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        *get_js_runtime_args(),
        "--no-playlist",
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--print", "after_move:filepath",
        url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print("[downloader] Download timed out (10 min limit)")
        return None

    if result.returncode != 0:
        print(f"[downloader] yt-dlp error: {result.stderr[:300]}")
        return None

    # yt-dlp prints the final filepath
    filepath = result.stdout.strip().split("\n")[-1]
    if filepath and os.path.exists(filepath):
        return filepath

    # Fallback: look for the file in output_dir
    return _find_newest_file(output_dir)


def _download_archive(url: str, output_dir: str, filename: str = None) -> Optional[str]:
    """Download from Internet Archive — picks the best video file."""
    # Extract identifier from URL
    identifier = url.rstrip("/").split("/")[-1]

    # If URL points directly to a file, download it
    if "." in identifier.split("/")[-1]:
        return _download_file(url, output_dir, filename)

    # Otherwise, get the file list and pick the best video
    files = archive_org.get_downloadable_files(identifier)
    if not files:
        # Try yt-dlp as fallback (it supports archive.org too)
        return _download_ytdlp(url, output_dir, filename)

    best = files[0]  # Already sorted by preference
    return _download_file(best["url"], output_dir, filename or _sanitize(identifier))


def _download_file(url: str, output_dir: str, filename: str = None) -> Optional[str]:
    """Direct HTTP download of a file."""
    try:
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[downloader] HTTP error: {e}")
        return None

    # Determine filename
    if not filename:
        filename = url.split("/")[-1].split("?")[0]
    elif "." not in filename:
        # Try to get extension from URL
        ext = url.split("/")[-1].split("?")[0].rsplit(".", 1)[-1]
        if ext in ("mp4", "avi", "mkv", "ogv", "webm", "mpg", "mpeg"):
            filename = f"{filename}.{ext}"
        else:
            filename = f"{filename}.mp4"

    filepath = os.path.join(output_dir, _sanitize(filename))

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    with open(filepath, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            downloaded += len(chunk)
            f.write(chunk)
            if total > 0:
                pct = (downloaded / total) * 100
                print(f"\r  Downloading: {pct:.0f}% ({downloaded // 1024}KB / {total // 1024}KB)", end="", flush=True)

    print()  # newline after progress
    return filepath


def _find_newest_file(directory: str) -> Optional[str]:
    """Find the most recently modified file in a directory."""
    files = list(Path(directory).iterdir())
    if not files:
        return None
    return str(max(files, key=lambda f: f.stat().st_mtime))


def _sanitize(name: str) -> str:
    """Sanitize a filename."""
    keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_ ")
    return "".join(c if c in keep else "_" for c in name).strip()
