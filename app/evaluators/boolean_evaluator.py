# -*- coding: utf-8 -*-
"""
Boolean Evaluator — Checks yes/no compliance declarations.

Handles: mandatory compliance, declarations, undertakings.
"""

from __future__ import annotations

from typing import Any


def evaluate(
    expected_value: Any,
    extracted: dict[str, Any],
    sub_component: str = "",
) -> dict[str, Any]:
    """
    Check if submission has a boolean compliance (yes/no/present).
    """
    boolean_result = extracted.get("boolean")

    if boolean_result is None:
        # Check if any text is present (sometimes just presence = compliance)
        raw_text = extracted.get("raw_text", "")
        if raw_text and len(raw_text.strip()) > 10:
            return {
                "verdict": "NEEDS_MANUAL_REVIEW",
                "score": 0.5,
                "reason": "Evidence text found but could not extract a clear yes/no. Manual verification needed.",
                "expected": True,
                "found": None,
                "found_raw": raw_text,
            }
        return {
            "verdict": "NEEDS_MANUAL_REVIEW",
            "score": 0.0,
            "reason": "No boolean compliance value found in submission evidence.",
            "expected": True,
            "found": None,
            "found_raw": "",
        }

    found = boolean_result["value"]

    # Expected is typically True (must comply)
    expected = True
    if isinstance(expected_value, bool):
        expected = expected_value
    elif isinstance(expected_value, str):
        expected = expected_value.lower() not in ("no", "false", "not required")

    passed = found == expected

    return {
        "verdict": "PASS" if passed else "FAIL",
        "score": 1.0 if passed else 0.0,
        "reason": f"{'Compliant' if passed else 'Non-compliant'}: found '{found}', expected '{expected}'",
        "expected": expected,
        "found": found,
        "found_raw": boolean_result.get("raw", ""),
    }
