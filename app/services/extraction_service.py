# -*- coding: utf-8 -*-
"""
Extraction Service — Structured value extraction from matched evidence text.

Normalizes raw text into structured numeric values, booleans, percentages,
currency amounts, document names, project counts, etc.
"""

from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Currency multipliers ──────────────────────────────────────────────────────

_MULTIPLIERS = {
    "lakh": 1_00_000,
    "lakhs": 1_00_000,
    "lac": 1_00_000,
    "lacs": 1_00_000,
    "crore": 1_00_00_000,
    "crores": 1_00_00_000,
    "cr": 1_00_00_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
    "thousand": 1_000,
    "k": 1_000,
}

_BOOLEAN_TRUE = {"yes", "true", "available", "compliant", "applicable", "valid", "registered", "certified", "submitted", "enclosed", "attached"}
_BOOLEAN_FALSE = {"no", "false", "not available", "not compliant", "not applicable", "na", "n/a", "nil", "none", "not submitted", "not enclosed"}

# Known document/certificate patterns
_DOCUMENT_PATTERNS = [
    r"\bGST\b", r"\bGSTIN\b", r"\bPAN\b", r"\bTAN\b",
    r"\bISO[\s\-]?\d{4,5}", r"\bBIS\b", r"\bFSSAI\b",
    r"\bPF\b", r"\bESI\b", r"\bEPF\b",
    r"\bMSME\b", r"\bUdyam\b", r"\bSSI\b",
    r"\bincorporation\s+certificate\b",
    r"\bregistration\s+certificate\b",
    r"\bsolvency\s+certificate\b",
    r"\bpower\s+of\s+attorney\b",
    r"\bboard\s+resolution\b",
    r"\bbalance\s+sheet\b", r"\baudited\b",
    r"\binsurance\b", r"\bindemnity\b",
    r"\bwork\s+order\b", r"\bcompletion\s+certificate\b",
    r"\bexperience\s+certificate\b",
]


def extract_amount(text: str) -> dict[str, Any] | None:
    """Extract numeric amount with optional currency multiplier."""
    if not text:
        return None

    # Pattern: number followed by optional multiplier
    pattern = r"(?:Rs\.?|INR|₹)?\s*(\d[\d,]*\.?\d*)\s*(lakh|lakhs|lac|lacs|crore|crores|cr|million|billion|thousand|k)?"
    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    results = []
    for num_str, unit in matches:
        try:
            num = float(num_str.replace(",", ""))
            multiplier = _MULTIPLIERS.get(unit.lower(), 1) if unit else 1
            results.append(num * multiplier)
        except (ValueError, AttributeError):
            continue

    if not results:
        return None

    # Return the largest amount found (most likely the relevant threshold)
    value = max(results)
    return {"value": value, "unit": "INR", "raw": text.strip()}


def extract_percentage(text: str) -> dict[str, Any] | None:
    """Extract percentage value."""
    if not text:
        return None
    match = re.search(r"(\d+\.?\d*)\s*%", text)
    if match:
        return {"value": float(match.group(1)), "unit": "%", "raw": text.strip()}
    return None


def extract_years(text: str) -> dict[str, Any] | None:
    """Extract year count."""
    if not text:
        return None
    match = re.search(r"(\d+)\s*(?:years?|yrs?)", text, re.IGNORECASE)
    if match:
        return {"value": int(match.group(1)), "unit": "years", "raw": text.strip()}
    return None


def extract_count(text: str) -> dict[str, Any] | None:
    """Extract a general numeric count (project count, etc.)."""
    if not text:
        return None
    match = re.search(r"(\d+)\s*(?:projects?|orders?|works?|nos?\.?|numbers?)?", text, re.IGNORECASE)
    if match:
        return {"value": int(match.group(1)), "unit": "count", "raw": text.strip()}
    return None


def extract_boolean(text: str) -> dict[str, Any] | None:
    """Extract boolean yes/no value."""
    if not text:
        return None
    lower = text.strip().lower()

    for word in _BOOLEAN_TRUE:
        if word in lower:
            return {"value": True, "raw": text.strip()}

    for word in _BOOLEAN_FALSE:
        if word in lower:
            return {"value": False, "raw": text.strip()}

    return None


def extract_documents(text: str) -> list[str]:
    """Extract document/certificate names from text."""
    if not text:
        return []
    found = []
    for pattern in _DOCUMENT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                found.append(match.group(0).strip())
    return found


def extract_structured_value(text: str, sub_component: str = "") -> dict[str, Any]:
    """
    Master extraction function. Tries all extractors and returns
    the best structured result based on the sub_component hint.
    """
    result: dict[str, Any] = {
        "amount": None,
        "percentage": None,
        "years": None,
        "count": None,
        "boolean": None,
        "documents": [],
        "raw_text": text,
    }

    if not text:
        return result

    result["amount"] = extract_amount(text)
    result["percentage"] = extract_percentage(text)
    result["years"] = extract_years(text)
    result["count"] = extract_count(text)
    result["boolean"] = extract_boolean(text)
    result["documents"] = extract_documents(text)

    return result
