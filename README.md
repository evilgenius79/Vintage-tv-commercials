# Vintage TV Commercial Downloader

Search, download, and catalog vintage TV commercials from the 1980s and 1990s.

## Sources

- **Internet Archive** (archive.org) — Free, legal collection of vintage media
- **YouTube** — Via yt-dlp (no API key needed)

## Install

### Prerequisites

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (installed automatically as a dependency)

### Setup

```bash
# Clone the repo
git clone https://github.com/evilgenius79/Vintage-tv-commercials.git
cd Vintage-tv-commercials

# Create a virtual environment (recommended)
python -m venv venv

# Activate it:
source venv/bin/activate        # Linux / Mac
venv\Scripts\activate           # Windows (Command Prompt)
venv\Scripts\Activate.ps1       # Windows (PowerShell)
source venv/Scripts/activate    # Windows (Git Bash)

# Install the package and all dependencies
pip install -e .
```

After installation, the `vintage-commercials` command will be available in your terminal.

## Usage

### Search and download interactively

All search commands support **multiple keywords** (comma-separated) and **year ranges**.

```bash
# Single keyword
vintage-commercials search "coca cola"

# Multiple keywords at once
vintage-commercials search "coca cola, pepsi, dr pepper"

# Filter by decade
vintage-commercials search "cereal" --decade 1980s

# Filter by specific year range
vintage-commercials search "nike, reebok" --years 1987-1993

# Single year
vintage-commercials search "super bowl" --years 1986
```

### Scan and catalog without downloading

```bash
vintage-commercials scan "fast food, soda, candy" --decade 1980s
vintage-commercials scan "toy" --years 1985-1992
vintage-commercials scan "car, truck" --years 1980-1999
```

### Batch search (the big one)

Search across many keywords and decades automatically. Without keywords it uses built-in categories (cereal, fast food, soda, toys, cars, beer, sneakers, candy, video games, etc.).

```bash
# Use built-in categories across 80s and 90s
vintage-commercials batch

# Custom keywords across both decades
vintage-commercials batch "coca cola, pepsi, sprite, 7up"

# Narrow to specific years
vintage-commercials batch "nike, reebok" --years 1987-1993

# Only search the 80s
vintage-commercials batch --decades 1980s

# Load keyword list from a file (one per line)
vintage-commercials batch --keywords-file my_brands.txt

# Search AND download everything found
vintage-commercials batch "mcdonalds, burger king" --download-all
```

### Download a specific URL

```bash
vintage-commercials grab "https://archive.org/details/some-commercial" --brand "Pepsi" --decade 1980s
vintage-commercials grab "https://www.youtube.com/watch?v=abc123"
```

### Browse your catalog

```bash
vintage-commercials list
vintage-commercials list --decade 1980s --downloaded
vintage-commercials list -q "nike"
```

### View stats

```bash
vintage-commercials stats
```

### Launch the web interface

```bash
# Start the web app (YouTube-like browsing experience)
vintage-commercials web

# Custom port
vintage-commercials web -p 8080

# Debug mode
vintage-commercials web --debug
```

Then open http://localhost:5000 in your browser.

## Web Interface

The web app provides a YouTube-like experience for browsing your vintage commercial collection:

- **Home page** — hero search, decade cards, recently added grid
- **Search** — searches your local catalog first; if under 3 results, automatically searches the internet, downloads metadata, and adds new finds to your archive
- **Browse** — filterable grid by decade with pagination
- **Watch** — video player page with description, metadata, and related videos
- **Download on demand** — click "Download" on any cataloged video to fetch it in the background; the page auto-refreshes when the download completes
- **Responsive** — works on desktop, tablet, and mobile

## Keywords File Format

For `--keywords-file`, create a text file with one search term per line:

```
# brands.txt
coca cola
pepsi
mcdonalds
burger king
nike
reebok
nintendo
sega
```

Lines starting with `#` are ignored.

## How It Works

1. **Search** — Queries Internet Archive's API and YouTube via yt-dlp
2. **Catalog** — Stores metadata (title, year, decade, brand, source) in a local SQLite database
3. **Download** — Downloads video files to a local `downloads/` directory (500MB size limit, SSRF-protected)
4. **Browse (CLI)** — Rich terminal UI for browsing and filtering your collection
5. **Browse (Web)** — Flask-based YouTube-like web interface with auto-discover

## API Endpoints

The web app exposes a JSON API:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/search?q=...&decade=...` | GET | Search the local catalog |
| `/api/discover` | POST | Search external sources and add to catalog |
| `/api/download` | POST | Start a background download |
| `/api/download/status?source_url=...` | GET | Check download progress |
| `/api/stats` | GET | Catalog statistics |

## Project Structure

```
vintage_commercials/
├── cli.py              # Click-based CLI commands
├── webapp.py           # Flask web application
├── catalog.py          # SQLite catalog database
├── downloader.py       # Download engine (yt-dlp + direct HTTP)
├── utils.py            # Shared helpers (truncate, year_to_decade, etc.)
├── templates/          # Jinja2 HTML templates
│   ├── base.html
│   ├── index.html      # Home page
│   ├── browse.html     # Browse/filter page
│   ├── search.html     # Search results (local + auto-discover)
│   ├── watch.html      # Video player page
│   └── components/
│       └── video_card.html
├── static/
│   ├── style.css       # Dark theme YouTube-like styling
│   └── app.js          # Download handling & interactions
└── sources/
    ├── archive_org.py  # Internet Archive search
    └── youtube.py      # YouTube search via yt-dlp
```
