from fastapi import APIRouter, File, HTTPException, UploadFile

from app.services.ingest_service import ingest_pdf

router = APIRouter(prefix="/tender", tags=["tender"])

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@router.post("/upload")
async def upload_tender(file: UploadFile = File(...)) -> dict:
    """
    Step 1 of the Tender Upload Plan.
    Accepts a PDF, runs the full async pipeline, and returns the tender_id + status.
    """
    # Validate MIME type
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=415,
            detail="Only PDF files are accepted.",
        )

    # Read once here to check size; ingest_service will use what it receives
    contents = await file.read()
    if len(contents) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {_MAX_FILE_SIZE // (1024*1024)} MB.",
        )
    # Rewind so ingest_service.ingest_pdf can read again via file.read()
    await file.seek(0)

    try:
        result = await ingest_pdf(file)
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
