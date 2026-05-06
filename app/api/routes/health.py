from fastapi import APIRouter

from app.models.db import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/db")
def health_db() -> dict[str, str]:
    db = get_db()
    db.client.admin.command("ping")
    return {"status": "ok", "database": db.name}

