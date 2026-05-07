# -*- coding: utf-8 -*-
"""
Report Service — Standardized evaluation report generation.

Builds a complete, auditable report with:
- Overall score + verdict
- Category-wise breakdowns
- Criterion-wise detail with evidence proof
- Audit trail with source evidence IDs and page numbers
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def build_report(
    submission_id: str,
    tender_id: str,
    scoring_result: dict[str, Any],
    evaluation_results: list[dict[str, Any]],
    llm_category_scores: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Build the complete standardized evaluation report.
    """
    now = datetime.now(timezone.utc)

    # ── Submission Summary ────────────────────────────────────────────────────
    summary = {
        "submission_id": submission_id,
        "tender_id": tender_id,
        "evaluation_timestamp": now.isoformat(),
        "overall_score": scoring_result.get("overall_score", 0.0),
        "verdict": scoring_result.get("verdict", "MANUAL_REVIEW"),
        "total_criteria_evaluated": len(evaluation_results),
        "mandatory_failures_count": len(scoring_result.get("mandatory_failures", [])),
    }

    # ── Category-wise Scores ──────────────────────────────────────────────────
    category_breakdown = {}
    category_scores = scoring_result.get("category_scores", {})

    for cat, cat_data in category_scores.items():
        category_breakdown[cat] = {
            "deterministic_score": cat_data.get("deterministic_score", 0.0),
            "llm_score": cat_data.get("llm_score", 0.0),
            "final_score": cat_data.get("final_score", 0.0),
            "total_criteria": cat_data.get("total_criteria", 0),
            "passed": cat_data.get("passed", 0),
            "failed": cat_data.get("failed", 0),
            "needs_review": cat_data.get("needs_review", 0),
        }

    # ── Criterion-wise Detail ─────────────────────────────────────────────────
    criteria_details = []
    for ev in evaluation_results:
        detail = {
            "criterion_evidence_id": ev.get("evidence_id"),
            "category": ev.get("category"),
            "sub_component": ev.get("sub_component"),
            "expected_value": ev.get("expected"),
            "found_value": ev.get("found"),
            "found_raw": ev.get("found_raw", ""),
            "deterministic_score": ev.get("score", 0.0),
            "verdict": ev.get("verdict", "NEEDS_MANUAL_REVIEW"),
            "reasoning": ev.get("reason", ""),
            "matched_evidence_ids": ev.get("matched_evidence_ids", []),
            "matched_pages": ev.get("matched_pages", []),
            "similarity_scores": ev.get("similarity_scores", []),
        }
        criteria_details.append(detail)

    # ── Audit Trail ───────────────────────────────────────────────────────────
    all_evidence_ids = set()
    all_pages = set()
    for ev in evaluation_results:
        for eid in ev.get("matched_evidence_ids", []):
            if eid:
                all_evidence_ids.add(eid)
        for p in ev.get("matched_pages", []):
            if p is not None:
                all_pages.add(p)

    audit_trail = {
        "total_submission_evidence_used": len(all_evidence_ids),
        "all_source_evidence_ids": sorted(all_evidence_ids),
        "all_source_pages": sorted(all_pages),
    }

    # ── Mandatory Failures ────────────────────────────────────────────────────
    mandatory_failures = scoring_result.get("mandatory_failures", [])

    # ── Assemble Report ───────────────────────────────────────────────────────
    report = {
        "submission_id": submission_id,
        "tender_id": tender_id,
        "summary": summary,
        "category_scores": category_breakdown,
        "criteria_details": criteria_details,
        "mandatory_failures": mandatory_failures,
        "audit_trail": audit_trail,
        "generated_at": now.isoformat(),
    }

    logger.info(
        "Report generated for submission %s: score=%.2f, verdict=%s",
        submission_id, summary["overall_score"], summary["verdict"],
    )

    return report
