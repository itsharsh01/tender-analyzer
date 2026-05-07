# -*- coding: utf-8 -*-
"""
Numeric Evaluator — Compares numeric submission values against canonical thresholds.

Handles: turnover, net worth, solvency, percentages, contract values.
"""

from __future__ import annotations

from typing import Any

from app.services.extraction_service import extract_amount, extract_percentage


def evaluate(
    expected_value: Any,
    operator: str,
    extracted: dict[str, Any],
    sub_component: str = "",
) -> dict[str, Any]:
    """
    Compare extracted numeric value against expected threshold.

    Returns:
        {"verdict": "PASS|FAIL|NEEDS_MANUAL_REVIEW", "score": float, ...}
    """
    # Determine which extracted value to use
    found_value = None
    found_raw = ""

    # Try amount first (most common for financial)
    if extracted.get("amount"):
        found_value = extracted["amount"]["value"]
        found_raw = extracted["amount"].get("raw", "")
    elif extracted.get("percentage"):
        found_value = extracted["percentage"]["value"]
        found_raw = extracted["percentage"].get("raw", "")
    elif extracted.get("count"):
        found_value = extracted["count"]["value"]
        found_raw = extracted["count"].get("raw", "")

    if found_value is None:
        return {
            "verdict": "NEEDS_MANUAL_REVIEW",
            "score": 0.0,
            "reason": "Could not extract numeric value from submission evidence.",
            "expected": expected_value,
            "found": None,
            "found_raw": "",
        }

    # Normalize expected value
    try:
        if isinstance(expected_value, str):
            # Try to parse expected_value as amount
            parsed = extract_amount(expected_value)
            if parsed:
                expected_num = parsed["value"]
            else:
                expected_num = float(expected_value.replace(",", ""))
        else:
            expected_num = float(expected_value)
    except (ValueError, TypeError):
        return {
            "verdict": "NEEDS_MANUAL_REVIEW",
            "score": 0.0,
            "reason": f"Cannot parse expected value: {expected_value}",
            "expected": expected_value,
            "found": found_value,
            "found_raw": found_raw,
        }

    # Compare using operator
    op = (operator or ">=").strip()
    passed = False

    if op in (">=", "≥"):
        passed = found_value >= expected_num
    elif op in ("<=", "≤"):
        passed = found_value <= expected_num
    elif op in ("==", "="):
        passed = abs(found_value - expected_num) < 0.01
    elif op == ">":
        passed = found_value > expected_num
    elif op == "<":
        passed = found_value < expected_num
    else:
        passed = found_value >= expected_num  # Default to >=

    return {
        "verdict": "PASS" if passed else "FAIL",
        "score": 1.0 if passed else 0.0,
        "reason": f"{'Met' if passed else 'Did not meet'} threshold: found {found_value} {op} {expected_num}",
        "expected": expected_num,
        "found": found_value,
        "found_raw": found_raw,
    }
