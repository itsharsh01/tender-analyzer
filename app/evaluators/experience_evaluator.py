# -*- coding: utf-8 -*-
"""
Experience Evaluator — Checks experience requirements.

Handles: years of existence, project count, project value thresholds.
"""

from __future__ import annotations

from typing import Any

from app.services.extraction_service import extract_amount, extract_years, extract_count


def evaluate(
    expected_value: Any,
    operator: str,
    extracted: dict[str, Any],
    sub_component: str = "",
) -> dict[str, Any]:
    """
    Evaluate experience-related criteria.
    """
    sub_lower = sub_component.lower() if sub_component else ""

    # Determine what type of experience to check
    if "year" in sub_lower or "existence" in sub_lower:
        return _evaluate_years(expected_value, operator, extracted)
    elif "project value" in sub_lower or "value threshold" in sub_lower:
        return _evaluate_project_value(expected_value, operator, extracted)
    elif "project" in sub_lower or "similar" in sub_lower:
        return _evaluate_project_count(expected_value, operator, extracted)
    else:
        # Generic experience check — try years first, then count, then amount
        if extracted.get("years"):
            return _evaluate_years(expected_value, operator, extracted)
        elif extracted.get("count"):
            return _evaluate_project_count(expected_value, operator, extracted)
        elif extracted.get("amount"):
            return _evaluate_project_value(expected_value, operator, extracted)
        else:
            return {
                "verdict": "NEEDS_MANUAL_REVIEW",
                "score": 0.0,
                "reason": "Could not extract experience data from submission.",
                "expected": expected_value,
                "found": None,
                "found_raw": extracted.get("raw_text", ""),
            }


def _evaluate_years(expected_value: Any, operator: str, extracted: dict[str, Any]) -> dict[str, Any]:
    years_data = extracted.get("years")
    if not years_data:
        return {
            "verdict": "NEEDS_MANUAL_REVIEW",
            "score": 0.0,
            "reason": "Could not extract years from submission evidence.",
            "expected": expected_value,
            "found": None,
            "found_raw": extracted.get("raw_text", ""),
        }

    found = years_data["value"]
    try:
        expected = int(expected_value) if expected_value else 0
    except (ValueError, TypeError):
        parsed = extract_years(str(expected_value))
        expected = parsed["value"] if parsed else 0

    op = (operator or ">=").strip()
    passed = _compare(found, expected, op)

    return {
        "verdict": "PASS" if passed else "FAIL",
        "score": 1.0 if passed else 0.0,
        "reason": f"{'Met' if passed else 'Did not meet'} experience: {found} years {op} {expected} years",
        "expected": expected,
        "found": found,
        "found_raw": years_data.get("raw", ""),
    }


def _evaluate_project_count(expected_value: Any, operator: str, extracted: dict[str, Any]) -> dict[str, Any]:
    count_data = extracted.get("count")
    if not count_data:
        return {
            "verdict": "NEEDS_MANUAL_REVIEW",
            "score": 0.0,
            "reason": "Could not extract project count from submission evidence.",
            "expected": expected_value,
            "found": None,
            "found_raw": extracted.get("raw_text", ""),
        }

    found = count_data["value"]
    try:
        expected = int(expected_value) if expected_value else 0
    except (ValueError, TypeError):
        parsed = extract_count(str(expected_value))
        expected = parsed["value"] if parsed else 0

    op = (operator or ">=").strip()
    passed = _compare(found, expected, op)

    return {
        "verdict": "PASS" if passed else "FAIL",
        "score": 1.0 if passed else 0.0,
        "reason": f"{'Met' if passed else 'Did not meet'} requirement: {found} projects {op} {expected}",
        "expected": expected,
        "found": found,
        "found_raw": count_data.get("raw", ""),
    }


def _evaluate_project_value(expected_value: Any, operator: str, extracted: dict[str, Any]) -> dict[str, Any]:
    amount_data = extracted.get("amount")
    if not amount_data:
        return {
            "verdict": "NEEDS_MANUAL_REVIEW",
            "score": 0.0,
            "reason": "Could not extract project value from submission evidence.",
            "expected": expected_value,
            "found": None,
            "found_raw": extracted.get("raw_text", ""),
        }

    found = amount_data["value"]
    try:
        if isinstance(expected_value, str):
            parsed = extract_amount(expected_value)
            expected = parsed["value"] if parsed else float(expected_value.replace(",", ""))
        else:
            expected = float(expected_value) if expected_value else 0
    except (ValueError, TypeError):
        expected = 0

    op = (operator or ">=").strip()
    passed = _compare(found, expected, op)

    return {
        "verdict": "PASS" if passed else "FAIL",
        "score": 1.0 if passed else 0.0,
        "reason": f"{'Met' if passed else 'Did not meet'} value threshold: {found} INR {op} {expected} INR",
        "expected": expected,
        "found": found,
        "found_raw": amount_data.get("raw", ""),
    }


def _compare(found: float, expected: float, op: str) -> bool:
    if op in (">=", "≥"):
        return found >= expected
    elif op in ("<=", "≤"):
        return found <= expected
    elif op in ("==", "="):
        return abs(found - expected) < 0.01
    elif op == ">":
        return found > expected
    elif op == "<":
        return found < expected
    return found >= expected
