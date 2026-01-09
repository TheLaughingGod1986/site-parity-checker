"""Sitemap fetching and parsing."""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from typing import Set, List, Tuple, Optional

from .url_utils import URLNormalizer
from ..models.progress import ProgressTracker
from ..config import EXCLUDED_EXTENSIONS


class SitemapFetcher:
    """Fetches and parses sitemaps."""
    
    def __init__(self, 
                 progress: Optional[ProgressTracker] = None,
                 site: str = 'old'):
        """Initialize sitemap fetcher.
        
        Args:
            progress: Optional progress tracker
            site: 'old' or 'new' for progress tracking
        """
        self.progress = progress
        self.site = site
        self._visited: Set[str] = set()
    
    def get_sitemap_url(self, base_url: str) -> str:
        """Get sitemap URL, checking robots.txt first.
        
        Args:
            base_url: Base URL of the site
            
        Returns:
            Sitemap URL
        """
        if base_url.endswith('/sitemap.xml'):
            return base_url
        
        parsed = urlparse(base_url)
        base_domain = f"{parsed.scheme}://{parsed.netloc}"
        
        # Check robots.txt for sitemap directive
        try:
            robots_url = f"{base_domain}/robots.txt"
            response = requests.get(
                robots_url, 
                timeout=5, 
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            if response.status_code == 200:
                for line in response.text.split('\n'):
                    line = line.strip()
                    if line.lower().startswith('sitemap:'):
                        sitemap_url = line.split(':', 1)[1].strip()
                        if sitemap_url:
                            return sitemap_url
        except Exception:
            pass
        
        # Fall back to default location
        return f"{base_domain}/sitemap.xml"
    
    def fetch(self, 
              url: str, 
              expected_domain: Optional[str] = None) -> Tuple[Set[str], List[str]]:
        """Fetch sitemap and extract URLs.
        
        Args:
            url: Sitemap URL
            expected_domain: Expected domain for URL mapping
            
        Returns:
            Tuple of (urls_set, errors_list)
        """
        return self._fetch_recursive(url, expected_domain)
    
    def _fetch_recursive(self, 
                         url: str, 
                         expected_domain: Optional[str]) -> Tuple[Set[str], List[str]]:
        """Recursively fetch sitemap and nested sitemaps.
        
        Args:
            url: Sitemap URL
            expected_domain: Expected domain for URL mapping
            
        Returns:
            Tuple of (urls_set, errors_list)
        """
        if url in self._visited:
            return set(), []
        
        self._visited.add(url)
        errors: List[str] = []
        
        self._send_message(f"Fetching: {url}")
        
        # Fetch sitemap
        try:
            timeout = 15 if len(self._visited) > 1 else 30
            response = requests.get(
                url, 
                timeout=timeout, 
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            response.raise_for_status()
        except requests.exceptions.Timeout:
            errors.append(f"Timeout fetching sitemap: {url}")
            self._send_message(f"⚠️ Timeout: {url}")
            return set(), errors
        except Exception as e:
            errors.append(f"Failed to fetch sitemap {url}: {str(e)}")
            self._send_message(f"❌ Error: {url}")
            return set(), errors
        
        # Parse XML
        soup = BeautifulSoup(response.content, 'xml')
        
        # Check for sitemap index
        sitemap_tags = soup.find_all('sitemap')
        if sitemap_tags:
            return self._process_sitemap_index(sitemap_tags, expected_domain, errors)
        
        # Process regular sitemap
        return self._process_sitemap(soup, url, expected_domain)
    
    def _process_sitemap_index(self, 
                               sitemap_tags, 
                               expected_domain: Optional[str],
                               errors: List[str]) -> Tuple[Set[str], List[str]]:
        """Process a sitemap index file.
        
        Args:
            sitemap_tags: BeautifulSoup sitemap tags
            expected_domain: Expected domain for URL mapping
            errors: List to append errors to
            
        Returns:
            Tuple of (urls_set, errors_list)
        """
        self._send_message(f"Found sitemap index with {len(sitemap_tags)} nested sitemaps")
        
        all_urls: Set[str] = set()
        
        for idx, tag in enumerate(sitemap_tags, 1):
            loc = tag.find('loc')
            if not loc:
                continue
            
            nested_url = loc.get_text().strip()
            self._send_message(f"Processing nested sitemap {idx}/{len(sitemap_tags)}: {nested_url}")
            
            nested_urls, nested_errors = self._fetch_recursive(nested_url, expected_domain)
            all_urls.update(nested_urls)
            errors.extend(nested_errors)
            
            if nested_urls:
                self._send_message(f"✓ Found {len(nested_urls)} URLs in {nested_url}")
                self._record_progress(nested_urls)
        
        return all_urls, errors
    
    def _process_sitemap(self, 
                         soup: BeautifulSoup, 
                         sitemap_url: str,
                         expected_domain: Optional[str]) -> Tuple[Set[str], List[str]]:
        """Process a regular sitemap file.
        
        Args:
            soup: Parsed sitemap XML
            sitemap_url: URL of the sitemap
            expected_domain: Expected domain for URL mapping
            
        Returns:
            Tuple of (urls_set, errors_list)
        """
        locs = soup.find_all('loc')
        urls: Set[str] = set()
        domain_mismatches = []
        
        for loc in locs:
            url_text = loc.get_text().strip()
            parsed = urlparse(url_text)
            
            # Skip excluded extensions
            path_lower = parsed.path.lower()
            if any(path_lower.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
                continue
            
            # Handle domain mapping
            if expected_domain and parsed.netloc != expected_domain:
                mapped_url = f"{parsed.scheme}://{expected_domain}{parsed.path}"
                if parsed.query:
                    mapped_url += f"?{parsed.query}"
                normalized = URLNormalizer.normalize(mapped_url)
                domain_mismatches.append((url_text, normalized))
            else:
                normalized = URLNormalizer.normalize(url_text)
            
            urls.add(normalized)
        
        # Warn about domain mismatches
        if domain_mismatches:
            unique_domains = set(urlparse(orig)[1] for orig, _ in domain_mismatches[:5])
            self._send_message(f"⚠️ Warning: Found {len(domain_mismatches)} URLs from different domain(s): {', '.join(unique_domains)}")
            self._send_message(f"   Mapping them to expected domain: {expected_domain}")
        
        if urls:
            self._send_message(f"✓ Found {len(urls)} URLs in {sitemap_url}")
            self._record_progress(urls)
        
        return urls, []
    
    def _send_message(self, message: str) -> None:
        """Send a progress message."""
        if self.progress:
            self.progress.send_message(message)
    
    def _record_progress(self, urls: Set[str]) -> None:
        """Record progress for discovered URLs."""
        if not self.progress:
            return
        
        # For sitemaps, record one "page" per sitemap fetch (not per URL)
        self.progress.record_page(self.site)
        self.progress.add_urls(self.site, urls)
        
        # Update total estimate based on URLs found
        if self.site == 'old':
            self.progress.old_site.total_estimate = max(
                self.progress.old_site.total_estimate,
                len(self.progress.old_site.urls_found)
            )
        else:
            self.progress.new_site.total_estimate = max(
                self.progress.new_site.total_estimate,
                len(self.progress.new_site.urls_found)
            )
        
        # Always send update for sitemap progress
        self.progress.send_update()

