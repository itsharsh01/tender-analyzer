# -*- coding: utf-8 -*-
"""
LLM Scoring Service — Category-wise LLM reasoning scores.

For each evaluation category, sends the canonical criteria, matched evidence,
deterministic verdicts, and extracted values to the LLM for a reasoning score.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.utils.groq_llm import _chat_completion_with_fallback, _strip_markdown_fences

logger = logging.getLogger(__name__)

_LLM_SCORING_PROMPT = """\
You are a Tender Submission Scoring Engine.

You are given a category of tender evaluation criteria with:
- Each criterion's canonical requirement
- The matched submission evidence for each criterion
- The deterministic evaluation verdict (PASS/FAIL/NEEDS_MANUAL_REVIEW)
- Extracted values from the submission

Your task is to provide an overall reasoning score for this category.

Score on a scale of 0 to 1 where:
- 1.0 = Perfect compliance, all criteria met with strong evidence
- 0.7-0.9 = Good compliance, most criteria met
- 0.4-0.6 = Partial compliance, some criteria unclear
- 0.1-0.3 = Poor compliance, significant gaps
- 0.0 = No compliance evidence found

Consider:
- Strength and clarity of the evidence
- Whether extracted values truly satisfy requirements
- Whether documents appear genuine/complete
- Overall completeness of the category

Output format (STRICT JSON ONLY):
{
  "score": 0.85,
  "reason": "Brief reasoning for the score"
}

No markdown code blocks. No extra text. Only valid JSON object.
"""


def score_categories_with_llm(
    evaluation_results: list[dict[str, Any]],
) -> dict[str, float]:
    """
    Send each category's evaluation results to the LLM for reasoning scores.

    Returns:
        dict mapping category name → LLM reasoning score (0-1)
    """
    # Group by category
    by_category: dict[str, list[dict[str, Any]]] = {}
    for ev in evaluation_results:
        cat = ev.get("category", "Unknown")
        if cat == "Ignore":
            continue
        by_category.setdefault(cat, []).append(ev)

    category_scores: dict[str, float] = {}

    for cat, evals in by_category.items():
        try:
            score = _score_single_category(cat, evals)
            category_scores[cat] = score
            logger.info("LLM scoring: %s → %.2f", cat, score)
        except Exception as exc:
            logger.warning("LLM scoring failed for '%s' (%s). Using 0.5 fallback.", cat, exc)
            category_scores[cat] = 0.5  # Neutral fallback
            # Rate limit backoff
            if "429" in str(exc) or "rate_limit" in str(exc).lower():
                logger.info("Rate limited. Waiting 10s before next category...")
                time.sleep(10)

    return category_scores


def _score_single_category(
    category_name: str,
    evaluations: list[dict[str, Any]],
) -> float:
    """Make a single LLM call for one category's evaluations."""
    # Prepare a concise summary for the LLM
    summary = []
    for ev in evaluations:
        summary.append({
            "sub_component": ev.get("sub_component"),
            "verdict": ev.get("verdict"),
            "score": ev.get("score"),
            "reason": ev.get("reason"),
            "expected": str(ev.get("expected", "")),
            "found": str(ev.get("found", "")),
        })

    payload = json.dumps({
        "category": category_name,
        "criteria_evaluations": summary,
    }, ensure_ascii=False, indent=2)

    user_message = f"Score this category:\n{payload}"

    raw = _chat_completion_with_fallback(
        system_prompt=_LLM_SCORING_PROMPT,
        user_message=user_message,
        temperature=0.0,
    )
    raw = _strip_markdown_fences(raw)

    parsed = json.loads(raw)
    score = float(parsed.get("score", 0.5))
    return max(0.0, min(1.0, score))  # Clamp to [0, 1]
