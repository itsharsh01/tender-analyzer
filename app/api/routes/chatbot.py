from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.chatbot_service import answer_query

router = APIRouter(prefix="/chatbot", tags=["chatbot"])


class ChatbotQueryRequest(BaseModel):
    tender_id: str = Field(..., min_length=1)
    submission_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=2)
    top_k: int = Field(8, ge=1, le=20)


@router.post("/query")
def chatbot_query(payload: ChatbotQueryRequest) -> dict:
    """
    Retrieve + rerank + LLM short answer over tender/submission context.
    """
    try:
        result = answer_query(
            tender_id=payload.tender_id,
            submission_id=payload.submission_id,
            query=payload.query.strip(),
            top_k=payload.top_k,
        )
        # Frontend requested a minimal response: only the final answer text.
        return {"answer": result.get("answer", "").strip()}
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

