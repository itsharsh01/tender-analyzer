from fastapi import APIRouter, HTTPException

from app.models.db import get_db

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/{tender_id}")
def get_evidence(tender_id: str) -> dict:
    db = get_db()
    docs = list(db.evidence_items.find({"tender_id": tender_id}, {"_id": 0}))
    if not docs:
        raise HTTPException(status_code=404, detail="No evidence found for tender_id")
    return {"tender_id": tender_id, "count": len(docs), "items": docs}

