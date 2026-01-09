"""URL verification service to validate missing/new URLs actually don't exist."""

import asyncio
import aiohttp
from typing import Set, List, Tuple, Optional
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass

from .url_utils import URLNormalizer
from ..models.progress import ProgressTracker
from ..config import CrawlConfig, DEFAULT_CRAWL_CONFIG


@dataclass
class VerificationResult:
    """Result of URL verification."""
    verified_missing: List[str]  # URLs that are truly missing
    false_positives: List[str]   # URLs that exist (wrongly flagged as missing)
    verified_new: List[str]      # URLs that are truly new
    false_new: List[str]         # URLs that exist on old (wrongly flagged as new)


class URLVerifier:
    """Verifies if URLs actually exist by making HTTP requests."""
    
    def __init__(self, 
                 config: CrawlConfig = DEFAULT_CRAWL_CONFIG,
                 progress: Optional[ProgressTracker] = None,
                 concurrency: int = 20):
        """Initialize URL verifier.
        
        Args:
            config: Crawl configuration
            progress: Optional progress tracker
            concurrency: Number of concurrent verification requests
        """
        self.config = config
        self.progress = progress
        self.concurrency = concurrency
    
    async def verify_comparison(self,
                                 old_base_url: str,
                                 new_base_url: str,
                                 missing_on_new: List[str],
                                 new_only: List[str]) -> VerificationResult:
        """Verify that missing and new-only URLs are correctly categorized.
        
        For each "missing on new" URL:
          - Check if the path exists on the new site
          - If it does, it's a false positive
          
        For each "new only" URL:
          - Check if the path exists on the old site
          - If it does, it's a false positive
        
        Args:
            old_base_url: Base URL of old site
            new_base_url: Base URL of new site
            missing_on_new: URLs flagged as missing on new site
            new_only: URLs flagged as only on new site
            
        Returns:
            VerificationResult with verified and false positive lists
        """
        self._send_message("🔍 Verifying comparison results...")
        self._send_message(f"   Checking {len(missing_on_new)} 'missing' URLs on new site...")
        self._send_message(f"   Checking {len(new_only)} 'new only' URLs on old site...")
        
        # Extract base domains
        old_parsed = urlparse(old_base_url)
        new_parsed = urlparse(new_base_url)
        old_base = f"{old_parsed.scheme}://{old_parsed.netloc}"
        new_base = f"{new_parsed.scheme}://{new_parsed.netloc}"
        
        # Create timeout and session
        timeout = aiohttp.ClientTimeout(total=5)
        connector = aiohttp.TCPConnector(limit=self.concurrency)
        
        async with aiohttp.ClientSession(
            connector=connector, 
            timeout=timeout,
            headers={'User-Agent': self.config.user_agent}
        ) as session:
            
            # Verify "missing on new" URLs by checking if they exist on new site
            missing_paths = [URLNormalizer.get_path(url) for url in missing_on_new]
            new_urls_to_check = [f"{new_base}{path}" for path in missing_paths if path]
            
            missing_exists = await self._check_urls_exist(session, new_urls_to_check)
            
            verified_missing = []
            false_missing = []
            for i, url in enumerate(missing_on_new):
                if i < len(new_urls_to_check):
                    if missing_exists[i]:
                        false_missing.append(url)
                    else:
                        verified_missing.append(url)
            
            # Verify "new only" URLs by checking if they exist on old site
            new_paths = [URLNormalizer.get_path(url) for url in new_only]
            old_urls_to_check = [f"{old_base}{path}" for path in new_paths if path]
            
            new_exists = await self._check_urls_exist(session, old_urls_to_check)
            
            verified_new = []
            false_new = []
            for i, url in enumerate(new_only):
                if i < len(old_urls_to_check):
                    if new_exists[i]:
                        false_new.append(url)
                    else:
                        verified_new.append(url)
        
        # Report results
        self._send_message(f"✓ Verification complete!")
        self._send_message(f"   Missing on new: {len(verified_missing)} verified, {len(false_missing)} false positives")
        self._send_message(f"   New only: {len(verified_new)} verified, {len(false_new)} false positives")
        
        if false_missing:
            self._send_message(f"⚠️ {len(false_missing)} URLs flagged as 'missing' actually exist on new site")
        if false_new:
            self._send_message(f"⚠️ {len(false_new)} URLs flagged as 'new only' actually exist on old site")
        
        return VerificationResult(
            verified_missing=verified_missing,
            false_positives=false_missing,
            verified_new=verified_new,
            false_new=false_new
        )
    
    async def _check_urls_exist(self, 
                                 session: aiohttp.ClientSession, 
                                 urls: List[str]) -> List[bool]:
        """Check if a list of URLs exist (return 2xx/3xx status).
        
        Args:
            session: aiohttp session
            urls: URLs to check
            
        Returns:
            List of booleans - True if URL exists
        """
        semaphore = asyncio.Semaphore(self.concurrency)
        
        async def check_one(url: str) -> bool:
            async with semaphore:
                try:
                    async with session.head(url, allow_redirects=True) as response:
                        return response.status < 400
                except Exception:
                    try:
                        # Fallback to GET if HEAD fails
                        async with session.get(url, allow_redirects=True) as response:
                            return response.status < 400
                    except Exception:
                        return False
        
        tasks = [check_one(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return [r if isinstance(r, bool) else False for r in results]
    
    def _send_message(self, message: str) -> None:
        """Send a progress message."""
        if self.progress:
            self.progress.send_message(message)


async def verify_comparison_results(old_base_url: str,
                                     new_base_url: str,
                                     missing_on_new: List[str],
                                     new_only: List[str],
                                     config: CrawlConfig = DEFAULT_CRAWL_CONFIG,
                                     progress: Optional[ProgressTracker] = None,
                                     concurrency: int = 20) -> VerificationResult:
    """Convenience function to verify comparison results.
    
    Args:
        old_base_url: Base URL of old site
        new_base_url: Base URL of new site  
        missing_on_new: URLs flagged as missing on new site
        new_only: URLs flagged as only on new site
        config: Crawl configuration
        progress: Optional progress tracker
        concurrency: Number of concurrent requests
        
    Returns:
        VerificationResult
    """
    verifier = URLVerifier(config=config, progress=progress, concurrency=concurrency)
    return await verifier.verify_comparison(old_base_url, new_base_url, missing_on_new, new_only)

