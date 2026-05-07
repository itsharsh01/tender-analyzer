# -*- coding: utf-8 -*-
"""
Canonical Service — LLM-based canonical criteria generation.

Instead of regex/keyword pattern matching, this sends evidence items
to the LLM in manageable batches. The LLM categorises each item and
extracts structured canonical criteria.

Flow:
  1. Receive enriched evidence pool (already merged fragments).
  2. Prepare lightweight evidence summaries for the LLM.
  3. Split into batches (~8 000 chars each to stay under token limits).
  4. For each batch → LLM call → collect canonical criteria.
  5. Merge results into the final canonical dict, keyed by category.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.utils.groq_llm import _chat_completion_with_fallback, _split_into_batches, _strip_markdown_fences

logger = logging.getLogger(__name__)

# ── LLM system prompt for canonical generation ───────────────────────────────

_CANONICAL_SYSTEM_PROMPT = """\
You are an **AI Tender Evidence Classification Engine**.

Your task is to classify each tender evidence item into the correct procurement evaluation category and sub-component.

The evidence is already cleaned and extracted from tender documents (tables, lists, paragraphs, OCR).
Each evidence item may contain:
* requirement statements
* numeric thresholds
* document requirements
* compliance clauses
* experience requirements
* technical specifications
* payment / commercial terms
* irrelevant boilerplate text

You must classify carefully.

---

## Classification Categories

### 1) Technical Specifications
Use when evidence describes what is being procured, how it should perform, quality expectations, interoperability, warranty, technical standards, dimensions, product specifications, SLAs, service capabilities, infrastructure requirements, manpower requirements, hardware/software compatibility, repair timelines, design constraints, functional modules, APIs, protocols.

Sub-components:
* Product/Service Description
* Functional Requirements
* Technical Parameters & Standards
* Quality & Warranty
* Design / Interoperability Constraints
* Equipment / Infrastructure
* Manpower / Personnel

### 2) Financial Thresholds & Stability
Use when evidence discusses bidder financial capacity, turnover, solvency, net worth, profitability, price rules, contract value ratios, financial eligibility, bid value calculations, pricing evaluation, audited balance sheet requirements.

Sub-components:
* Minimum Turnover
* Relevant Category Turnover
* Net Worth / Profitability
* Contract Value Ratio
* Price Evaluation Rule
* Financial Solvency
* Audited Financial Documents

### 3) Experience & Capability
Use when evidence discusses prior projects, work experience, company age, number of completed projects, project size/value thresholds, domain/sector experience, key personnel expertise, operational capacity, fleet/assets ownership, implementation capability.

Sub-components:
* Minimum Years of Existence
* Similar Projects Completed
* Project Value Threshold
* Geographic / Sector Experience
* Key Personnel Experience
* Delivery / Execution Capacity
* Operational Capability

### 4) Legal & Compliance
Use when evidence requires legal registration, statutory documents, certificates, tax compliance, labor compliance, company incorporation, PAN/GST, PF/ESI, insurance, ISO, quality certifications, NOCs, declarations, undertakings, mandatory registrations, compliance proof.

Sub-components:
* Company Documents
* Financial Documents
* Experience Documents
* Statutory Compliance
* Tax Compliance
* Labor Compliance
* Quality / Safety Certifications
* Insurance / Legal Undertakings

### 5) Commercial / Tender Terms
Use when evidence discusses EMD, PBG, bid validity, delivery schedule, penalties, liquidated damages, payment milestones, contract duration, renewal clauses, warranty support conditions, cancellation terms.

Sub-components:
* EMD
* Performance Bank Guarantee
* Payment Terms
* Delivery Timeline
* Penalty / Liquidated Damages
* Contract Duration
* Bid Validity
* Cancellation / Termination Clause

### 6) Ignore
If evidence is disclaimer text, repeated header/footer, navigation text, boilerplate policy text, corrupted OCR text, irrelevant fragments, duplicated meaningless text.

Sub-components:
* Ignore

---

## Instructions

For every evidence item in the batch:
1. Read complete text carefully.
2. Determine most relevant category.
3. Determine most relevant sub-component.
4. Assign confidence score (0–1).
5. Give short reasoning.
6. Keep original evidence_id.
7. If mixed category, choose primary category.
8. If irrelevant or metadata → select category "Ignore" and sub_component "Ignore".

