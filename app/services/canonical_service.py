from typing import Any

import evidence_pipeline


def build_canonical(evidence_docs: list[dict[str, Any]]) -> dict[str, Any]:
    pool = [evidence_pipeline.EvidenceItem(**doc) for doc in evidence_docs]
    return evidence_pipeline.match_fields(pool)

