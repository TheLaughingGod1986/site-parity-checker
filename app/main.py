"""Site Parity Checker - FastAPI Application.

A tool to compare URLs between two websites to identify:
- Pages missing on the new site
- Pages only on the new site  
- Pages that match between sites
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os

from .api.routes import router

# Create FastAPI app
app = FastAPI(
    title="Site Parity Checker",
    description="Compare URLs between two websites",
    version="2.0.0"
)

# Mount static files if directory exists
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Include API routes
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

