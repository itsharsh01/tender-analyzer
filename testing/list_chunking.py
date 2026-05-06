# -*- coding: utf-8 -*-
"""
Dynamic list/bullet chunking for tender PDFs.

Output hierarchy for list content:
  L0 -> Section heading (heuristic)
  L1 -> Full list block (raw preserved)
  L2 -> One bullet/numbered item per chunk (heading prepended)

This complements paragraph chunking by extracting items that are better represented
as a checklist than as sentence-split prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
import argparse
import json
import re

try:
    import fitz  # PyMuPDF
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "PyMuPDF is required for list extraction. Install it with `pip install pymupdf`."
    ) from e

from chunking import Chunk, make_id


@dataclass(frozen=True)
class TextBlock:
    page: int
    block_id: str
    raw_text: str
    normalized_text: str
    bbox: Tuple[float, float, float, float]
    is_heading: bool
    heading_text: Optional[str] = None


_WS_RE = re.compile(r"\s+")
_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")

_BULLET_LINE_RE = re.compile(
    r"^\s*(?:"
    r"[•\-\–\—]"  # bullets
    r"|"
    r"\(?\d{1,3}\)?[.)]"  # 1. 1) (1)
    r"|"
    r"\(?[A-Za-z]\)?[.)]"  # a) A. (b)
    r"|"
    r"\(?[ivxlcdmIVXLCDM]{1,6}\)?[.)]"  # roman numerals
    r")\s+"
)


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = _CID_TOKEN_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _span_is_bold(span: Dict[str, Any]) -> bool:
    font = (span.get("font") or "").lower()
    flags = int(span.get("flags") or 0)
    return ("bold" in font) or bool(flags & 16)


def _block_font_stats(block: Dict[str, Any]) -> Tuple[float, float, int]:
    sizes: List[float] = []
    bold_chars = 0
    total_chars = 0
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            text = span.get("text") or ""
            if not text.strip():
                continue
            size = float(span.get("size") or 0.0)
            sizes.append(size)
            n = len(text)
            total_chars += n
            if _span_is_bold(span):
                bold_chars += n
    avg_size = (sum(sizes) / len(sizes)) if sizes else 0.0
    bold_ratio = (bold_chars / total_chars) if total_chars else 0.0
    return avg_size, bold_ratio, total_chars


def extract_text_blocks(pdf_path: str) -> List[TextBlock]:
    doc = fitz.open(pdf_path)
    out: List[TextBlock] = []

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        page_no = page_index + 1
        data = page.get_text("dict")
        text_blocks = [b for b in data.get("blocks", []) if b.get("type") == 0]

        block_stats = [(_block_font_stats(b), b) for b in text_blocks]
        sizes = sorted([s[0][0] for s in block_stats if s[0][0] > 0])
        median_size = sizes[len(sizes) // 2] if sizes else 0.0

        for i, ((avg_size, bold_ratio, char_count), block) in enumerate(block_stats):
            raw = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    raw += (span.get("text") or "")
                raw += "\n"
            raw = raw.strip()
            if not raw:
                continue

            norm = normalize_text(raw)
            looks_short = len(norm) <= 120 and char_count <= 180
            no_sentence_end = not norm.endswith(".")
            larger_font = median_size > 0 and avg_size >= (median_size + 1.0)
            mostly_bold = bold_ratio >= 0.60 and char_count >= 5
            is_heading = bool(looks_short and no_sentence_end and (larger_font or mostly_bold))

            bbox = tuple(block.get("bbox") or (0, 0, 0, 0))
            out.append(
                TextBlock(
                    page=page_no,
                    block_id=f"p{page_no}_b{i}",
                    raw_text=raw,
                    normalized_text=norm,
                    bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                    is_heading=is_heading,
                    heading_text=norm if is_heading else None,
                )
            )

    return out


def is_list_block(raw_text: str) -> bool:
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False

    bullet_like = sum(1 for ln in lines if _BULLET_LINE_RE.match(ln))
    # Require at least two bullet-like lines or majority bullet-like for robustness.
    return bullet_like >= 2 or bullet_like >= max(2, int(0.6 * len(lines)))


def extract_list_items(raw_text: str) -> List[str]:
    """
    Extract list items from a list block. Handles multi-line wrapping:
    lines not starting with a bullet marker are appended to the previous item.
    """
    items: List[str] = []
    current: List[str] = []

    for line in raw_text.splitlines():
        if not line.strip():
            continue
        if _BULLET_LINE_RE.match(line):
            if current:
                items.append(normalize_text(" ".join(current)))
            # remove the bullet prefix
            cleaned = _BULLET_LINE_RE.sub("", line).strip()
            current = [cleaned] if cleaned else []
        else:
            # wrapped continuation
            if current:
                current.append(line.strip())
            else:
                # If the first line isn't bullet-marked, treat as a single item starter.
                current = [line.strip()]

    if current:
        items.append(normalize_text(" ".join(current)))

    return [it for it in items if it]


def build_list_chunks(blocks: Iterable[TextBlock], *, default_heading: str = "General") -> List[Chunk]:
    l0_chunks: List[Chunk] = []
    current_heading = default_heading
    current_heading_page: Optional[int] = None
    l0_by_heading: Dict[str, Chunk] = {}

    for block in blocks:
        if block.is_heading and block.heading_text:
            current_heading = block.heading_text
            current_heading_page = block.page
            continue

        if not is_list_block(block.raw_text):
            continue

        # Create L0 only when we actually have list content to attach.
        current_l0 = l0_by_heading.get(current_heading)
        if current_l0 is None:
            current_l0 = Chunk(
                id=make_id(),
                level="L0",
                content=current_heading,
                chunk_type="section_heading",
                metadata={"page": current_heading_page or block.page, "heading": current_heading},
            )
            l0_by_heading[current_heading] = current_l0
            l0_chunks.append(current_l0)

        list_id = f"{block.block_id}_list"
        l1 = Chunk(
            id=make_id(),
            level="L1",
            content=block.raw_text,
            chunk_type="list_block",
            parent_id=current_l0.id,
            metadata={
                "page": block.page,
                "heading": current_heading,
                "list_id": list_id,
                "bbox": block.bbox,
                "raw_text": block.raw_text,
                "normalized_text": block.normalized_text,
            },
        )

        items = extract_list_items(block.raw_text)
        for idx, item in enumerate(items, start=1):
            l1.children.append(
                Chunk(
                    id=make_id(),
                    level="L2",
                    content=f"[{current_heading}] {item}",
                    chunk_type="list_item",
                    parent_id=l1.id,
                    metadata={
                        "page": block.page,
                        "heading": current_heading,
                        "list_id": list_id,
                        "position_in_list": idx,
                        "raw_text": block.raw_text,
                        "normalized_text": item,
                    },
                )
            )

        current_l0.children.append(l1)

    return l0_chunks


def run(pdf_path: str, out_path: str) -> None:
    blocks = extract_text_blocks(pdf_path)
    l0_chunks = build_list_chunks(blocks)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([c.to_dict() for c in l0_chunks], f, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default="GeM-Bidding-9257724.pdf")
    parser.add_argument("--out", default="list_chunks.json")
    args = parser.parse_args()
    run(args.pdf, args.out)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()

