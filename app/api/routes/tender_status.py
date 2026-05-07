from fastapi import APIRouter, HTTPException

from app.models.db import get_db

router = APIRouter(prefix="/tender", tags=["tender"])


@router.get("/{tender_id}/status")
def get_tender_status(tender_id: str) -> dict:
    """Returns the current processing status for a tender."""
    db = get_db()
    record = db.tenders.find_one({"_id": tender_id}, {"status": 1, "name": 1, "checksum": 1, "upload_timestamp": 1})
    if not record:
        raise HTTPException(status_code=404, detail=f"Tender '{tender_id}' not found.")
    record["tender_id"] = record.pop("_id")
    return record
