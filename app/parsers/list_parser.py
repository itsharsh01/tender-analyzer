from typing import Any

import list_chunking as list_chunker


def parse_lists(pdf_path: str) -> list[dict[str, Any]]:
    blocks = list_chunker.extract_text_blocks(pdf_path)
    return [c.to_dict() for c in list_chunker.build_list_chunks(blocks)]

