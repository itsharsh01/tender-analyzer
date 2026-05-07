# -*- coding: utf-8 -*-
"""
Paragraph parser: extracts and chunks paragraph blocks from tender PDFs.
Fully self-contained — no root-level imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except Exception as e:
    raise RuntimeError(
        "PyMuPDF is required for paragraph extraction. Install with `pip install pymupdf`."
    ) from e

from app.parsers.table_parser import Chunk, make_id


# ── Normalisation helpers ─────────────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")
_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")

_DEP_MERGE_PREFIXES = (
    "in case", "however", "provided that", "subject to",
    "unless", "further", "also",
)


def _normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = _CID_TOKEN_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


# ── Font heuristics ───────────────────────────────────────────────────────────

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
            sizes.append(float(span.get("size") or 0.0))
            n = len(text)
            total_chars += n
            if _span_is_bold(span):
                bold_chars += n
    avg_size = (sum(sizes) / len(sizes)) if sizes else 0.0
    bold_ratio = (bold_chars / total_chars) if total_chars else 0.0
    return avg_size, bold_ratio, total_chars


# ── Block dataclass ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ParagraphBlock:
    page: int
    block_id: str
    raw_text: str
    normalized_text: str
    bbox: Tuple[float, float, float, float]
    is_heading: bool
    heading_text: Optional[str] = None


# ── Extraction ────────────────────────────────────────────────────────────────

def extract_paragraph_blocks(pdf_path: str) -> List[ParagraphBlock]:
    doc = fitz.open(pdf_path)
    blocks_out: List[ParagraphBlock] = []

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

            norm = _normalize_text(raw)
            looks_short = len(norm) <= 120 and char_count <= 180
            no_sentence_end = not norm.endswith(".")
            larger_font = median_size > 0 and avg_size >= (median_size + 1.0)
            mostly_bold = bold_ratio >= 0.60 and char_count >= 5
            is_heading = bool(looks_short and no_sentence_end and (larger_font or mostly_bold))

            bbox = tuple(block.get("bbox") or (0, 0, 0, 0))
            blocks_out.append(
                ParagraphBlock(
                    page=page_no,
                    block_id=f"p{page_no}_b{i}",
                    raw_text=raw,
                    normalized_text=norm,
                    bbox=(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                    is_heading=is_heading,
                    heading_text=norm if is_heading else None,
                )
            )

    return blocks_out


# ── Sentence segmentation ─────────────────────────────────────────────────────

def _get_nlp():
    try:
        import spacy
        try:
            nlp = spacy.load("en_core_web_sm")
        except Exception:
            nlp = spacy.blank("en")
            if "sentencizer" not in nlp.pipe_names:
                nlp.add_pipe("sentencizer")
        return nlp
    except Exception as e:
        raise RuntimeError(
            "spaCy is required for sentence segmentation. "
            "Install with `pip install spacy`."
        ) from e


def _segment_sentences(paragraph_text: str) -> List[str]:
    nlp = _get_nlp()
    doc = nlp(paragraph_text)
    return [_normalize_text(s.text) for s in doc.sents if _normalize_text(s.text)]


def _merge_dependency_sentences(sentences: List[str]) -> List[str]:
    merged: List[str] = []
    for s in sentences:
        s_norm = s.strip()
        if not merged:
            merged.append(s_norm)
            continue
        prefix = s_norm.lower()
        if any(prefix.startswith(p) for p in _DEP_MERGE_PREFIXES):
            merged[-1] = _normalize_text(f"{merged[-1]} {s_norm}")
        else:
            merged.append(s_norm)
    return merged


# ── Chunking ──────────────────────────────────────────────────────────────────

def build_paragraph_chunks(
    blocks: Iterable[ParagraphBlock],
    *,
    default_heading: str = "General",
) -> List[Chunk]:
    l0_chunks: List[Chunk] = []
    current_l0: Optional[Chunk] = None
    current_heading = default_heading

    for block in blocks:
        if block.is_heading and block.heading_text:
            current_heading = block.heading_text
            current_l0 = Chunk(
                id=make_id(),
                level="L0",
                content=current_heading,
                chunk_type="section_heading",
                metadata={"page": block.page, "heading": current_heading},
            )
            l0_chunks.append(current_l0)
            continue

        if current_l0 is None:
            current_l0 = Chunk(
                id=make_id(),
                level="L0",
                content=current_heading,
                chunk_type="section_heading",
                metadata={"page": block.page, "heading": current_heading},
            )
            l0_chunks.append(current_l0)

        l1 = Chunk(
            id=make_id(),
            level="L1",
            content=block.raw_text,
            chunk_type="paragraph",
            parent_id=current_l0.id,
            metadata={
                "page": block.page,
                "heading": current_heading,
                "paragraph_id": block.block_id,
                "bbox": block.bbox,
                "raw_text": block.raw_text,
                "normalized_text": block.normalized_text,
            },
        )

        sentences = _merge_dependency_sentences(_segment_sentences(block.normalized_text))
        for pos, sent in enumerate(sentences, start=1):
            l1.children.append(
                Chunk(
                    id=make_id(),
                    level="L2",
                    content=f"[{current_heading}] {sent}",
                    chunk_type="paragraph_sentence",
                    parent_id=l1.id,
                    metadata={
                        "page": block.page,
                        "heading": current_heading,
                        "paragraph_id": block.block_id,
                        "position_in_paragraph": pos,
                        "raw_text": block.raw_text,
                        "normalized_text": sent,
                    },
                )
            )

        current_l0.children.append(l1)

    return l0_chunks


def parse_paragraphs(pdf_path: str) -> List[Dict[str, Any]]:
    """Entry point used by the pipeline."""
    blocks = extract_paragraph_blocks(pdf_path)
    return [c.to_dict() for c in build_paragraph_chunks(blocks)]
