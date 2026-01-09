"""Comparison result models."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class ComparisonResult:
    """Result of comparing two sites."""
    
    # URL lists
    missing_on_new: List[str] = field(default_factory=list)
    new_only: List[str] = field(default_factory=list)
    matched: List[str] = field(default_factory=list)
    
    # Totals
    old_total: int = 0
    new_total: int = 0
    
    # Sample URLs for debugging
    old_sample_urls: List[str] = field(default_factory=list)
    new_sample_urls: List[str] = field(default_factory=list)
    
    # Sitemap info
    old_sitemap: Optional[str] = None
    new_sitemap: Optional[str] = None
    
    # Warnings
    warnings: List[str] = field(default_factory=list)
    warning_message: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            'missing_on_new': self.missing_on_new,
            'new_only': self.new_only,
            'matched': self.matched,
            'old_total': self.old_total,
            'new_total': self.new_total,
            'old_sample_urls': self.old_sample_urls,
            'new_sample_urls': self.new_sample_urls,
        }
        
        if self.old_sitemap:
            result['old_sitemap'] = self.old_sitemap
        if self.new_sitemap:
            result['new_sitemap'] = self.new_sitemap
        if self.warnings:
            result['warnings'] = self.warnings
            result['warning_message'] = self.warning_message or f"Some operations failed ({len(self.warnings)} errors)"
        
        return result

