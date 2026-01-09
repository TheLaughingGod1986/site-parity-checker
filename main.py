from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import pandas as pd
from typing import Dict, Set, List, Tuple, Optional, Callable
import io
import json
import asyncio
import time
from collections import deque
import re
from urllib.robotparser import RobotFileParser
from datetime import datetime

# Try to import Playwright for JavaScript rendering
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

app = FastAPI(title="Site Parity Checker")
templates = Jinja2Templates(directory="templates")


def normalize_url(url: str) -> str:
    """Normalize URL: lowercase, strip trailing slash, remove query string and fragment."""
    parsed = urlparse(url)
    path = parsed.path.rstrip('/').lower()
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def get_path_from_url(url: str) -> str:
    """Extract just the path from a normalized URL for comparison (ignores domain)."""
    parsed = urlparse(url)
    return parsed.path.rstrip('/').lower()


def should_exclude_url(url: str, excluded_extensions: set, excluded_path_patterns: list) -> bool:
    """Check if a URL should be excluded from crawling."""
    try:
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        
        # Check excluded extensions
        if any(path_lower.endswith(ext) for ext in excluded_extensions):
            return True
        
        # Check excluded path patterns
        if any(pattern.search(path_lower) for pattern in excluded_path_patterns):
            return True
        
        return False
    except Exception:
        return True  # Exclude if we can't parse it


class ProgressTracker:
    """Tracks progress for site comparison with real-time statistics."""
    
    def __init__(self, progress_callback: Optional[Callable] = None, update_frequency: int = 10):
        self.start_time = time.time()
        self.progress_callback = progress_callback
        self.update_frequency = update_frequency
        
        # Old site tracking
        self.old_pages_scanned = 0
        self.old_urls_found = set()
        self.old_total_estimate = 0
        
        # New site tracking
        self.new_pages_scanned = 0
        self.new_urls_found = set()
        self.new_total_estimate = 0
        
        # Timing data for ETA calculation (moving average of last 20 pages)
        self.page_times = deque(maxlen=20)
        self.last_page_time = None
        
        # Comparison stats
        self.missing_count = 0
        self.new_only_count = 0
        self.matched_count = 0
        self.match_percentage = 0.0
        
        # Limit tracking
        self.limit_reached = False
        self.remaining_queue = 0
        
    def get_elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time
    
    def get_eta(self) -> Optional[float]:
        """Calculate ETA in seconds using moving average."""
        if len(self.page_times) < 2:
            return None
        
        avg_time_per_page = sum(self.page_times) / len(self.page_times)
        remaining_pages = max(0, (self.old_total_estimate - self.old_pages_scanned) + 
                              (self.new_total_estimate - self.new_pages_scanned))
        
        if remaining_pages <= 0:
            return 0.0
        
        return remaining_pages * avg_time_per_page
    
    def record_page_processed(self, site: str = 'old'):
        """Record that a page was processed and update timing."""
        current_time = time.time()
        
        if self.last_page_time is not None:
            page_time = current_time - self.last_page_time
            self.page_times.append(page_time)
        
        self.last_page_time = current_time
        
        if site == 'old':
            self.old_pages_scanned += 1
        else:
            self.new_pages_scanned += 1
    
    def update_urls(self, site: str, urls: Set[str]):
        """Update discovered URLs for a site."""
        if site == 'old':
            self.old_urls_found.update(urls)
        else:
            self.new_urls_found.update(urls)
        
        # Recalculate comparison stats
        self._update_comparison_stats()
    
    def _update_comparison_stats(self):
        """Update comparison statistics.
        Only calculates if both sites have been crawled (to avoid false positives)."""
        # Don't calculate comparison if new site hasn't started crawling yet
        # This prevents showing false "missing" pages when new site crawl hasn't started
        if len(self.new_urls_found) == 0 and self.new_pages_scanned == 0:
            # New site hasn't started - don't show misleading comparison stats
            self.missing_count = 0
            self.new_only_count = 0
            self.matched_count = 0
            self.match_percentage = 0.0
            return
        
        missing = self.old_urls_found - self.new_urls_found
        new_only = self.new_urls_found - self.old_urls_found
        matched = self.old_urls_found & self.new_urls_found
        
        self.missing_count = len(missing)
        self.new_only_count = len(new_only)
        self.matched_count = len(matched)
        
        if len(self.old_urls_found) > 0:
            self.match_percentage = (len(matched) / len(self.old_urls_found)) * 100.0
        else:
            self.match_percentage = 0.0
    
    def get_progress_data(self) -> Dict:
        """Get structured progress data for frontend."""
        elapsed = self.get_elapsed_time()
        eta = self.get_eta()
        
        total_pages = self.old_pages_scanned + self.new_pages_scanned
        total_estimate = max(self.old_total_estimate, self.new_total_estimate, total_pages)
        
        percentage = (total_pages / total_estimate * 100.0) if total_estimate > 0 else 0.0
        
        return {
            'old_site': {
                'pages_scanned': self.old_pages_scanned,
                'total_estimate': self.old_total_estimate,
                'urls_found': len(self.old_urls_found)
            },
            'new_site': {
                'pages_scanned': self.new_pages_scanned,
                'total_estimate': self.new_total_estimate,
                'urls_found': len(self.new_urls_found)
            },
            'comparison': {
                'missing_count': self.missing_count,
                'new_only_count': self.new_only_count,
                'matched_count': self.matched_count,
                'match_percentage': round(self.match_percentage, 1)
            },
            'time': {
                'elapsed_seconds': round(elapsed, 1),
                'eta_seconds': round(eta, 1) if eta is not None else None
            },
            'percentage': round(percentage, 1),
            'limit_reached': self.limit_reached,
            'remaining_queue': self.remaining_queue
        }
    
    def should_send_update(self, site: str = 'old') -> bool:
        """Check if we should send a progress update."""
        pages = self.old_pages_scanned if site == 'old' else self.new_pages_scanned
        # Send updates more frequently for first 100 pages (every page), then every N pages
        if pages <= 100:
            return True  # Send every page for first 100
        return pages % self.update_frequency == 0
    
    def send_progress_update(self, message: str = None, force: bool = False):
        """Send progress update via callback.
        
        Args:
            message: Optional message to include
            force: If True, send update even if frequency check would skip it
        """
        if self.progress_callback:
            progress_data = self.get_progress_data()
            if message:
                self.progress_callback({'type': 'message', 'message': message})
            # Always send progress data (includes time which should update continuously)
            self.progress_callback({'type': 'progress', 'data': progress_data})


