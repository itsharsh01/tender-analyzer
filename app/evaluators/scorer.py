# -*- coding: utf-8 -*-
"""
Scorer — Weighted scoring with mandatory gate.

Computes:
- Per-criterion deterministic score
- Category-wise aggregated scores
- Weighted final score across categories
- Mandatory gate check
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Category weights for final scoring
CATEGORY_WEIGHTS = {
    "Technical Specifications": 0.30,
    "Financial Thresholds & Stability": 0.25,
    "Experience & Capability": 0.20,
    "Legal & Compliance": 0.15,
    "Commercial / Tender Terms": 0.10,
}


def compute_category_scores(
    evaluation_results: list[dict[str, Any]],
    llm_category_scores: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Aggregate evaluation results into category scores and weighted final score.

    Args:
        evaluation_results: list of individual criterion evaluations
        llm_category_scores: optional dict of category → LLM reasoning score (0-1)

    Returns:
        {
            "category_scores": {...},
            "overall_score": float,
            "verdict": "ELIGIBLE|NOT_ELIGIBLE|MANUAL_REVIEW",
            "mandatory_failures": [...],
        }
    """
    # Group evaluations by category
    by_category: dict[str, list[dict[str, Any]]] = {}
    for ev in evaluation_results:
        cat = ev.get("category", "Unknown")
        by_category.setdefault(cat, []).append(ev)

    category_scores = {}
    mandatory_failures = []
    has_manual_review = False

    for cat, evals in by_category.items():
        if cat == "Ignore":
            continue

        total = len(evals)
        if total == 0:
            continue

        # Deterministic category score = average of individual scores
        det_score = sum(e.get("score", 0.0) for e in evals) / total

        # LLM reasoning score for the category (default to deterministic if unavailable)
        llm_score = (llm_category_scores or {}).get(cat, det_score)

        # Weighted: 70% deterministic + 30% LLM
        final_cat_score = 0.7 * det_score + 0.3 * llm_score

        # Track pass/fail/review counts
        pass_count = sum(1 for e in evals if e.get("verdict") == "PASS")
        fail_count = sum(1 for e in evals if e.get("verdict") == "FAIL")
        review_count = sum(1 for e in evals if e.get("verdict") == "NEEDS_MANUAL_REVIEW")

        if review_count > 0:
            has_manual_review = True

        # Check mandatory failures
        for e in evals:
            if e.get("verdict") == "FAIL":
                mandatory_failures.append({
                    "category": cat,
                    "sub_component": e.get("sub_component"),
                    "evidence_id": e.get("evidence_id"),
                    "reason": e.get("reason", ""),
                })

        category_scores[cat] = {
            "deterministic_score": round(det_score, 4),
            "llm_score": round(llm_score, 4),
            "final_score": round(final_cat_score, 4),
            "total_criteria": total,
            "passed": pass_count,
            "failed": fail_count,
            "needs_review": review_count,
        }

    # Compute weighted overall score
    overall = 0.0
    total_weight = 0.0

    for cat, weight in CATEGORY_WEIGHTS.items():
        if cat in category_scores:
            overall += weight * category_scores[cat]["final_score"]
            total_weight += weight

    if total_weight > 0:
        overall = overall / total_weight  # Normalize in case not all categories present

    overall = round(overall, 4)

    # Mandatory gate
    if mandatory_failures:
        verdict = "NOT_ELIGIBLE"
    elif has_manual_review:
        verdict = "MANUAL_REVIEW"
    else:
        verdict = "ELIGIBLE"

    return {
        "category_scores": category_scores,
        "overall_score": overall,
        "verdict": verdict,
        "mandatory_failures": mandatory_failures,
    }
