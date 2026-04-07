"""Shared utility functions for the vintage commercials project."""

import re


def truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, appending '...' if truncated."""
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    return text[:max_len] + "..." if len(text) > max_len else text


def year_to_decade(year: str | None) -> str | None:
    """Convert a year string to a decade label (e.g., '1985' -> '1980s')."""
    if not year:
        return None
    try:
        y = int(year)
        return f"{(y // 10) * 10}s"
    except ValueError:
        return None


def guess_year_from_text(text: str) -> str | None:
    """Try to extract a year (1970-1999) from text like titles/descriptions."""
    matches = re.findall(r'\b(19[789]\d)\b', text)
    return matches[0] if matches else None


def catalog_add_result(catalog, result: dict) -> int | None:
    """Add a search result to the catalog if not already present. Returns row ID or None."""
    if catalog.exists(result["source_url"]):
        return None
    return catalog.add(
        title=result["title"],
        source=result["source"],
        source_url=result["source_url"],
        year_estimate=result.get("year_estimate"),
        decade=result.get("decade"),
        description=result.get("description"),
        duration_seconds=result.get("duration_seconds"),
        thumbnail_url=result.get("thumbnail_url"),
        metadata=result,
    )
