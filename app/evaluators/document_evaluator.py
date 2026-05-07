# -*- coding: utf-8 -*-
"""
Document Evaluator — Checks if required documents/certificates are present.

Handles: GST, PAN, ISO, insurance, work orders, balance sheets, etc.
"""

from __future__ import annotations

from typing import Any


def evaluate(
    required_documents: list[str] | str | None,
    extracted: dict[str, Any],
    sub_component: str = "",
) -> dict[str, Any]:
    """
    Check if the required documents are referenced in matched evidence.
    """
    found_docs = extracted.get("documents", [])
    raw_text = extracted.get("raw_text", "")

    # Normalize required_documents to a list
    if isinstance(required_documents, str):
        required_list = [d.strip() for d in required_documents.split(",") if d.strip()]
    elif isinstance(required_documents, list):
        required_list = [str(d).strip() for d in required_documents if d]
    else:
        required_list = []

    if not required_list:
        # No specific document required — if evidence exists, treat as present
        if found_docs or (raw_text and len(raw_text.strip()) > 10):
            return {
                "verdict": "PASS",
                "score": 1.0,
                "reason": "Document evidence present in submission.",
                "expected": "Document presence",
                "found": found_docs or [raw_text[:100]],
                "found_raw": raw_text,
            }
        return {
            "verdict": "NEEDS_MANUAL_REVIEW",
            "score": 0.0,
            "reason": "No document evidence found in submission.",
            "expected": "Document presence",
            "found": [],
            "found_raw": "",
        }

    # Check which required documents are found
    matched = []
    missing = []
    raw_lower = raw_text.lower()

    for req in required_list:
        req_lower = req.lower().strip()
        # Check in extracted documents list
        if any(req_lower in fd.lower() for fd in found_docs):
            matched.append(req)
        # Also check raw text for mentions
        elif req_lower in raw_lower:
            matched.append(req)
        else:
            missing.append(req)

    total = len(required_list)
    found_count = len(matched)
    score = found_count / total if total > 0 else 0.0

    if found_count == total:
        verdict = "PASS"
        reason = f"All {total} required documents found: {', '.join(matched)}"
    elif found_count > 0:
        verdict = "NEEDS_MANUAL_REVIEW"
        reason = f"{found_count}/{total} documents found. Missing: {', '.join(missing)}"
    else:
        verdict = "FAIL"
        reason = f"None of the required documents found. Missing: {', '.join(missing)}"

    return {
        "verdict": verdict,
        "score": score,
        "reason": reason,
        "expected": required_list,
        "found": matched,
        "missing": missing,
        "found_raw": raw_text,
    }
