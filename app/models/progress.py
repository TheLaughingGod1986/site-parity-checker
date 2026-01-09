"""Progress tracking for site comparison."""

from dataclasses import dataclass, field
from typing import Dict, Set, Optional, Callable, List
from collections import deque
import time


@dataclass
class SiteProgress:
    """Progress data for a single site."""
    pages_scanned: int = 0
    urls_found: Set[str] = field(default_factory=set)
    total_estimate: int = 0
    
    @property
    def percentage(self) -> float:
        """Calculate completion percentage."""
        if self.total_estimate <= 0:
            return 0.0
        return min(100.0, (self.pages_scanned / self.total_estimate) * 100)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'pages_scanned': self.pages_scanned,
            'total_estimate': self.total_estimate,
            'urls_found': len(self.urls_found)
        }


class ProgressTracker:
    """Tracks progress for site comparison with real-time statistics."""
    
    def __init__(self, 
                 callback: Optional[Callable[[Dict], None]] = None,
                 update_frequency: int = 10):
        """Initialize progress tracker.
        
        Args:
            callback: Function to call with progress updates
            update_frequency: Send update every N pages (after first 100)
        """
        self.callback = callback
        self.update_frequency = update_frequency
        
        # Site progress
        self.old_site = SiteProgress()
        self.new_site = SiteProgress()
        
        # Timing
        self.start_time = time.time()
        self._page_times: deque = deque(maxlen=20)
        self._last_page_time: Optional[float] = None
        
        # Comparison stats (only valid when both sites scanned)
        self._missing_count = 0
        self._new_only_count = 0
        self._matched_count = 0
        
        # Limit tracking
        self.limit_reached = False
        self.remaining_queue = 0
    
    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time
    
    @property
    def eta_seconds(self) -> Optional[float]:
        """Calculate ETA in seconds using moving average."""
        if len(self._page_times) < 2:
            return None
        
        avg_time = sum(self._page_times) / len(self._page_times)
        remaining = max(0, 
            (self.old_site.total_estimate - self.old_site.pages_scanned) +
            (self.new_site.total_estimate - self.new_site.pages_scanned)
        )
        
        if remaining <= 0:
            return 0.0
        
        return remaining * avg_time
    
    @property
    def match_percentage(self) -> float:
        """Calculate match percentage.
        
        Match percentage = (matched pages / verified old site total) * 100
        Where verified old total = matched + missing (after verification)
        This shows what percentage of old site pages exist on the new site.
        """
        # Use verified totals: old_total = matched + missing
        verified_old_total = self._matched_count + self._missing_count
        
        if verified_old_total <= 0:
            # Fall back to crawled URLs if no verified stats yet
            verified_old_total = len(self.old_site.urls_found)
        
        if verified_old_total <= 0:
            return 0.0
        
        return (self._matched_count / verified_old_total) * 100
    
    def record_page(self, site: str = 'old') -> None:
        """Record that a page was processed.
        
        Args:
            site: 'old' or 'new'
        """
        current_time = time.time()
        
        # Track timing for ETA calculation
        if self._last_page_time is not None:
            self._page_times.append(current_time - self._last_page_time)
        self._last_page_time = current_time
        
        # Update page count
        if site == 'old':
            self.old_site.pages_scanned += 1
        else:
            self.new_site.pages_scanned += 1
    
    def add_urls(self, site: str, urls: Set[str]) -> None:
        """Add discovered URLs for a site.
        
        Args:
            site: 'old' or 'new'
            urls: Set of URLs to add
        """
        if site == 'old':
            self.old_site.urls_found.update(urls)
        else:
            self.new_site.urls_found.update(urls)
        
        self._update_comparison_stats()
    
    def _update_comparison_stats(self) -> None:
        """Update comparison statistics."""
        # Don't calculate if new site hasn't started (prevents false positives)
        if not self.new_site.urls_found and self.new_site.pages_scanned == 0:
            self._missing_count = 0
            self._new_only_count = 0
            self._matched_count = 0
            return
        
        # Calculate based on URL paths (domain-agnostic)
        from ..services.url_utils import URLNormalizer
        
        old_paths = {URLNormalizer.get_path(url) for url in self.old_site.urls_found}
        new_paths = {URLNormalizer.get_path(url) for url in self.new_site.urls_found}
        
        self._matched_count = len(old_paths & new_paths)
        self._missing_count = len(old_paths - new_paths)
        self._new_only_count = len(new_paths - old_paths)
    
    def set_verified_stats(self, missing_count: int, new_only_count: int, matched_count: int) -> None:
        """Set verified comparison statistics after verification step.
        
        Args:
            missing_count: Verified count of missing URLs
            new_only_count: Verified count of new only URLs
            matched_count: Verified count of matched URLs
        """
        self._missing_count = missing_count
        self._new_only_count = new_only_count
        self._matched_count = matched_count
    
    def should_send_update(self, site: str = 'old') -> bool:
        """Check if we should send a progress update.
        
        Args:
            site: 'old' or 'new'
            
        Returns:
            True if update should be sent
        """
        pages = self.old_site.pages_scanned if site == 'old' else self.new_site.pages_scanned
        
        # Always send for first 100 pages
        if pages <= 100:
            return True
        
        return pages % self.update_frequency == 0
    
    def send_update(self, message: Optional[str] = None) -> None:
        """Send progress update via callback.
        
        Args:
            message: Optional message to include
        """
        if not self.callback:
            return
        
        if message:
            self.callback({'type': 'message', 'message': message})
        
        self.callback({'type': 'progress', 'data': self.to_dict()})
    
    def send_message(self, message: str) -> None:
        """Send a message without progress data.
        
        Args:
            message: Message to send
        """
        if self.callback:
            self.callback({'type': 'message', 'message': message})
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        total_pages = self.old_site.pages_scanned + self.new_site.pages_scanned
        total_estimate = max(
            self.old_site.total_estimate,
            self.new_site.total_estimate,
            total_pages
        )
        
        percentage = (total_pages / total_estimate * 100) if total_estimate > 0 else 0
        
        return {
            'old_site': self.old_site.to_dict(),
            'new_site': self.new_site.to_dict(),
            'comparison': {
                'missing_count': self._missing_count,
                'new_only_count': self._new_only_count,
                'matched_count': self._matched_count,
                'match_percentage': round(self.match_percentage, 1)
            },
            'time': {
                'elapsed_seconds': round(self.elapsed_seconds, 1),
                'eta_seconds': round(self.eta_seconds, 1) if self.eta_seconds is not None else None
            },
            'percentage': round(percentage, 1),
            'limit_reached': self.limit_reached,
            'remaining_queue': self.remaining_queue
        }

