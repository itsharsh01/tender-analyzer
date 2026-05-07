# -*- coding: utf-8 -*-
"""
OCR parser: extracts and chunks scanned/low-text pages from tender PDFs.
Fully self-contained — no root-level imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except Exception as e:
    raise RuntimeError("PyMuPDF is required. Install with `pip install pymupdf`.") from e

from app.parsers.table_parser import Chunk, make_id


# ── Normalisation ─────────────────────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")
_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")


def _normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = _CID_TOKEN_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


# ── spaCy sentence segmentation ───────────────────────────────────────────────

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
            "spaCy is required for sentence segmentation. Install with `pip install spacy`."
        ) from e


def _segment_sentences(text: str) -> List[str]:
    nlp = _get_nlp()
    doc = nlp(text)
    return [_normalize_text(s.text) for s in doc.sents if _normalize_text(s.text)]


# ── Image rendering + OCR ─────────────────────────────────────────────────────

def _render_page_image(page: "fitz.Page", *, zoom: float) -> "Any":
    try:
        from PIL import Image
    except Exception as e:
        raise RuntimeError("Pillow is required. Install with `pip install pillow`.") from e
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _ocr_with_pytesseract(img: "Any", *, lang: str) -> str:
    try:
        import pytesseract
    except Exception as e:
        raise RuntimeError(
            "pytesseract is required. Install with `pip install pytesseract` and ensure "
            "the Tesseract binary is installed on your system."
        ) from e
    return pytesseract.image_to_string(img, lang=lang)


def _ocr_page(page: "fitz.Page", *, engine: str, zoom: float, lang: str) -> str:
    img = _render_page_image(page, zoom=zoom)
    engine = engine.lower().strip()
    if engine == "pytesseract":
        return _ocr_with_pytesseract(img, lang=lang)
    raise ValueError(f"Unsupported OCR engine: {engine!r}")


# ── Block dataclass ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OcrBlock:
    page: int
    block_id: str
    raw_text: str
    normalized_text: str
    bbox: Optional[Tuple[float, float, float, float]] = None


# ── Extraction ────────────────────────────────────────────────────────────────

def extract_ocr_blocks(
    pdf_path: str,
    *,
    engine: str = "pytesseract",
    zoom: float = 2.0,
    lang: str = "eng",
    min_text_chars: int = 200,
) -> List[OcrBlock]:
    doc = fitz.open(pdf_path)
    out: List[OcrBlock] = []

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        page_no = page_index + 1
        extracted_text = page.get_text() or ""
        if len(_normalize_text(extracted_text)) >= min_text_chars:
            continue  # page has enough native text; skip OCR

        raw = _ocr_page(page, engine=engine, zoom=zoom, lang=lang)
        norm = _normalize_text(raw)
        if not norm:
            continue

        out.append(
            OcrBlock(
                page=page_no,
                block_id=f"ocr_p{page_no}",
                raw_text=raw,
                normalized_text=norm,
                bbox=None,
            )
        )

    return out


# ── Chunking ──────────────────────────────────────────────────────────────────

def build_ocr_chunks(
    blocks: List[OcrBlock],
    *,
    default_heading: str = "General",
) -> List[Chunk]:
    l0_chunks: List[Chunk] = []
    current_heading = default_heading

    l0 = Chunk(
        id=make_id(),
        level="L0",
        content=current_heading,
        chunk_type="section_heading",
        metadata={"page": blocks[0].page if blocks else 1, "heading": current_heading},
    )
    l0_chunks.append(l0)

    for block in blocks:
        l1 = Chunk(
            id=make_id(),
            level="L1",
            content=block.raw_text,
            chunk_type="ocr_block",
            parent_id=l0.id,
            metadata={
                "page": block.page,
                "heading": current_heading,
                "ocr_block_id": block.block_id,
                "bbox": block.bbox,
                "raw_text": block.raw_text,
                "normalized_text": block.normalized_text,
            },
        )

        for pos, sent in enumerate(_segment_sentences(block.normalized_text), start=1):
            l1.children.append(
                Chunk(
                    id=make_id(),
                    level="L2",
                    content=f"[{current_heading}] {sent}",
                    chunk_type="ocr_sentence",
                    parent_id=l1.id,
                    metadata={
                        "page": block.page,
                        "heading": current_heading,
                        "ocr_block_id": block.block_id,
                        "position_in_block": pos,
                        "raw_text": block.raw_text,
                        "normalized_text": sent,
                    },
                )
            )

        l0.children.append(l1)

    return l0_chunks


def parse_ocr(pdf_path: str) -> List[Any]:
    """Entry point used by the pipeline."""
    blocks = extract_ocr_blocks(pdf_path)
    if not blocks:
        return []
    return [c.to_dict() for c in build_ocr_chunks(blocks)]
