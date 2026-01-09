"""API routes for site comparison."""

import json
import queue
import asyncio
import concurrent.futures
from typing import AsyncGenerator

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from ..models.progress import ProgressTracker
from ..models.comparison import ComparisonResult
from ..services.comparator import SiteComparator
from ..config import CrawlConfig, DEFAULT_APP_CONFIG
from .export import export_csv, export_all_csv


router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the home page."""
    return templates.TemplateResponse("index.html", {"request": request})


async def _compare_with_progress(
    old_url: str,
    new_url: str,
    use_crawl: bool,
    max_pages: int,
    combine_methods: bool,
    ignore_robots: bool
) -> AsyncGenerator[str, None]:
    """Compare sites with progress updates via SSE.
    
    Args:
        old_url: URL of old site
        new_url: URL of new site
        use_crawl: Whether to crawl instead of using sitemap
        max_pages: Maximum pages to crawl
        combine_methods: Whether to use both sitemap and crawl
        ignore_robots: Whether to ignore robots.txt
        
    Yields:
        SSE formatted progress updates
    """
    progress_queue: queue.Queue = queue.Queue()
    
    def progress_callback(data: dict):
        progress_queue.put(data)
    
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Create progress tracker and comparator
            progress = ProgressTracker(callback=progress_callback)
            config = CrawlConfig(max_pages=max_pages)
            comparator = SiteComparator(progress=progress, config=config)
            
            # Submit comparison task
            future = executor.submit(
                comparator.compare,
                old_url,
                new_url,
                use_crawl,
                combine_methods,
                ignore_robots
            )
            
            # Yield progress updates while waiting
            while not future.done():
                await asyncio.sleep(0.1)
                try:
                    while True:
                        data = progress_queue.get_nowait()
                        yield f"data: {json.dumps(data)}\n\n"
                except queue.Empty:
                    pass
            
            # Get result
            result: ComparisonResult = future.result()
            
            # Send remaining progress
            try:
                while True:
                    data = progress_queue.get_nowait()
                    yield f"data: {json.dumps(data)}\n\n"
            except queue.Empty:
                pass
            
            # Send final result
            yield f"data: {json.dumps({'type': 'result', 'data': result.to_dict()})}\n\n"
            
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@router.post("/compare")
async def compare(
    old_url: str = Form(...),
    new_url: str = Form(...),
    use_crawl: str = Form("false"),
    max_pages: str = Form("10000"),
    combine_methods: str = Form("false"),
    ignore_robots: str = Form("false")
):
    """Compare two sites with real-time progress updates via SSE."""
    # Parse form parameters
    crawl_enabled = use_crawl.lower() in ('true', '1', 'yes', 'on')
    combine_enabled = combine_methods.lower() in ('true', '1', 'yes', 'on')
    ignore_robots_enabled = ignore_robots.lower() in ('true', '1', 'yes', 'on')
    
    try:
        max_pages_int = int(max_pages)
    except (ValueError, TypeError):
        max_pages_int = DEFAULT_APP_CONFIG.default_max_pages
    
    return StreamingResponse(
        _compare_with_progress(
            old_url,
            new_url,
            crawl_enabled,
            max_pages_int,
            combine_enabled,
            ignore_robots_enabled
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/export")
async def export(
    category: str = Form(...),
    missing_on_new: str = Form(""),
    new_only: str = Form(""),
    matched: str = Form(""),
    export_all: str = Form("false")
):
    """Export results as CSV."""
    try:
        # Parse JSON data
        data_map = {
            'missing_on_new': json.loads(missing_on_new) if missing_on_new else [],
            'new_only': json.loads(new_only) if new_only else [],
            'matched': json.loads(matched) if matched else []
        }
        
        export_all_enabled = export_all.lower() in ('true', '1', 'yes', 'on')
        
        if export_all_enabled:
            missing_urls = data_map['missing_on_new']
            new_only_urls = data_map['new_only']
            
            if not missing_urls and not new_only_urls:
                return JSONResponse(status_code=400, content={"error": "No data to export"})
            
            csv_content = export_all_csv(missing_urls, new_only_urls)
            filename = "all_differences.csv"
        else:
            if category not in data_map:
                return JSONResponse(status_code=400, content={"error": "Invalid category"})
            
            urls = data_map[category]
            if not urls:
                return JSONResponse(status_code=400, content={"error": "No data to export"})
            
            csv_content = export_csv(urls, category)
            filename = f"{category}.csv"
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except json.JSONDecodeError as e:
        return JSONResponse(status_code=400, content={"error": f"Invalid JSON data: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Export failed: {str(e)}"})

