"""YouTube search source using yt-dlp.

Uses yt-dlp's built-in YouTube search to find vintage TV commercials.
No API key required — yt-dlp handles it via web scraping.
"""

import json
import subprocess
import shutil
from typing import Optional


def search(query: str, decade: Optional[str] = None,
           year_from: Optional[int] = None, year_to: Optional[int] = None,
           max_results: int = 15) -> list[dict]:
    """Search YouTube for vintage TV commercials using yt-dlp.

    Args:
        query: Search terms (e.g., "pepsi commercial 1985").
        decade: Optional decade filter ("1980s" or "1990s") — appended to query.
        year_from: Start year for a custom range (appended to query).
        year_to: End year for a custom range.
        max_results: Maximum number of results.

    Returns:
        List of result dicts with video metadata.
    """
    if not shutil.which("yt-dlp"):
        print("[youtube] yt-dlp not found. Install with: pip install yt-dlp")
        return []

    # Build search query
    search_query = f"{query} vintage TV commercial"
    if year_from and year_to and year_from == year_to:
        search_query += f" {year_from}"
    elif year_from and year_to:
        search_query += f" {year_from}-{year_to}"
    elif year_from:
        search_query += f" {year_from}"
    elif decade:
        search_query += f" {decade}"

    search_url = f"ytsearch{max_results}:{search_query}"

    cmd = [
        "yt-dlp",
        "--dump-json",
        "--flat-playlist",
        "--no-download",
        "--no-warnings",
        search_url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print("[youtube] Search timed out")
        return []

    if result.returncode != 0:
        print(f"[youtube] Search error: {result.stderr[:200]}")
        return []

    results = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue

        video_id = info.get("id", "")
        title = info.get("title", "Unknown")
        year = _guess_year_from_text(title + " " + info.get("description", ""))
        decade_val = _year_to_decade(year)

        results.append({
            "source": "youtube",
            "source_url": f"https://www.youtube.com/watch?v={video_id}",
            "identifier": video_id,
            "title": title,
            "description": _truncate(info.get("description", ""), 500),
            "year_estimate": year,
            "decade": decade_val,
            "brand": None,
            "duration_seconds": info.get("duration"),
            "thumbnail_url": info.get("thumbnail") or info.get("thumbnails", [{}])[0].get("url"),
            "uploader": info.get("uploader"),
            "view_count": info.get("view_count"),
        })

    return results


def _guess_year_from_text(text: str) -> str | None:
    """Try to extract a year (1970-1999) from text like titles/descriptions."""
    import re
    matches = re.findall(r'\b(19[789]\d)\b', text)
    if matches:
        return matches[0]
    return None


def _year_to_decade(year: str | None) -> str | None:
    if not year:
        return None
    try:
        y = int(year)
        return f"{(y // 10) * 10}s"
    except ValueError:
        return None


def _truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text
