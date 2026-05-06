from pydantic import BaseModel


class TenderRecord(BaseModel):
    tender_id: str
    filename: str | None = None
    local_pdf_path: str
    status: str

