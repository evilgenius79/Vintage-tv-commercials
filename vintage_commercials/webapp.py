"""Flask web application — a YouTube-like interface for vintage TV commercials."""

import os
import threading
from collections import OrderedDict
from urllib.parse import urlparse

from flask import (
    Flask, render_template, request, jsonify, send_file, abort, Response,
    url_for, redirect,
)

from .catalog import Catalog
from .sources import archive_org, youtube
from .downloader import download as download_video, DEFAULT_DOWNLOAD_DIR
from .utils import catalog_add_result

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# --- Config ---
DB_PATH = os.environ.get("VINTAGE_DB", "catalog.db")
DOWNLOAD_DIR = os.environ.get("VINTAGE_DOWNLOADS", DEFAULT_DOWNLOAD_DIR)
catalog = Catalog(DB_PATH)

# Track background download tasks with bounded size
_MAX_TASKS = 500
_download_tasks: OrderedDict[str, dict] = OrderedDict()
_tasks_lock = threading.Lock()


def _set_task(source_url: str, value: dict):
    """Set a download task entry, evicting oldest if over capacity."""
    with _tasks_lock:
        if source_url in _download_tasks:
            _download_tasks.move_to_end(source_url)
        _download_tasks[source_url] = value
        while len(_download_tasks) > _MAX_TASKS:
            _download_tasks.popitem(last=False)


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
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 24

    results = catalog.search(
        query=q or None,
        decade=decade,
        brand=brand,
        limit=per_page + 1,
        offset=(page - 1) * per_page,
    )

    has_next = len(results) > per_page
    results = results[:per_page]

    return render_template("browse.html", results=results, query=q,
                           decade=decade, brand=brand, page=page,
                           has_next=has_next)


@app.route("/watch/<int:video_id>")
def watch(video_id):
    """Video player page."""
    video = catalog.get_by_id(video_id)
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
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except (ValueError, TypeError):
        limit = 50

    results = catalog.search(query=q or None, decade=decade, brand=brand, limit=limit)
    return jsonify({"results": results, "count": len(results)})


@app.route("/api/discover", methods=["POST"])
def api_discover():
    """Search external sources for new commercials and add to catalog."""
    data = request.get_json(force=True, silent=True) or {}
    q = data.get("query", "").strip()
    decade = data.get("decade")

    if not q:
        return jsonify({"error": "query required"}), 400

    results = _search_external(q, decade)
    return jsonify({"results": results, "count": len(results)})


@app.route("/api/download", methods=["POST"])
def api_download():
    """Start downloading a video in the background."""
    data = request.get_json(force=True, silent=True) or {}
    source_url = data.get("source_url")
    title = data.get("title", "")

    if not source_url:
        return jsonify({"error": "source_url required"}), 400

    if not _is_safe_download_url(source_url):
        return jsonify({"error": "URL not allowed"}), 400

    with _tasks_lock:
        if source_url in _download_tasks:
            return jsonify(_download_tasks[source_url])

    _set_task(source_url, {"status": "downloading", "file_path": None})

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
    # Don't leak internal file paths to the client
    return jsonify({"status": task.get("status", "unknown")})


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
    video = catalog.get_by_id(video_id)
    if not video or not video.get("file_path"):
        abort(404)

    file_path = video["file_path"]
    if not _is_safe_file_path(file_path):
        abort(403)
    if not os.path.exists(file_path):
        abort(404)

    # Support range requests for video seeking
    range_header = request.headers.get("Range")
    file_size = os.path.getsize(file_path)

    if range_header:
        parsed = _parse_range(range_header, file_size)
        if parsed is None:
            abort(416)  # Range Not Satisfiable
        byte_start, byte_end = parsed
        length = byte_end - byte_start + 1

        def generate():
            chunk_size = 64 * 1024  # 64KB chunks
            with open(file_path, "rb") as f:
                f.seek(byte_start)
                remaining = length
                while remaining > 0:
                    read_size = min(chunk_size, remaining)
                    data = f.read(read_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        return Response(
            generate(),
            status=206,
            mimetype="video/mp4",
            headers={
                "Content-Range": f"bytes {byte_start}-{byte_end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": length,
            },
        )

    return send_file(file_path, mimetype="video/mp4")


@app.route("/thumbnail/<int:video_id>")
def serve_thumbnail(video_id):
    """Serve a thumbnail — redirect to external URL if available."""
    video = catalog.get_by_id(video_id)
    if not video:
        abort(404)

    thumb_url = video.get("thumbnail_url")
    if thumb_url and thumb_url.startswith(("http://", "https://")):
        return redirect(thumb_url)

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

    for r in all_results:
        catalog_add_result(catalog, r)

    # Auto-download all newly discovered videos in background
    for r in all_results:
        source_url = r["source_url"]
        if _is_safe_download_url(source_url):
            with _tasks_lock:
                if source_url in _download_tasks:
                    continue
            _set_task(source_url, {"status": "downloading", "file_path": None})
            thread = threading.Thread(
                target=_bg_download, args=(source_url, r.get("title", "")), daemon=True
            )
            thread.start()

    return catalog.search(query=query, decade=decade, limit=50)


def _bg_download(source_url: str, title: str):
    """Background download task."""
    try:
        filepath = download_video(source_url, output_dir=DOWNLOAD_DIR)
        if filepath:
            catalog.mark_downloaded(source_url, filepath)
            _set_task(source_url, {"status": "complete", "file_path": filepath})
        else:
            _set_task(source_url, {"status": "failed", "file_path": None})
    except Exception:
        _set_task(source_url, {"status": "failed", "file_path": None})


CLIPS_DIR = os.environ.get("VINTAGE_CLIPS", "clips")


def _is_safe_file_path(file_path: str) -> bool:
    """Validate that a file path is within allowed directories."""
    real_path = os.path.realpath(file_path)
    for allowed in (DOWNLOAD_DIR, CLIPS_DIR):
        base = os.path.realpath(allowed)
        if real_path.startswith(base + os.sep) or real_path == base:
            return True
    return False


def _is_safe_download_url(url: str) -> bool:
    """Validate that a URL is safe to download from (not internal/private)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    blocked = {"localhost", "127.0.0.1", "0.0.0.0", "::1",
               "metadata.google.internal", "169.254.169.254"}
    if hostname in blocked:
        return False

    # Block private IP ranges
    try:
        from ipaddress import ip_address
        ip = ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return False
    except ValueError:
        pass  # hostname is a domain name, not an IP — that's fine

    return True


def _parse_range(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse HTTP Range header. Returns (start, end) or None if invalid."""
    try:
        if not range_header.startswith("bytes="):
            return None
        range_spec = range_header[6:].split(",")[0].strip()  # only first range
        parts = range_spec.split("-", 1)
        if len(parts) != 2:
            return None

        if not parts[0]:
            # Suffix range: bytes=-500 means last 500 bytes
            suffix_length = int(parts[1])
            start = max(0, file_size - suffix_length)
            end = file_size - 1
        else:
            start = int(parts[0])
            end = int(parts[1]) if parts[1] else file_size - 1

        if start < 0 or end < 0 or start >= file_size or start > end:
            return None

        return start, min(end, file_size - 1)
    except (ValueError, IndexError):
        return None


def run_web(host="0.0.0.0", port=5000, debug=False):
    """Run the web server."""
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print(f"Starting Vintage TV Commercials at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
