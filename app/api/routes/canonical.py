from fastapi import APIRouter, HTTPException

from app.models.db import get_db

router = APIRouter(prefix="/canonical", tags=["canonical"])


@router.get("/{tender_id}")
def get_canonical(tender_id: str) -> dict:
    db = get_db()
    doc = db.canonical_tenders.find_one({"tender_id": tender_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Canonical not found for tender_id")
    return doc

