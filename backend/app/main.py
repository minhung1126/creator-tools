import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.app.api.router import api_router
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


app = FastAPI(
    title="Creator Tools Dashboard API",
    description="FastAPI backend for Google OAuth, Google Sheets, and direct YouTube workflows.",
    version="1.1.0",
)

origins = {settings.frontend_url, settings.base_url}
if not settings.is_production:
    origins.update(
        {
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        }
    )
origins.discard("")

app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts))

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; connect-src 'self'; img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'",
    )
    if settings.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.get("/api/v1/health")
def health_check():
    google_oauth_ready = bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
    youtube_primary = settings.youtube_oauth_slot("primary")
    youtube_secondary = settings.youtube_oauth_slot("secondary")
    youtube_login_ready = google_oauth_ready
    youtube_primary_ready = youtube_primary.configured
    youtube_secondary_ready = youtube_secondary.configured
    access_allowlist_ready = bool(settings.allowed_google_emails) or not settings.allowlist_required
    warnings = []
    if not google_oauth_ready:
        warnings.append("Google OAuth credentials are not configured")
    if not access_allowlist_ready:
        warnings.append("ALLOWED_GOOGLE_EMAILS is required for HTTPS/production deployments")
    if google_oauth_ready and not youtube_primary_ready:
        warnings.append("YouTube primary OAuth credentials are not configured")
    if youtube_primary.uses_legacy_google_credentials:
        warnings.append(
            "YouTube primary OAuth is using the legacy Google login client; configure YOUTUBE_OAUTH_PRIMARY_* to complete migration"
        )
    return {
        "status": "healthy",
        "ready": google_oauth_ready and youtube_primary_ready and access_allowlist_ready,
        "service": "Creator Tools Backend",
        "host": settings.base_url,
        "redirect_uri": settings.get_redirect_uri(),
        "configuration": {
            "google_oauth_ready": google_oauth_ready,
            "access_allowlist_ready": access_allowlist_ready,
        },
        "youtube": {
            "login_configured": youtube_login_ready,
            "primary_configured": youtube_primary_ready,
            "secondary_configured": youtube_secondary_ready,
            "secondary_enabled": youtube_secondary.enabled,
        },
        "warnings": warnings,
        "commit_sha": os.getenv("APP_COMMIT_SHA", "development"),
    }


frontend_dist = (Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()


def resolve_frontend_path(full_path: str) -> Path:
    """Resolve a frontend request only when it remains inside the build output."""
    requested_path = (frontend_dist / full_path).resolve()
    try:
        requested_path.relative_to(frontend_dist)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Frontend resource not found") from exc
    return requested_path


if frontend_dist.is_dir():
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        requested_path = resolve_frontend_path(full_path)
        if requested_path.is_file():
            return FileResponse(str(requested_path))
        return FileResponse(str(resolve_frontend_path("index.html")))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.main:app", host=settings.BIND_HOST, port=settings.PORT, reload=True)
