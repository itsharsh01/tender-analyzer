from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import uuid

from fastapi import UploadFile

from app.models.db import get_db
from app.services.canonical_service import build_canonical
from app.services.embedding_service import build_semantic_embeddings, build_tfidf_index
from app.services.evidence_service import build_evidence_pool
from app.utils.settings import settings


async def ingest_pdf(file: UploadFile) -> dict[str, Any]:
    tender_id = str(uuid.uuid4())
    ext = Path(file.filename or "upload.pdf").suffix or ".pdf"
    storage_dir = Path(settings.pdf_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = storage_dir / f"{tender_id}{ext}"

    contents = await file.read()
    pdf_path.write_bytes(contents)

    db = get_db()
    now = datetime.now(timezone.utc)
    db.tenders.insert_one(
        {
            "_id": tender_id,
            "filename": file.filename,
            "local_pdf_path": str(pdf_path),
            "created_at": now,
            "status": "processing",
        }
    )

    evidence_docs = build_evidence_pool(str(pdf_path))
    for doc in evidence_docs:
        doc["tender_id"] = tender_id
    if evidence_docs:
        db.evidence_items.insert_many(evidence_docs)

    canonical = build_canonical(evidence_docs)
    canonical["tender_id"] = tender_id
    canonical["created_at"] = now
    db.canonical_tenders.insert_one(canonical)

    tfidf_index = build_tfidf_index(evidence_docs)
    embeddings = build_semantic_embeddings(evidence_docs)
    for emb in embeddings:
        emb["tender_id"] = tender_id
    if embeddings:
        db.embeddings.insert_many(embeddings)
    db.tfidf_indexes.update_one(
        {"tender_id": tender_id},
        {"$set": {"tender_id": tender_id, "index": tfidf_index, "created_at": now}},
        upsert=True,
    )

    db.tenders.update_one({"_id": tender_id}, {"$set": {"status": "completed"}})
    return {
        "tender_id": tender_id,
        "evidence_count": len(evidence_docs),
        "canonical_fields": list((canonical.get("fields") or {}).keys()),
        "embeddings_count": len(embeddings),
        "tfidf_shape": tfidf_index.get("matrix_shape", [0, 0]),
    }

