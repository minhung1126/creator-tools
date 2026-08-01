import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.router import api_router
from backend.app.core.config import settings
from backend.app.core.credential_store import credential_store
from backend.app.core.task_repository import migrate_legacy_instagram_jobs, task_repository
from backend.app.services.task_queue import task_queue

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Recover durable tasks before starting the two worker lanes."""

    task_repository.db.initialize()
    migrate_legacy_instagram_jobs(repository=task_repository)
    task_repository.recover_after_restart()
    try:
        google_credentials = credential_store.get_google_credentials()
    except Exception:
        google_credentials = None
    if not google_credentials or not google_credentials.get("token"):
        task_repository.pause_queued_without_credentials()
    task_queue.start()
    try:
        yield
    finally:
        task_queue.stop()


app = FastAPI(
    title="Creator Tools Dashboard API",
    description="FastAPI backend for Google OAuth, YouTube workflows, and Instagram Reels publish jobs.",
    version="1.1.0",
    lifespan=lifespan,
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
    return {
        "status": "healthy",
        "service": "Creator Tools Backend",
        "host": settings.base_url,
        "redirect_uri": settings.get_redirect_uri(),
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
