from dataclasses import asdict
from typing import Any

import evidence_pipeline


def build_evidence_pool(pdf_path: str) -> list[dict[str, Any]]:
    pool = evidence_pipeline.build_evidence_pool(pdf_path)
    return [asdict(ev) for ev in pool]

