import os
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.app.core.config import settings
from backend.app.api.router import api_router

logger = logging.getLogger(__name__)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

app = FastAPI(
    title="YouTube Creator Tools Dashboard API",
    description="Python FastAPI backend for managing Google OAuth, YouTube Draft Batch Metadata Updates, and Publish Playlist Cleanups.",
    version="1.0.0"
)

# CORS Configuration
origins = [
    f"http://localhost:3000",
    f"http://localhost:5173",
    f"http://127.0.0.1:3000",
    f"http://127.0.0.1:5173",
    settings.frontend_url,
    settings.base_url,
]
# Deduplicate
origins = list(set(origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Router
app.include_router(api_router)


@app.get("/api/v1/health")
def health_check():
    return {
        "status": "healthy",
        "service": "YouTube Creator Tools Backend",
        "host": settings.base_url,
        "redirect_uri": settings.get_redirect_uri()
    }


# Serve Frontend static files if dist folder exists (for production/Docker)
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        file_path = os.path.join(frontend_dist, full_path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dist, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=True
    )
