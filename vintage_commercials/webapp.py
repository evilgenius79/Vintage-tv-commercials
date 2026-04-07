"""Flask web application — a YouTube-like interface for vintage TV commercials."""

import os
import threading
from pathlib import Path

from flask import (
    Flask, render_template, request, jsonify, send_file, abort, Response,
    url_for, redirect,
)

from .catalog import Catalog
from .sources import archive_org, youtube
from .downloader import download as download_video, DEFAULT_DOWNLOAD_DIR

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# --- Config ---
DB_PATH = os.environ.get("VINTAGE_DB", "catalog.db")
DOWNLOAD_DIR = os.environ.get("VINTAGE_DOWNLOADS", DEFAULT_DOWNLOAD_DIR)

catalog = Catalog(DB_PATH)

# Track background download tasks: source_url -> {"status": ..., "file_path": ...}
_download_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Home page — shows recent additions and featured decades."""
    recent = catalog.search(limit=24)
    stats = catalog.stats()
    return render_template("index.html", recent=recent, stats=stats)


@app.route("/browse")
def browse():
    """Browse catalog with filters."""
    decade = request.args.get("decade")
    brand = request.args.get("brand")
    q = request.args.get("q", "").strip()
    page = int(request.args.get("page", 1))
    per_page = 24

    results = catalog.search(
        query=q or None,
        decade=decade,
        brand=brand,
        limit=per_page + 1,  # fetch one extra to know if there's a next page
    )

    has_next = len(results) > per_page
    results = results[:per_page]

    return render_template("browse.html", results=results, query=q,
                           decade=decade, brand=brand, page=page,
                           has_next=has_next)


@app.route("/watch/<int:video_id>")
def watch(video_id):
    """Video player page."""
    results = catalog.search(limit=1000)
    video = None
    for r in results:
        if r["id"] == video_id:
            video = r
            break

    if not video:
        abort(404)

    # Get related videos (same decade)
    related = catalog.search(decade=video.get("decade"), limit=12)
    related = [r for r in related if r["id"] != video_id][:8]

    return render_template("watch.html", video=video, related=related)


@app.route("/search")
def search_page():
    """Search page — searches local catalog first, then external sources if needed."""
    q = request.args.get("q", "").strip()
    if not q:
        return redirect(url_for("index"))

    decade = request.args.get("decade")
    auto_discover = request.args.get("discover", "").lower() == "true"

    # Search local catalog first
    local_results = catalog.search(query=q, decade=decade, limit=50)

    external_results = []
    if auto_discover or len(local_results) < 3:
        # Not enough local results — search externally
        external_results = _search_external(q, decade)

    return render_template("search.html", query=q, decade=decade,
                           local_results=local_results,
                           external_results=external_results,
                           auto_discovered=auto_discover or len(local_results) < 3)


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/search")
def api_search():
    """JSON API for searching the catalog."""
    q = request.args.get("q", "").strip()
    decade = request.args.get("decade")
    brand = request.args.get("brand")
    limit = min(int(request.args.get("limit", 50)), 200)

    results = catalog.search(query=q or None, decade=decade, brand=brand, limit=limit)
    return jsonify({"results": results, "count": len(results)})


@app.route("/api/discover", methods=["POST"])
def api_discover():
    """Search external sources for new commercials and add to catalog."""
    data = request.get_json(force=True)
    q = data.get("query", "").strip()
    decade = data.get("decade")

    if not q:
        return jsonify({"error": "query required"}), 400

    results = _search_external(q, decade)
    return jsonify({"results": results, "count": len(results)})


@app.route("/api/download", methods=["POST"])
def api_download():
    """Start downloading a video in the background."""
    data = request.get_json(force=True)
    source_url = data.get("source_url")
    title = data.get("title", "")

    if not source_url:
        return jsonify({"error": "source_url required"}), 400

    with _tasks_lock:
        if source_url in _download_tasks:
            return jsonify(_download_tasks[source_url])

        _download_tasks[source_url] = {"status": "downloading", "file_path": None}

    # Start background download
    thread = threading.Thread(target=_bg_download, args=(source_url, title), daemon=True)
    thread.start()

    return jsonify({"status": "downloading", "source_url": source_url})


@app.route("/api/download/status")
def api_download_status():
    """Check download status."""
    source_url = request.args.get("source_url")
    if not source_url:
        return jsonify({"error": "source_url required"}), 400

    with _tasks_lock:
        task = _download_tasks.get(source_url, {"status": "unknown"})
    return jsonify(task)


@app.route("/api/stats")
def api_stats():
    """Catalog statistics."""
    return jsonify(catalog.stats())


# ---------------------------------------------------------------------------
# Video Serving
# ---------------------------------------------------------------------------

@app.route("/video/<int:video_id>")
def serve_video(video_id):
    """Stream a downloaded video file."""
    results = catalog.search(limit=5000)
    video = None
    for r in results:
        if r["id"] == video_id:
            video = r
            break

    if not video or not video.get("file_path"):
        abort(404)

    file_path = video["file_path"]
    if not os.path.exists(file_path):
        abort(404)

    # Support range requests for video seeking
    range_header = request.headers.get("Range")
    file_size = os.path.getsize(file_path)

    if range_header:
        byte_start, byte_end = _parse_range(range_header, file_size)
        length = byte_end - byte_start + 1

        with open(file_path, "rb") as f:
            f.seek(byte_start)
            data = f.read(length)

        resp = Response(
            data,
            status=206,
            mimetype="video/mp4",
            headers={
                "Content-Range": f"bytes {byte_start}-{byte_end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": length,
            },
        )
        return resp

    return send_file(file_path, mimetype="video/mp4")


@app.route("/thumbnail/<int:video_id>")
def serve_thumbnail(video_id):
    """Serve a thumbnail — either local or redirect to external URL."""
    results = catalog.search(limit=5000)
    video = None
    for r in results:
        if r["id"] == video_id:
            video = r
            break

    if not video:
        abort(404)

    thumb_url = video.get("thumbnail_url")
    if thumb_url:
        return redirect(thumb_url)

    # Return a default placeholder
    abort(404)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _search_external(query: str, decade: str = None) -> list[dict]:
    """Search external sources, add new finds to catalog, return them."""
    all_results = []

    try:
        results = archive_org.search(query, decade=decade, max_results=15)
        all_results.extend(results)
    except Exception:
        pass

    try:
        results = youtube.search(query, decade=decade, max_results=10)
        all_results.extend(results)
    except Exception:
        pass

    new_results = []
    for r in all_results:
        if not catalog.exists(r["source_url"]):
            catalog.add(
                title=r["title"],
                source=r["source"],
                source_url=r["source_url"],
                year_estimate=r.get("year_estimate"),
                decade=r.get("decade"),
                description=r.get("description"),
                duration_seconds=r.get("duration_seconds"),
                thumbnail_url=r.get("thumbnail_url"),
                metadata=r,
            )
            new_results.append(r)

    # Re-fetch from catalog to get IDs
    return catalog.search(query=query, decade=decade, limit=50)


def _bg_download(source_url: str, title: str):
    """Background download task."""
    try:
        filepath = download_video(source_url, output_dir=DOWNLOAD_DIR)
        if filepath:
            catalog.mark_downloaded(source_url, filepath)
            with _tasks_lock:
                _download_tasks[source_url] = {"status": "complete", "file_path": filepath}
        else:
            with _tasks_lock:
                _download_tasks[source_url] = {"status": "failed", "file_path": None}
    except Exception as e:
        with _tasks_lock:
            _download_tasks[source_url] = {"status": "failed", "error": str(e), "file_path": None}


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse HTTP Range header."""
    ranges = range_header.replace("bytes=", "").split("-")
    start = int(ranges[0]) if ranges[0] else 0
    end = int(ranges[1]) if ranges[1] else file_size - 1
    return start, min(end, file_size - 1)


def run_web(host="0.0.0.0", port=5000, debug=False):
    """Run the web server."""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print(f"Starting Vintage TV Commercials at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
