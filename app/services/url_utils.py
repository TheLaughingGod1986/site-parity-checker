"""URL utilities for normalization and comparison."""

from urllib.parse import urlparse, urljoin
from typing import Set, List, Optional
import re

from ..config import EXCLUDED_EXTENSIONS, EXCLUDED_PATH_PATTERNS


class URLNormalizer:
    """Handles URL normalization for consistent comparison."""
    
    @staticmethod
    def normalize(url: str) -> str:
        """Normalize URL to canonical form.
        
        - Lowercase scheme and host
        - Remove trailing slash from path
        - Remove query string and fragment
        - Keep path case as-is (URLs are case-sensitive)
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL string
        """
        try:
            # Clean backslashes that might be in malformed URLs
            url = url.replace('\\', '')
            
            parsed = urlparse(url)
            # Lowercase scheme and netloc, keep path as-is but strip trailing slash
            path = parsed.path.rstrip('/')
            if not path:
                path = ''
            
            return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"
        except Exception:
            return url.lower().rstrip('/')
    
    @staticmethod
    def get_path(url: str) -> str:
        """Extract just the path from a URL for domain-agnostic comparison.
        
        Args:
            url: URL to extract path from
            
        Returns:
            Lowercase path without trailing slash
        """
        try:
            # Clean backslashes first
            url = url.replace('\\', '')
            parsed = urlparse(url)
            return parsed.path.rstrip('/').lower()
        except Exception:
            return ''
    
    @staticmethod
    def get_domain(url: str) -> str:
        """Extract domain from URL.
        
        Args:
            url: URL to extract domain from
            
        Returns:
            Domain (netloc) in lowercase
        """
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return ''
    
    @staticmethod
    def normalize_domain(domain: str) -> str:
        """Normalize domain by removing www. prefix.
        
        Args:
            domain: Domain to normalize
            
        Returns:
            Domain without www. prefix
        """
        domain = domain.lower()
        if domain.startswith('www.'):
            return domain[4:]
        return domain
    
    @staticmethod
    def is_same_domain(url1: str, url2: str) -> bool:
        """Check if two URLs are from the same domain (handles www).
        
        Args:
            url1: First URL
            url2: Second URL
            
        Returns:
            True if domains match (ignoring www prefix)
        """
        domain1 = URLNormalizer.normalize_domain(URLNormalizer.get_domain(url1))
        domain2 = URLNormalizer.normalize_domain(URLNormalizer.get_domain(url2))
        return domain1 == domain2
    
    @staticmethod
    def make_absolute(href: str, base_url: str) -> Optional[str]:
        """Convert a relative URL to absolute.
        
        Args:
            href: Relative or absolute URL
            base_url: Base URL for resolution
            
        Returns:
            Absolute URL or None if invalid
        """
        try:
            # Clean up href
            href = href.strip().replace('\\', '')
            
            # Skip invalid hrefs
            if not href or href.startswith(('javascript:', 'mailto:', 'tel:', '#', 'data:')):
                return None
            
            return urljoin(base_url, href)
        except Exception:
            return None


def get_base_domain(url: str) -> str:
    """Get the base domain URL (scheme + netloc).
    
    Args:
        url: Full URL
        
    Returns:
        Base domain URL (e.g., 'https://example.com')
    """
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def is_excluded_url(url: str, 
                    extensions: Set[str] = EXCLUDED_EXTENSIONS,
                    patterns: List[re.Pattern] = EXCLUDED_PATH_PATTERNS) -> bool:
    """Check if a URL should be excluded from crawling.
    
    Args:
        url: URL to check
        extensions: Set of file extensions to exclude
        patterns: List of regex patterns for paths to exclude
        
    Returns:
        True if URL should be excluded
    """
    try:
        # Clean backslashes first
        url = url.replace('\\', '')
        
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        
        # Check excluded extensions
        if any(path_lower.endswith(ext) for ext in extensions):
            return True
        
        # Check excluded path patterns
        if any(pattern.search(path_lower) for pattern in patterns):
            return True
        
        return False
    except Exception:
        return True  # Exclude if we can't parse it

