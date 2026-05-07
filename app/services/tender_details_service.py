# -*- coding: utf-8 -*-
"""
Tender Details Service
======================
Business logic for the **Tender Details Page** API contract:

  - GET /tenders                                  → dropdown listing
  - GET /tenders/{tender_id}/details/meta         → header + tabs config
  - GET /tenders/{tender_id}/details/items        → tab-specific table data
  - GET /tenders/{tender_id}/pdf                  → PDF download

This module is intentionally pure (no FastAPI imports) so it can be tested
in isolation. Routes call into these helpers and translate domain errors
into HTTP responses.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.models.db import get_db
from app.utils.settings import settings


# ── Domain errors (mapped to HTTP at the route layer) ─────────────────────────


class TenderNotFoundError(Exception):
    """Raised when a tender_id has no record in MongoDB."""


class InvalidTabKeyError(Exception):
    """Raised when an unknown tab_key is requested."""


class PDFNotFoundError(Exception):
    """Raised when the on-disk PDF is missing for a known tender."""


# ── Status filtering ──────────────────────────────────────────────────────────

# Mapping of frontend status filter → set of internal pipeline statuses.
# - ACTIVE     : fully processed, ready for use
# - PROCESSING : in the middle of the ingest pipeline
# - FAILED     : pipeline aborted
# - ALL        : no filter
_STATUS_FILTER = {
    "ACTIVE": {"READY_FOR_SUBMISSIONS"},
    "PROCESSING": {
        "UPLOADED",
        "PARSING",
        "MERGING",
        "PARSED",
        "CANONICAL_GENERATING",
        "LLM_NORMALIZED",
        "INDEXING",
    },
    "FAILED": {"FAILED"},
}

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def _frontend_tender_status(internal_status: str | None) -> str:
    status = (internal_status or "").upper()
    if status == "READY_FOR_SUBMISSIONS":
        return "ACTIVE"
    if status == "FAILED":
        return "FAILED"
    return "PROCESSING"


# ── Tab → canonical category/sub-component map ────────────────────────────────
#
# Each tab pulls items from one or more canonical buckets. We support two
# levels of granularity:
#   - whole category   → take everything in canonical[category]
#   - category + subs  → only items whose sub_component is in the allowed set.
#
# The four tabs match the frontend contract exactly.

_TAB_CONFIG: dict[str, dict[str, Any]] = {
    "general_specs": {
        "label": "General Specs",
        "is_default": True,
        "sources": [
            {
                "category": "Technical Specifications",
                "sub_components": {"Product/Service Description", "Functional Requirements"},
            },
            {
                "category": "Commercial / Tender Terms",
                "sub_components": {"Bid Validity", "Contract Duration", "Delivery Timeline"},
            },
        ],
    },
    "technical_requirements": {
        "label": "Technical Requirements",
        "is_default": False,
        "sources": [
            {
                "category": "Technical Specifications",
                "sub_components": {
                    "Technical Parameters & Standards",
                    "Quality & Warranty",
                    "Design / Interoperability Constraints",
                    "Equipment / Infrastructure",
                    "Manpower / Personnel",
                },
            },
        ],
    },
    "financial_terms": {
        "label": "Financial Terms",
        "is_default": False,
        "sources": [
            {"category": "Financial Thresholds & Stability", "sub_components": None},
            {
                "category": "Commercial / Tender Terms",
                "sub_components": {
                    "EMD",
                    "Performance Bank Guarantee",
                    "Payment Terms",
                    "Penalty / Liquidated Damages",
                    "Cancellation / Termination Clause",
                },
            },
        ],
    },
    "compliance_details": {
        "label": "Compliance Details",
        "is_default": False,
        "sources": [
            {"category": "Legal & Compliance", "sub_components": None},
            {"category": "Experience & Capability", "sub_components": None},
        ],
    },
}


def _tabs_meta() -> list[dict[str, Any]]:
    """Public tabs payload — order is preserved from `_TAB_CONFIG` insertion."""
    return [
        {"tab_key": key, "tab_label": cfg["label"], "is_default": cfg["is_default"]}
        for key, cfg in _TAB_CONFIG.items()
    ]


# ── Internal helpers ──────────────────────────────────────────────────────────


def _format_due_date(canonical: dict[str, Any] | None) -> str | None:
    """Return ISO date (YYYY-MM-DD) of bid end if available."""
    if not canonical:
        return None
    fields = canonical.get("fields") or {}
    end_dt = fields.get("bid.end_date_time")
    if not end_dt:
        return None
    # Accept ISO strings or datetimes; trim time portion.
    if isinstance(end_dt, str):
        return end_dt.split("T", 1)[0]
    return str(end_dt)[:10]


def _category_from_canonical(canonical: dict[str, Any] | None) -> str | None:
    """
    Best-effort category label for the dropdown row.
    Picks the highest-confidence Technical Specification → Product/Service
    Description, falling back to the first non-empty technical item.
    """
    if not canonical:
        return None
    items = canonical.get("Technical Specifications") or []
    best: dict[str, Any] | None = None
    for it in items:
        if it.get("sub_component") == "Product/Service Description":
            if best is None or it.get("classification_confidence", 0) > best.get(
                "classification_confidence", 0
            ):
                best = it
    if best is None and items:
        best = items[0]
    if not best:
        return None
    text = (best.get("text_norm") or best.get("text_raw") or "").strip()
    return text[:80] if text else None


def _location_from_canonical(canonical: dict[str, Any] | None) -> str | None:
    """
    Best-effort location label. We don't yet extract a structured location
    field, so this returns None for now (frontend should render a dash).
    """
    if not canonical:
        return None
    fields = canonical.get("fields") or {}
    return fields.get("buyer.location") or fields.get("delivery.location") or None


def _build_tender_summary(tender_doc: dict[str, Any]) -> dict[str, Any]:
    """Shape used by both the list and the meta header (header is a superset)."""
    tender_id = tender_doc.get("_id") or tender_doc.get("tender_id")
    canonical = _get_canonical(tender_id) if tender_id else None
    return {
        "tender_id": tender_id,
        "tender_name": tender_doc.get("name") or tender_id,
        "reference": tender_doc.get("reference") or tender_id,
        "status": _frontend_tender_status(tender_doc.get("status")),
        "category": _category_from_canonical(canonical),
        "location": _location_from_canonical(canonical),
        "due_date": _format_due_date(canonical),
    }


def _get_canonical(tender_id: str) -> dict[str, Any] | None:
    db = get_db()
    return db.canonical_tenders.find_one({"tender_id": tender_id}, {"_id": 0})


# ── Item shaping (canonical → frontend table row) ─────────────────────────────


def _derive_spec_name_and_value(item: dict[str, Any]) -> tuple[str, str | None]:
    """
    Map canonical fields to the UI contract:
      - table rows      -> spec_name=key_norm, value_threshold=value_norm
      - non-table rows  -> spec_name=heading, value_threshold=text_norm

    Small fallbacks are kept so empty values don't break the UI.
    """
    source = item.get("source")
    heading = (item.get("heading") or "").strip()
    key = (item.get("key_norm") or "").strip()
    value = (item.get("value_norm") or "").strip()
    text = (item.get("text_norm") or item.get("text_raw") or "").strip()

    if source == "table":
        # Requested behavior: use key_norm/value_norm for table evidence.
        # Fallbacks avoid blanks when parser couldn't isolate key/value.
        name = key or heading or "Specification"
        return name[:120], (value or text or None)

    # Requested behavior for non-table evidence: heading + text_norm.
    name = heading or "Specification"
    return name[:120], (text or None)


def _round_confidence(item: dict[str, Any]) -> int:
    """Round to nearest integer percentage. Falls back to extractor confidence."""
    conf = item.get("classification_confidence")
    if conf is None:
        conf = item.get("confidence", 0.0)
    try:
        return max(0, min(100, int(round(float(conf) * 100))))
    except (TypeError, ValueError):
        return 0


def _shape_item(
    tender_id: str,
    index: int,
    item: dict[str, Any],
    api_base: str,
) -> dict[str, Any]:
    """Convert a canonical item into the frontend-facing row."""
    item_id = f"SPEC-{index:03d}"
    name, value = _derive_spec_name_and_value(item)
    description = (item.get("text_norm") or item.get("text_raw") or "").strip()
    return {
        "item_id": item_id,
        "spec_name": name,
        "spec_description": description,
        "value_threshold": value,
        "ai_confidence_percent": _round_confidence(item),
        "item_detail_url": f"{api_base}/tenders/{tender_id}/items/{item_id}",
    }


def _is_hindi_key_item(item: dict[str, Any]) -> bool:
    """
    Exclude items whose UI key/name field contains Hindi for now.
    - table rows: key is key_norm
    - non-table rows: key is heading
    """
    source = (item.get("source") or "").strip().lower()
    if source == "table":
        key_candidate = (item.get("key_norm") or "").strip()
    else:
        key_candidate = (item.get("heading") or "").strip()
    return bool(key_candidate and _DEVANAGARI_RE.search(key_candidate))


def _columns_for_tab() -> list[dict[str, str]]:
    """All tabs use the same column shape per the frontend contract."""
    return [
        {"key": "item_id", "label": "Item ID"},
        {"key": "spec_name", "label": "Specifications & Parameters"},
        {"key": "value_threshold", "label": "Value / Threshold"},
        {"key": "ai_confidence", "label": "AI Confidence"},
        {"key": "action", "label": "Action"},
    ]


def _collect_items_for_tab(
    canonical: dict[str, Any], tab_key: str
) -> list[dict[str, Any]]:
    """Pull canonical items matching the tab's source filter."""
    cfg = _TAB_CONFIG[tab_key]
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for source in cfg["sources"]:
        category = source["category"]
        allowed_subs: set[str] | None = source["sub_components"]
        bucket = canonical.get(category) or []
        for it in bucket:
            if allowed_subs is not None and it.get("sub_component") not in allowed_subs:
                continue
            ev_id = it.get("evidence_id")
            if ev_id and ev_id in seen_ids:
                continue
            if ev_id:
                seen_ids.add(ev_id)
            out.append(it)
    return out


