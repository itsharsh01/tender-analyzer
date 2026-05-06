# -*- coding: utf-8 -*-
"""
End-to-end pipeline:
  Table extractor
  Paragraph extractor
  List extractor
  OCR extractor
        ↓
  Unified evidence pool
        ↓
  Field matching / merge
        ↓
  Final canonical tender schema

This is a production-oriented *baseline* implementation:
- Evidence is stored with provenance + linking to the extractor chunk ids.
- Field matching is rule/regex-based and intentionally conservative.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
import argparse
import json
import re
import uuid

# Extractors (already in this repo)
import chunking as table_chunker
import paragraph_chunking as paragraph_chunker
import list_chunking as list_chunker
import ocr_chunking as ocr_chunker


def _uuid() -> str:
    return str(uuid.uuid4())


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


@dataclass
class EvidenceItem:
    evidence_id: str
    source: str  # table|paragraph|list|ocr
    kind: str  # kv|sentence|bullet|ocr_sentence
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


def _iter_chunks(tree: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        for c in reversed(node.get("children") or []):
            stack.append(c)


def evidence_from_table_chunks(table_l0: Dict[str, Any]) -> List[EvidenceItem]:
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


def evidence_from_paragraph_chunks(l0: Dict[str, Any]) -> List[EvidenceItem]:
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


def evidence_from_list_chunks(l0: Dict[str, Any]) -> List[EvidenceItem]:
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


def evidence_from_ocr_chunks(l0: Dict[str, Any]) -> List[EvidenceItem]:
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


def build_evidence_pool(pdf_path: str) -> List[EvidenceItem]:
    pool: List[EvidenceItem] = []

    # Table
    tables = table_chunker.extract_tables(pdf_path)
    for i, table in enumerate(tables):
        l0 = table_chunker.build_table_chunks(table["rows"], heading=f"Table_{i + 1}", page_no=table["page"]).to_dict()
        pool.extend(evidence_from_table_chunks(l0))

    # Paragraph
    p_blocks = paragraph_chunker.extract_paragraph_blocks(pdf_path)
    for l0 in paragraph_chunker.build_paragraph_chunks(p_blocks):
        pool.extend(evidence_from_paragraph_chunks(l0.to_dict()))

    # List
    t_blocks = list_chunker.extract_text_blocks(pdf_path)
    for l0 in list_chunker.build_list_chunks(t_blocks):
        pool.extend(evidence_from_list_chunks(l0.to_dict()))

    # OCR (may return none)
    ocr_blocks = ocr_chunker.extract_ocr_blocks(
        pdf_path, engine="pytesseract", zoom=2.0, lang="eng", min_text_chars=200
    )
    if ocr_blocks:
        for l0 in ocr_chunker.build_ocr_chunks(ocr_blocks):
            pool.extend(evidence_from_ocr_chunks(l0.to_dict()))

    return pool


# -----------------------------
# Field matching / merge
# -----------------------------

_DT_RE = re.compile(r"\b(\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}:\d{2})\b")


def _parse_dt(s: str) -> Optional[str]:
    m = _DT_RE.search(s or "")
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%d-%m-%Y %H:%M:%S")
        return dt.isoformat()
    except Exception:
        return None


def _parse_int_days(s: str) -> Optional[int]:
    m = re.search(r"\b(\d{1,4})\b", s or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _score_source(src: str) -> int:
    return {"table": 4, "list": 3, "paragraph": 2, "ocr": 1}.get(src, 0)


def choose_best(candidates: List[Tuple[EvidenceItem, Any]]) -> Optional[Tuple[EvidenceItem, Any]]:
    if not candidates:
        return None

    def key_fn(item: Tuple[EvidenceItem, Any]):
        ev, parsed = item
        return (_score_source(ev.source), ev.confidence, -(ev.page or 0))

    return sorted(candidates, key=key_fn, reverse=True)[0]


def _dedupe_requirements(reqs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for req in reqs:
        key = (req.get("type"), _norm_ws(str(req.get("text", "")).lower()))
        if key in seen:
            continue
        seen.add(key)
        out.append(req)
    return out


def _make_req(req_type: str, ev: EvidenceItem, text: str, **extra: Any) -> Dict[str, Any]:
    payload = {
        "type": req_type,
        "text": _norm_ws(text),
        "page": ev.page,
        "heading": ev.heading,
        "source": ev.source,
        "evidence_ids": [ev.evidence_id],
    }
    payload.update(extra)
    return payload


def _extract_money(text: str) -> Optional[Dict[str, Any]]:
    t = text or ""
    m = re.search(
        r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(crore|cr|lakh|lakhs|million|billion)?",
        t,
        flags=re.I,
    )
    if not m:
        return None
    amount = float(m.group(1))
    unit = (m.group(2) or "").lower()
    multiplier = 1.0
    if unit in {"crore", "cr"}:
        multiplier = 10_000_000.0
    elif unit in {"lakh", "lakhs"}:
        multiplier = 100_000.0
    elif unit == "million":
        multiplier = 1_000_000.0
    elif unit == "billion":
        multiplier = 1_000_000_000.0
    return {
        "amount_value": amount,
        "amount_unit": unit or None,
        "amount_inr_estimate": int(amount * multiplier),
        "currency": "INR",
    }


def _contains_any(text: str, words: List[str]) -> bool:
    t = (text or "").lower()
    return any(w in t for w in words)


def _quality_ok(text: str) -> bool:
    t = _norm_ws(text)
    if len(t) < 8:
        return False
    if t.lower() in {"*", "-", "--", "na", "n/a", "no", "yes"}:
        return False
    if t.lower().count("cid") >= 2:
        return False
    alpha = sum(ch.isalpha() for ch in t)
    if alpha == 0:
        return False
    return True


def _heading_bonus(ev: EvidenceItem, target: str) -> float:
    h = (ev.heading or "").lower()
    if target == "financial" and _contains_any(h, ["financial", "turnover", "price", "emd", "cost"]):
        return 0.2
    if target == "technical" and _contains_any(h, ["technical", "specification", "quality", "warranty"]):
        return 0.2
    if target == "experience" and _contains_any(h, ["experience", "past performance", "eligibility"]):
        return 0.2
    if target == "legal" and _contains_any(h, ["document", "compliance", "certificate", "legal"]):
        return 0.2
    if target == "bid_dates" and _contains_any(h, ["bid details", "critical dates", "schedule"]):
        return 0.2
    return 0.0


def _best_with_context(
    candidates: List[Tuple[EvidenceItem, Any]],
    *,
    target: str,
) -> Optional[Tuple[EvidenceItem, Any]]:
    if not candidates:
        return None

    def key_fn(item: Tuple[EvidenceItem, Any]):
        ev, _ = item
        score = ev.confidence + _heading_bonus(ev, target)
        return (_score_source(ev.source), score, -(ev.page or 0))

    return sorted(candidates, key=key_fn, reverse=True)[0]


def _extract_iso_codes(text: str) -> List[str]:
    t = text or ""
    codes = re.findall(r"\biso\s*[-:]?\s*(\d{4,5})\b", t, flags=re.I)
    out = [f"ISO {c}" for c in codes]
    if re.search(r"\bohsas\b", t, flags=re.I):
        out.append("OHSAS")
    return sorted(set(out))


def _extract_company_docs(text: str) -> List[str]:
    t = (text or "").lower()
    mapping = {
        "certificate_of_incorporation": ["certificate of incorporation", "incorporation certificate"],
        "memorandum_and_articles": ["memorandum", "articles of association", "moa", "aoa"],
        "pan_card": ["pan"],
        "gst_certificate": ["gst certificate", "gst registration", "gstin"],
        "msme_udyam_registration": ["msme", "udyam"],
    }
    out: List[str] = []
    for k, keys in mapping.items():
        if any(s in t for s in keys):
            out.append(k)
    return out


def _extract_financial_docs(text: str) -> List[str]:
    t = (text or "").lower()
    mapping = {
        "audited_balance_sheet": ["audited balance sheet", "balance sheet"],
        "profit_and_loss_statement": ["profit and loss", "p&l"],
        "bank_solvency_certificate": ["bank solvency", "comfort letter"],
        "auditor_certificate": ["auditor certificate", "chartered accountant", "cost accountant"],
    }
    out: List[str] = []
    for k, keys in mapping.items():
        if any(s in t for s in keys):
            out.append(k)
    return out


def _extract_experience_docs(text: str) -> List[str]:
    t = (text or "").lower()
    mapping = {
        "completion_certificate": ["completion certificate"],
        "experience_certificate": ["experience certificate"],
        "work_order": ["work order"],
        "noc": ["noc", "no objection"],
        "contract_copy": ["contract", "relevant contracts"],
    }
    out: List[str] = []
    for k, keys in mapping.items():
        if any(s in t for s in keys):
            out.append(k)
    return out


def _extract_statutory_docs(text: str) -> List[str]:
    t = (text or "").lower()
    mapping = {
        "income_tax_clearance": ["income-tax", "income tax clearance"],
        "pf_compliance": ["pf"],
        "esi_compliance": ["esi"],
        "gst_compliance": ["gst compliance"],
        "insurance_certificate": ["insurance"],
    }
    out: List[str] = []
    for k, keys in mapping.items():
        if any(s in t for s in keys):
            out.append(k)
    return out


def match_fields(pool: List[EvidenceItem]) -> Dict[str, Any]:
    """
    Minimal canonical schema (expand as you add matchers):
      - bid.end_date_time
      - bid.opening_date_time
      - bid.offer_validity_days
    """
    out: Dict[str, Any] = {
        "fields": {},
        "evidence": {},
        "technical_specifications": {"items": []},
        "financial_criteria": {
            "turnover_requirements": [],
            "net_worth_requirements": [],
            "contract_value_ratio_rules": [],
            "price_rules": [],
        },
        "experience_criteria": {
            "minimum_years_existence": [],
            "similar_projects": [],
            "project_value_thresholds": [],
            "geographic_or_sector_experience": [],
            "key_personnel_requirements": [],
            "equipment_infrastructure_requirements": [],
        },
        "legal_and_compliance": {
            "company_documents": [],
            "financial_documents": [],
            "experience_related_documents": [],
            "statutory_compliance_certificates": [],
            "quality_safety_certifications": [],
        },
        "unmapped_requirements": [],
    }

    # Bid End Date/Time
    end_candidates: List[Tuple[EvidenceItem, str]] = []
    for ev in pool:
        blob = f"{ev.key_norm or ''} {ev.text_norm}"
        if re.search(r"\bbid\s*end\s*date", blob, re.I):
            parsed = _parse_dt(ev.value_norm or ev.text_norm)
            if parsed:
                end_candidates.append((ev, parsed))
    chosen = _best_with_context(end_candidates, target="bid_dates")
    if chosen:
        ev, parsed = chosen
        out["fields"]["bid.end_date_time"] = parsed
        out["evidence"]["bid.end_date_time"] = [ev.evidence_id]

    # Bid Opening Date/Time
    open_candidates: List[Tuple[EvidenceItem, str]] = []
    for ev in pool:
        blob = f"{ev.key_norm or ''} {ev.text_norm}"
        if re.search(r"\bbid\s*opening\s*date", blob, re.I):
            parsed = _parse_dt(ev.value_norm or ev.text_norm)
            if parsed:
                open_candidates.append((ev, parsed))
    chosen = _best_with_context(open_candidates, target="bid_dates")
    if chosen:
        ev, parsed = chosen
        out["fields"]["bid.opening_date_time"] = parsed
        out["evidence"]["bid.opening_date_time"] = [ev.evidence_id]

    # Bid Offer Validity (Days)
    validity_candidates: List[Tuple[EvidenceItem, int]] = []
    for ev in pool:
        blob = f"{ev.key_norm or ''} {ev.text_norm}"
        if re.search(r"\boffer\s*validity\b", blob, re.I) or re.search(r"\bbid\s*offer\s*validity\b", blob, re.I):
            val = _parse_int_days(ev.value_norm or ev.text_norm)
            if val:
                validity_candidates.append((ev, val))
    chosen = _best_with_context(validity_candidates, target="financial")
    if chosen:
        ev, parsed = chosen
        out["fields"]["bid.offer_validity_days"] = parsed
        out["evidence"]["bid.offer_validity_days"] = [ev.evidence_id]

    # Rich canonical classification from unified evidence pool
    for ev in pool:
        blob = _norm_ws(f"{ev.heading} {ev.key_norm or ''} {ev.text_norm}")
        blob_l = blob.lower()
        if not _quality_ok(ev.text_norm):
            continue

        # 1) Technical specifications
        if _contains_any(
            blob_l,
            [
                "model",
                "version",
                "quantity",
                "functional requirement",
                "workflow",
                "integration",
                "sla",
                "technical",
                "specification",
                "standard",
                "iso",
                "warranty",
                "amc",
                "interoperability",
                "api",
                "protocol",
                "platform",
            ],
        ):
            req_type = "technical_requirement"
            if _contains_any(blob_l, ["warranty", "amc", "defect liability", "repair timeline"]):
                req_type = "quality_warranty"
            elif _contains_any(blob_l, ["iso", "standard", "safety"]):
                req_type = "technical_parameter_standard"
            elif _contains_any(blob_l, ["api", "protocol", "interoperability", "platform"]):
                req_type = "design_interoperability_constraint"
            elif _contains_any(blob_l, ["functional requirement", "workflow", "integration", "sla"]):
                req_type = "functional_requirement"
            elif _contains_any(blob_l, ["quantity", "model", "version", "product", "service"]):
                req_type = "product_service_description"
            out["technical_specifications"]["items"].append(
                _make_req(
                    req_type,
                    ev,
                    ev.text_norm,
                    confidence=round(ev.confidence + _heading_bonus(ev, "technical"), 3),
                )
            )
            continue

        # 2) Financial thresholds and stability criteria
        if _contains_any(blob_l, ["turnover"]):
            money = _extract_money(blob_l) or {}
            yrs_m = re.search(r"last\s+(\d+)\s+year", blob_l)
            out["financial_criteria"]["turnover_requirements"].append(
                _make_req(
                    "minimum_turnover",
                    ev,
                    ev.text_norm,
                    period_years=int(yrs_m.group(1)) if yrs_m else None,
                    confidence=round(ev.confidence + _heading_bonus(ev, "financial"), 3),
                    **money,
                )
            )
            continue

        if _contains_any(blob_l, ["net worth", "profitability", "profitable"]):
            out["financial_criteria"]["net_worth_requirements"].append(
                _make_req(
                    "net_worth_profitability",
                    ev,
                    ev.text_norm,
                    confidence=round(ev.confidence + _heading_bonus(ev, "financial"), 3),
                    **(_extract_money(blob_l) or {}),
                )
            )
            continue

        if _contains_any(blob_l, ["1.5x", "ratio", "contract value", "cumulative value"]):
            ratio_m = re.search(r"(\d+(?:\.\d+)?)\s*x", blob_l)
            out["financial_criteria"]["contract_value_ratio_rules"].append(
                _make_req(
                    "contract_value_ratio",
                    ev,
                    ev.text_norm,
                    ratio=float(ratio_m.group(1)) if ratio_m else None,
                    confidence=round(ev.confidence + _heading_bonus(ev, "financial"), 3),
                )
            )
            continue

        if _contains_any(blob_l, ["lowest bid", "l1", "weighted", "technical", "price"]):
            out["financial_criteria"]["price_rules"].append(
                _make_req(
                    "price_evaluation_rule",
                    ev,
                    ev.text_norm,
                    confidence=round(ev.confidence + _heading_bonus(ev, "financial"), 3),
                )
            )
            continue

        # 3) Experience and technical capability
        if _contains_any(blob_l, ["years of existence", "company age", "less than 3 year", "operational history"]):
            yr = _parse_int_days(blob_l)
            out["experience_criteria"]["minimum_years_existence"].append(
                _make_req(
                    "minimum_years_existence",
                    ev,
                    ev.text_norm,
                    years=yr,
                    confidence=round(ev.confidence + _heading_bonus(ev, "experience"), 3),
                )
            )
            continue

        if _contains_any(blob_l, ["similar project", "projects", "past performance", "completed contract"]):
            count_m = re.search(r"at least\s+(\d+)\s+project", blob_l)
            yrs_m = re.search(r"last\s+(\d+)\s+year", blob_l)
            out["experience_criteria"]["similar_projects"].append(
                _make_req(
                    "similar_projects_completed",
                    ev,
                    ev.text_norm,
                    min_project_count=int(count_m.group(1)) if count_m else None,
                    period_years=int(yrs_m.group(1)) if yrs_m else None,
                    confidence=round(ev.confidence + _heading_bonus(ev, "experience"), 3),
                    **(_extract_money(blob_l) or {}),
                )
            )
            continue

        if _contains_any(blob_l, ["project value", "contract value threshold", "value of contract"]):
            out["experience_criteria"]["project_value_thresholds"].append(
                _make_req(
                    "project_value_threshold",
                    ev,
                    ev.text_norm,
                    confidence=round(ev.confidence + _heading_bonus(ev, "experience"), 3),
                    **(_extract_money(blob_l) or {}),
                )
            )
            continue

        if _contains_any(blob_l, ["sector", "defence", "geographic", "state govt", "central govt"]):
            out["experience_criteria"]["geographic_or_sector_experience"].append(
                _make_req(
                    "geographic_sector_experience",
                    ev,
                    ev.text_norm,
                    confidence=round(ev.confidence + _heading_bonus(ev, "experience"), 3),
                )
            )
            continue

        if _contains_any(blob_l, ["key personnel", "engineer", "doctor", "project manager", "manpower"]):
            out["experience_criteria"]["key_personnel_requirements"].append(
                _make_req(
                    "key_personnel_manpower",
                    ev,
                    ev.text_norm,
                    confidence=round(ev.confidence + _heading_bonus(ev, "experience"), 3),
                )
            )
            continue

        if _contains_any(blob_l, ["equipment", "infrastructure", "fleet", "vehicle", "hardware"]):
            out["experience_criteria"]["equipment_infrastructure_requirements"].append(
                _make_req(
                    "equipment_infrastructure",
                    ev,
                    ev.text_norm,
                    confidence=round(ev.confidence + _heading_bonus(ev, "experience"), 3),
                )
            )
            continue

        # 4) Legal and compliance conditions
        if _contains_any(blob_l, ["incorporation", "memorandum", "articles", "pan", "gst", "msme", "udyam"]):
            doc_types = _extract_company_docs(blob_l)
            out["legal_and_compliance"]["company_documents"].append(
                _make_req(
                    "company_document",
                    ev,
                    ev.text_norm,
                    document_types=doc_types,
                    confidence=round(ev.confidence + _heading_bonus(ev, "legal"), 3),
                )
            )
            continue

        if _contains_any(blob_l, ["audited balance sheet", "profit and loss", "solvency", "auditor"]):
            doc_types = _extract_financial_docs(blob_l)
            out["legal_and_compliance"]["financial_documents"].append(
                _make_req(
                    "financial_document",
                    ev,
                    ev.text_norm,
                    document_types=doc_types,
                    confidence=round(ev.confidence + _heading_bonus(ev, "legal"), 3),
                )
            )
            continue

        if _contains_any(blob_l, ["completion certificate", "experience certificate", "work order", "noc"]):
            doc_types = _extract_experience_docs(blob_l)
            out["legal_and_compliance"]["experience_related_documents"].append(
                _make_req(
                    "experience_related_document",
                    ev,
                    ev.text_norm,
                    document_types=doc_types,
                    confidence=round(ev.confidence + _heading_bonus(ev, "legal"), 3),
                )
            )
            continue

        if _contains_any(blob_l, ["income-tax", "pf", "esi", "insurance", "gst compliance"]):
            doc_types = _extract_statutory_docs(blob_l)
            out["legal_and_compliance"]["statutory_compliance_certificates"].append(
                _make_req(
                    "statutory_compliance",
                    ev,
                    ev.text_norm,
                    document_types=doc_types,
                    confidence=round(ev.confidence + _heading_bonus(ev, "legal"), 3),
                )
            )
            continue

        if _contains_any(blob_l, ["iso 9001", "iso 27001", "iso 14001", "ohsas", "quality certification"]):
            iso_codes = _extract_iso_codes(blob_l)
            out["legal_and_compliance"]["quality_safety_certifications"].append(
                _make_req(
                    "quality_safety_certification",
                    ev,
                    ev.text_norm,
                    certification_codes=iso_codes,
                    confidence=round(ev.confidence + _heading_bonus(ev, "legal"), 3),
                )
            )
            continue

        out["unmapped_requirements"].append(
            _make_req(
                "unmapped",
                ev,
                ev.text_norm,
                confidence=round(ev.confidence, 3),
            )
        )

    # Dedupe requirement arrays for cleaner canonical output
    out["technical_specifications"]["items"] = _dedupe_requirements(out["technical_specifications"]["items"])
    for k in out["financial_criteria"]:
        out["financial_criteria"][k] = _dedupe_requirements(out["financial_criteria"][k])
    for k in out["experience_criteria"]:
        out["experience_criteria"][k] = _dedupe_requirements(out["experience_criteria"][k])
    for k in out["legal_and_compliance"]:
        out["legal_and_compliance"][k] = _dedupe_requirements(out["legal_and_compliance"][k])
    out["unmapped_requirements"] = _dedupe_requirements(out["unmapped_requirements"])

    return out


def run(pdf_path: str, out_dir: str) -> None:
    pool = build_evidence_pool(pdf_path)
    evidence_path = f"{out_dir.rstrip('/\\\\')}\\evidence_pool.json"
    canonical_path = f"{out_dir.rstrip('/\\\\')}\\canonical_tender.json"

    with open(evidence_path, "w", encoding="utf-8") as f:
        json.dump([asdict(ev) for ev in pool], f, indent=2, ensure_ascii=False)

    canonical = match_fields(pool)
    canonical["pdf_path"] = pdf_path
    canonical["evidence_pool_path"] = evidence_path

    with open(canonical_path, "w", encoding="utf-8") as f:
        json.dump(canonical, f, indent=2, ensure_ascii=False)

    print(f"Wrote {evidence_path}")
    print(f"Wrote {canonical_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default="GeM-Bidding-9257724.pdf")
    parser.add_argument("--out-dir", default=".")
    args = parser.parse_args()
    run(args.pdf, args.out_dir)


if __name__ == "__main__":
    main()

