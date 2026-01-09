"""Application configuration and constants."""

from dataclasses import dataclass
from typing import Set, List
import re


@dataclass(frozen=True)
class CrawlConfig:
    """Configuration for web crawling."""
    max_pages: int = 10000
    max_depth: int = 5
    request_timeout: int = 10
    js_render_timeout: int = 30000
    crawl_delay: float = 0.05  # 50ms between requests
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


@dataclass(frozen=True)
class AppConfig:
    """Application-wide configuration."""
    # Default crawl settings
    default_max_pages: int = 10000
    default_max_depth: int = 5
    
    # Progress update frequency
    progress_update_frequency: int = 10
    progress_update_first_n: int = 100  # Send every update for first N pages


# File extensions to exclude from crawling
EXCLUDED_EXTENSIONS: Set[str] = frozenset({
    '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.ico',
    '.css', '.js', '.pdf', '.zip', '.xml',
    '.woff', '.woff2', '.ttf', '.eot',
    '.mp4', '.mp3', '.avi', '.mov', '.webm',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
})

# Path patterns to exclude (compiled regex for performance)
EXCLUDED_PATH_PATTERNS: List[re.Pattern] = [
    re.compile(r'^/api/'),
    re.compile(r'^/admin/'),
    re.compile(r'^/wp-admin/'),
    re.compile(r'/chunks/'),
    re.compile(r'/chunk/'),
    re.compile(r'\.chunk\.'),
    re.compile(r'^/embed/'),
    re.compile(r'/wp-content/uploads/'),
    re.compile(r'/_next/static/'),
    re.compile(r'^/static/'),
    re.compile(r'^/assets/'),
    re.compile(r'^/images/'),
    re.compile(r'^/img/'),
    re.compile(r'^/css/'),
    re.compile(r'^/js/'),
    re.compile(r'^/fonts/'),
    re.compile(r'/media/[^/]+-[a-f0-9]+'),  # Media files with hash
]

# Default configuration instances
DEFAULT_CRAWL_CONFIG = CrawlConfig()
DEFAULT_APP_CONFIG = AppConfig()

