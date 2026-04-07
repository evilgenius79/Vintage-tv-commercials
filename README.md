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
