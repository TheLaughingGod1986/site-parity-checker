# Site Parity Checker

A tool to compare URLs between two websites to identify differences during migrations or redesigns.

## Features

- **Sitemap Parsing** - Extract URLs from XML sitemaps (including sitemap indexes)
- **Web Crawling** - Discover pages by following links (works for sites without sitemaps)
- **JavaScript Rendering** - Uses Playwright to render SPAs and dynamic content
- **Real-time Progress** - Live updates on scan progress, time elapsed, and ETA
- **Path-based Comparison** - Compares URL paths, ignoring domain differences
- **CSV Export** - Export results for further analysis

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd site-parity-checker

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (for JavaScript rendering)
playwright install chromium
```

## Usage

```bash
# Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Open in browser
open http://localhost:8000
```

### Options

- **Crawl site instead of using sitemap** - Discover pages by following links
- **Use both sitemap and crawling** - Most comprehensive coverage
- **Ignore robots.txt** - Allow crawling even if blocked

## Architecture

```
site-parity-checker/
├── app/
│   ├── __init__.py          # Package init
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Configuration constants
│   ├── models/
│   │   ├── progress.py      # Progress tracking
│   │   └── comparison.py    # Comparison results
│   ├── services/
│   │   ├── url_utils.py     # URL normalization
│   │   ├── sitemap.py       # Sitemap fetching
│   │   ├── crawler.py       # Web crawling
│   │   ├── renderer.py      # JS rendering
│   │   ├── robots.py        # robots.txt handling
│   │   ├── link_extractors.py # Link extraction
│   │   └── comparator.py    # Site comparison
│   └── api/
│       ├── routes.py        # API endpoints
│       └── export.py        # CSV export
├── static/js/               # Frontend JavaScript
├── templates/               # HTML templates
└── requirements.txt         # Python dependencies
```

## How It Works

1. **URL Discovery**
   - Fetches sitemap.xml (checks robots.txt for location)
   - Crawls links starting from homepage
   - Extracts URLs from JSON-LD, JavaScript, and data attributes

2. **URL Normalization**
   - Removes query strings and fragments
   - Handles www/non-www domains
   - Strips trailing slashes

3. **Comparison**
   - Compares URL paths (ignores domain)
   - Identifies: Missing on New, New Only, Matched

## API Endpoints

- `GET /` - Web interface
- `POST /compare` - Start comparison (SSE stream)
- `POST /export` - Export results as CSV

## Configuration

Default settings in `app/config.py`:

- `max_pages`: 10,000 pages per site
- `max_depth`: 5 levels deep
- `request_timeout`: 10 seconds
- `crawl_delay`: 0.1 seconds between requests

## Requirements

- Python 3.10+
- Chromium (for Playwright JS rendering)

## License

MIT
