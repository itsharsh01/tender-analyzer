from typing import Any

import ocr_chunking as ocr_chunker


def parse_ocr(pdf_path: str) -> list[dict[str, Any]]:
    blocks = ocr_chunker.extract_ocr_blocks(
        pdf_path,
        engine="pytesseract",
        zoom=2.0,
        lang="eng",
        min_text_chars=200,
    )
    if not blocks:
        return []
    return [c.to_dict() for c in ocr_chunker.build_ocr_chunks(blocks)]

