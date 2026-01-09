"""Site comparison logic."""

import asyncio
from urllib.parse import urlparse
from typing import Set, Dict, List, Optional

from .url_utils import URLNormalizer, get_base_domain
from .sitemap import SitemapFetcher
from .crawler import WebCrawler
from .async_crawler import AsyncWebCrawler
from .verifier import URLVerifier
from ..models.progress import ProgressTracker
from ..models.comparison import ComparisonResult
from ..config import CrawlConfig, DEFAULT_CRAWL_CONFIG


class SiteComparator:
    """Compares two websites to find differences."""
    
    def __init__(self,
                 progress: Optional[ProgressTracker] = None,
                 config: CrawlConfig = DEFAULT_CRAWL_CONFIG):
        """Initialize site comparator.
        
        Args:
            progress: Optional progress tracker
            config: Crawl configuration
        """
        self.progress = progress
        self.config = config
    
    def compare(self,
                old_url: str,
                new_url: str,
                use_crawl: bool = False,
                combine_methods: bool = False,
                ignore_robots: bool = False,
                verify_results: bool = True) -> ComparisonResult:
        """Compare two sites and return differences.
        
        Args:
            old_url: URL of the old site
            new_url: URL of the new site
            use_crawl: If True, crawl instead of using sitemap
            combine_methods: If True, use both sitemap AND crawl
            ignore_robots: If True, ignore robots.txt
            verify_results: If True, verify missing/new URLs actually exist
            
        Returns:
            ComparisonResult with differences
        """
        # Store base URLs for verification
        self._old_base_url = old_url
        self._new_base_url = new_url
        self._verify_results = verify_results
        # Parse URLs
        old_parsed = urlparse(old_url)
        new_parsed = urlparse(new_url)
        old_domain = get_base_domain(old_url)
        new_domain = get_base_domain(new_url)
        
        self._send_message("Starting comparison...")
        self._send_message(f"Old site: {old_domain}")
        self._send_message(f"New site: {new_domain}")
        
        method = "Sitemap + Crawling" if combine_methods else ("Crawling" if use_crawl else "Sitemap")
        self._send_message(f"Method: {method}")
        
        # Collect URLs
        old_urls: Set[str] = set()
        new_urls: Set[str] = set()
        errors: List[str] = []
        old_sitemap = None
        new_sitemap = None
        
        # Get sitemaps
        old_fetcher = SitemapFetcher(self.progress, 'old')
        new_fetcher = SitemapFetcher(self.progress, 'new')
        old_sitemap = old_fetcher.get_sitemap_url(old_url)
        new_sitemap = new_fetcher.get_sitemap_url(new_url)
        
        self._send_message(f"Old site sitemap: {old_sitemap}")
        self._send_message(f"New site sitemap: {new_sitemap}")
        
        # Fetch sitemaps if needed
        if combine_methods or not use_crawl:
            self._send_message("📥 Fetching sitemaps...")
            
            old_sitemap_urls, old_errors = old_fetcher.fetch(old_sitemap, old_parsed.netloc)
            new_sitemap_urls, new_errors = new_fetcher.fetch(new_sitemap, new_parsed.netloc)
            
            old_urls.update(old_sitemap_urls)
            new_urls.update(new_sitemap_urls)
            errors.extend(old_errors)
            errors.extend(new_errors)
            
            self._send_message(f"✓ Sitemaps: Old={len(old_sitemap_urls)}, New={len(new_sitemap_urls)}")
        
        # Crawl if needed - use async crawler for parallel fetching
        if combine_methods or use_crawl:
            self._send_message("🚀 Crawling sites in parallel (async mode)...")
            
            old_crawler = AsyncWebCrawler(
                config=self.config,
                progress=self.progress,
                site='old',
                use_js_rendering=True,
                respect_robots=not ignore_robots,
                concurrency=10
            )
            new_crawler = AsyncWebCrawler(
                config=self.config,
                progress=self.progress,
                site='new',
                use_js_rendering=True,
                respect_robots=not ignore_robots,
                concurrency=10
            )
            
            # Run both crawls in parallel
            old_crawl_urls, new_crawl_urls, old_crawl_errors, new_crawl_errors = \
                self._run_parallel_crawls(old_crawler, old_url, new_crawler, new_url)
            
            old_urls.update(old_crawl_urls)
            new_urls.update(new_crawl_urls)
            errors.extend(old_crawl_errors)
            errors.extend(new_crawl_errors)
            
            self._send_message(f"✓ Crawl: Old={len(old_crawl_urls)}, New={len(new_crawl_urls)}")
            
            # Sitemap fallback for crawl-only mode
            if use_crawl and not combine_methods:
                self._sitemap_fallback(
                    old_urls, new_urls, old_fetcher, new_fetcher,
                    old_sitemap, new_sitemap, old_parsed, new_parsed, errors
                )
        
        if combine_methods:
            self._send_message(f"✓ Combined: Old={len(old_urls)} total, New={len(new_urls)} total")
        
        # Compare
        return self._compare_urls(
            old_urls, new_urls, errors,
            old_sitemap, new_sitemap
        )
    
    def _run_parallel_crawls(self,
                              old_crawler: AsyncWebCrawler,
                              old_url: str,
                              new_crawler: AsyncWebCrawler,
                              new_url: str):
        """Run both site crawls using async (sequential crawls with concurrent page fetching).
        
        Note: We run sites sequentially to avoid Playwright conflicts, but
        each site's pages are fetched concurrently for speed.
        
        Returns:
            Tuple of (old_urls, new_urls, old_errors, new_errors)
        """
        async def crawl_both():
            # Crawl old site first (with concurrent page fetching)
            old_result = await old_crawler.crawl(old_url)
            # Then crawl new site (with concurrent page fetching)
            new_result = await new_crawler.crawl(new_url)
            return old_result[0], new_result[0], old_result[1], new_result[1]
        
        # Create a new event loop and run
        try:
            # Try to get existing loop (for testing in async context)
            loop = asyncio.get_running_loop()
            # If we're in an async context, we need to run in a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, crawl_both())
                return future.result()
        except RuntimeError:
            # No running loop, create one
            return asyncio.run(crawl_both())
    
    def _sitemap_fallback(self,
                          old_urls: Set[str],
                          new_urls: Set[str],
                          old_fetcher: SitemapFetcher,
                          new_fetcher: SitemapFetcher,
                          old_sitemap: str,
                          new_sitemap: str,
                          old_parsed,
                          new_parsed,
                          errors: List[str]) -> None:
        """Supplement crawl results with sitemap data if crawl found few URLs."""
        old_few = len(old_urls) < 10
        new_few = len(new_urls) < 10
        
        if old_few or new_few:
            self._send_message("⚠️ Crawl found very few URLs. Attempting sitemap fallback...")
        
        # Always try sitemap supplement
        old_sitemap_urls = set()
        new_sitemap_urls = set()
        
        if old_sitemap:
            try:
                self._send_message(f"📋 Fetching old site sitemap: {old_sitemap}")
                old_sitemap_urls, _ = old_fetcher.fetch(old_sitemap, old_parsed.netloc)
                if old_sitemap_urls:
                    self._send_message(f"✓ Fetched {len(old_sitemap_urls)} URLs from old site sitemap")
                    if len(old_sitemap_urls) < 20:
                        self._send_message(f"⚠️ WARNING: Old site sitemap only has {len(old_sitemap_urls)} URLs - may be incomplete!")
            except Exception as e:
                self._send_message(f"❌ Failed to fetch old site sitemap: {str(e)}")
        
        if new_sitemap:
            try:
                self._send_message(f"📋 Fetching new site sitemap: {new_sitemap}")
                new_sitemap_urls, _ = new_fetcher.fetch(new_sitemap, new_parsed.netloc)
                if new_sitemap_urls:
                    self._send_message(f"✓ Fetched {len(new_sitemap_urls)} URLs from new site sitemap")
                    if len(new_sitemap_urls) < 20:
                        self._send_message(f"⚠️ WARNING: New site sitemap only has {len(new_sitemap_urls)} URLs - may be incomplete!")
            except Exception as e:
                self._send_message(f"❌ Failed to fetch new site sitemap: {str(e)}")
        
        # Add sitemap URLs
        old_before = len(old_urls)
        new_before = len(new_urls)
        old_urls.update(old_sitemap_urls)
        new_urls.update(new_sitemap_urls)
        old_added = len(old_urls) - old_before
        new_added = len(new_urls) - new_before
        
        if old_added > 0 or new_added > 0:
            self._send_message(f"✓ Sitemap supplement: Added {old_added} old URLs, {new_added} new URLs")
    
    def _compare_urls(self,
                      old_urls: Set[str],
                      new_urls: Set[str],
                      errors: List[str],
                      old_sitemap: Optional[str],
                      new_sitemap: Optional[str]) -> ComparisonResult:
        """Compare URL sets and build result.
        
        Args:
            old_urls: URLs from old site
            new_urls: URLs from new site
            errors: List of errors
            old_sitemap: Old site sitemap URL
            new_sitemap: New site sitemap URL
            
        Returns:
            ComparisonResult
        """
        self._send_message("🔍 Comparing sites (by path only, ignoring domains)...")
        self._send_message(f"   Old site: {len(old_urls)} URLs found")
        self._send_message(f"   New site: {len(new_urls)} URLs found")
        
        # Extract paths for comparison
        old_paths = {URLNormalizer.get_path(url) for url in old_urls}
        new_paths = {URLNormalizer.get_path(url) for url in new_urls}
        
        self._send_message(f"   Old site unique paths: {len(old_paths)}")
        self._send_message(f"   New site unique paths: {len(new_paths)}")
        
        # Compare
        missing_paths = old_paths - new_paths
        new_only_paths = new_paths - old_paths
        matched_paths = old_paths & new_paths
        
        self._send_message(f"   Matched paths: {len(matched_paths)}")
        self._send_message(f"   Missing on new: {len(missing_paths)} paths")
        self._send_message(f"   New only: {len(new_only_paths)} paths")
        
        # Map paths back to URLs
        old_path_map = self._build_path_map(old_urls)
        new_path_map = self._build_path_map(new_urls)
        
        missing_on_new = self._paths_to_urls(missing_paths, old_path_map)
        new_only = self._paths_to_urls(new_only_paths, new_path_map)
        matched = self._paths_to_urls(matched_paths, old_path_map)
        
        self._send_message("✓ Comparison complete!")
        self._send_message(f"  - Missing on new: {len(missing_on_new)}")
        self._send_message(f"  - New only: {len(new_only)}")
        self._send_message(f"  - Matched: {len(matched)}")
        
        # Debug sample
        if new_only and len(new_only) > 0:
            self._send_message(f"  📋 Sample of 'New Only' URLs (first 10):")
            for url in list(new_only)[:10]:
                self._send_message(f"     - {URLNormalizer.get_path(url)}")
        
        # Verify results if enabled
        if getattr(self, '_verify_results', True) and (missing_on_new or new_only):
            self._send_message("")
            self._send_message("🔍 Verifying results (checking if URLs actually exist)...")
            
            verifier = URLVerifier(
                config=self.config,
                progress=self.progress,
                concurrency=20
            )
            
            try:
                # Run async verification
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    verification = loop.run_until_complete(
                        verifier.verify_comparison(
                            old_base_url=getattr(self, '_old_base_url', ''),
                            new_base_url=getattr(self, '_new_base_url', ''),
                            missing_on_new=missing_on_new,
                            new_only=new_only
                        )
                    )
                finally:
                    loop.close()
                
                # Update lists with verified results
                false_positive_count = len(verification.false_positives) + len(verification.false_new)
                if false_positive_count > 0:
                    self._send_message(f"✓ Corrected {false_positive_count} false positives!")
                    
                    # Add false positives to matched
                    for url in verification.false_positives:
                        path = URLNormalizer.get_path(url)
                        if path:
                            matched.append(url)
                    
                    for url in verification.false_new:
                        path = URLNormalizer.get_path(url)
                        if path:
                            matched.append(url)
                    
                    # Update the lists
                    missing_on_new = verification.verified_missing
                    new_only = verification.verified_new
                    
                    self._send_message(f"  Final counts after verification:")
                    self._send_message(f"    - Missing on new: {len(missing_on_new)}")
                    self._send_message(f"    - New only: {len(new_only)}")
                    self._send_message(f"    - Matched: {len(matched)}")
                else:
                    self._send_message("✓ All results verified - no false positives found")
                    
            except Exception as e:
                self._send_message(f"⚠️ Verification failed: {str(e)}")
        
        # Final progress update - mark as complete
        if self.progress:
            self.progress.add_urls('old', old_urls)
            self.progress.add_urls('new', new_urls)
            # Set final totals and mark as complete
            self.progress.old_site.total_estimate = len(old_urls)
            self.progress.new_site.total_estimate = len(new_urls)
            self.progress.old_site.pages_scanned = len(old_urls)
            self.progress.new_site.pages_scanned = len(new_urls)
            self.progress.send_update()
        
        return ComparisonResult(
            missing_on_new=missing_on_new,
            new_only=new_only,
            matched=matched,
            old_total=len(old_urls),
            new_total=len(new_urls),
            old_sample_urls=list(old_urls)[:10],
            new_sample_urls=list(new_urls)[:10],
            old_sitemap=old_sitemap,
            new_sitemap=new_sitemap,
            warnings=errors if errors else None,
            warning_message=f"Some operations failed ({len(errors)} errors)" if errors else None
        )
    
    def _build_path_map(self, urls: Set[str]) -> Dict[str, List[str]]:
        """Build a map from path to URLs."""
        path_map: Dict[str, List[str]] = {}
        for url in urls:
            path = URLNormalizer.get_path(url)
            if path not in path_map:
                path_map[path] = []
            path_map[path].append(url)
        return path_map
    
    def _paths_to_urls(self, paths: Set[str], path_map: Dict[str, List[str]]) -> List[str]:
        """Convert paths back to URLs."""
        urls = []
        for path in paths:
            urls.extend(path_map.get(path, []))
        return urls
    
    def _send_message(self, message: str) -> None:
        """Send a progress message."""
        if self.progress:
            self.progress.send_message(message)

