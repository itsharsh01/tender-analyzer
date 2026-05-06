from pydantic import BaseModel


class EvidenceRecord(BaseModel):
    evidence_id: str
    tender_id: str
    source: str
    kind: str
    page: int
    heading: str
    text_norm: str

