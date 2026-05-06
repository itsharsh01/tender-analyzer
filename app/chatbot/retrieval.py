from typing import Any


def retrieve_context_placeholder(query: str, evidence_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    q = query.lower().strip()
    if not q:
        return []
    return [e for e in evidence_items if q in (e.get("text_norm", "").lower())][:10]