def check_robots_txt(base_url: str, path: str) -> bool:
    """Check if a path is allowed by robots.txt.
    
    Args:
        base_url: Base URL of the site
        path: Path to check (e.g., '/page.html')
    
    Returns:
        True if allowed, False if disallowed. Returns True if robots.txt can't be read.
    """
    try:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        full_url = f"{parsed.scheme}://{parsed.netloc}{path}"
        return rp.can_fetch('*', full_url)
    except Exception:
        # If robots.txt doesn't exist or can't be read, allow crawling
        return True


def get_sitemap_url(base_url: str) -> str:
    """Get sitemap URL, checking robots.txt first, then appending /sitemap.xml if needed."""
    if base_url.endswith('/sitemap.xml'):
        return base_url
    
    parsed = urlparse(base_url)
    base_domain = f"{parsed.scheme}://{parsed.netloc}"
    
    # First, try to get sitemap from robots.txt (more reliable)
    try:
        robots_url = f"{base_domain}/robots.txt"
        response = requests.get(robots_url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code == 200:
            for line in response.text.split('\n'):
                line = line.strip()
                if line.lower().startswith('sitemap:'):
                    sitemap_url = line.split(':', 1)[1].strip()
                    if sitemap_url:
                        return sitemap_url
    except Exception:
        pass  # If robots.txt fails, fall back to default
    
    # Fall back to default sitemap.xml location
    return f"{base_domain}/sitemap.xml"


def fetch_sitemap(url: str, visited: Set[str] = None, errors: List[str] = None, progress_callback=None, expected_domain: str = None, progress_tracker=None, site: str = 'old') -> Tuple[Set[str], List[str]]:
    """Fetch sitemap and extract all <loc> entries, filtering out non-HTML content.
    Handles sitemap index files by recursively fetching nested sitemaps.
    If expected_domain is provided, URLs from sitemap will be mapped to that domain.
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
        if callable(progress_callback):
            progress_callback({'type': 'message', 'message': f"Fetching: {url}"})
        else:
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
            if callable(progress_callback):
                progress_callback({'type': 'message', 'message': f"⚠️ Timeout: {url}"})
            else:
                progress_callback(f"⚠️ Timeout: {url}")
        return set(), errors
    except Exception as e:
        error_msg = f"Failed to fetch sitemap {url}: {str(e)}"
        errors.append(error_msg)
        if progress_callback:
            if callable(progress_callback):
                progress_callback({'type': 'message', 'message': f"❌ Error: {url}"})
            else:
                progress_callback(f"❌ Error: {url}")
        return set(), errors
    
    soup = BeautifulSoup(response.content, 'xml')
    
    # Check if this is a sitemap index (contains <sitemap> tags)
    sitemap_tags = soup.find_all('sitemap')
    if sitemap_tags:
        # This is a sitemap index, recursively fetch nested sitemaps
        if progress_callback:
            msg = f"Found sitemap index with {len(sitemap_tags)} nested sitemaps"
            if callable(progress_callback):
                progress_callback({'type': 'message', 'message': msg})
            else:
                progress_callback(msg)
        paths = set()
        for idx, sitemap_tag in enumerate(sitemap_tags, 1):
            loc_tag = sitemap_tag.find('loc')
            if loc_tag:
                nested_url = loc_tag.get_text().strip()
                if progress_callback:
                    msg = f"Processing nested sitemap {idx}/{len(sitemap_tags)}: {nested_url}"
                    if callable(progress_callback):
                        progress_callback({'type': 'message', 'message': msg})
                    else:
                        progress_callback(msg)
                nested_paths, nested_errors = fetch_sitemap(nested_url, visited, errors, progress_callback, expected_domain, progress_tracker, site)
                paths.update(nested_paths)
                errors.extend(nested_errors)
                
                # Record progress for nested sitemaps
                if progress_tracker and nested_paths:
                    progress_tracker.record_page_processed(site)
                    progress_tracker.update_urls(site, nested_paths)
                    if progress_tracker.should_send_update(site):
                        progress_tracker.send_progress_update()
                if progress_callback and nested_paths:
                    msg = f"✓ Found {len(nested_paths)} URLs in {nested_url}"
                    if callable(progress_callback):
                        progress_callback({'type': 'message', 'message': msg})
                    else:
                        progress_callback(msg)
        return paths, errors
    
    # Regular sitemap with <url> or <loc> tags
    locs = soup.find_all('loc')
    
    # Filter out non-HTML content
    excluded_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', 
                          '.css', '.js', '.pdf', '.zip', '.xml', '.ico'}
    
    paths = set()
    domain_mismatches = []
    sitemap_domain = urlparse(url).netloc
    
    for loc in locs:
        url_text = loc.get_text().strip()
        parsed = urlparse(url_text)
        
        # Check if URL has excluded extension
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in excluded_extensions):
            continue
        
        # If expected_domain is provided and URL is from a different domain, map it
        if expected_domain and parsed.netloc != expected_domain:
            # Map the URL to the expected domain
            mapped_url = f"{parsed.scheme}://{expected_domain}{parsed.path}"
            if parsed.query:
                mapped_url += f"?{parsed.query}"
            normalized = normalize_url(mapped_url)
            domain_mismatches.append((url_text, normalized))
        else:
            # Normalize the URL as-is
            normalized = normalize_url(url_text)
        
        paths.add(normalized)
    
    # Record progress for all URLs found in this sitemap (treat each URL as a "page")
    if progress_tracker and paths:
        for _ in paths:
            progress_tracker.record_page_processed(site)
        progress_tracker.update_urls(site, paths)
        if progress_tracker.should_send_update(site):
            progress_tracker.send_progress_update()
    
    # Warn about domain mismatches
    if domain_mismatches and progress_callback:
        unique_domains = set(urlparse(orig_url).netloc for orig_url, _ in domain_mismatches[:5])
        if len(unique_domains) > 0:
            msg1 = f"⚠️ Warning: Found {len(domain_mismatches)} URLs from different domain(s): {', '.join(unique_domains)}"
            msg2 = f"   Mapping them to expected domain: {expected_domain}"
            if callable(progress_callback):
                progress_callback({'type': 'message', 'message': msg1})
                progress_callback({'type': 'message', 'message': msg2})
            else:
                progress_callback(msg1)
                progress_callback(msg2)
    
    if progress_callback and paths:
        msg = f"✓ Found {len(paths)} URLs in {url}"
        if callable(progress_callback):
            progress_callback({'type': 'message', 'message': msg})
        else:
            progress_callback(msg)
    
    return paths, errors


def get_rendered_html(url: str, timeout: int = 30000) -> Optional[str]:
    """Get fully rendered HTML from a URL using Playwright (for JavaScript-rendered sites).
    
    Args:
        url: URL to fetch
        timeout: Timeout in milliseconds
    
    Returns:
        Rendered HTML content or None if Playwright is not available or fails
    """
    if not PLAYWRIGHT_AVAILABLE:
        return None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            # Set a longer timeout for slow-loading pages
            page.set_default_timeout(timeout)
            # Navigate and wait for content to load
            page.goto(url, wait_until='domcontentloaded', timeout=timeout)
            # Wait a bit for JavaScript to execute
            page.wait_for_timeout(2000)  # Wait 2 seconds for JS to render
            # Try to wait for network to be idle, but don't fail if it doesn't
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except:
                pass  # Continue even if networkidle doesn't happen
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        return None


def crawl_domain(base_url: str, max_pages: int = 10000, max_depth: int = 5, progress_callback=None, progress_tracker: Optional[ProgressTracker] = None, site: str = 'old', use_js_rendering: bool = False, respect_robots: bool = True) -> Tuple[Set[str], List[str]]:
    """Crawl a domain starting from base_url to discover all pages.
    
    Args:
        base_url: Starting URL (typically homepage)
        max_pages: Maximum number of pages to crawl
        max_depth: Maximum depth to crawl from starting URL
        progress_callback: Optional callback function for progress updates
        progress_tracker: Optional ProgressTracker instance for structured progress
        site: Site identifier ('old' or 'new') for progress tracking
        use_js_rendering: Whether to use Playwright for JavaScript rendering
        respect_robots: Whether to respect robots.txt (default: True)
    
    Returns:
        Tuple of (discovered_urls_set, errors_list)
    """
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc
    base_scheme = parsed_base.scheme
    base_netloc = f"{base_scheme}://{base_domain}"
    
    # Handle www redirects - normalize domain for comparison
    base_domain_normalized = base_domain.replace('www.', '')
    
    visited = set()  # Use normalized URLs
    to_visit = deque([(base_url, 0)])  # (url, depth)
    queued_urls = set()  # Track queued URLs for O(1) lookup
    discovered = set()
    errors = []
    robots_blocked_count = 0  # Track blocked URLs without spamming logs
    
    # Filter out non-HTML content
    excluded_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', 
                          '.css', '.js', '.pdf', '.zip', '.xml', '.ico', '.woff', '.woff2',
                          '.ttf', '.eot', '.mp4', '.mp3', '.avi', '.mov'}
    
    # Use regex patterns for more precise path exclusion
    excluded_path_patterns = [
        re.compile(r'^/api/'),
        re.compile(r'^/admin/'),
        re.compile(r'^/wp-admin/'),
        re.compile(r'/chunks/'),  # Filter out JS bundle chunks
        re.compile(r'/chunk/'),   # Alternative chunk path
        re.compile(r'\.chunk\.'), # Chunk files
        re.compile(r'/media/[^/]+-[a-f0-9]+'),  # Media files with hash (e.g., /media/abc-123)
        re.compile(r'/media/[^/]+-[a-z0-9]+'),  # Media files with hash (alternative pattern)
        re.compile(r'/s/[a-f0-9]+'),  # Shortened URLs (e.g., /s/abc123)
        re.compile(r'^/embed/'),  # Embed URLs (e.g., /embed/NB0, /embed/video)
        re.compile(r'/wp-content/uploads/'),  # WordPress media uploads
        re.compile(r'/_next/'),
        re.compile(r'/static/'),
        re.compile(r'/assets/'),
        re.compile(r'/images/'),
        re.compile(r'/img/'),
        re.compile(r'/css/'),
        re.compile(r'/js/'),
        re.compile(r'/fonts/')
    ]
    
    if progress_tracker:
        progress_tracker.old_total_estimate = max_pages if site == 'old' else progress_tracker.old_total_estimate
        progress_tracker.new_total_estimate = max_pages if site == 'new' else progress_tracker.new_total_estimate
    
    if progress_callback:
        msg1 = f"🕷️ Starting crawl of {base_domain}..."
        msg2 = f"   Max pages: {max_pages}, Max depth: {max_depth}"
        if callable(progress_callback):
            progress_callback({'type': 'message', 'message': msg1})
            progress_callback({'type': 'message', 'message': msg2})
        else:
            progress_callback(msg1)
            progress_callback(msg2)
    
    while to_visit and len(visited) < max_pages:
        current_url, depth = to_visit.popleft()
        
        # Normalize URL immediately before checking visited set
        normalized = normalize_url(current_url)
        
        # Skip if already visited or too deep
        if normalized in visited or depth > max_depth:
            continue
        
        visited.add(normalized)
        queued_urls.discard(normalized)  # Remove from queue tracking
        
        # Check if URL should be excluded
        parsed = urlparse(current_url)
        path_lower = parsed.path.lower()
        
        # Skip excluded extensions
        if any(path_lower.endswith(ext) for ext in excluded_extensions):
            continue
        
        # Check excluded paths with regex (more precise)
        if any(pattern.search(path_lower) for pattern in excluded_path_patterns):
            continue
        
        # Only crawl same domain (handle www redirects)
        parsed_domain_normalized = parsed.netloc.replace('www.', '')
        if parsed.netloc != base_domain and parsed_domain_normalized != base_domain_normalized:
            continue
        
        # Check robots.txt (if enabled)
        if respect_robots and not check_robots_txt(base_url, parsed.path):
            robots_blocked_count += 1
            # Only log first few and then summarize periodically to reduce spam
            if robots_blocked_count <= 3:
                if progress_callback:
                    msg = f"🚫 Blocked by robots.txt: {current_url}"
                    if callable(progress_callback):
                        progress_callback({'type': 'message', 'message': msg})
                    else:
                        progress_callback(msg)
            elif robots_blocked_count % 50 == 0:
                if progress_callback:
                    msg = f"🚫 {robots_blocked_count} URLs blocked by robots.txt so far..."
                    if callable(progress_callback):
                        progress_callback({'type': 'message', 'message': msg})
                    else:
                        progress_callback(msg)
            continue
        
        try:
            # Try regular request first
            response = requests.get(current_url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=True)
            response.raise_for_status()
            
            # Use final URL after redirects
            final_url = response.url
            final_normalized = normalize_url(final_url)
            
            # Check if it's HTML
            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type:
                continue
            
            # Add final URL to discovered set (not original)
            discovered.add(final_normalized)
            
            # Record page processing for progress tracking (after successful fetch)
            if progress_tracker:
                progress_tracker.record_page_processed(site)
                progress_tracker.update_urls(site, discovered)
                # Send progress update more frequently (every page for first 100, then every 10)
                if len(visited) <= 100 or progress_tracker.should_send_update(site):
                    progress_tracker.send_progress_update()
            
            # Report progress message
            if progress_callback and len(visited) % 10 == 0:
                msg = f"   Crawled {len(visited)} pages, found {len(discovered)} URLs, queue: {len(to_visit)}"
                if callable(progress_callback):
                    progress_callback({'type': 'message', 'message': msg})
                else:
                    progress_callback(msg)
            
            # Get HTML content - use Playwright if enabled and available
            html_content = response.content
            # Use Playwright more aggressively:
            # - Always for homepage (depth 0)
            # - For first 3 levels (depth < 3) when enabled
            # - For new site, be more aggressive (depth < 4)
            should_render_js = use_js_rendering and PLAYWRIGHT_AVAILABLE
            if should_render_js:
                max_js_depth = 4 if site == 'new' else 3  # More aggressive for new site
                if depth == 0 or depth < max_js_depth:
                    if progress_callback:
                        msg = f"   🌐 Rendering JavaScript for {final_url}..."
                        if callable(progress_callback):
                            progress_callback({'type': 'message', 'message': msg})
                        else:
                            progress_callback(msg)
                    rendered_html = get_rendered_html(final_url, timeout=45000)  # Longer timeout
                    if rendered_html:
                        html_content = rendered_html.encode('utf-8')
            
            # Parse HTML and extract links
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Check for canonical URL
            canonical = soup.find('link', {'rel': 'canonical'})
            if canonical and canonical.get('href'):
                canonical_url = urljoin(final_url, canonical['href'])
                canonical_normalized = normalize_url(canonical_url)
                if canonical_normalized != final_normalized:
                    discovered.add(canonical_normalized)
            
            # Extract links from JavaScript data (common in SPAs)
            # Look for JSON-LD structured data
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        # Look for URLs in common fields
                        for key in ['url', 'mainEntityOfPage', 'sameAs', 'breadcrumb']:
                            if key in data:
                                if isinstance(data[key], str) and data[key].startswith('http'):
                                    discovered.add(normalize_url(data[key]))
                                elif isinstance(data[key], dict) and 'url' in data[key]:
                                    discovered.add(normalize_url(data[key]['url']))
                except:
                    pass
            
            # Look for links in data attributes (common in React/Vue apps)
            for element in soup.find_all(attrs={'data-href': True}):
                href = element.get('data-href')
                if href:
                    absolute_url = urljoin(final_url, href)
                    parsed_link = urlparse(absolute_url)
                    link_domain_normalized = parsed_link.netloc.replace('www.', '')
                    if link_domain_normalized == base_domain_normalized:
                        normalized_link = normalize_url(absolute_url)
                        if normalized_link not in visited and normalized_link not in queued_urls:
                            # Filter out excluded URLs before adding to queue
                            if not should_exclude_url(absolute_url, excluded_extensions, excluded_path_patterns):
                                to_visit.append((absolute_url, depth + 1))
                                queued_urls.add(normalized_link)
            
            # Look for links in JavaScript variables (common pattern)
            # Enhanced patterns for SPAs (Next.js, React Router, etc.)
            script_tags = soup.find_all('script')
            js_urls_found = 0
            for script in script_tags:
                if script.string:
                    # Multiple URL patterns for JavaScript
                    url_patterns = [
                        re.compile(r'["\'](https?://[^"\']+)["\']'),  # Standard URLs in quotes
                        re.compile(r'["\'](/(?:[a-z0-9-]+/)+[a-z0-9-]+)["\']', re.IGNORECASE),  # Path patterns
                        re.compile(r'path:\s*["\']([^"\']+)["\']', re.IGNORECASE),  # Route paths
                        re.compile(r'url:\s*["\']([^"\']+)["\']', re.IGNORECASE),  # URL properties
                        re.compile(r'href:\s*["\']([^"\']+)["\']', re.IGNORECASE),  # href in objects
                        re.compile(r'/(?:[a-z0-9-]+/)+[a-z0-9-]+', re.IGNORECASE),  # General path patterns
                    ]
                    
                    for pattern in url_patterns:
                        matches = pattern.findall(script.string)
                        for match in matches:
                            try:
                                # Clean match - remove backslashes FIRST
                                match = match.replace('\\', '')
                                match = match.strip('"\'')
                                if not match:
                                    continue
                                
                                # Convert to absolute URL if relative
                                if match.startswith('http'):
                                    parsed_match = urlparse(match)
                                elif match.startswith('/'):
                                    match = f"{base_scheme}://{base_domain}{match}"
                                    parsed_match = urlparse(match)
                                else:
                                    continue
                                
                                match_domain_normalized = parsed_match.netloc.replace('www.', '')
                                if match_domain_normalized == base_domain_normalized:
                                    normalized_match = normalize_url(match)
                                    if normalized_match not in visited and normalized_match not in queued_urls:
                                        # Filter out excluded URLs before adding to queue
                                        if not should_exclude_url(match, excluded_extensions, excluded_path_patterns):
                                            to_visit.append((match, depth + 1))
                                            queued_urls.add(normalized_match)
                                            js_urls_found += 1
                            except Exception:
                                pass
            
            # Find all links (including in <nav>, <menu>, etc.)
            links_found = 0
            for link in soup.find_all('a', href=True):
                href = link['href'].strip()
                
                # Skip empty, javascript, mailto, tel links
                if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                    continue
                
                # Clean up href - remove escaped characters that might cause issues
                href = href.replace('\\', '')
                
                # Convert relative URLs to absolute (use final_url after redirects)
                try:
                    absolute_url = urljoin(final_url, href)
                except Exception:
                    continue
                    
                parsed_link = urlparse(absolute_url)
                
                # Only follow same-domain links (handle www redirects)
                # Check if domains match (with or without www)
                link_domain = parsed_link.netloc
                link_domain_normalized = link_domain.replace('www.', '')
                
                # Allow links to same domain (with or without www)
                if link_domain != base_domain and link_domain_normalized != base_domain_normalized:
                    continue
                
                # Normalize and check if we should visit
                normalized_link = normalize_url(absolute_url)
                
                # Efficient O(1) check
                if normalized_link not in visited and normalized_link not in queued_urls:
                    # Filter out excluded URLs before adding to queue
                    if not should_exclude_url(absolute_url, excluded_extensions, excluded_path_patterns):
                        to_visit.append((absolute_url, depth + 1))
                        queued_urls.add(normalized_link)
                        links_found += 1
            
            # Always run aggressive URL extraction on homepage (depth == 0) for SPAs
            # Also run if very few links found (less than 10) on any page
            should_scan_aggressively = (depth == 0) or (links_found < 10 and depth < 2)
            
            if should_scan_aggressively:
                if progress_callback and depth == 0:
                    msg = f"   Scanning page content for URLs (SPA detection)..."
                    if callable(progress_callback):
                        progress_callback({'type': 'message', 'message': msg})
                    else:
                        progress_callback(msg)
                
                # Try to find any URLs in the page content as fallback
                # Use rendered HTML if available, otherwise use response text
                if should_render_js and PLAYWRIGHT_AVAILABLE and (depth == 0 or depth < (4 if site == 'new' else 3)):
                    # If we already rendered with Playwright, use that content
                    if isinstance(html_content, bytes):
                        page_text = html_content.decode('utf-8', errors='ignore')
                    else:
                        page_text = str(html_content)
                else:
                    page_text = response.text
                
                # Look for URL patterns in the raw HTML (more aggressive)
                # Match URLs with the domain (with or without www)
                url_patterns = [
                    re.compile(r'https?://(?:www\.)?' + re.escape(base_domain_normalized) + r'[^\s"\'<>)]+', re.IGNORECASE),
                    re.compile(r'["\'](?:https?://)?(?:www\.)?' + re.escape(base_domain_normalized) + r'[^\s"\'<>)]+["\']', re.IGNORECASE),
                    re.compile(r'/(?:[a-z0-9-]+/)+[a-z0-9-]+', re.IGNORECASE),  # Path patterns
                    re.compile(r'["\']/(?:[a-z0-9-]+/)+[a-z0-9-]+["\']', re.IGNORECASE),  # Quoted paths
                ]
                
                found_urls = set()
                for pattern in url_patterns:
                    matches = pattern.findall(page_text)
                    for match in matches:
                        # Clean up the match
                        match = match.strip('"\'')
                        if match.startswith('http'):
                            found_urls.add(match)
                        elif match.startswith('/'):
                            found_urls.add(f"{base_scheme}://{base_domain}{match}")
                
                aggressive_found = 0
                for found_url in list(found_urls)[:200]:  # Increased limit for SPAs
                    try:
                        # Clean URL FIRST - remove backslashes before any other processing
                        found_url = found_url.replace('\\', '')
                        # Remove escaped characters, quotes, etc.
                        found_url = found_url.split('"')[0].split("'")[0].split(')')[0].split('?')[0].split('#')[0]
                        # Remove any trailing punctuation that might have been captured
                        found_url = found_url.rstrip('.,;:!?')
                        
                        # Skip if empty or too short
                        if len(found_url) < 10:
                            continue
                            
                        parsed_found = urlparse(found_url)
                        if not parsed_found.netloc:
                            continue
                        found_domain_normalized = parsed_found.netloc.replace('www.', '')
                        if found_domain_normalized == base_domain_normalized:
                            found_normalized = normalize_url(found_url)
                            if found_normalized not in visited and found_normalized not in queued_urls:
                                # Filter out excluded URLs before adding to queue
                                if not should_exclude_url(found_url, excluded_extensions, excluded_path_patterns):
                                    to_visit.append((found_url, depth + 1))
                                    queued_urls.add(found_normalized)
                                    aggressive_found += 1
                    except Exception as e:
                        pass
                
                if aggressive_found > 0 and progress_callback:
                    msg = f"   ✓ Found {aggressive_found} additional URLs by scanning page content"
                    if callable(progress_callback):
                        progress_callback({'type': 'message', 'message': msg})
                    else:
                        progress_callback(msg)
                elif links_found == 0 and js_urls_found == 0 and progress_callback:
                    msg = f"⚠️ Warning: Very few links found on {final_url}. This might be a JavaScript-rendered page (SPA)."
                    if callable(progress_callback):
                        progress_callback({'type': 'message', 'message': msg})
                    else:
                        progress_callback(msg)
            
            # Small delay to be respectful
            time.sleep(0.1)
            
        except requests.exceptions.Timeout:
            error_msg = f"Timeout crawling: {current_url}"
            errors.append(error_msg)
            if progress_callback:
                msg = f"⚠️ Timeout: {current_url}"
                if callable(progress_callback):
                    progress_callback({'type': 'message', 'message': msg})
                else:
                    progress_callback(msg)
        except requests.exceptions.TooManyRedirects:
            error_msg = f"Too many redirects: {current_url}"
            errors.append(error_msg)
        except Exception as e:
            error_msg = f"Error crawling {current_url}: {str(e)}"
            errors.append(error_msg)
            # Don't spam errors for every failed page
            if len(errors) <= 10:
                if progress_callback:
                    msg = f"⚠️ Error: {current_url[:80]}..."
                    if callable(progress_callback):
                        progress_callback({'type': 'message', 'message': msg})
                    else:
                        progress_callback(msg)
    
    # Check if we hit the max_pages limit
    limit_reached = len(visited) >= max_pages and to_visit
    
    # Report robots.txt blocking summary
    if robots_blocked_count > 3:
        if progress_callback:
            msg = f"🚫 Total: {robots_blocked_count} URLs blocked by robots.txt (not crawled)"
            if callable(progress_callback):
                progress_callback({'type': 'message', 'message': msg})
            else:
                progress_callback(msg)
    
    # Final update with all discovered URLs
    if progress_tracker:
        progress_tracker.update_urls(site, discovered)
        # Mark if limit was reached in progress data
        if limit_reached:
            progress_tracker.limit_reached = True
            progress_tracker.remaining_queue = len(to_visit)
        progress_tracker.send_progress_update()
    
    if progress_callback:
        if limit_reached:
            msg1 = f"⚠️ WARNING: Reached maximum page limit ({max_pages})"
            msg2 = f"   Found {len(discovered)} URLs from {len(visited)} pages crawled"
            msg3 = f"   ⚠️ {len(to_visit)} URLs still in queue - some pages may be missing!"
            msg4 = f"   💡 Tip: Increase 'Max Pages to Crawl' above {max_pages} to crawl more pages"
            if callable(progress_callback):
                progress_callback({'type': 'message', 'message': msg1})
                progress_callback({'type': 'message', 'message': msg2})
                progress_callback({'type': 'message', 'message': msg3})
                progress_callback({'type': 'message', 'message': msg4})
            else:
                progress_callback(msg1)
                progress_callback(msg2)
                progress_callback(msg3)
                progress_callback(msg4)
        else:
            msg = f"✓ Crawl complete: Found {len(discovered)} URLs from {len(visited)} pages crawled"
            if callable(progress_callback):
                progress_callback({'type': 'message', 'message': msg})
            else:
                progress_callback(msg)
    
    return discovered, errors


def compare_sites(old_url: str, new_url: str, progress_callback=None, use_crawl: bool = False, max_pages: int = 10000, combine_methods: bool = False, ignore_robots: bool = False) -> Dict:
    """Compare two sites and return differences.
    
    Args:
        old_url: URL of the old site
        new_url: URL of the new site
        progress_callback: Optional callback for progress updates (can be dict-based or string-based)
        use_crawl: If True, crawl the site instead of using sitemap
        max_pages: Maximum pages to crawl (if use_crawl=True)
        combine_methods: If True, use both sitemap AND crawl, merging results
    """
    # Parse base URLs to get expected domains
    old_parsed = urlparse(old_url)
    new_parsed = urlparse(new_url)
    old_domain = f"{old_parsed.scheme}://{old_parsed.netloc}"
    new_domain = f"{new_parsed.scheme}://{new_parsed.netloc}"
    
    # Create progress tracker - always create if callback provided
    progress_tracker = None
    if progress_callback:
        progress_tracker = ProgressTracker(progress_callback, update_frequency=10)
        # Initialize total estimates to max_pages for both sites
        progress_tracker.old_total_estimate = max_pages
        progress_tracker.new_total_estimate = max_pages
    
    # Helper function to send messages
    def send_message(msg: str):
        if progress_callback:
            # Send as structured message dict
            progress_callback({'type': 'message', 'message': msg})
    
    send_message("Starting comparison...")
    send_message(f"Old site: {old_domain}")
    send_message(f"New site: {new_domain}")
    
    if combine_methods:
        send_message("Method: Sitemap + Crawling (comprehensive)")
    else:
        send_message(f"Method: {'Crawling' if use_crawl else 'Sitemap'}")
    
    old_paths = set()
    new_paths = set()
    old_errors = []
    new_errors = []
    old_sitemap = None
    new_sitemap = None
    
    # Always try to get sitemaps (even when crawling, to ensure we don't miss pages)
    old_sitemap = get_sitemap_url(old_url)
    new_sitemap = get_sitemap_url(new_url)
    send_message(f"Old site sitemap: {old_sitemap}")
    send_message(f"New site sitemap: {new_sitemap}")
    
    # Fetch sitemaps if available and not crawling-only
    # (If crawling-only, we'll still try sitemap as a fallback to catch unlinked pages)
    if combine_methods or not use_crawl:
        # Fetch sitemaps
        send_message("📥 Fetching sitemaps...")
        
        old_sitemap_paths, old_sitemap_errors = fetch_sitemap(
            old_sitemap, 
            progress_callback=progress_callback, 
            expected_domain=old_parsed.netloc,
            progress_tracker=progress_tracker,
            site='old'
        )
        new_sitemap_paths, new_sitemap_errors = fetch_sitemap(
            new_sitemap, 
            progress_callback=progress_callback, 
            expected_domain=new_parsed.netloc,
            progress_tracker=progress_tracker,
            site='new'
        )
        
        old_paths.update(old_sitemap_paths)
        new_paths.update(new_sitemap_paths)
        old_errors.extend(old_sitemap_errors)
        new_errors.extend(new_sitemap_errors)
        
        if progress_tracker:
            # Set estimates based on URLs found (for sitemap, URLs = "pages")
            progress_tracker.old_total_estimate = max(len(old_sitemap_paths), progress_tracker.old_total_estimate)
            progress_tracker.new_total_estimate = max(len(new_sitemap_paths), progress_tracker.new_total_estimate)
            # Update pages scanned (for sitemap, treat each URL as a "page")
            progress_tracker.old_pages_scanned = len(old_sitemap_paths)
            progress_tracker.new_pages_scanned = len(new_sitemap_paths)
            progress_tracker.update_urls('old', old_sitemap_paths)
            progress_tracker.update_urls('new', new_sitemap_paths)
            progress_tracker.send_progress_update()
        
        send_message(f"✓ Sitemaps: Old={len(old_sitemap_paths)}, New={len(new_sitemap_paths)}")
    
    if combine_methods or use_crawl:
        # Crawl sites
        send_message("🕷️ Crawling sites...")
        
        # Use JavaScript rendering for crawling (helps with SPAs)
        old_crawl_paths, old_crawl_errors = crawl_domain(
            old_url, 
            max_pages=max_pages, 
            progress_callback=progress_callback,
            progress_tracker=progress_tracker,
            site='old',
            use_js_rendering=True,
            respect_robots=not ignore_robots
        )
        new_crawl_paths, new_crawl_errors = crawl_domain(
            new_url, 
            max_pages=max_pages, 
            progress_callback=progress_callback,
            progress_tracker=progress_tracker,
            site='new',
            use_js_rendering=True,
            respect_robots=not ignore_robots
        )
        
        old_paths.update(old_crawl_paths)
        new_paths.update(new_crawl_paths)
        old_errors.extend(old_crawl_errors)
        new_errors.extend(new_crawl_errors)
        
        if progress_tracker:
            progress_tracker.update_urls('old', old_crawl_paths)
            progress_tracker.update_urls('new', new_crawl_paths)
            progress_tracker.send_progress_update()
        
        send_message(f"✓ Crawl: Old={len(old_crawl_paths)}, New={len(new_crawl_paths)}")
        
        # If crawling-only (not combining), try to supplement with sitemap if available
        # This helps catch pages that aren't linked from other pages
        # Also use sitemap as fallback if crawl found very few URLs (likely blocked by robots.txt)
        if use_crawl and not combine_methods:
            # Check if crawl found very few URLs (possible robots.txt blocking)
            old_crawl_found_few = len(old_crawl_paths) < 10
            new_crawl_found_few = len(new_crawl_paths) < 10
            
            if old_crawl_found_few or new_crawl_found_few:
                send_message("⚠️ Crawl found very few URLs. Attempting sitemap fallback...")
                if old_crawl_found_few:
                    send_message(f"   Old site: Only {len(old_crawl_paths)} URLs from crawl (expected many more)")
                if new_crawl_found_few:
                    send_message(f"   New site: Only {len(new_crawl_paths)} URLs from crawl (expected many more)")
            
            # ALWAYS try to fetch sitemaps as a supplement (critical for accurate comparison)
            old_sitemap_paths = set()
            new_sitemap_paths = set()
            old_sitemap_error = None
            new_sitemap_error = None
            
            if old_sitemap:
                try:
                    send_message(f"📋 Fetching old site sitemap: {old_sitemap}")
                    old_sitemap_paths, old_sitemap_errors = fetch_sitemap(
                        old_sitemap, 
                        progress_callback=progress_callback,
                        expected_domain=old_parsed.netloc,
                        progress_tracker=progress_tracker,
                        site='old'
                    )
                    if old_sitemap_paths:
                        send_message(f"✓ Fetched {len(old_sitemap_paths)} URLs from old site sitemap")
                        # Warn if sitemap seems incomplete (very few URLs)
                        if len(old_sitemap_paths) < 20:
                            send_message(f"⚠️ WARNING: Old site sitemap only has {len(old_sitemap_paths)} URLs - this seems incomplete!")
                            send_message(f"   💡 Enable 'Ignore robots.txt' to allow full crawling, or 'Combine methods' for better coverage")
                    elif old_sitemap_errors:
                        send_message(f"⚠️ Old site sitemap had {len(old_sitemap_errors)} errors")
                except Exception as e:
                    old_sitemap_error = str(e)
                    send_message(f"❌ Failed to fetch old site sitemap: {str(e)}")
            
            if new_sitemap:
                try:
                    send_message(f"📋 Fetching new site sitemap: {new_sitemap}")
                    new_sitemap_paths, new_sitemap_errors = fetch_sitemap(
                        new_sitemap, 
                        progress_callback=progress_callback,
                        expected_domain=new_parsed.netloc,
                        progress_tracker=progress_tracker,
                        site='new'
                    )
                    if new_sitemap_paths:
                        send_message(f"✓ Fetched {len(new_sitemap_paths)} URLs from new site sitemap")
                        # Warn if sitemap seems incomplete (very few URLs)
                        if len(new_sitemap_paths) < 20:
                            send_message(f"⚠️ WARNING: New site sitemap only has {len(new_sitemap_paths)} URLs - this seems incomplete!")
                            send_message(f"   💡 Enable 'Ignore robots.txt' to allow full crawling, or 'Combine methods' for better coverage")
                    elif new_sitemap_errors:
                        send_message(f"⚠️ New site sitemap had {len(new_sitemap_errors)} errors")
                except Exception as e:
                    new_sitemap_error = str(e)
                    send_message(f"❌ Failed to fetch new site sitemap: {str(e)}")
            
            # Add any URLs from sitemap that weren't found by crawling
            old_before = len(old_paths)
            new_before = len(new_paths)
            old_paths.update(old_sitemap_paths)
            new_paths.update(new_sitemap_paths)
            old_added = len(old_paths) - old_before
            new_added = len(new_paths) - new_before
            
            if old_added > 0 or new_added > 0:
                send_message(f"✓ Sitemap supplement: Added {old_added} old URLs, {new_added} new URLs not found by crawling")
            elif old_crawl_found_few and old_sitemap_paths:
                send_message(f"⚠️ Old site crawl blocked, using sitemap as primary source ({len(old_sitemap_paths)} URLs)")
                if len(old_sitemap_paths) < 20:
                    send_message(f"⚠️ WARNING: Sitemap appears incomplete ({len(old_sitemap_paths)} URLs). Enable 'Ignore robots.txt' for full crawling!")
            elif new_crawl_found_few and new_sitemap_paths:
                send_message(f"⚠️ New site crawl blocked, using sitemap as primary source ({len(new_sitemap_paths)} URLs)")
                if len(new_sitemap_paths) < 20:
                    send_message(f"⚠️ WARNING: Sitemap appears incomplete ({len(new_sitemap_paths)} URLs). Enable 'Ignore robots.txt' for full crawling!")
            elif old_crawl_found_few and not old_sitemap_paths and not old_sitemap_error:
                send_message(f"⚠️ WARNING: Old site crawl found only {len(old_crawl_paths)} URLs and sitemap is empty/unavailable!")
                send_message(f"   This will cause inaccurate comparison results!")
                send_message(f"   💡 Enable 'Ignore robots.txt' to allow full crawling")
            elif new_crawl_found_few and not new_sitemap_paths and not new_sitemap_error:
                send_message(f"⚠️ WARNING: New site crawl found only {len(new_crawl_paths)} URLs and sitemap is empty/unavailable!")
                send_message(f"   This will cause inaccurate comparison results!")
                send_message(f"   💡 Enable 'Ignore robots.txt' to allow full crawling")
        
        if combine_methods:
            send_message(f"✓ Combined: Old={len(old_paths)} total, New={len(new_paths)} total")
    
    # Combine all errors
    all_errors = old_errors + new_errors
    
    # Compare using paths only (ignore domain differences)
    send_message("🔍 Comparing sites (by path only, ignoring domains)...")
    send_message(f"   Old site: {len(old_paths)} URLs found")
    send_message(f"   New site: {len(new_paths)} URLs found")
    
    # Extract paths from URLs for comparison
    old_paths_only = {get_path_from_url(url) for url in old_paths}
    new_paths_only = {get_path_from_url(url) for url in new_paths}
    
    send_message(f"   Old site unique paths: {len(old_paths_only)}")
    send_message(f"   New site unique paths: {len(new_paths_only)}")
    
    # Compare paths
    missing_on_new_paths = old_paths_only - new_paths_only
    new_only_paths = new_paths_only - old_paths_only
    matched_paths = old_paths_only & new_paths_only
    
    send_message(f"   Matched paths: {len(matched_paths)}")
    send_message(f"   Missing on new: {len(missing_on_new_paths)} paths")
    send_message(f"   New only: {len(new_only_paths)} paths")
    
    # Map paths back to full URLs for results
    # Create mapping from path to full URLs (handle multiple URLs with same path)
    old_path_to_urls = {}
    for url in old_paths:
        path = get_path_from_url(url)
        if path not in old_path_to_urls:
            old_path_to_urls[path] = []
        old_path_to_urls[path].append(url)
    
    new_path_to_urls = {}
    for url in new_paths:
        path = get_path_from_url(url)
        if path not in new_path_to_urls:
            new_path_to_urls[path] = []
        new_path_to_urls[path].append(url)
    
    # Convert back to full URLs for results (use first URL for each path)
    missing_on_new = []
    for path in missing_on_new_paths:
        missing_on_new.extend(old_path_to_urls.get(path, []))
    
    new_only = []
    for path in new_only_paths:
        new_only.extend(new_path_to_urls.get(path, []))
    
    matched = []
    for path in matched_paths:
        # Include both old and new URLs for matched paths
        matched.extend(old_path_to_urls.get(path, []))
    
    send_message("✓ Comparison complete!")
    send_message(f"  - Missing on new: {len(missing_on_new)}")
    send_message(f"  - New only: {len(new_only)}")
    send_message(f"  - Matched: {len(matched)}")
    
    # Debug: Show sample of "new only" URLs to help diagnose
    if new_only and len(new_only) > 0:
        send_message(f"  📋 Sample of 'New Only' URLs (first 10):")
        for url in list(new_only)[:10]:
            path = get_path_from_url(url)
            send_message(f"     - {path}")
        
        # Also show what old site has for comparison
        if len(old_paths_only) < 50:  # Only if old site has few paths
            send_message(f"  📋 For comparison, Old site paths ({len(old_paths_only)} total):")
            for path in sorted(list(old_paths_only))[:20]:
                send_message(f"     - {path}")
    
    # Send final progress update with 100% completion
    if progress_tracker:
        # Ensure we have final URL counts
        progress_tracker.update_urls('old', old_paths)
        progress_tracker.update_urls('new', new_paths)
        # Set pages scanned to match total estimate for 100% completion
        progress_tracker.old_pages_scanned = max(progress_tracker.old_pages_scanned, len(old_paths))
        progress_tracker.new_pages_scanned = max(progress_tracker.new_pages_scanned, len(new_paths))
        progress_tracker.old_total_estimate = max(progress_tracker.old_total_estimate, len(old_paths))
        progress_tracker.new_total_estimate = max(progress_tracker.new_total_estimate, len(new_paths))
        progress_tracker.send_progress_update()
    
    result = {
        'missing_on_new': list(missing_on_new),
        'new_only': list(new_only),
        'matched': list(matched),
        'old_sample_urls': list(old_paths)[:10],
        'new_sample_urls': list(new_paths)[:10],
        'old_total': len(old_paths),
        'new_total': len(new_paths)
    }
    
    if old_sitemap:
        result['old_sitemap'] = old_sitemap
    if new_sitemap:
        result['new_sitemap'] = new_sitemap
    
    # Add warnings if there were errors (but we still got some data)
    if all_errors:
        result['warnings'] = all_errors
        result['warning_message'] = f"Some operations failed ({len(all_errors)} errors). Results may be incomplete."
    
    return result


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with form."""
    return templates.TemplateResponse("index.html", {"request": request})


async def compare_with_progress(old_url: str, new_url: str, use_crawl: bool = False, max_pages: int = 10000, combine_methods: bool = False, ignore_robots: bool = False):
    """Compare sites with progress updates via generator."""
    import queue
    progress_queue = queue.Queue()
    
    def progress_callback(data: dict):
        """Structured progress callback that accepts dict or string."""
        progress_queue.put(data)
    
    try:
        # Run comparison in a thread to avoid blocking
        import concurrent.futures
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(compare_sites, old_url, new_url, progress_callback, use_crawl, max_pages, combine_methods, ignore_robots)
            
            # Yield progress updates while waiting
            while not future.done():
                await asyncio.sleep(0.1)  # Small delay to check for updates
                try:
                    while True:
                        data = progress_queue.get_nowait()
                        # Handle both structured and legacy string callbacks
                        if isinstance(data, dict):
                            yield f"data: {json.dumps(data)}\n\n"
                        else:
                            # Legacy string message
                            yield f"data: {json.dumps({'type': 'progress', 'message': data})}\n\n"
                except queue.Empty:
                    pass
            
            # Get final result
            result = future.result()
            
            # Send any remaining progress messages
            try:
                while True:
                    data = progress_queue.get_nowait()
                    if isinstance(data, dict):
                        yield f"data: {json.dumps(data)}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'progress', 'message': data})}\n\n"
            except queue.Empty:
                pass
            
            # Send final result
            yield f"data: {json.dumps({'type': 'result', 'data': result})}\n\n"
            
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@app.post("/compare")
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
        max_pages_int = 10000  # Default to 10,000 for comprehensive crawling
    
    return StreamingResponse(
        compare_with_progress(old_url, new_url, crawl_enabled, max_pages_int, combine_enabled, ignore_robots_enabled),
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
    matched: str = Form(""),
    export_all: str = Form("false")
):
    """Export selected category as CSV, or export all (missing + new_only) if export_all is true."""
    import json
    
    try:
        # Parse the JSON strings (they come as strings from form data)
        data_map = {
            'missing_on_new': json.loads(missing_on_new) if missing_on_new else [],
            'new_only': json.loads(new_only) if new_only else [],
            'matched': json.loads(matched) if matched else []
        }
        
        export_all_enabled = export_all.lower() in ('true', '1', 'yes', 'on')
        
        if export_all_enabled:
            # Export both missing_on_new and new_only together
            missing_urls = data_map['missing_on_new']
            new_only_urls = data_map['new_only']
            
            if not missing_urls and not new_only_urls:
                return JSONResponse(status_code=400, content={"error": "No data to export"})
            
            # Create DataFrame with category column
            all_urls = []
            all_paths = []
            all_categories = []
            
            for url in missing_urls:
                all_urls.append(url)
                all_paths.append(urlparse(url).path)
                all_categories.append('Missing on New')
            
            for url in new_only_urls:
                all_urls.append(url)
                all_paths.append(urlparse(url).path)
                all_categories.append('New Only')
            
            df = pd.DataFrame({
                'Category': all_categories,
                'URL': all_urls,
                'Path': all_paths
            })
            
            # Create CSV in memory
            output = io.StringIO()
            df.to_csv(output, index=False)
            csv_content = output.getvalue()
            
            return Response(
                content=csv_content,
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=all_differences.csv"}
            )
        else:
            # Export single category
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