---

## Output Format (STRICT JSON ARRAY ONLY)

[
  {
    "evidence_id": "<preserve from input>",
    "category": "<Must be one of the 6 exact category names above>",
    "sub_component": "<Must be one of the sub-components listed under the chosen category>",
    "confidence": 0.95,
    "reason": "<Short reasoning for classification>"
  }
]

Only return valid JSON array.
No markdown code blocks (do not wrap in ```json).
No explanation outside JSON.
"""


# ── Evidence summariser ──────────────────────────────────────────────────────

def _summarise_evidence(ev: dict[str, Any]) -> dict[str, Any]:
    """
    Create a lightweight summary dict for the LLM.
    We format text into `text_for_llm` as requested by the prompt.
    """
    text = ev.get("text_norm") or ev.get("text_raw") or ""
    if ev.get("source") == "table":
        k = ev.get("key_norm", "").strip()
        v = ev.get("value_norm", "").strip()
        if k and v:
            text = f"{k}: {v}"
        elif k:
            text = k
        elif v:
            text = v

    return {
        "evidence_id": ev.get("evidence_id"),
        "source": ev.get("source"),
        "heading": ev.get("heading") or "Unknown",
        "text_for_llm": text,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def build_canonical(evidence_docs: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Process the enriched evidence pool through the LLM in batches,
    producing a categorised and fully classified canonical dictionary.
    """
    # Create lookup map to merge original data back with classifications
    ev_map = {ev["evidence_id"]: ev for ev in evidence_docs if "evidence_id" in ev}

    # Prepare lightweight summaries for the LLM
    summaries = [_summarise_evidence(ev) for ev in evidence_docs]

    # Split into batches
    batches = _split_into_batches(summaries)
    logger.info("Classification: %d evidence items → %d LLM batches", len(summaries), len(batches))

    all_classifications: list[dict[str, Any]] = []

    for batch_idx, batch in enumerate(batches, 1):
        try:
            results = _call_llm_canonical(batch)
            all_classifications.extend(results)
            logger.info(
                "Classification batch %d/%d: %d evidence → %d classified",
                batch_idx, len(batches), len(batch), len(results),
            )
        except Exception as exc:
            logger.warning(
                "Classification batch %d/%d failed (%s). Skipping batch.",
                batch_idx, len(batches), exc,
            )

    # Group results by category
    canonical: dict[str, Any] = {
        "Technical Specifications": [],
        "Financial Thresholds & Stability": [],
        "Experience & Capability": [],
        "Legal & Compliance": [],
        "Commercial / Tender Terms": [],
        "Ignore": [],
    }

    valid_categories = set(canonical.keys())

    for item in all_classifications:
        cat = item.get("category", "Ignore")
        # Ensure fallback for hallucinated categories
        if cat not in valid_categories:
            cat = "Ignore"
        
        # Merge original text for the final output so it's fully readable
        ev_id = item.get("evidence_id")
        if ev_id in ev_map:
            original_ev = ev_map[ev_id]
            # Attach classification info to the full evidence dict
            enriched_item = dict(original_ev)
            enriched_item["category"] = cat
            enriched_item["sub_component"] = item.get("sub_component", "Unknown")
            enriched_item["classification_confidence"] = item.get("confidence", 0.0)
            enriched_item["classification_reason"] = item.get("reason", "")
            
            canonical[cat].append(enriched_item)

    canonical["total_classified"] = sum(len(lst) for cat, lst in canonical.items() if cat != "Ignore")
    canonical["total_ignored"] = len(canonical["Ignore"])
    canonical["batch_count"] = len(batches)

    return canonical


def _call_llm_canonical(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Make a single LLM call for a batch of evidence summaries
    using the classification system prompt.
    """
    payload = json.dumps(batch, ensure_ascii=False, indent=2)
    user_message = f"Classify this evidence batch:\n{payload}"
    raw = _chat_completion_with_fallback(
        system_prompt=_CANONICAL_SYSTEM_PROMPT,
        user_message=user_message,
        temperature=0.0,
    )
    raw = _strip_markdown_fences(raw)

    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("LLM returned non-list JSON.")
    return parsed
