"""JavaScript rendering using Playwright."""

from typing import Optional

# Try to import Playwright
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def is_playwright_available() -> bool:
    """Check if Playwright is available."""
    return PLAYWRIGHT_AVAILABLE


def render_page(url: str, timeout: int = 45000) -> Optional[str]:
    """Render a page with JavaScript using Playwright.
    
    Args:
        url: URL to render
        timeout: Timeout in milliseconds
        
    Returns:
        Rendered HTML content or None if rendering fails
    """
    if not PLAYWRIGHT_AVAILABLE:
        return None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(timeout)
            
            # Navigate and wait for content
            page.goto(url, wait_until='domcontentloaded', timeout=timeout)
            
            # Wait for JavaScript to execute
            page.wait_for_timeout(2000)
            
            # Try to wait for network idle
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except Exception:
                pass  # Continue even if networkidle doesn't happen
            
            html = page.content()
            browser.close()
            return html
    except Exception:
        return None

