# Site Parity Checker

A FastAPI web application that compares two websites by analyzing their sitemaps to identify pages that exist on one site but not the other.

## Features

- 🔍 **Sitemap Comparison**: Automatically fetches and compares sitemaps from two websites
- 📊 **Visual Results**: Clean, tabbed interface showing:
  - Pages missing on the new site
  - Pages only on the new site
  - Pages matched on both sites
- 📥 **Export Functionality**: Export comparison results as CSV files
- ⚡ **Real-time Progress**: Live progress log showing what's happening during the comparison
- 🛡️ **Error Handling**: Gracefully handles timeouts and failed sitemap fetches, continuing with available data
- 🗂️ **Sitemap Index Support**: Automatically handles nested sitemaps (sitemap index files)

## Installation

### Prerequisites

- Python 3.9 or higher
- pip

### Setup

1. Clone the repository:
```bash
git clone https://github.com/TheLaughingGod1986/site-parity-checker.git
cd site-parity-checker
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Starting the Server

Run the FastAPI application:

```bash
uvicorn main:app --reload
```

The application will be available at `http://127.0.0.1:8000`

### Using the Application

1. Open your browser and navigate to `http://127.0.0.1:8000`
2. Enter the URLs for the old and new sites
3. Click "Compare Sites"
4. Watch the real-time progress log as sitemaps are fetched
5. Review the results in the tabbed interface
6. Export results to CSV if needed

## How It Works

1. **Sitemap Detection**: The app automatically appends `/sitemap.xml` to the base URL if a sitemap URL isn't provided
2. **Sitemap Parsing**: 
   - Fetches sitemap XML files
   - Handles sitemap index files (recursively fetches nested sitemaps)
   - Filters out non-HTML content (images, CSS, JS, PDFs, etc.)
3. **URL Normalization**: 
   - Converts URLs to lowercase
   - Strips trailing slashes
   - Removes query strings
4. **Comparison**: Creates three sets:
   - Pages in old site but not in new site
   - Pages in new site but not in old site
   - Pages common to both sites
5. **Results Display**: Shows results in a user-friendly table with export functionality

## Technical Stack

- **Backend**: FastAPI (Python)
- **Frontend**: Jinja2 templates, Vanilla JavaScript, Tailwind CSS
- **Libraries**:
  - `requests` - HTTP requests for fetching sitemaps
  - `beautifulsoup4` - XML parsing
  - `pandas` - CSV export functionality
  - `uvicorn` - ASGI server

## Project Structure

```
site-parity-checker/
├── main.py              # FastAPI application and endpoints
├── templates/
│   └── index.html      # Frontend template
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

## API Endpoints

- `GET /` - Home page with comparison form
- `POST /compare` - Compare two sites (returns Server-Sent Events stream with progress)
- `POST /export` - Export results as CSV

## Error Handling

The application includes robust error handling:
- **Timeouts**: Uses shorter timeouts for nested sitemaps (15s vs 30s)
- **Partial Results**: Continues processing even if some sitemaps fail
- **Warnings**: Displays warnings for failed sitemaps while still showing available results
- **Progress Feedback**: Real-time log shows exactly which sitemaps are being processed

## License

MIT License - feel free to use this project for your own purposes.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

