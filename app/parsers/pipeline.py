# -*- coding: utf-8 -*-
"""
Evidence pool pipeline.
Merges outputs from all four app-internal parsers into a unified
list of evidence dicts — no root-level imports.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.parsers.list_parser import parse_lists
from app.parsers.ocr_parser import parse_ocr
from app.parsers.paragraph_parser import parse_paragraphs
from app.parsers.table_parser import parse_tables


# ── EvidenceItem (mirrors evidence_pipeline.EvidenceItem) ────────────────────

def _uuid() -> str:
    return str(uuid.uuid4())


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


@dataclass
class EvidenceItem:
    evidence_id: str
    source: str
    kind: str
    page: int
    heading: str
    text_raw: str
    text_norm: str
    bbox: Optional[Tuple[float, float, float, float]] = None
    key_raw: Optional[str] = None
    key_norm: Optional[str] = None
    value_raw: Optional[str] = None
    value_norm: Optional[str] = None
    extractor_chunk_id: Optional[str] = None
    parent_chunk_id: Optional[str] = None
    position: Optional[int] = None
    confidence: float = 0.6


# ── Per-parser evidence converters ───────────────────────────────────────────

def _evidence_from_table_chunk(table_l0: Dict[str, Any]) -> List[EvidenceItem]:
    out: List[EvidenceItem] = []
    for l1 in table_l0.get("children") or []:
        md = l1.get("metadata") or {}
        page = int(md.get("page") or table_l0.get("metadata", {}).get("page") or 1)
        heading = str(md.get("heading") or table_l0.get("metadata", {}).get("heading") or table_l0.get("content") or "")
        key_raw = md.get("raw_key")
        key_norm = md.get("normalized_key")
        val_raw = md.get("raw_value")
        val_norm = md.get("normalized_value")
        text_raw = f"{key_raw}: {val_raw}"
        text_norm = f"{key_norm}: {val_norm}"
        out.append(
            EvidenceItem(
                evidence_id=_uuid(),
                source="table",
                kind="kv",
                page=page,
                heading=heading,
                text_raw=str(text_raw),
                text_norm=_norm_ws(str(text_norm)),
                key_raw=str(key_raw) if key_raw is not None else None,
                key_norm=str(key_norm) if key_norm is not None else None,
                value_raw=str(val_raw) if val_raw is not None else None,
                value_norm=str(val_norm) if val_norm is not None else None,
                extractor_chunk_id=l1.get("id"),
                parent_chunk_id=table_l0.get("id"),
                confidence=0.9,
            )
        )
    return out


def _evidence_from_paragraph_chunk(l0: Dict[str, Any]) -> List[EvidenceItem]:
    out: List[EvidenceItem] = []
    for l1 in l0.get("children") or []:
        for l2 in l1.get("children") or []:
            md = l2.get("metadata") or {}
            page = int(md.get("page") or 1)
            heading = str(md.get("heading") or l0.get("content") or "")
            position = md.get("position_in_paragraph")
            out.append(
                EvidenceItem(
                    evidence_id=_uuid(),
                    source="paragraph",
                    kind="sentence",
                    page=page,
                    heading=heading,
                    text_raw=str(l2.get("content") or ""),
                    text_norm=_norm_ws(str(md.get("normalized_text") or l2.get("content") or "")),
                    bbox=tuple((l1.get("metadata") or {}).get("bbox")) if (l1.get("metadata") or {}).get("bbox") else None,
                    extractor_chunk_id=l2.get("id"),
                    parent_chunk_id=l1.get("id"),
                    position=int(position) if position is not None else None,
                    confidence=0.7,
                )
            )
    return out


def _evidence_from_list_chunk(l0: Dict[str, Any]) -> List[EvidenceItem]:
    out: List[EvidenceItem] = []
    for l1 in l0.get("children") or []:
        for l2 in l1.get("children") or []:
            md = l2.get("metadata") or {}
            page = int(md.get("page") or 1)
            heading = str(md.get("heading") or l0.get("content") or "")
            position = md.get("position_in_list")
            out.append(
                EvidenceItem(
                    evidence_id=_uuid(),
                    source="list",
                    kind="bullet",
                    page=page,
                    heading=heading,
                    text_raw=str(l2.get("content") or ""),
                    text_norm=_norm_ws(str(md.get("normalized_text") or l2.get("content") or "")),
                    bbox=tuple((l1.get("metadata") or {}).get("bbox")) if (l1.get("metadata") or {}).get("bbox") else None,
                    extractor_chunk_id=l2.get("id"),
                    parent_chunk_id=l1.get("id"),
                    position=int(position) if position is not None else None,
                    confidence=0.8,
                )
            )
    return out


def _evidence_from_ocr_chunk(l0: Dict[str, Any]) -> List[EvidenceItem]:
    out: List[EvidenceItem] = []
    for l1 in l0.get("children") or []:
        for l2 in l1.get("children") or []:
            md = l2.get("metadata") or {}
            page = int(md.get("page") or 1)
            heading = str(md.get("heading") or l0.get("content") or "")
            position = md.get("position_in_block")
            out.append(
                EvidenceItem(
                    evidence_id=_uuid(),
                    source="ocr",
                    kind="ocr_sentence",
                    page=page,
                    heading=heading,
                    text_raw=str(l2.get("content") or ""),
                    text_norm=_norm_ws(str(md.get("normalized_text") or l2.get("content") or "")),
                    extractor_chunk_id=l2.get("id"),
                    parent_chunk_id=l1.get("id"),
                    position=int(position) if position is not None else None,
                    confidence=0.4,
                )
            )
    return out


# ── Public API ────────────────────────────────────────────────────────────────

def build_evidence_pool(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Run all four parsers and merge into a unified evidence pool.
    Returns a list of dicts (serialisable for MongoDB / JSON).
    """
    pool: List[EvidenceItem] = []

    # Table parser
    for table_l0 in parse_tables(pdf_path):
        pool.extend(_evidence_from_table_chunk(table_l0))

    # Paragraph parser
    for l0 in parse_paragraphs(pdf_path):
        pool.extend(_evidence_from_paragraph_chunk(l0))

    # List parser
    for l0 in parse_lists(pdf_path):
        pool.extend(_evidence_from_list_chunk(l0))

    # OCR parser (fault-isolated)
    try:
        for l0 in parse_ocr(pdf_path):
            pool.extend(_evidence_from_ocr_chunk(l0))
    except Exception:
        pass  # OCR is optional; proceed without it if it fails

    return [asdict(ev) for ev in pool]
