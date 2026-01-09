"""Export functionality for CSV and PDF."""

import io
from datetime import datetime
from urllib.parse import urlparse
from typing import List, Optional, Dict, Any

import pandas as pd

# Try to import reportlab for PDF generation
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


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


def export_pdf(
    old_url: str,
    new_url: str,
    old_total: int,
    new_total: int,
    matched: List[str],
    missing_on_new: List[str],
    new_only: List[str],
    match_percentage: float
) -> Optional[bytes]:
    """Export comparison results to PDF format.
    
    Args:
        old_url: URL of old site
        new_url: URL of new site
        old_total: Total URLs found on old site
        new_total: Total URLs found on new site
        matched: List of matched URLs
        missing_on_new: List of URLs missing on new site
        new_only: List of URLs only on new site
        match_percentage: Match percentage
        
    Returns:
        PDF content as bytes, or None if reportlab not available
    """
    if not REPORTLAB_AVAILABLE:
        return None
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=TA_CENTER
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        spaceBefore=20,
        spaceAfter=10
    )
    normal_style = styles['Normal']
    
    story = []
    
    # Title
    story.append(Paragraph("Site Parity Checker Report", title_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", normal_style))
    story.append(Spacer(1, 20))
    
    # Summary Table
    story.append(Paragraph("Summary", heading_style))
    summary_data = [
        ["Old Site", old_url],
        ["New Site", new_url],
        ["Old Site Total", str(old_total)],
        ["New Site Total", str(new_total)],
        ["Matched Pages", str(len(matched))],
        ["Missing on New", str(len(missing_on_new))],
        ["New Only", str(len(new_only))],
        ["Match Rate", f"{match_percentage:.1f}%"]
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 4.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 30))
    
    # Missing on New section
    if missing_on_new:
        story.append(Paragraph(f"Missing on New ({len(missing_on_new)} URLs)", heading_style))
        story.append(Paragraph("Pages that exist on the old site but are missing from the new site:", normal_style))
        story.append(Spacer(1, 10))
        
        missing_data = [["#", "Path"]]
        for i, url in enumerate(missing_on_new[:100], 1):
            path = urlparse(url).path
            missing_data.append([str(i), path])
        
        if len(missing_on_new) > 100:
            missing_data.append(["...", f"(and {len(missing_on_new) - 100} more)"])
        
        missing_table = Table(missing_data, colWidths=[0.5*inch, 6*inch])
        missing_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EF4444')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        story.append(missing_table)
        story.append(Spacer(1, 20))
    
    # New Only section
    if new_only:
        story.append(Paragraph(f"New Only ({len(new_only)} URLs)", heading_style))
        story.append(Paragraph("Pages that only exist on the new site:", normal_style))
        story.append(Spacer(1, 10))
        
        new_data = [["#", "Path"]]
        for i, url in enumerate(new_only[:100], 1):
            path = urlparse(url).path
            new_data.append([str(i), path])
        
        if len(new_only) > 100:
            new_data.append(["...", f"(and {len(new_only) - 100} more)"])
        
        new_table = Table(new_data, colWidths=[0.5*inch, 6*inch])
        new_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6366F1')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
        ]))
        story.append(new_table)
    
    # Build PDF
    doc.build(story)
    return buffer.getvalue()


def is_pdf_available() -> bool:
    """Check if PDF export is available."""
    return REPORTLAB_AVAILABLE
