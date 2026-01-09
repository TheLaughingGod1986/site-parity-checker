"""Robots.txt handling."""

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from typing import Dict
import time


class RobotsChecker:
    """Checks robots.txt rules with caching."""
    
    def __init__(self, cache_ttl: int = 300):
        """Initialize robots checker.
        
        Args:
            cache_ttl: Cache time-to-live in seconds
        """
        self._cache: Dict[str, tuple] = {}  # domain -> (parser, timestamp)
        self._cache_ttl = cache_ttl
    
    def is_allowed(self, url: str, respect_robots: bool = True) -> bool:
        """Check if a URL is allowed by robots.txt.
        
        Args:
            url: URL to check
            respect_robots: Whether to respect robots.txt
            
        Returns:
            True if allowed (or if robots.txt can't be read)
        """
        if not respect_robots:
            return True
        
        try:
            parsed = urlparse(url)
            domain = f"{parsed.scheme}://{parsed.netloc}"
            
            parser = self._get_parser(domain)
            if parser is None:
                return True
            
            return parser.can_fetch('*', url)
        except Exception:
            return True
    
    def _get_parser(self, domain: str) -> RobotFileParser:
        """Get or create a robot parser for a domain.
        
        Args:
            domain: Base domain URL
            
        Returns:
            RobotFileParser instance or None
        """
        now = time.time()
        
        # Check cache
        if domain in self._cache:
            parser, timestamp = self._cache[domain]
            if now - timestamp < self._cache_ttl:
                return parser
        
        # Create new parser
        try:
            robots_url = f"{domain}/robots.txt"
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.read()
            self._cache[domain] = (parser, now)
            return parser
        except Exception:
            return None