def _filter_by_search(items: list[dict[str, Any]], search: str) -> list[dict[str, Any]]:
    if not search:
        return items
    needle = search.lower().strip()
    if not needle:
        return items
    return [
        it
        for it in items
        if needle in (it.get("text_norm") or "").lower()
        or needle in (it.get("key_norm") or "").lower()
        or needle in (it.get("value_norm") or "").lower()
        or needle in (it.get("sub_component") or "").lower()
    ]


# ── Public API ────────────────────────────────────────────────────────────────


def list_tenders(status: str, page: int, page_size: int) -> dict[str, Any]:
    """
    Paginated tender listing for the dropdown selector.
    """
    db = get_db()
    query: dict[str, Any] = {}
    status_upper = (status or "ALL").upper()
    if status_upper != "ALL":
        statuses = _STATUS_FILTER.get(status_upper)
        if not statuses:
            # Unknown status filter → 400 at the route layer.
            raise InvalidTabKeyError(f"Unknown status filter '{status}'.")
        query["status"] = {"$in": list(statuses)}

    total = db.tenders.count_documents(query)
    skip = (page - 1) * page_size
    cursor = (
        db.tenders.find(query)
        .sort("upload_timestamp", -1)
        .skip(max(skip, 0))
        .limit(page_size)
    )

    items = [_build_tender_summary(doc) for doc in cursor]
    return {
        "items": items,
        "total": total,
        "total_items": total,
        "page": page,
        "page_size": page_size,
    }


