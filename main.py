from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import pandas as pd
from typing import Dict, Set, List, Tuple
import io
import json
import asyncio

app = FastAPI(title="Site Parity Checker")
templates = Jinja2Templates(directory="templates")


def normalize_url(url: str) -> str:
    """Normalize URL: lowercase, strip trailing slash, remove query string."""
    parsed = urlparse(url)
    path = parsed.path.rstrip('/').lower()
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def get_sitemap_url(base_url: str) -> str:
    """Get sitemap URL, appending /sitemap.xml if needed."""
    if base_url.endswith('/sitemap.xml'):
        return base_url
    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return urljoin(base, '/sitemap.xml')


def fetch_sitemap(url: str, visited: Set[str] = None, errors: List[str] = None, progress_callback=None) -> Tuple[Set[str], List[str]]:
    """Fetch sitemap and extract all <loc> entries, filtering out non-HTML content.
    Handles sitemap index files by recursively fetching nested sitemaps.
    Returns (paths_set, errors_list)."""
    if visited is None:
        visited = set()
    if errors is None:
        errors = []
    
    if url in visited:
        return set(), errors
    
    visited.add(url)
    
    # Report progress
    if progress_callback:
        progress_callback(f"Fetching: {url}")
    
    try:
        # Use shorter timeout for nested sitemaps (15s instead of 30s)
        timeout = 15 if len(visited) > 1 else 30
        response = requests.get(url, timeout=timeout, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
    except requests.exceptions.Timeout:
        error_msg = f"Timeout fetching sitemap: {url}"
        errors.append(error_msg)
        if progress_callback:
            progress_callback(f"⚠️ Timeout: {url}")
        return set(), errors
    except Exception as e:
        error_msg = f"Failed to fetch sitemap {url}: {str(e)}"
        errors.append(error_msg)
        if progress_callback:
            progress_callback(f"❌ Error: {url}")
        return set(), errors
    
    soup = BeautifulSoup(response.content, 'xml')
    
    # Check if this is a sitemap index (contains <sitemap> tags)
    sitemap_tags = soup.find_all('sitemap')
    if sitemap_tags:
        # This is a sitemap index, recursively fetch nested sitemaps
        if progress_callback:
            progress_callback(f"Found sitemap index with {len(sitemap_tags)} nested sitemaps")
        paths = set()
        for idx, sitemap_tag in enumerate(sitemap_tags, 1):
            loc_tag = sitemap_tag.find('loc')
            if loc_tag:
                nested_url = loc_tag.get_text().strip()
                if progress_callback:
                    progress_callback(f"Processing nested sitemap {idx}/{len(sitemap_tags)}: {nested_url}")
                nested_paths, nested_errors = fetch_sitemap(nested_url, visited, errors, progress_callback)
                paths.update(nested_paths)
                errors.extend(nested_errors)
                if progress_callback and nested_paths:
                    progress_callback(f"✓ Found {len(nested_paths)} URLs in {nested_url}")
        return paths, errors
    
    # Regular sitemap with <url> or <loc> tags
    locs = soup.find_all('loc')
    
    # Filter out non-HTML content
    excluded_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', 
                          '.css', '.js', '.pdf', '.zip', '.xml', '.ico'}
    
    paths = set()
    for loc in locs:
        url_text = loc.get_text().strip()
        parsed = urlparse(url_text)
        
        # Check if URL has excluded extension
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in excluded_extensions):
            continue
        
        # Normalize the URL
        normalized = normalize_url(url_text)
        paths.add(normalized)
    
    if progress_callback and paths:
        progress_callback(f"✓ Found {len(paths)} URLs in {url}")
    
    return paths, errors


