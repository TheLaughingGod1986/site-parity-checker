"""Async web crawler for high-performance parallel page fetching."""

import asyncio
import aiohttp
from collections import deque
from urllib.parse import urlparse
from typing import Set, List, Tuple, Optional, Deque
from dataclasses import dataclass

from .url_utils import URLNormalizer, is_excluded_url, get_base_domain
from .link_extractors import LinkExtractor
from .robots import RobotsChecker
from .renderer import render_page, is_playwright_available
from ..models.progress import ProgressTracker
from ..config import CrawlConfig, DEFAULT_CRAWL_CONFIG, EXCLUDED_EXTENSIONS, EXCLUDED_PATH_PATTERNS


@dataclass
class CrawlTask:
    """A single crawl task."""
    url: str
    depth: int


class AsyncWebCrawler:
    """High-performance async web crawler with concurrent fetching."""
    
    def __init__(self,
                 config: CrawlConfig = DEFAULT_CRAWL_CONFIG,
                 progress: Optional[ProgressTracker] = None,
                 site: str = 'old',
                 use_js_rendering: bool = True,
                 respect_robots: bool = True,
                 concurrency: int = 10):
        """Initialize async web crawler.
        
        Args:
            config: Crawl configuration
            progress: Optional progress tracker
            site: 'old' or 'new' for progress tracking
            use_js_rendering: Whether to use Playwright for JS rendering
            respect_robots: Whether to respect robots.txt
            concurrency: Maximum number of concurrent requests
        """
        self.config = config
        self.progress = progress
        self.site = site
        self.use_js_rendering = use_js_rendering and is_playwright_available()
        self.respect_robots = respect_robots
        self.concurrency = concurrency
        
        self._robots = RobotsChecker()
        self._robots_blocked_count = 0
        
        # Thread-safe sets (we use regular sets since asyncio is single-threaded)
        self.visited: Set[str] = set()
        self.queued: Set[str] = set()
        self.discovered: Set[str] = set()
        self.errors: List[str] = []
        
        # Queue for pending tasks
        self.queue: Deque[CrawlTask] = deque()
        
        # Base URL info
        self.base_domain: str = ""
        self.base_netloc: str = ""
        
        # Stats
        self.pages_fetched = 0
    
    async def crawl(self, base_url: str) -> Tuple[Set[str], List[str]]:
        """Crawl a site starting from base_url using async/await.
        
        Args:
            base_url: Starting URL (typically homepage)
            
        Returns:
            Tuple of (discovered_urls, errors)
        """
        # Setup
        parsed = urlparse(base_url)
        self.base_domain = URLNormalizer.normalize_domain(parsed.netloc)
        self.base_netloc = f"{parsed.scheme}://{parsed.netloc}"
        
        # Reset state
        self.visited.clear()
        self.queued.clear()
        self.discovered.clear()
        self.errors.clear()
        self.queue.clear()
        self.pages_fetched = 0
        self._robots_blocked_count = 0
        
        # Initialize queue
        self.queue.append(CrawlTask(base_url, 0))
        self.queued.add(URLNormalizer.normalize(base_url))
        
        # Initialize progress
        if self.progress:
            if self.site == 'old':
                self.progress.old_site.total_estimate = self.config.max_pages
            else:
                self.progress.new_site.total_estimate = self.config.max_pages
        
        self._send_message(f"🚀 Starting async crawl of {parsed.netloc}...")
        self._send_message(f"   Max pages: {self.config.max_pages}, Concurrency: {self.concurrency}")
        
        # Create aiohttp session with connection limit
        connector = aiohttp.TCPConnector(limit=self.concurrency, limit_per_host=self.concurrency)
        timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Render homepage with JavaScript if enabled
            if self.use_js_rendering and self.queue:
                await self._render_homepage(base_url, session)
            
            # Process queue with semaphore for concurrency control
            semaphore = asyncio.Semaphore(self.concurrency)
            
            while self.queue and len(self.visited) < self.config.max_pages:
                # Get batch of tasks
                batch_size = min(self.concurrency, len(self.queue), 
                               self.config.max_pages - len(self.visited))
                
                if batch_size == 0:
                    break
                
                # Create tasks for batch
                tasks = []
                for _ in range(batch_size):
                    if not self.queue:
                        break
                    task = self.queue.popleft()
                    
                    # Skip if already visited
                    normalized = URLNormalizer.normalize(task.url)
                    if normalized in self.visited or task.depth > self.config.max_depth:
                        continue
                    
                    self.visited.add(normalized)
                    self.queued.discard(normalized)
                    
                    tasks.append(self._fetch_page(session, semaphore, task))
                
                if not tasks:
                    continue
                
                # Execute batch concurrently
                await asyncio.gather(*tasks, return_exceptions=True)
                
                # Progress message
                if self.pages_fetched % 20 == 0 and self.pages_fetched > 0:
                    self._send_message(
                        f"   Crawled {self.pages_fetched} pages, "
                        f"found {len(self.discovered)} URLs, queue: {len(self.queue)}"
                    )
        
        # Final reporting
        self._finish_crawl()
        
        return self.discovered, self.errors
    
    async def _render_homepage(self, base_url: str, session: aiohttp.ClientSession) -> None:
        """Render homepage with JavaScript to discover SPA links."""
        self._send_message("   🌐 Rendering JavaScript for homepage...")
        
        # Get homepage task
        if not self.queue:
            return
        
        task = self.queue.popleft()
        normalized = URLNormalizer.normalize(task.url)
        self.visited.add(normalized)
        self.queued.discard(normalized)
        
        html = None
        
        # Try Playwright rendering first
        try:
            rendered_html = render_page(base_url, self.config.js_render_timeout)
            if rendered_html:
                html = rendered_html
                self._send_message("   ✓ JavaScript rendering successful")
        except Exception as e:
            self._send_message(f"   ⚠️ JavaScript rendering failed: {str(e)[:50]}")
        
        # Fallback to regular fetch if JS rendering failed
        if not html:
            try:
                async with session.get(
                    base_url, 
                    headers={'User-Agent': self.config.user_agent}
                ) as response:
                    if response.status < 400:
                        html = await response.text()
                        self._send_message("   ✓ Fetched homepage without JS rendering")
            except Exception as e:
                self._send_message(f"   ⚠️ Homepage fetch failed: {str(e)[:50]}")
        
        if html:
            # Extract links
            extractor = LinkExtractor(base_url, self.base_domain)
            links = extractor.extract_all(html)
            
            # Aggressive extraction
            self._send_message("   Scanning page content for URLs (SPA detection)...")
            aggressive_links = extractor.extract_aggressive(html)
            new_links = aggressive_links - links
            
            if new_links:
                self._send_message(f"   ✓ Found {len(new_links)} additional URLs by scanning page content")
                links.update(new_links)
            
            self._send_message(f"   ✓ Homepage extracted {len(links)} links")
            
            # Add to discovered and queue new links
            self.discovered.add(normalized)
            self._add_links_to_queue(links, 1)
            
            # Record progress
            self.pages_fetched += 1
            self._record_progress()
        else:
            self._send_message("   ❌ Could not fetch homepage - crawl may find fewer pages")
    
    async def _fetch_page(self, 
                          session: aiohttp.ClientSession, 
                          semaphore: asyncio.Semaphore,
                          task: CrawlTask) -> None:
        """Fetch and process a single page.
        
        Args:
            session: aiohttp session
            semaphore: Concurrency limiter
            task: Crawl task
        """
        async with semaphore:
            url = task.url
            depth = task.depth
            
            # Check exclusions
            if is_excluded_url(url, EXCLUDED_EXTENSIONS, EXCLUDED_PATH_PATTERNS):
                return
            
            # Check domain
            parsed = urlparse(url)
            url_domain = URLNormalizer.normalize_domain(parsed.netloc)
            if url_domain != self.base_domain:
                return
            
            # Check robots.txt
            if not self._check_robots(url):
                return
            
            try:
                # Fetch page
                async with session.get(
                    url,
                    headers={'User-Agent': self.config.user_agent},
                    allow_redirects=True
                ) as response:
                    if response.status >= 400:
                        return
                    
                    # Check content type
                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'text/html' not in content_type:
                        return
                    
                    # Get final URL after redirects
                    final_url = URLNormalizer.normalize(str(response.url))
                    
                    # Read HTML
                    try:
                        html = await response.text()
                    except Exception:
                        return
                    
                    # Extract links
                    extractor = LinkExtractor(str(response.url), self.base_domain)
                    links = extractor.extract_all(html)
                    
                    # Aggressive extraction for shallow pages
                    if depth <= 1 or len(links) < 10:
                        aggressive_links = extractor.extract_aggressive(html)
                        links.update(aggressive_links)
                    
                    # Record discovered URL
                    self.discovered.add(final_url)
                    
                    # Add new links to queue
                    self._add_links_to_queue(links, depth + 1)
                    
                    # Update progress
                    self.pages_fetched += 1
                    self._record_progress()
                    
            except asyncio.TimeoutError:
                self.errors.append(f"Timeout: {url}")
            except aiohttp.ClientError as e:
                self.errors.append(f"Error: {url} - {str(e)[:50]}")
            except Exception as e:
                self.errors.append(f"Unknown error: {url}")
    
    def _add_links_to_queue(self, links: Set[str], depth: int) -> None:
        """Add discovered links to the crawl queue.
        
        Args:
            links: Set of URLs to add
            depth: Depth for new tasks
        """
        for link in links:
            normalized = URLNormalizer.normalize(link)
            if normalized not in self.visited and normalized not in self.queued:
                self.queue.append(CrawlTask(link, depth))
                self.queued.add(normalized)
    
    def _check_robots(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt."""
        if not self._robots.is_allowed(url, self.respect_robots):
            self._robots_blocked_count += 1
            
            if self._robots_blocked_count <= 3:
                self._send_message(f"🚫 Blocked by robots.txt: {url}")
            elif self._robots_blocked_count % 100 == 0:
                self._send_message(f"🚫 {self._robots_blocked_count} URLs blocked by robots.txt...")
            
            return False
        return True
    
    def _record_progress(self) -> None:
        """Record crawl progress."""
        if not self.progress:
            return
        
        self.progress.record_page(self.site)
        self.progress.add_urls(self.site, self.discovered)
        
        if self.progress.should_send_update(self.site):
            self.progress.send_update()
    
    def _finish_crawl(self) -> None:
        """Finish crawl and report results."""
        limit_reached = len(self.visited) >= self.config.max_pages and self.queue
        
        # Report robots.txt summary
        if self._robots_blocked_count > 3:
            self._send_message(f"🚫 Total: {self._robots_blocked_count} URLs blocked by robots.txt")
        
        # Final progress update
        if self.progress:
            self.progress.add_urls(self.site, self.discovered)
            
            if limit_reached:
                self.progress.limit_reached = True
                self.progress.remaining_queue = len(self.queue)
            
            self.progress.send_update()
        
        # Report completion
        if limit_reached:
            self._send_message(f"⚠️ WARNING: Reached maximum page limit ({self.config.max_pages})")
            self._send_message(f"   Found {len(self.discovered)} URLs from {len(self.visited)} pages crawled")
            self._send_message(f"   ⚠️ {len(self.queue)} URLs still in queue!")
        else:
            self._send_message(f"✓ Async crawl complete: {len(self.discovered)} URLs from {len(self.visited)} pages")
    
    def _send_message(self, message: str) -> None:
        """Send a progress message."""
        if self.progress:
            self.progress.send_message(message)


async def crawl_async(base_url: str,
                      config: CrawlConfig = DEFAULT_CRAWL_CONFIG,
                      progress: Optional[ProgressTracker] = None,
                      site: str = 'old',
                      use_js_rendering: bool = True,
                      respect_robots: bool = True,
                      concurrency: int = 10) -> Tuple[Set[str], List[str]]:
    """Convenience function to crawl a site asynchronously.
    
    Args:
        base_url: Starting URL
        config: Crawl configuration
        progress: Optional progress tracker
        site: 'old' or 'new' for progress tracking
        use_js_rendering: Whether to use Playwright for JS rendering
        respect_robots: Whether to respect robots.txt
        concurrency: Number of concurrent requests
        
    Returns:
        Tuple of (discovered_urls, errors)
    """
    crawler = AsyncWebCrawler(
        config=config,
        progress=progress,
        site=site,
        use_js_rendering=use_js_rendering,
        respect_robots=respect_robots,
        concurrency=concurrency
    )
    return await crawler.crawl(base_url)

