# Vintage TV Commercial Downloader

Search, download, and catalog vintage TV commercials from the 1980s and 1990s.

## Sources

- **Internet Archive** (archive.org) — Free, legal collection of vintage media
- **YouTube** — Via yt-dlp (no API key needed)

## Install

```bash
pip install -e .
```

## Usage

### Search and download interactively
```bash
vintage-commercials search "coca cola" --decade 1980s
vintage-commercials search "cereal commercial" --decade 1990s --source archive
```

### Scan and catalog without downloading
```bash
vintage-commercials scan "fast food" --decade 1980s
vintage-commercials scan "toy commercial" --decade 1990s
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

## How It Works

1. **Search** — Queries Internet Archive's API and YouTube via yt-dlp
2. **Catalog** — Stores metadata (title, year, decade, brand, source) in a local SQLite database
3. **Download** — Downloads video files to a local `downloads/` directory
4. **Browse** — Rich terminal UI for browsing and filtering your collection

## Project Structure

```
vintage_commercials/
├── cli.py              # Click-based CLI interface
├── catalog.py          # SQLite catalog database
├── downloader.py       # Download engine (yt-dlp + direct HTTP)
└── sources/
    ├── archive_org.py  # Internet Archive search
    └── youtube.py      # YouTube search via yt-dlp
```