def compare_sites(old_url: str, new_url: str, progress_callback=None) -> Dict:
    """Compare two sites and return differences."""
    # Get sitemap URLs
    old_sitemap = get_sitemap_url(old_url)
    new_sitemap = get_sitemap_url(new_url)
    
    if progress_callback:
        progress_callback(f"Starting comparison...")
        progress_callback(f"Old site sitemap: {old_sitemap}")
        progress_callback(f"New site sitemap: {new_sitemap}")
    
    # Fetch and parse sitemaps (with error collection)
    if progress_callback:
        progress_callback("📥 Fetching old site sitemap...")
    old_paths, old_errors = fetch_sitemap(old_sitemap, progress_callback=progress_callback)
    if progress_callback:
        progress_callback(f"✓ Old site: Found {len(old_paths)} URLs")
    
    if progress_callback:
        progress_callback("📥 Fetching new site sitemap...")
    new_paths, new_errors = fetch_sitemap(new_sitemap, progress_callback=progress_callback)
    if progress_callback:
        progress_callback(f"✓ New site: Found {len(new_paths)} URLs")
    
    # Combine all errors
    all_errors = old_errors + new_errors
    
    # Compare
    if progress_callback:
        progress_callback("🔍 Comparing sites...")
    missing_on_new = old_paths - new_paths
    new_only = new_paths - old_paths
    matched = old_paths & new_paths
    
    if progress_callback:
        progress_callback(f"✓ Comparison complete!")
        progress_callback(f"  - Missing on new: {len(missing_on_new)}")
        progress_callback(f"  - New only: {len(new_only)}")
        progress_callback(f"  - Matched: {len(matched)}")
    
    result = {
        'missing_on_new': list(missing_on_new),
        'new_only': list(new_only),
        'matched': list(matched),
        'old_sitemap': old_sitemap,
        'new_sitemap': new_sitemap
    }
    
    # Add warnings if there were errors (but we still got some data)
    if all_errors:
        result['warnings'] = all_errors
        result['warning_message'] = f"Some sitemaps failed to load ({len(all_errors)} errors). Results may be incomplete."
    
    return result


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with form."""
    return templates.TemplateResponse("index.html", {"request": request})


async def compare_with_progress(old_url: str, new_url: str):
    """Compare sites with progress updates via generator."""
    import queue
    progress_queue = queue.Queue()
    
    def progress_callback(message: str):
        progress_queue.put(message)
    
    try:
        # Run comparison in a thread to avoid blocking
        import concurrent.futures
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(compare_sites, old_url, new_url, progress_callback)
            
            # Yield progress updates while waiting
            while not future.done():
                await asyncio.sleep(0.1)  # Small delay to check for updates
                try:
                    while True:
                        msg = progress_queue.get_nowait()
                        yield f"data: {json.dumps({'type': 'progress', 'message': msg})}\n\n"
                except queue.Empty:
                    pass
            
            # Get final result
            result = future.result()
            
            # Send any remaining progress messages
            try:
                while True:
                    msg = progress_queue.get_nowait()
                    yield f"data: {json.dumps({'type': 'progress', 'message': msg})}\n\n"
            except queue.Empty:
                pass
            
            # Send final result
            yield f"data: {json.dumps({'type': 'result', 'data': result})}\n\n"
            
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@app.post("/compare")
async def compare(old_url: str = Form(...), new_url: str = Form(...)):
    """Compare two sites with real-time progress updates via SSE."""
    return StreamingResponse(
        compare_with_progress(old_url, new_url),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/export")
async def export(
    category: str = Form(...),
    missing_on_new: str = Form(""),
    new_only: str = Form(""),
    matched: str = Form("")
):
    """Export selected category as CSV."""
    import json
    
    try:
        # Parse the JSON strings (they come as strings from form data)
        data_map = {
            'missing_on_new': json.loads(missing_on_new) if missing_on_new else [],
            'new_only': json.loads(new_only) if new_only else [],
            'matched': json.loads(matched) if matched else []
        }
        
        if category not in data_map:
            return JSONResponse(status_code=400, content={"error": "Invalid category"})
        
        urls = data_map[category]
        
        if not urls:
            return JSONResponse(status_code=400, content={"error": "No data to export for this category"})
        
        # Create DataFrame
        df = pd.DataFrame({
            'URL': urls,
            'Path': [urlparse(url).path for url in urls]
        })
        
        # Create CSV in memory
        output = io.StringIO()
        df.to_csv(output, index=False)
        csv_content = output.getvalue()
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={category}.csv"}
        )
    except json.JSONDecodeError as e:
        return JSONResponse(status_code=400, content={"error": f"Invalid JSON data: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Export failed: {str(e)}"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

