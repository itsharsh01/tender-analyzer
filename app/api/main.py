import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes.canonical import router as canonical_router
from app.api.routes.evidence import router as evidence_router
from app.api.routes.health import router as health_router
from app.api.routes.ingest import router as ingest_router
from app.api.routes.search import router as search_router
from app.api.routes.submission import router as submission_router
from app.api.routes.tender_status import router as tender_status_router
from app.models.db import init_db
from app.utils.settings import settings

logger = logging.getLogger(__name__)

# ── Request timeout middleware ────────────────────────────────────────────────

class TimeoutMiddleware(BaseHTTPMiddleware):
    """
    Returns HTTP 504 if a request takes longer than `timeout_seconds`.
    Upload/pipeline routes are long-running so set a generous value (10 min).
    """

    def __init__(self, app, timeout_seconds: int = 600):
        super().__init__(app)
        self.timeout = timeout_seconds

    async def dispatch(self, request: Request, call_next):
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.error("Request timed out: %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=504,
                content={
                    "detail": f"Request timed out after {self.timeout}s. "
                              "The pipeline is still running — check /tender/{{tender_id}}/status."
                },
            )


# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add timeout middleware FIRST (outermost layer)
app.add_middleware(TimeoutMiddleware, timeout_seconds=settings.request_timeout_seconds)


@app.on_event("startup")
def startup() -> None:
    Path(settings.pdf_storage_dir).mkdir(parents=True, exist_ok=True)
    init_db()


app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(tender_status_router)
app.include_router(evidence_router)
app.include_router(canonical_router)
app.include_router(search_router)
app.include_router(submission_router)
