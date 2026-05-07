# -*- coding: utf-8 -*-
"""
Rules Engine — Dispatches each criterion to the correct evaluator.

Routes based on category and sub_component to the appropriate
evaluator (numeric, boolean, document, experience).
"""

from __future__ import annotations

import logging
from typing import Any

from app.evaluators import (
    numeric_evaluator,
    boolean_evaluator,
    document_evaluator,
    experience_evaluator,
)
from app.services.extraction_service import extract_structured_value

logger = logging.getLogger(__name__)

# Category → sub_component patterns → evaluator routing
_FINANCIAL_SUBS = {
    "minimum turnover", "relevant category turnover", "net worth / profitability",
    "contract value ratio", "price evaluation rule", "financial solvency",
}
_EXPERIENCE_SUBS = {
    "minimum years of existence", "similar projects completed",
    "project value threshold", "geographic / sector experience",
    "key personnel experience", "delivery / execution capacity",
    "operational capability",
}
_DOCUMENT_SUBS = {
    "company documents", "financial documents", "experience documents",
    "statutory compliance", "tax compliance", "labor compliance",
    "quality / safety certifications", "insurance / legal undertakings",
}
_COMMERCIAL_SUBS = {
    "emd", "performance bank guarantee", "payment terms", "delivery timeline",
    "penalty / liquidated damages", "contract duration", "bid validity",
    "cancellation / termination clause",
}


def evaluate_criterion(
    match_record: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate a single criterion by routing to the correct evaluator.

    Args:
        match_record: dict with keys:
            - category, sub_component, canonical_text
            - aggregated_text (merged matched evidence text)
            - matched_evidence (list of evidence matches)

    Returns:
        Evaluation result dict.
    """
    category = (match_record.get("category") or "").strip()
    sub_component = (match_record.get("sub_component") or "").strip()
    aggregated_text = match_record.get("aggregated_text", "")
    canonical_text = match_record.get("canonical_text", "")

    # Extract structured values from matched submission evidence
    extracted = extract_structured_value(aggregated_text, sub_component)

    sub_lower = sub_component.lower()

    # Route to the correct evaluator
    if category == "Financial Thresholds & Stability" or sub_lower in _FINANCIAL_SUBS:
        result = numeric_evaluator.evaluate(
            expected_value=_guess_expected(canonical_text),
            operator=">=",
            extracted=extracted,
            sub_component=sub_component,
        )

    elif category == "Experience & Capability" or sub_lower in _EXPERIENCE_SUBS:
        result = experience_evaluator.evaluate(
            expected_value=_guess_expected(canonical_text),
            operator=">=",
            extracted=extracted,
            sub_component=sub_component,
        )

    elif category == "Legal & Compliance" or sub_lower in _DOCUMENT_SUBS:
        result = document_evaluator.evaluate(
            required_documents=_guess_documents(canonical_text),
            extracted=extracted,
            sub_component=sub_component,
        )

    elif category == "Commercial / Tender Terms" or sub_lower in _COMMERCIAL_SUBS:
        # Commercial terms are often numeric (EMD, PBG) or boolean
        if extracted.get("amount"):
            result = numeric_evaluator.evaluate(
                expected_value=_guess_expected(canonical_text),
                operator=">=",
                extracted=extracted,
                sub_component=sub_component,
            )
        else:
            result = boolean_evaluator.evaluate(
                expected_value=True,
                extracted=extracted,
                sub_component=sub_component,
            )

    elif category == "Technical Specifications":
        # Technical specs can be numeric, boolean, or document-based
        if extracted.get("amount") or extracted.get("percentage"):
            result = numeric_evaluator.evaluate(
                expected_value=_guess_expected(canonical_text),
                operator=">=",
                extracted=extracted,
                sub_component=sub_component,
            )
        elif extracted.get("documents"):
            result = document_evaluator.evaluate(
                required_documents=_guess_documents(canonical_text),
                extracted=extracted,
                sub_component=sub_component,
            )
        else:
            result = boolean_evaluator.evaluate(
                expected_value=True,
                extracted=extracted,
                sub_component=sub_component,
            )

    else:
        # Default: boolean presence check
        result = boolean_evaluator.evaluate(
            expected_value=True,
            extracted=extracted,
            sub_component=sub_component,
        )

    # Attach metadata
    result["category"] = category
    result["sub_component"] = sub_component
    result["evidence_id"] = match_record.get("evidence_id")
    result["matched_evidence_ids"] = [
        m["evidence_id"] for m in match_record.get("matched_evidence", [])
    ]
    result["matched_pages"] = list(set(
        m.get("page") for m in match_record.get("matched_evidence", [])
        if m.get("page") is not None
    ))
    result["similarity_scores"] = [
        m["similarity"] for m in match_record.get("matched_evidence", [])
    ]

    return result


def _guess_expected(canonical_text: str) -> str:
    """Extract the expected value from canonical text as a raw string."""
    return canonical_text


def _guess_documents(canonical_text: str) -> str:
    """Return canonical text as the document requirement description."""
    return canonical_text
