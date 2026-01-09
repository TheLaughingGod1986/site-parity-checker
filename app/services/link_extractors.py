"""Link extraction from HTML content."""

import re
import json
from typing import Set, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from .url_utils import URLNormalizer, is_excluded_url
from ..config import EXCLUDED_EXTENSIONS, EXCLUDED_PATH_PATTERNS


class LinkExtractor:
    """Extracts links from HTML content."""
    
    def __init__(self, base_url: str, base_domain: str):
        """Initialize link extractor.
        
        Args:
            base_url: Base URL for resolving relative links
            base_domain: Normalized base domain for filtering
        """
        self.base_url = base_url
        self.base_domain = base_domain
        self.base_scheme = urlparse(base_url).scheme
    
    def extract_all(self, html: str) -> Set[str]:
        """Extract all links from HTML content.
        
        Args:
            html: HTML content
            
        Returns:
            Set of normalized URLs
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        links: Set[str] = set()
        
        # Standard <a> tags
        links.update(self._extract_anchor_links(soup))
        
        # Canonical URL
        canonical = self._extract_canonical(soup)
        if canonical:
            links.add(canonical)
        
        # JSON-LD structured data
        links.update(self._extract_json_ld(soup))
        
        # Data attributes (React/Vue apps)
        links.update(self._extract_data_attributes(soup))
        
        # JavaScript URLs
        links.update(self._extract_js_urls(soup))
        
        return links
    
    def extract_aggressive(self, html: str) -> Set[str]:
        """Aggressively extract URLs from raw HTML (for SPAs).
        
        Args:
            html: HTML or text content
            
        Returns:
            Set of normalized URLs
        """
        links: Set[str] = set()
        
        # Multiple URL patterns
        patterns = [
            re.compile(r'https?://(?:www\.)?' + re.escape(self.base_domain) + r'[^\s"\'<>)]+', re.IGNORECASE),
            re.compile(r'["\'](?:https?://)?(?:www\.)?' + re.escape(self.base_domain) + r'[^\s"\'<>)]+["\']', re.IGNORECASE),
            re.compile(r'["\']/(?:[a-z0-9-]+/)+[a-z0-9-]+["\']', re.IGNORECASE),
        ]
        
        for pattern in patterns:
            for match in pattern.findall(html):
                url = self._clean_and_validate(match)
                if url:
                    links.add(url)
        
        return links
    
    def _extract_anchor_links(self, soup: BeautifulSoup) -> Set[str]:
        """Extract links from <a> tags."""
        links: Set[str] = set()
        
        for anchor in soup.find_all('a', href=True):
            href = anchor['href'].strip().replace('\\', '')
            
            # Skip invalid hrefs
            if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#', 'data:')):
                continue
            
            url = self._resolve_and_validate(href)
            if url:
                links.add(url)
        
        return links
    
    def _extract_canonical(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract canonical URL."""
        canonical = soup.find('link', {'rel': 'canonical'})
        if canonical and canonical.get('href'):
            return self._resolve_and_validate(canonical['href'])
        return None
    
    def _extract_json_ld(self, soup: BeautifulSoup) -> Set[str]:
        """Extract URLs from JSON-LD structured data."""
        links: Set[str] = set()
        
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    for key in ['url', 'mainEntityOfPage', 'sameAs']:
                        value = data.get(key)
                        if isinstance(value, str) and value.startswith('http'):
                            url = self._resolve_and_validate(value)
                            if url:
                                links.add(url)
                        elif isinstance(value, dict) and 'url' in value:
                            url = self._resolve_and_validate(value['url'])
                            if url:
                                links.add(url)
            except (json.JSONDecodeError, TypeError):
                pass
        
        return links
    
    def _extract_data_attributes(self, soup: BeautifulSoup) -> Set[str]:
        """Extract URLs from data attributes."""
        links: Set[str] = set()
        
        for element in soup.find_all(attrs={'data-href': True}):
            href = element.get('data-href')
            if href:
                url = self._resolve_and_validate(href)
                if url:
                    links.add(url)
        
        return links
    
    def _extract_js_urls(self, soup: BeautifulSoup) -> Set[str]:
        """Extract URLs from JavaScript code."""
        links: Set[str] = set()
        
        patterns = [
            re.compile(r'["\'](https?://[^"\']+)["\']'),
            re.compile(r'path:\s*["\']([^"\']+)["\']', re.IGNORECASE),
            re.compile(r'url:\s*["\']([^"\']+)["\']', re.IGNORECASE),
            re.compile(r'href:\s*["\']([^"\']+)["\']', re.IGNORECASE),
        ]
        
        for script in soup.find_all('script'):
            if not script.string:
                continue
            
            for pattern in patterns:
                for match in pattern.findall(script.string):
                    match = match.replace('\\', '').strip('"\'')
                    if not match:
                        continue
                    
                    url = self._resolve_and_validate(match)
                    if url:
                        links.add(url)
        
        return links
    
    def _resolve_and_validate(self, href: str) -> Optional[str]:
        """Resolve relative URL and validate it belongs to the domain.
        
        Args:
            href: URL or path to resolve
            
        Returns:
            Normalized URL if valid, None otherwise
        """
        try:
            # Clean the href
            href = href.replace('\\', '').strip('"\'')
            if not href:
                return None
            
            # Resolve to absolute URL
            if href.startswith('http'):
                absolute = href
            elif href.startswith('/'):
                absolute = f"{self.base_scheme}://{urlparse(self.base_url).netloc}{href}"
            else:
                absolute = urljoin(self.base_url, href)
            
            # Check domain
            parsed = urlparse(absolute)
            url_domain = URLNormalizer.normalize_domain(parsed.netloc)
            
            if url_domain != self.base_domain:
                return None
            
            # Check exclusions
            if is_excluded_url(absolute, EXCLUDED_EXTENSIONS, EXCLUDED_PATH_PATTERNS):
                return None
            
            return URLNormalizer.normalize(absolute)
        except Exception:
            return None
    
    def _clean_and_validate(self, match: str) -> Optional[str]:
        """Clean a regex match and validate it.
        
        Args:
            match: Raw match from regex
            
        Returns:
            Normalized URL if valid, None otherwise
        """
        try:
            # Clean the match
            url = match.replace('\\', '').strip('"\'')
            url = url.split('"')[0].split("'")[0].split(')')[0].split('?')[0].split('#')[0]
            url = url.rstrip('.,;:!?')
            
            if len(url) < 10:
                return None
            
            # Make absolute if needed
            if not url.startswith('http'):
                if url.startswith('/'):
                    url = f"{self.base_scheme}://{urlparse(self.base_url).netloc}{url}"
                else:
                    return None
            
            return self._resolve_and_validate(url)
        except Exception:
            return None

