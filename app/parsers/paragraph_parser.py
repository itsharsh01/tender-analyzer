from typing import Any

import paragraph_chunking as paragraph_chunker


def parse_paragraphs(pdf_path: str) -> list[dict[str, Any]]:
    blocks = paragraph_chunker.extract_paragraph_blocks(pdf_path)
    return [c.to_dict() for c in paragraph_chunker.build_paragraph_chunks(blocks)]

