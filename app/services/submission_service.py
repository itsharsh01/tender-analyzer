# -*- coding: utf-8 -*-
"""
Submission Service — Full submission evaluation pipeline.

Pipeline:
  Step 1 – Upload & register submission
  Step 2 – Parse submission PDF (same 4 parsers + merger)
  Step 3 – Generate search_text + embeddings
  Step 4 – Load canonical criteria from DB
  Step 5 – Semantic matching (top-k)
  Step 6 – Deterministic evaluation per criterion
  Step 7 – LLM reasoning scores per category
  Step 8 – Weighted final score + mandatory gate
  Step 9 – Generate standardized report
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.models.db import get_db
from app.parsers import pipeline as parser_pipeline
from app.parsers.evidence_merger import merge_evidence_pool
from app.services.embedding_service import build_submission_embeddings
from app.services.matching_service import match_criteria_to_submission
from app.evaluators.rules_engine import evaluate_criterion
from app.evaluators.scorer import compute_category_scores
from app.services.llm_scoring_service import score_categories_with_llm
from app.services.report_service import build_report
from app.utils.settings import settings

logger = logging.getLogger(__name__)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _set_status(submission_id: str, status: str) -> None:
    db = get_db()
    db.submissions.update_one({"_id": submission_id}, {"$set": {"status": status}})
    logger.info("Submission %s → %s", submission_id, status)


def _get_submission_dir(tender_id: str, submission_id: str) -> Path:
    d = Path(settings.pdf_storage_dir) / tender_id / "submissions" / submission_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Step 1: Save & Register ──────────────────────────────────────────────────

def _save_submission(
    tender_id: str,
    submission_id: str,
    file_bytes: bytes,
    filename: str,
    checksum: str,
    now: datetime,
) -> Path:
    sub_dir = _get_submission_dir(tender_id, submission_id)
    pdf_path = sub_dir / "submission.pdf"
    pdf_path.write_bytes(file_bytes)

    db = get_db()
    db.submissions.insert_one({
        "_id": submission_id,
        "tender_id": tender_id,
        "bidder_name": filename,
        "file_path": str(pdf_path),
        "checksum": checksum,
        "upload_timestamp": now,
        "status": "UPLOADED",
    })

    return pdf_path


# ── Step 4: Load canonical from DB ───────────────────────────────────────────

def _load_canonical_embeddings(tender_id: str) -> list[dict[str, Any]]:
    """Load canonical embeddings from DB for the given tender."""
    db = get_db()
    cursor = db.embeddings.find({"tender_id": tender_id})
    items = list(cursor)
    logger.info("Loaded %d canonical embeddings for tender %s", len(items), tender_id)
    return items


# ── Main Pipeline ─────────────────────────────────────────────────────────────

async def evaluate_submission(
    tender_id: str,
    file: UploadFile,
) -> dict[str, Any]:
    """
    Full submission evaluation pipeline.
    """
    import uuid

    submission_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    file_bytes = await file.read()
    checksum = _sha256(file_bytes)
    filename = file.filename or "submission.pdf"

    # ── Step 1: Save ──────────────────────────────────────────────────────────
    pdf_path = _save_submission(
        tender_id, submission_id, file_bytes, filename, checksum, now
    )
    logger.info(
        "Submission %s for tender %s uploaded (%d bytes)",
        submission_id, tender_id, len(file_bytes),
    )

    try:
        # ── Step 2: Parse submission PDF ──────────────────────────────────────
        _set_status(submission_id, "PARSING")
        raw_evidence = parser_pipeline.build_evidence_pool(str(pdf_path))

        # Merge fragments
        _set_status(submission_id, "MERGING")
        evidence_docs = merge_evidence_pool(raw_evidence)
        logger.info(
            "Submission parsing: %d raw → %d merged evidence items",
            len(raw_evidence), len(evidence_docs),
        )

        # Save evidence pool to disk
        sub_dir = _get_submission_dir(tender_id, submission_id)
        pool_path = sub_dir / "evidence_pool.json"
        pool_path.write_text(
            json.dumps(evidence_docs, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Save to DB
        db = get_db()
        for doc in evidence_docs:
            doc["submission_id"] = submission_id
            doc["tender_id"] = tender_id
        if evidence_docs:
            db.submission_evidence.insert_many(
                [dict(d) for d in evidence_docs]
            )

        # ── Step 3: Generate embeddings ───────────────────────────────────────
        _set_status(submission_id, "EMBEDDING")
        submission_embeddings = build_submission_embeddings(evidence_docs)
        logger.info("Generated %d submission embeddings", len(submission_embeddings))

        # ── Step 4: Load canonical ────────────────────────────────────────────
        _set_status(submission_id, "MATCHING")
        canonical_embeddings = _load_canonical_embeddings(tender_id)

        if not canonical_embeddings:
            raise RuntimeError(
                f"No canonical embeddings found for tender {tender_id}. "
                "Upload and process the tender PDF first."
            )

        # ── Step 5: Semantic matching ─────────────────────────────────────────
        matches = match_criteria_to_submission(
            canonical_items=canonical_embeddings,
            submission_evidence=submission_embeddings,
            top_k=5,
        )
        logger.info("Semantic matching: %d criteria matched", len(matches))

        # ── Step 6: Deterministic evaluation ──────────────────────────────────
        _set_status(submission_id, "EVALUATING")
        evaluation_results = []
        for match_record in matches:
            result = evaluate_criterion(match_record)
            evaluation_results.append(result)

        logger.info(
            "Deterministic evaluation: %d criteria evaluated",
            len(evaluation_results),
        )

        # ── Step 7: LLM reasoning scores ──────────────────────────────────────
        _set_status(submission_id, "LLM_SCORING")
        try:
            llm_scores = score_categories_with_llm(evaluation_results)
        except Exception as exc:
            logger.warning("LLM scoring failed (%s). Using deterministic only.", exc)
            llm_scores = None

        # ── Step 8: Weighted scoring + mandatory gate ─────────────────────────
        _set_status(submission_id, "SCORING")
        scoring_result = compute_category_scores(
            evaluation_results, llm_scores
        )

        # ── Step 9: Generate report ───────────────────────────────────────────
        report = build_report(
            submission_id=submission_id,
            tender_id=tender_id,
            scoring_result=scoring_result,
            evaluation_results=evaluation_results,
            llm_category_scores=llm_scores,
        )

        # Save report to disk
        report_path = sub_dir / "evaluation_report.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        # Save to DB
        db.evaluation_reports.update_one(
            {"submission_id": submission_id},
            {"$set": report},
            upsert=True,
        )

        # ── Final ─────────────────────────────────────────────────────────────
        _set_status(submission_id, "READY")

        return {
            "submission_id": submission_id,
            "tender_id": tender_id,
            "status": "READY",
            "overall_score": scoring_result["overall_score"],
            "verdict": scoring_result["verdict"],
            "evidence_count": len(evidence_docs),
            "criteria_evaluated": len(evaluation_results),
            "category_scores": scoring_result["category_scores"],
            "mandatory_failures": len(scoring_result["mandatory_failures"]),
        }

    except Exception as exc:
        logger.exception("Submission evaluation failed for %s", submission_id)
        _set_status(submission_id, "FAILED")
        raise RuntimeError(f"Submission evaluation failed: {exc}") from exc
