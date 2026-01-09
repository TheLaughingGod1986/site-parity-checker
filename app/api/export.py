"""CSV export functionality."""

import io
from urllib.parse import urlparse
from typing import List
import pandas as pd


def export_csv(urls: List[str], category: str) -> str:
    """Export a list of URLs to CSV format.
    
    Args:
        urls: List of URLs to export
        category: Category name for the export
        
    Returns:
        CSV content as string
    """
    df = pd.DataFrame({
        'URL': urls,
        'Path': [urlparse(url).path for url in urls]
    })
    
    output = io.StringIO()
    df.to_csv(output, index=False)
    return output.getvalue()


def export_all_csv(missing_urls: List[str], new_only_urls: List[str]) -> str:
    """Export both missing and new-only URLs to CSV format.
    
    Args:
        missing_urls: List of URLs missing on new site
        new_only_urls: List of URLs only on new site
        
    Returns:
        CSV content as string
    """
    all_urls = []
    all_paths = []
    all_categories = []
    
    for url in missing_urls:
        all_urls.append(url)
        all_paths.append(urlparse(url).path)
        all_categories.append('Missing on New')
    
    for url in new_only_urls:
        all_urls.append(url)
        all_paths.append(urlparse(url).path)
        all_categories.append('New Only')
    
    df = pd.DataFrame({
        'Category': all_categories,
        'URL': all_urls,
        'Path': all_paths
    })
    
    output = io.StringIO()
    df.to_csv(output, index=False)
    return output.getvalue()

