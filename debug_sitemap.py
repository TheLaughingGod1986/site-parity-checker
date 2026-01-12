#!/usr/bin/env python3
"""Debug script to check sitemap contents."""

import sys
from app.services.sitemap import SitemapFetcher

def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_sitemap.py <url>")
        sys.exit(1)
    
    url = sys.argv[1]
    print(f"Checking sitemap for: {url}\n")
    
    fetcher = SitemapFetcher()
    
    # Discover sitemaps
    sitemaps = fetcher.discover_sitemaps(url)
    print(f"Found {len(sitemaps)} sitemap(s):")
    for sitemap in sitemaps:
        print(f"  - {sitemap}")
    print()
    
    # Fetch all URLs
    from urllib.parse import urlparse
    parsed = urlparse(url)
    urls, errors = fetcher.fetch_all(url, parsed.netloc)
    
    print(f"Total URLs found: {len(urls)}")
    print(f"Errors: {len(errors)}")
    
    if errors:
        print("\nErrors:")
        for error in errors[:10]:
            print(f"  - {error}")
    
    if urls:
        print(f"\nFirst 20 URLs:")
        for url in list(urls)[:20]:
            print(f"  - {url}")
        
        if len(urls) > 20:
            print(f"\n... and {len(urls) - 20} more URLs")

if __name__ == '__main__':
    main()

