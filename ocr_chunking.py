# -*- coding: utf-8 -*-
"""
OCR-based chunking for scanned/low-text tender PDF pages.

Strategy:
- For each page, try normal text extraction via PyMuPDF.
- If text is below a threshold, render the page to an image and OCR it.
- Chunk OCR text into:
  L0 -> Section heading (fallback "General"; OCR headings are not robust by default)
  L1 -> OCR block (page-level block)
  L2 -> Sentence-level atomic chunks (spaCy sentencizer) with heading prepend

Notes:
- This requires both `pymupdf` and an OCR backend.
- Default backend is `pytesseract` (requires Tesseract installed on the system).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import argparse
import json
import re

try:
    import fitz  # PyMuPDF
except Exception as e:  # pragma: no cover
    raise RuntimeError("PyMuPDF is required. Install with `pip install pymupdf`.") from e

from chunking import Chunk, make_id


_WS_RE = re.compile(r"\s+")
_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = _CID_TOKEN_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


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
            "spaCy is required for sentence segmentation. Install it with `pip install spacy`."
        ) from e


def segment_sentences(text: str) -> List[str]:
    nlp = _get_nlp()
    doc = nlp(text)
    sents = [normalize_text(s.text) for s in doc.sents]
    return [s for s in sents if s]


def _render_page_image(page: "fitz.Page", *, zoom: float) -> "Any":
    """
    Returns a PIL image.
    """
    try:
        from PIL import Image
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Pillow is required. Install with `pip install pillow`.") from e

    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    mode = "RGB"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    return img


def _ocr_with_pytesseract(img: "Any", *, lang: str) -> str:
    try:
        import pytesseract
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "pytesseract is required for OCR. Install with `pip install pytesseract`. "
            "Also install the Tesseract OCR engine on your system and ensure it's on PATH."
        ) from e

    # Image-to-string gives a page-level text blob; we then sentence-segment it.
    return pytesseract.image_to_string(img, lang=lang)


def ocr_page(page: "fitz.Page", *, engine: str, zoom: float, lang: str) -> str:
    img = _render_page_image(page, zoom=zoom)
    engine = engine.lower().strip()
    if engine == "pytesseract":
        return _ocr_with_pytesseract(img, lang=lang)
    raise ValueError(f"Unsupported OCR engine: {engine!r}")


@dataclass(frozen=True)
class OcrBlock:
    page: int
    block_id: str
    raw_text: str
    normalized_text: str
    bbox: Optional[Tuple[float, float, float, float]] = None


def extract_ocr_blocks(
    pdf_path: str,
    *,
    engine: str,
    zoom: float,
    lang: str,
    min_text_chars: int,
) -> List[OcrBlock]:
    doc = fitz.open(pdf_path)
    out: List[OcrBlock] = []

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        page_no = page_index + 1

        extracted_text = page.get_text() or ""
        if len(normalize_text(extracted_text)) >= min_text_chars:
            # Page already has enough text; skip OCR.
            continue

        raw = ocr_page(page, engine=engine, zoom=zoom, lang=lang)
        norm = normalize_text(raw)
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


def build_ocr_chunks(blocks: List[OcrBlock], *, default_heading: str = "General") -> List[Chunk]:
    l0_chunks: List[Chunk] = []
    current_heading = default_heading

    # For now we emit a single L0 for all OCR blocks (headings from OCR are unreliable).
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

        for pos, sent in enumerate(segment_sentences(block.normalized_text), start=1):
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


def run(
    pdf_path: str,
    out_path: str,
    *,
    engine: str,
    zoom: float,
    lang: str,
    min_text_chars: int,
) -> None:
    blocks = extract_ocr_blocks(
        pdf_path,
        engine=engine,
        zoom=zoom,
        lang=lang,
        min_text_chars=min_text_chars,
    )
    chunks = build_ocr_chunks(blocks) if blocks else []
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([c.to_dict() for c in chunks], f, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default="GeM-Bidding-9257724.pdf")
    parser.add_argument("--out", default="ocr_chunks.json")
    parser.add_argument("--engine", default="pytesseract", choices=["pytesseract"])
    parser.add_argument("--zoom", type=float, default=2.0)
    parser.add_argument("--lang", default="eng")
    parser.add_argument("--min-text-chars", type=int, default=200)
    args = parser.parse_args()

    run(
        args.pdf,
        args.out,
        engine=args.engine,
        zoom=args.zoom,
        lang=args.lang,
        min_text_chars=args.min_text_chars,
    )
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()

