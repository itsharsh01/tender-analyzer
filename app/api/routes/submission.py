# -*- coding: utf-8 -*-
"""
Submission API routes.

Endpoints:
  POST   /submission/upload             – Upload submission PDF for evaluation
  GET    /submission/{id}/status        – Check evaluation progress
  GET    /submission/{id}/report        – Get full evaluation report
  GET    /tender/{tender_id}/submissions – List all submissions for a tender
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse

from app.models.db import get_db

router = APIRouter(tags=["submission"])
logger = logging.getLogger(__name__)


@router.post("/submission/upload")
async def upload_submission(
    file: UploadFile = File(...),
    tender_id: str = Form(...),
):
    """Upload a bidder submission PDF and trigger full evaluation."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Check that the tender exists
    db = get_db()
    tender = db.tenders.find_one({"_id": tender_id})
    if not tender:
        raise HTTPException(status_code=404, detail=f"Tender {tender_id} not found.")

    # Check that canonical embeddings exist
    emb_count = db.embeddings.count_documents({"tender_id": tender_id})
    if emb_count == 0:
        raise HTTPException(
            status_code=400,
            detail=f"Tender {tender_id} has no canonical embeddings. "
                   "Upload and process the tender PDF first.",
        )

    from app.services.submission_service import evaluate_submission

    try:
        result = await evaluate_submission(tender_id, file)
        return JSONResponse(content=result)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/submission/{submission_id}/status")
async def get_submission_status(submission_id: str):
    """Check the evaluation status of a submission."""
    db = get_db()
    submission = db.submissions.find_one(
        {"_id": submission_id}, {"_id": 1, "status": 1, "tender_id": 1}
    )
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found.")

    return {
        "submission_id": submission_id,
        "tender_id": submission.get("tender_id"),
        "status": submission.get("status"),
    }


@router.get("/submission/{submission_id}/report")
async def get_submission_report(submission_id: str):
    """Get the full evaluation report for a submission."""
    db = get_db()
    report = db.evaluation_reports.find_one({"submission_id": submission_id})

    if not report:
        raise HTTPException(
            status_code=404,
            detail="Evaluation report not found. Check submission status.",
        )

    # Remove MongoDB internal _id for JSON serialization
    report.pop("_id", None)
    return JSONResponse(content=report)


@router.get("/tender/{tender_id}/submissions")
async def list_submissions(tender_id: str):
    """List all submissions for a tender with their scores."""
    db = get_db()
    submissions = list(
        db.submissions.find(
            {"tender_id": tender_id},
            {"_id": 1, "bidder_name": 1, "status": 1, "upload_timestamp": 1},
        )
    )

    # Enrich with scores from evaluation reports
    results = []
    for sub in submissions:
        sub_id = sub["_id"]
        report = db.evaluation_reports.find_one(
            {"submission_id": sub_id},
            {"summary.overall_score": 1, "summary.verdict": 1},
        )

        entry = {
            "submission_id": sub_id,
            "bidder_name": sub.get("bidder_name"),
            "status": sub.get("status"),
            "upload_timestamp": str(sub.get("upload_timestamp", "")),
        }

        if report and report.get("summary"):
            entry["overall_score"] = report["summary"].get("overall_score")
            entry["verdict"] = report["summary"].get("verdict")
        else:
            entry["overall_score"] = None
            entry["verdict"] = None

        results.append(entry)

    # Sort by score descending (for ranking)
    results.sort(key=lambda x: x.get("overall_score") or 0, reverse=True)

    return {
        "tender_id": tender_id,
        "total_submissions": len(results),
        "submissions": results,
    }
