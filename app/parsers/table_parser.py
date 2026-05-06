from typing import Any

import chunking as table_chunker


def parse_tables(pdf_path: str) -> list[dict[str, Any]]:
    tables = table_chunker.extract_tables(pdf_path)
    out: list[dict[str, Any]] = []
    for i, table in enumerate(tables):
        l0 = table_chunker.build_table_chunks(
            table["rows"],
            heading=f"Table_{i + 1}",
            page_no=table["page"],
        )
        out.append(l0.to_dict())
    return out

