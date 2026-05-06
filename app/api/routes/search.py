from fastapi import APIRouter

from app.models.db import get_db

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/tfidf/{tender_id}")
def get_tfidf_meta(tender_id: str) -> dict:
    db = get_db()
    doc = db.tfidf_indexes.find_one({"tender_id": tender_id}, {"_id": 0})
    return doc or {"tender_id": tender_id, "index": {"vocabulary": {}, "matrix_shape": [0, 0]}}

