# -*- coding: utf-8 -*-
"""
Groq LLM utility for the Tender Analyzer.

Exposes a single function `normalize_canonical_category` that takes a
category name and its raw extracted items, sends them to the Groq LLM
with the normalization prompt defined in the Tender Upload Plan, and
returns the cleaned list of canonical criteria.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from groq import Groq

from app.utils.settings import settings

logger = logging.getLogger(__name__)

# ── Prompt template ──────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a Tender Criteria Normalization Engine.
Your task is to clean, normalize, deduplicate, and map extracted tender criteria into canonical structured criteria.

Context
I have already parsed a tender PDF into structured JSON.
The extracted data may contain:
- duplicate entries
- OCR noise
- Hindi + English mixed text
- broken headers
- repeated paragraph/table/list evidence
- irrelevant lines
- partially extracted numeric values
- incorrectly mapped entries

Your job is to convert noisy extracted records into clean canonical evaluation criteria.

Rules
1. Remove garbage / OCR noise
   Ignore: corrupted unicode, incomplete text, random fragments, broken Hindi text, meaningless repeated lines.

2. Merge duplicates
   If multiple records represent the same criterion, merge them into one canonical criterion.
   Example: "Minimum Average Annual Turnover of bidder", "Average Annual Financial Turnover", "Bidder Turnover"
   → one canonical criterion: "Bidder Annual Turnover"

3. Normalize naming
   Convert raw header into clean canonical name.
   Examples:
     Past Performance → Past Supply Performance
     OEM Turnover → OEM Annual Turnover
     GST Registration → GST Compliance

4. Extract structured values
   Identify: threshold_value, unit, operator, years, percentage, required_documents, exemptions, mandatory (true/false).
   Examples: 1 Lakh → 100000 INR | 50% → 50 percent | 3 Years → 3 years

5. Identify evaluation type
   Choose one: numeric_threshold | boolean_requirement | document_requirement |
               experience_requirement | compliance_requirement | technical_requirement | weighted_requirement

6. Generate matching aliases
   Create aliases bidder submissions may use.
   Example: Bidder Annual Turnover aliases: ["turnover", "annual turnover", "financial turnover", "audited turnover", "bidder turnover"]

7. Confidence score
   Return confidence: 0–1

Output format (STRICT JSON ARRAY ONLY — no markdown, no explanation):
[
  {
    "canonical_name": "",
    "category": "",
    "criterion_type": "",
    "operator": "",
    "expected_value": null,
    "unit": "",
    "period_years": null,
    "mandatory": true,
    "required_documents": [],
    "aliases": [],
    "supporting_evidence_ids": [],
    "confidence": 0.95
  }
]
Only output a valid JSON array. No markdown code fences. No extra text.
"""


def _build_client() -> Groq:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set in environment.")
    return Groq(api_key=settings.groq_api_key)


# Rough character budget per batch to stay well under the 12 000 TPM limit.
# System prompt is ~900 tokens; leave ~2 500 tokens for the user payload
# (~10 chars/token on average → ~25 000 chars, but we keep it conservative).
_MAX_PAYLOAD_CHARS = 8_000


def _call_llm(category_name: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Single LLM call for a (possibly truncated) batch of items."""
    payload = json.dumps(
        {"category": category_name, "items": items},
        ensure_ascii=False,
        indent=2,
    )
    user_message = f"Now process this category:\n{payload}"

    client = _build_client()
    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.0,
    )
    raw = (response.choices[0].message.content or "").strip()

    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```", 2)[-1] if raw.count("```") >= 2 else raw
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rstrip("`").strip()

    parsed: list[dict[str, Any]] = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("LLM returned non-list JSON.")
    return parsed


def _split_into_batches(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """
    Split items into batches so each serialised batch stays under
    _MAX_PAYLOAD_CHARS to avoid Groq token-per-minute rate limits.
    """
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_len = 0

    for item in items:
        item_json = json.dumps(item, ensure_ascii=False)
        if current and current_len + len(item_json) > _MAX_PAYLOAD_CHARS:
            batches.append(current)
            current = []
            current_len = 0
        current.append(item)
        current_len += len(item_json)

    if current:
        batches.append(current)

    return batches


def normalize_canonical_category(
    category_name: str,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Send a canonical category's items to the Groq LLM for normalisation.
    Large categories are split into batches to stay under token limits.
    Falls back to the original items if the LLM call fails.
    """
    if not items:
        return []

    batches = _split_into_batches(items)
    results: list[dict[str, Any]] = []

    for batch_idx, batch in enumerate(batches, 1):
        try:
            cleaned = _call_llm(category_name, batch)
            results.extend(cleaned)
            logger.info(
                "LLM normalised '%s' batch %d/%d: %d → %d items",
                category_name, batch_idx, len(batches), len(batch), len(cleaned),
            )
        except Exception as exc:
            logger.warning(
                "LLM normalisation failed for '%s' batch %d/%d (%s). "
                "Using raw batch items.",
                category_name, batch_idx, len(batches), exc,
            )
            results.extend(batch)  # graceful fallback per batch

    return results
