# -*- coding: utf-8 -*-
"""
Tender Ingest Service
=====================
Implements the full upload-and-process pipeline from the Tender Upload Plan:

  Step 1 – Save PDF + create Mongo record (status: UPLOADED)
  Step 2 – Parse PDF into chunks via all four parsers    (status: PARSING)
  Step 3 – Build unified evidence pool + merge fragments (status: PARSED)
  Step 4 – LLM-based canonical criteria generation       (status: CANONICAL_READY → LLM_NORMALIZED)
  Step 5 – TF-IDF + semantic embeddings                  (status: INDEXED)
  Final  – Mark tender ready                             (status: READY_FOR_SUBMISSIONS)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.parsers import pipeline as parser_pipeline
from app.parsers.evidence_merger import merge_evidence_pool
from app.models.db import get_db
from app.services.embedding_service import build_semantic_embeddings
from app.utils.settings import settings

logger = logging.getLogger(__name__)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _set_status(tender_id: str, status: str) -> None:
    db = get_db()
    db.tenders.update_one({"_id": tender_id}, {"$set": {"status": status}})
    logger.info("Tender %s → %s", tender_id, status)


def _get_tender_dir(tender_id: str) -> Path:
    """Returns and creates the per-tender storage directory."""
    d = Path(settings.pdf_storage_dir) / tender_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Step 1 ────────────────────────────────────────────────────────────────────
def _save_upload(tender_id: str, file_bytes: bytes, filename: str) -> Path:
    tender_dir = _get_tender_dir(tender_id)
    pdf_path = tender_dir / "original.pdf"
    pdf_path.write_bytes(file_bytes)
    return pdf_path


def _create_tender_record(
    tender_id: str,
    filename: str | None,
    pdf_path: Path,
    checksum: str,
    now: datetime,
) -> None:
    db = get_db()
    db.tenders.insert_one(
        {
            "_id": tender_id,
            "name": filename,
            "file_path": str(pdf_path),
            "checksum": checksum,
            "upload_timestamp": now,
            "status": "UPLOADED",
        }
    )


# ── Step 3 ────────────────────────────────────────────────────────────────────
def _save_evidence(tender_id: str, evidence_docs: list[dict[str, Any]]) -> None:
    tender_dir = _get_tender_dir(tender_id)

    # Save enriched (merged) pool to disk
    pool_path = tender_dir / "evidence_pool.json"
    pool_path.write_text(
        json.dumps(evidence_docs, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Persist to MongoDB
    db = get_db()
    docs_for_mongo = []
    for doc in evidence_docs:
        mongo_doc = dict(doc)
        mongo_doc["tender_id"] = tender_id
        docs_for_mongo.append(mongo_doc)
    if docs_for_mongo:
        db.tender_evidence.insert_many(docs_for_mongo)


# ── Step 4 ────────────────────────────────────────────────────────────────────
def _build_and_save_canonical(
    tender_id: str,
    evidence_docs: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    from app.services.canonical_service import build_canonical

    canonical = build_canonical(evidence_docs)
    canonical["tender_id"] = tender_id
    canonical["pdf_path"] = str(_get_tender_dir(tender_id) / "original.pdf")
    canonical["created_at"] = now.isoformat()

    tender_dir = _get_tender_dir(tender_id)
    canon_path = tender_dir / "canonical.json"
    canon_path.write_text(
        json.dumps(canonical, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    db = get_db()
    db.canonical_tenders.update_one(
        {"tender_id": tender_id},
        {"$set": canonical},
        upsert=True,
    )
    return canonical


# ── Main pipeline ─────────────────────────────────────────────────────────────
async def ingest_pdf(file: UploadFile) -> dict[str, Any]:
    """
    Full upload-and-process pipeline (runs synchronously within the request
    as per plan — no external queue required).
    """
    import uuid

    tender_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    file_bytes = await file.read()
    checksum = _sha256(file_bytes)
    filename = file.filename or "upload.pdf"

    # ── Step 1: Save file + Mongo record ─────────────────────────────────────
    pdf_path = _save_upload(tender_id, file_bytes, filename)
    _create_tender_record(tender_id, filename, pdf_path, checksum, now)
    logger.info("Tender %s uploaded (%d bytes, SHA256=%s)", tender_id, len(file_bytes), checksum)

    try:
        # ── Step 2: Parse PDF ─────────────────────────────────────────────────
        _set_status(tender_id, "PARSING")
        raw_evidence = parser_pipeline.build_evidence_pool(str(pdf_path))

        # ── Step 3: Evidence pool + merge fragments ───────────────────────────
        _set_status(tender_id, "MERGING")
        evidence_docs = merge_evidence_pool(raw_evidence)
        logger.info(
            "Evidence merger: %d raw → %d enriched items",
            len(raw_evidence), len(evidence_docs),
        )
        _set_status(tender_id, "PARSED")
        _save_evidence(tender_id, evidence_docs)

        # ── Step 4: LLM-based canonical generation ───────────────────────────
        _set_status(tender_id, "CANONICAL_GENERATING")
        canonical = _build_and_save_canonical(tender_id, evidence_docs, now)
        _set_status(tender_id, "LLM_NORMALIZED")

        # ── Step 5: Embeddings ───────────────────────────────────────────────
        _set_status(tender_id, "INDEXING")
        
        # Build embeddings purely from the classified canonical dictionary
        embeddings = build_semantic_embeddings(canonical)
        
        db = get_db()
        for emb in embeddings:
            emb["tender_id"] = tender_id
            
        if embeddings:
            db.embeddings.insert_many(embeddings)

        # ── Final: Ready ──────────────────────────────────────────────────────
        _set_status(tender_id, "READY_FOR_SUBMISSIONS")

        return {
            "tender_id": tender_id,
            "status": "READY_FOR_SUBMISSIONS",
            "checksum": checksum,
            "evidence_count": len(evidence_docs),
            "canonical_criteria": canonical.get("total_classified", 0),
            "embeddings_count": len(embeddings),
        }

    except Exception as exc:
        logger.exception("Pipeline failed for tender %s", tender_id)
        _set_status(tender_id, "FAILED")
        raise RuntimeError(f"Tender processing failed: {exc}") from exc
