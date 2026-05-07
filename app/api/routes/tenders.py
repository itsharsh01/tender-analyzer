# -*- coding: utf-8 -*-
"""
Tender Details Page API
=======================
Implements the frontend `Tender Details Page` contract:

  GET /tenders                                  → dropdown listing
  GET /tenders/{tender_id}/details/meta         → header + tabs
  GET /tenders/{tender_id}/details/items        → tab table data
  GET /tenders/{tender_id}/pdf                  → original PDF stream

All routes require `Authorization: Bearer <JWT>` (enforced by global
JWTAuthMiddleware) and return errors in `{"detail": "..."}` form.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.services.tender_details_service import (
    InvalidTabKeyError,
    PDFNotFoundError,
    TenderNotFoundError,
    get_items,
    get_meta,
    get_pdf_path,
    list_tenders,
)

router = APIRouter(prefix="/tenders", tags=["tenders"])


# ── 1) Dropdown listing ───────────────────────────────────────────────────────


@router.get("")
def list_tenders_route(
    status: str = Query("ACTIVE", description="ACTIVE | PROCESSING | FAILED | ALL"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    """Paginated list of tenders for the dropdown selector."""
    try:
        return list_tenders(status=status, page=page, page_size=page_size)
    except InvalidTabKeyError as exc:
        # Re-used domain error for "unknown status" → 400 per contract.
        raise HTTPException(status_code=400, detail=str(exc))


# ── 2) Tender header + tabs ───────────────────────────────────────────────────


@router.get("/{tender_id}/details/meta")
def tender_meta_route(tender_id: str) -> dict:
    """Header info and tabs configuration for the details page."""
    try:
        return get_meta(tender_id)
    except TenderNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tender '{tender_id}' not found.")


# ── 3) Tab-specific item table ────────────────────────────────────────────────


@router.get("/{tender_id}/details/items")
def tender_items_route(
    tender_id: str,
    tab_key: str = Query(..., description="Tab key returned by /details/meta"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str = Query("", description="Optional case-insensitive text filter"),
) -> dict:
    """Paginated table data for the active tab."""
    try:
        return get_items(
            tender_id=tender_id,
            tab_key=tab_key,
            page=page,
            page_size=page_size,
            search=search,
        )
    except TenderNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tender '{tender_id}' not found.")
    except InvalidTabKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── 4) PDF download ───────────────────────────────────────────────────────────


@router.get("/{tender_id}/pdf")
def tender_pdf_route(tender_id: str) -> FileResponse:
    """Stream the original tender PDF as a binary download."""
    try:
        path = get_pdf_path(tender_id)
    except TenderNotFoundError:
        raise HTTPException(status_code=404, detail=f"Tender '{tender_id}' not found.")
    except PDFNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"PDF for tender '{tender_id}' is missing on disk.",
        )

    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=path.name,
    )
