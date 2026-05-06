from fastapi import APIRouter, File, UploadFile

from app.services.ingest_service import ingest_pdf

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("")
async def ingest(file: UploadFile = File(...)) -> dict:
    return await ingest_pdf(file)

