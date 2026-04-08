"""SQLite-based catalog for tracking downloaded commercials."""

import sqlite3
import json
from datetime import datetime


class Catalog:
    """Manages a local SQLite database of downloaded vintage commercials."""

    def __init__(self, db_path: str = "catalog.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commercials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_url TEXT UNIQUE NOT NULL,
                    file_path TEXT,
                    year_estimate TEXT,
                    decade TEXT,
                    brand TEXT,
                    description TEXT,
                    duration_seconds REAL,
                    tags TEXT,
                    thumbnail_url TEXT,
                    date_downloaded TEXT,
                    date_added TEXT DEFAULT CURRENT_TIMESTAMP,
                    metadata_json TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_decade ON commercials(decade)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_brand ON commercials(brand)
            """)

    def add(self, title: str, source: str, source_url: str, file_path: str = None,
            year_estimate: str = None, decade: str = None, brand: str = None,
            description: str = None, duration_seconds: float = None,
            tags: list = None, thumbnail_url: str = None, metadata: dict = None) -> int:
        """Add a commercial to the catalog. Returns the row id."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO commercials
                (title, source, source_url, file_path, year_estimate, decade, brand,
                 description, duration_seconds, tags, thumbnail_url, date_downloaded, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                title, source, source_url, file_path, year_estimate, decade, brand,
                description, duration_seconds,
                json.dumps(tags) if tags else None,
                thumbnail_url,
                datetime.now().isoformat() if file_path else None,
                json.dumps(metadata) if metadata else None,
            ))
            return cursor.lastrowid

    def mark_downloaded(self, source_url: str, file_path: str):
        """Mark a catalog entry as downloaded."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE commercials SET file_path = ?, date_downloaded = ?
                WHERE source_url = ?
            """, (file_path, datetime.now().isoformat(), source_url))

    def search(self, query: str = None, decade: str = None, brand: str = None,
               downloaded_only: bool = False, limit: int = 50,
               offset: int = 0) -> list[dict]:
        """Search the catalog with optional filters."""
        conditions = []
        params = []

        if query:
            conditions.append("(title LIKE ? OR description LIKE ? OR brand LIKE ?)")
            params.extend([f"%{query}%"] * 3)
        if decade:
            conditions.append("decade = ?")
            params.append(decade)
        if brand:
            conditions.append("brand LIKE ?")
            params.append(f"%{brand}%")
        if downloaded_only:
            conditions.append("file_path IS NOT NULL")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM commercials {where} ORDER BY date_added DESC LIMIT ? OFFSET ?",
                params + [limit, offset]
            ).fetchall()
            return [dict(row) for row in rows]

    def stats(self) -> dict:
        """Get catalog statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM commercials").fetchone()[0]
            downloaded = conn.execute(
                "SELECT COUNT(*) FROM commercials WHERE file_path IS NOT NULL"
            ).fetchone()[0]
            by_decade = conn.execute(
                "SELECT decade, COUNT(*) FROM commercials WHERE decade IS NOT NULL GROUP BY decade ORDER BY decade"
            ).fetchall()
            by_source = conn.execute(
                "SELECT source, COUNT(*) FROM commercials GROUP BY source"
            ).fetchall()
            return {
                "total_cataloged": total,
                "total_downloaded": downloaded,
                "by_decade": {row[0]: row[1] for row in by_decade},
                "by_source": {row[0]: row[1] for row in by_source},
            }

    def get_by_id(self, video_id: int) -> dict | None:
        """Get a single commercial by its ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM commercials WHERE id = ?", (video_id,)
            ).fetchone()
            return dict(row) if row else None

    def exists(self, source_url: str) -> bool:
        """Check if a URL is already in the catalog."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM commercials WHERE source_url = ?", (source_url,)
            ).fetchone()
            return row is not None