def get_meta(tender_id: str) -> dict[str, Any]:
    """Tender header + tab configuration for the details page."""
    db = get_db()
    doc = db.tenders.find_one({"_id": tender_id})
    if not doc:
        raise TenderNotFoundError(tender_id)

    tender = _build_tender_summary(doc)
    tender["download_pdf_url"] = f"{settings.api_base_url}/tenders/{tender_id}/pdf"

    return {"tender": tender, "tabs": _tabs_meta()}


def get_items(
    tender_id: str,
    tab_key: str,
    page: int,
    page_size: int,
    search: str = "",
) -> dict[str, Any]:
    """Table data for the active tab on the details page."""
    if tab_key not in _TAB_CONFIG:
        raise InvalidTabKeyError(
            f"Invalid tab_key '{tab_key}'. Allowed: {list(_TAB_CONFIG)}"
        )

    db = get_db()
    if not db.tenders.find_one({"_id": tender_id}, {"_id": 1}):
        raise TenderNotFoundError(tender_id)

    canonical = _get_canonical(tender_id) or {}
    raw_items = _collect_items_for_tab(canonical, tab_key)
    raw_items = [it for it in raw_items if not _is_hindi_key_item(it)]
    filtered = _filter_by_search(raw_items, search)

    total_items = len(filtered)
    total_pages = max(1, (total_items + page_size - 1) // page_size) if total_items else 0
    start = (page - 1) * page_size
    page_slice = filtered[start : start + page_size]

    shaped = [
        _shape_item(tender_id, start + idx + 1, raw, settings.api_base_url)
        for idx, raw in enumerate(page_slice)
    ]

    return {
        "tab_key": tab_key,
        "columns": _columns_for_tab(),
        "items": shaped,
        "pagination": {
            "total_items": total_items,
            "total_pages": total_pages,
            "page": page,
            "page_size": page_size,
        },
    }


def get_pdf_path(tender_id: str) -> Path:
    """Return absolute filesystem path of the original tender PDF."""
    db = get_db()
    doc = db.tenders.find_one({"_id": tender_id}, {"file_path": 1, "name": 1})
    if not doc:
        raise TenderNotFoundError(tender_id)

    file_path = doc.get("file_path")
    if not file_path:
        raise PDFNotFoundError(tender_id)

    p = Path(file_path)
    if not p.exists():
        raise PDFNotFoundError(tender_id)
    return p
