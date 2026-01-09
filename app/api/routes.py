"""API routes for site comparison."""

import json
import queue
import asyncio
import concurrent.futures
from typing import AsyncGenerator, Optional, Dict

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from ..models.progress import ProgressTracker
from ..models.comparison import ComparisonResult
from ..services.comparator import SiteComparator
from ..config import CrawlConfig, FilterConfig, ComparisonMode, DEFAULT_APP_CONFIG
from .export import export_csv, export_all_csv, export_pdf, is_pdf_available


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
    ignore_robots: bool,
    comparison_mode: str = 'fuzzy',
    filter_config: Optional[FilterConfig] = None,
    auth: Optional[Dict[str, str]] = None,
    custom_headers: Optional[Dict[str, str]] = None
) -> AsyncGenerator[str, None]:
    """Compare sites with progress updates via SSE.
    
    Args:
        old_url: URL of old site
        new_url: URL of new site
        use_crawl: Whether to crawl instead of using sitemap
        max_pages: Maximum pages to crawl
        combine_methods: Whether to use both sitemap and crawl
        ignore_robots: Whether to ignore robots.txt
        comparison_mode: How to compare URLs (strict/fuzzy/smart)
        filter_config: URL filtering configuration
        auth: Basic auth credentials
        custom_headers: Custom HTTP headers
        
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
            
            # Set additional options
            if filter_config:
                comparator.filter_config = filter_config
            if comparison_mode:
                comparator.comparison_mode = ComparisonMode.from_string(comparison_mode)
            if auth:
                comparator.auth = auth
            if custom_headers:
                comparator.custom_headers = custom_headers
            
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
    ignore_robots: str = Form("false"),
    comparison_mode: str = Form("fuzzy"),
    exclude_paths: str = Form(""),
    exclude_regex: str = Form(""),
    auth_user: str = Form(""),
    auth_pass: str = Form(""),
    custom_headers: str = Form("")
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
    
    # Parse filter config
    filter_config = None
    if exclude_paths or exclude_regex:
        exclude_list = [p.strip() for p in exclude_paths.split(',') if p.strip()]
        filter_config = FilterConfig(
            exclude_paths=exclude_list,
            exclude_regex=exclude_regex if exclude_regex else None
        )
    
    # Parse authentication
    auth = None
    if auth_user and auth_pass:
        auth = {'username': auth_user, 'password': auth_pass}
    
    # Parse custom headers
    headers_dict = None
    if custom_headers:
        try:
            headers_dict = json.loads(custom_headers)
        except json.JSONDecodeError:
            pass
    
    return StreamingResponse(
        _compare_with_progress(
            old_url,
            new_url,
            crawl_enabled,
            max_pages_int,
            combine_enabled,
            ignore_robots_enabled,
            comparison_mode,
            filter_config,
            auth,
            headers_dict
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


@router.post("/export-pdf")
async def export_pdf_route(
    old_url: str = Form(...),
    new_url: str = Form(...),
    old_total: str = Form("0"),
    new_total: str = Form("0"),
    missing_on_new: str = Form(""),
    new_only: str = Form(""),
    matched: str = Form(""),
    match_percentage: str = Form("0")
):
    """Export results as PDF report."""
    if not is_pdf_available():
        return JSONResponse(
            status_code=501, 
            content={"error": "PDF export not available. Install reportlab: pip install reportlab"}
        )
    
    try:
        # Parse JSON data
        missing_list = json.loads(missing_on_new) if missing_on_new else []
        new_only_list = json.loads(new_only) if new_only else []
        matched_list = json.loads(matched) if matched else []
        
        pdf_content = export_pdf(
            old_url=old_url,
            new_url=new_url,
            old_total=int(old_total),
            new_total=int(new_total),
            matched=matched_list,
            missing_on_new=missing_list,
            new_only=new_only_list,
            match_percentage=float(match_percentage)
        )
        
        if pdf_content is None:
            return JSONResponse(status_code=500, content={"error": "Failed to generate PDF"})
        
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=site_parity_report.pdf"}
        )
        
    except json.JSONDecodeError as e:
        return JSONResponse(status_code=400, content={"error": f"Invalid JSON data: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"PDF export failed: {str(e)}"})
