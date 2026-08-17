import logging
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.app.api.router import api_router
from backend.app.core.config import settings
from backend.app.core.error_contract import normalize_http_detail, validation_field_errors

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

HTML_CACHE_CONTROL = "no-cache, max-age=0, must-revalidate"
HASHED_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
HASHED_FRONTEND_ASSET_RE = re.compile(r"-[A-Za-z0-9_-]{8,}\.(?:js|css)$", re.IGNORECASE)


def frontend_cache_control(path: str, content_type: str | None) -> str | None:
    """Return the cache policy for a frontend response, if it is a frontend asset."""
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type == "text/html":
        return HTML_CACHE_CONTROL

    is_script_or_style = media_type in {"application/javascript", "text/javascript", "text/css"}
    filename = Path(path).name
    if path.startswith("/assets/") and is_script_or_style and HASHED_FRONTEND_ASSET_RE.search(filename):
        return HASHED_ASSET_CACHE_CONTROL
    return None


app = FastAPI(
    title="Creator Tools Dashboard API",
    description="FastAPI backend for Google OAuth, Google Sheets, and direct YouTube workflows.",
    version="1.1.0",
)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    del request
    detail = {
        "code": "validation_error",
        "message": "輸入資料格式不正確，請檢查欄位。",
        "retryable": False,
        "field_errors": validation_field_errors(exc.errors()),
    }
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    del request
    detail = normalize_http_detail(exc.status_code, exc.detail)
    headers = dict(exc.headers or {})
    retry_after = headers.get("Retry-After")
    if retry_after and "retry_after_seconds" not in detail:
        try:
            detail["retry_after_seconds"] = max(0, min(int(retry_after), 86_400))
        except (TypeError, ValueError):
            pass
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled API exception on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "internal_error",
                "message": "伺服器發生未預期錯誤，請稍後再試。",
                "retryable": False,
                "field_errors": {},
            }
        },
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
    cache_control = frontend_cache_control(request.url.path, response.headers.get("content-type"))
    if cache_control:
        response.headers["Cache-Control"] = cache_control
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
        warnings.append("尚未設定 Google OAuth 憑證")
    if not access_allowlist_ready:
        warnings.append("HTTPS／正式環境必須設定允許的 Google 帳號")
    if google_oauth_ready and not youtube_primary_ready:
        warnings.append("尚未設定 YouTube primary OAuth 憑證")
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
        raise HTTPException(status_code=404, detail="找不到前端資源。") from exc
    return requested_path


if frontend_dist.is_dir():
    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="找不到 API 端點。")
        requested_path = resolve_frontend_path(full_path)
        if requested_path.is_file():
            return FileResponse(str(requested_path))
        return FileResponse(str(resolve_frontend_path("index.html")))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.main:app", host=settings.BIND_HOST, port=settings.PORT, reload=True)
