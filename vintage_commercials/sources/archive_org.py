"""Internet Archive (archive.org) search source.

The Internet Archive has a massive collection of vintage TV commercials
that are freely available for download. This module uses their public
search API to find and retrieve commercial metadata.
"""

import requests
from typing import Optional

from ..utils import truncate as _truncate, year_to_decade as _year_to_decade


ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
ARCHIVE_METADATA_URL = "https://archive.org/metadata"
ARCHIVE_DOWNLOAD_URL = "https://archive.org/download"


def search(query: str, decade: Optional[str] = None,
           year_from: Optional[int] = None, year_to: Optional[int] = None,
           max_results: int = 25) -> list[dict]:
    """Search Internet Archive for vintage TV commercials.

    Args:
        query: Search terms (e.g., "coca cola commercial", "80s cereal ad").
        decade: Filter by decade ("1980s" or "1990s").
        year_from: Start year for a custom year range (e.g., 1985).
        year_to: End year for a custom year range (e.g., 1992).
        max_results: Maximum results to return.

    Returns:
        List of result dicts with title, url, description, year, etc.
    """
    # Build the search query targeting TV commercials
    q_parts = [query, "commercial OR advertisement OR ad OR promo"]

    # Media type filter — video
    q_parts.append("mediatype:movies")

    # Year range takes priority over decade
    if year_from or year_to:
        start = year_from or 1970
        end = year_to or 1999
        q_parts.append(f"date:[{start}-01-01 TO {end}-12-31]")
    elif decade == "1980s":
        q_parts.append("date:[1980-01-01 TO 1989-12-31]")
    elif decade == "1990s":
        q_parts.append("date:[1990-01-01 TO 1999-12-31]")
    elif decade:
        # Try to parse generic decade string
        try:
            start_year = int(decade.rstrip("s"))
            q_parts.append(f"date:[{start_year}-01-01 TO {start_year + 9}-12-31]")
        except ValueError:
            pass

    # Add collection hints for known commercial collections
    collection_boost = (
        "collection:(tvcommercials OR tvads OR "
        "commercials OR RetroAds OR tv_commercial)"
    )

    full_query = " AND ".join(q_parts) + f" OR ({collection_boost} AND {query})"

    params = {
        "q": full_query,
        "fl[]": ["identifier", "title", "description", "date", "year",
                 "creator", "collection", "avg_rating", "downloads"],
        "sort[]": "downloads desc",
        "rows": max_results,
        "page": 1,
        "output": "json",
    }

    headers = {"User-Agent": "VintageCommercialDownloader/0.1 (educational project)"}

    try:
        resp = requests.get(ARCHIVE_SEARCH_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[archive.org] Search error: {e}")
        return []

    results = []
    for doc in data.get("response", {}).get("docs", []):
        identifier = doc.get("identifier", "")
        year = doc.get("year") or _extract_year(doc.get("date", ""))
        decade_val = _year_to_decade(year)

        results.append({
            "source": "archive.org",
            "source_url": f"https://archive.org/details/{identifier}",
            "download_url": f"{ARCHIVE_DOWNLOAD_URL}/{identifier}",
            "identifier": identifier,
            "title": doc.get("title", "Unknown"),
            "description": _truncate(doc.get("description", ""), 500),
            "year_estimate": year,
            "decade": decade_val,
            "brand": None,  # Would need NLP to extract brand from title/desc
            "creator": doc.get("creator"),
            "collection": doc.get("collection"),
        })

    return results


def get_downloadable_files(identifier: str) -> list[dict]:
    """Get the list of downloadable files for an Archive.org item.

    Returns list of dicts with name, size, format for each file.
    """
    headers = {"User-Agent": "VintageCommercialDownloader/0.1 (educational project)"}

    try:
        resp = requests.get(f"{ARCHIVE_METADATA_URL}/{identifier}", headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[archive.org] Metadata error for {identifier}: {e}")
        return []

    files = []
    video_formats = {"MPEG4", "h.264", "Ogg Video", "512Kb MPEG4", "MPEG2",
                     "Quicktime", "Cinepack", "Animated GIF", "MP4", "WebM"}

    for f in data.get("files", []):
        fmt = f.get("format", "")
        if fmt in video_formats or f.get("name", "").endswith((".mp4", ".avi", ".mkv", ".ogv", ".webm")):
            files.append({
                "name": f["name"],
                "size": f.get("size"),
                "format": fmt,
                "url": f"{ARCHIVE_DOWNLOAD_URL}/{identifier}/{f['name']}",
            })

    # Sort by preference — mp4 first, then by size descending
    files.sort(key=lambda x: (
        0 if x["name"].endswith(".mp4") else 1,
        -(int(x.get("size") or 0))
    ))

    return files


def _extract_year(date_str: str) -> str | None:
    if not date_str:
        return None
    # Archive dates are often "YYYY-MM-DD" or just "YYYY"
    return date_str[:4] if len(date_str) >= 4 and date_str[:4].isdigit() else None


