from typing import Any

import evidence_pipeline


def create_evidence_pool(pdf_path: str) -> list[dict[str, Any]]:
    from dataclasses import asdict

    pool = evidence_pipeline.build_evidence_pool(pdf_path)
    return [asdict(ev) for ev in pool]

