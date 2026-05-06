from typing import Any

from pydantic import BaseModel


class CanonicalRecord(BaseModel):
    tender_id: str
    fields: dict[str, Any]
    evidence: dict[str, list[str]]

