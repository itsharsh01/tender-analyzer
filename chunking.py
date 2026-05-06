# -*- coding: utf-8 -*-
"""
Tender PDF table extraction + hierarchical chunking.

Key constraint:
- Normalize ONLY the left-column keys (often bilingual Hindi/English).
- Do NOT modify right-column values; store them exactly as extracted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
import argparse
import json
import re
import uuid

import pdfplumber


def make_id() -> str:
    return str(uuid.uuid4())


@dataclass
class Chunk:
    id: str
    level: str
    content: str
    chunk_type: str
    metadata: Dict[str, Any]
    parent_id: Optional[str] = None
    children: List["Chunk"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level,
            "content": self.content,
            "chunk_type": self.chunk_type,
            "metadata": self.metadata,
            "parent_id": self.parent_id,
            "children": [c.to_dict() for c in self.children],
        }


_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]+")
_LATIN_RE = re.compile(r"[A-Za-z]")
_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")
# Split on separators that usually indicate bilingual key formatting.
# We avoid splitting on a bare "/" so keys like "Date/Time" remain intact.
_BILINGUAL_SPLIT_RE = re.compile(r"(?:\s+/\s+|\s*//\s*|\s*[|｜]\s*|\s+[—–]\s+)")


def normalize_left_key(raw_key: Any) -> str:
    """
    Normalize ONLY left-column keys.

    Common pattern:
      "बिड बंद होने की तारीख/समय / Bid End Date/Time" -> "Bid End Date/Time"
    """
    if raw_key is None:
        return ""

    text = str(raw_key).replace("\n", " ").strip()
    if not text:
        return ""

    # Remove PDF font CID artifacts which may otherwise look "English" due to "cid".
    text = _CID_TOKEN_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()

    parts = [p.strip() for p in _BILINGUAL_SPLIT_RE.split(text) if p and p.strip()]

    # Prefer the last segment that has Latin letters after removing Devanagari.
    best: Optional[str] = None
    for part in parts:
        candidate = _DEVANAGARI_RE.sub(" ", part)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if _LATIN_RE.search(candidate):
            best = candidate.lstrip("/").strip()

    if best:
        return best

    # If there is no English segment at all, keep the key as-is (just collapse spaces).
    # This avoids deleting meaningful non-English-only keys.
    text = re.sub(r"\s+", " ", text).strip()
    return text


_COMPARISON_WORDS = {
    "minimum",
    "at least",
    "within",
    "less than",
    "greater than",
    "completed",
    "years",
    "lakhs",
    "crore",
}


def _should_split_flat_list(value: str) -> bool:
    """
    Split only flat enumerations like:
      "Experience, Certificate, PAN"

    Avoid splitting conditional phrases or numeric requirements.
    """
    if "," not in value:
        return False

    parts = [p.strip() for p in value.split(",")]
    for part in parts:
        words = part.lower().split()
        if len(words) > 5:
            return False
        if any(w in _COMPARISON_WORDS for w in words):
            return False
        if re.search(r"\d", part):
            return False

    return True


def split_value_into_l2_items(raw_value: str) -> List[str]:
    if _should_split_flat_list(raw_value):
        return [x.strip() for x in raw_value.split(",")]
    return [raw_value]


def extract_tables(pdf_path: str) -> List[Dict[str, Any]]:
    tables: List[Dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            for table in page.extract_tables() or []:
                tables.append({"page": page_no, "rows": table})
    return tables


def build_table_chunks(
    table_rows: Iterable[List[Any]],
    *,
    heading: str,
    page_no: int,
) -> Chunk:
    l0 = Chunk(
        id=make_id(),
        level="L0",
        content=heading,
        chunk_type="table",
        metadata={"page": page_no, "heading": heading},
    )

    for row in table_rows:
        if not row or len(row) < 2:
            continue

        raw_key = row[0]
        raw_value = row[1]
        if raw_key is None or raw_value is None:
            continue

        normalized_key = normalize_left_key(raw_key)
        # Values must remain exactly as extracted (no strip/cleanup).
        normalized_value = str(raw_value)

        l1 = Chunk(
            id=make_id(),
            level="L1",
            content=f"{normalized_key}: {normalized_value}",
            chunk_type="table_row",
            parent_id=l0.id,
            metadata={
                "page": page_no,
                "heading": heading,
                "raw_key": raw_key,
                "normalized_key": normalized_key,
                "raw_value": raw_value,
                "normalized_value": normalized_value,
            },
        )

        for item in split_value_into_l2_items(normalized_value):
            l1.children.append(
                Chunk(
                    id=make_id(),
                    level="L2",
                    content=item,
                    chunk_type="table_value",
                    parent_id=l1.id,
                    metadata={
                        "page": page_no,
                        "heading": heading,
                        "row_key": normalized_key,
                        "original_value": normalized_value,
                    },
                )
            )

        l0.children.append(l1)

    return l0


def run(pdf_path: str, out_path: str) -> None:
    tables = extract_tables(pdf_path)
    all_chunks: List[Dict[str, Any]] = []

    for i, table in enumerate(tables):
        chunk = build_table_chunks(
            table["rows"],
            heading=f"Table_{i + 1}",
            page_no=table["page"],
        )
        all_chunks.append(chunk.to_dict())

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default="GeM-Bidding-9257724.pdf")
    parser.add_argument("--out", default="chunks.json")
    args = parser.parse_args()
    run(args.pdf, args.out)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()