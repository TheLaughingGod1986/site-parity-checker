"""Web crawler for discovering pages."""

import requests
import time
from collections import deque
from urllib.parse import urlparse
from typing import Set, List, Tuple, Optional

from .url_utils import URLNormalizer, is_excluded_url, get_base_domain
from .link_extractors import LinkExtractor
from .robots import RobotsChecker
from .renderer import render_page, is_playwright_available
from ..models.progress import ProgressTracker
from ..config import CrawlConfig, DEFAULT_CRAWL_CONFIG, EXCLUDED_EXTENSIONS, EXCLUDED_PATH_PATTERNS


class WebCrawler:
    """Crawls websites to discover pages."""
    
    def __init__(self,
                 config: CrawlConfig = DEFAULT_CRAWL_CONFIG,
                 progress: Optional[ProgressTracker] = None,
                 site: str = 'old',
                 use_js_rendering: bool = True,
                 respect_robots: bool = True):
        """Initialize web crawler.
        
        Args:
            config: Crawl configuration
            progress: Optional progress tracker
            site: 'old' or 'new' for progress tracking
            use_js_rendering: Whether to use Playwright for JS rendering
            respect_robots: Whether to respect robots.txt
        """
        self.config = config
        self.progress = progress
        self.site = site
        self.use_js_rendering = use_js_rendering and is_playwright_available()
        self.respect_robots = respect_robots
        
        self._robots = RobotsChecker()
        self._robots_blocked_count = 0
    
    def crawl(self, base_url: str) -> Tuple[Set[str], List[str]]:
        """Crawl a site starting from base_url.
        
        Args:
            base_url: Starting URL (typically homepage)
            
        Returns:
            Tuple of (discovered_urls, errors)
        """
        # Setup
        parsed = urlparse(base_url)
        base_domain = URLNormalizer.normalize_domain(parsed.netloc)
        base_netloc = f"{parsed.scheme}://{parsed.netloc}"
        
        visited: Set[str] = set()
        queued: Set[str] = set()
        discovered: Set[str] = set()
        errors: List[str] = []
        
        queue: deque = deque([(base_url, 0)])  # (url, depth)
        queued.add(URLNormalizer.normalize(base_url))
        
        # Initialize progress
        if self.progress:
            if self.site == 'old':
                self.progress.old_site.total_estimate = self.config.max_pages
            else:
                self.progress.new_site.total_estimate = self.config.max_pages
        
        self._send_message(f"🕷️ Starting crawl of {parsed.netloc}...")
        self._send_message(f"   Max pages: {self.config.max_pages}, Max depth: {self.config.max_depth}")
        
        # Crawl loop
        while queue and len(visited) < self.config.max_pages:
            url, depth = queue.popleft()
            normalized = URLNormalizer.normalize(url)
            
            # Skip if visited or too deep
            if normalized in visited or depth > self.config.max_depth:
                continue
            
            visited.add(normalized)
            queued.discard(normalized)
            
            # Process page
            result = self._process_page(url, depth, base_domain, base_netloc)
            
            if result is None:
                continue
            
            final_url, links = result
            discovered.add(final_url)
            
            # Record progress
            self._record_progress(discovered)
            
            # Add new links to queue
            for link in links:
                link_normalized = URLNormalizer.normalize(link)
                if link_normalized not in visited and link_normalized not in queued:
                    queue.append((link, depth + 1))
                    queued.add(link_normalized)
            
            # Progress message
            if len(visited) % 10 == 0:
                self._send_message(f"   Crawled {len(visited)} pages, found {len(discovered)} URLs, queue: {len(queue)}")
            
            # Respect crawl delay
            time.sleep(self.config.crawl_delay)
        
        # Final reporting
        self._finish_crawl(visited, discovered, queue, errors)
        
        return discovered, errors
    
    def _process_page(self, 
                      url: str, 
                      depth: int,
                      base_domain: str,
                      base_netloc: str) -> Optional[Tuple[str, Set[str]]]:
        """Process a single page.
        
        Args:
            url: URL to process
            depth: Current crawl depth
            base_domain: Normalized base domain
            base_netloc: Base URL with scheme
            
        Returns:
            Tuple of (final_url, discovered_links) or None if page should be skipped
        """
        parsed = urlparse(url)
        
        # Check exclusions
        if is_excluded_url(url, EXCLUDED_EXTENSIONS, EXCLUDED_PATH_PATTERNS):
            return None
        
        # Check domain
        url_domain = URLNormalizer.normalize_domain(parsed.netloc)
        if url_domain != base_domain:
            return None
        
        # Check robots.txt
        if not self._check_robots(url):
            return None
        
        # Fetch page
        try:
            response = requests.get(
                url,
                timeout=self.config.request_timeout,
                headers={'User-Agent': self.config.user_agent},
                allow_redirects=True
            )
            response.raise_for_status()
        except requests.exceptions.Timeout:
            self._send_message(f"⚠️ Timeout: {url}")
            return None
        except requests.exceptions.TooManyRedirects:
            return None
        except Exception as e:
            return None
        
        # Check content type
        content_type = response.headers.get('Content-Type', '').lower()
        if 'text/html' not in content_type:
            return None
        
        # Get final URL after redirects
        final_url = URLNormalizer.normalize(response.url)
        
        # Get HTML content (with JS rendering if needed)
        html = self._get_html_content(response, url, depth)
        
        # Extract links
        extractor = LinkExtractor(response.url, base_domain)
        links = extractor.extract_all(html)
        
        # Aggressive extraction for SPAs
        if depth == 0 or len(links) < 10:
            if depth == 0:
                self._send_message("   Scanning page content for URLs (SPA detection)...")
            
            aggressive_links = extractor.extract_aggressive(html)
            new_links = aggressive_links - links
            
            if new_links:
                self._send_message(f"   ✓ Found {len(new_links)} additional URLs by scanning page content")
                links.update(new_links)
        
        return final_url, links
    
    def _get_html_content(self, response: requests.Response, url: str, depth: int) -> str:
        """Get HTML content, optionally with JS rendering.
        
        Args:
            response: HTTP response
            url: Original URL
            depth: Current crawl depth
            
        Returns:
            HTML content as string
        """
        # Only use JS rendering for homepage - it's too slow otherwise
        should_render = self.use_js_rendering and depth == 0
        
        if should_render:
            self._send_message(f"   🌐 Rendering JavaScript for homepage...")
            rendered = render_page(url, self.config.js_render_timeout)
            if rendered:
                return rendered
        
        return response.text
    
    def _check_robots(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt.
        
        Args:
            url: URL to check
            
        Returns:
            True if allowed
        """
        if not self._robots.is_allowed(url, self.respect_robots):
            self._robots_blocked_count += 1
            
            # Rate-limit logging
            if self._robots_blocked_count <= 3:
                self._send_message(f"🚫 Blocked by robots.txt: {url}")
            elif self._robots_blocked_count % 50 == 0:
                self._send_message(f"🚫 {self._robots_blocked_count} URLs blocked by robots.txt so far...")
            
            return False
        return True
    
    def _record_progress(self, discovered: Set[str]) -> None:
        """Record crawl progress."""
        if not self.progress:
            return
        
        self.progress.record_page(self.site)
        self.progress.add_urls(self.site, discovered)
        
        if self.progress.should_send_update(self.site):
            self.progress.send_update()
    
    def _finish_crawl(self, 
                      visited: Set[str], 
                      discovered: Set[str],
                      queue: deque,
                      errors: List[str]) -> None:
        """Finish crawl and report results."""
        limit_reached = len(visited) >= self.config.max_pages and queue
        
        # Report robots.txt summary
        if self._robots_blocked_count > 3:
            self._send_message(f"🚫 Total: {self._robots_blocked_count} URLs blocked by robots.txt")
        
        # Final progress update
        if self.progress:
            self.progress.add_urls(self.site, discovered)
            
            if limit_reached:
                self.progress.limit_reached = True
                self.progress.remaining_queue = len(queue)
            
            self.progress.send_update()
        
        # Report completion
        if limit_reached:
            self._send_message(f"⚠️ WARNING: Reached maximum page limit ({self.config.max_pages})")
            self._send_message(f"   Found {len(discovered)} URLs from {len(visited)} pages crawled")
            self._send_message(f"   ⚠️ {len(queue)} URLs still in queue - some pages may be missing!")
        else:
            self._send_message(f"✓ Crawl complete: Found {len(discovered)} URLs from {len(visited)} pages crawled")
    
    def _send_message(self, message: str) -> None:
        """Send a progress message."""
        if self.progress:
            self.progress.send_message(message)

