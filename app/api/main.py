from pathlib import Path

from fastapi import FastAPI

from app.api.routes.canonical import router as canonical_router
from app.api.routes.evidence import router as evidence_router
from app.api.routes.health import router as health_router
from app.api.routes.ingest import router as ingest_router
from app.api.routes.search import router as search_router
from app.models.db import init_db
from app.utils.settings import settings


app = FastAPI(title=settings.app_name)


@app.on_event("startup")
def startup() -> None:
    Path(settings.pdf_storage_dir).mkdir(parents=True, exist_ok=True)
    init_db()


app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(evidence_router)
app.include_router(canonical_router)
app.include_router(search_router)

