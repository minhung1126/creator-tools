import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.router import api_router
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


app = FastAPI(
    title="Creator Tools Dashboard API",
    description="FastAPI backend for Google OAuth, Google Sheets, and direct YouTube workflows.",
    version="1.1.0",
)

origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    settings.frontend_url,
    settings.base_url,
]
origins = list(set(origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/v1/health")
def health_check():
    google_oauth_ready = bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
    access_allowlist_ready = bool(settings.allowed_google_emails) or not settings.is_production
    warnings = []
    if not google_oauth_ready:
        warnings.append("Google OAuth credentials are not configured")
    if not access_allowlist_ready:
        warnings.append("ALLOWED_GOOGLE_EMAILS is required in production")
    return {
        "status": "healthy",
        "ready": google_oauth_ready and access_allowlist_ready,
        "service": "Creator Tools Backend",
        "host": settings.base_url,
        "redirect_uri": settings.get_redirect_uri(),
        "configuration": {
            "google_oauth_ready": google_oauth_ready,
            "access_allowlist_ready": access_allowlist_ready,
        },
        "warnings": warnings,
        "commit_sha": os.getenv("APP_COMMIT_SHA", "development"),
    }


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

    uvicorn.run("backend.app.main:app", host=settings.BIND_HOST, port=settings.PORT, reload=True)
