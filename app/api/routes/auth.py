from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.models.auth import LoginRequest, RegisterRequest
from app.services.auth_service import approve_user, login_user, register_user
from app.utils.jwt import create_access_token
from app.utils.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(payload: RegisterRequest) -> dict:
    try:
        return register_user(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login")
def login(payload: LoginRequest) -> dict:
    try:
        result = login_user(payload.username, payload.password)
        token = create_access_token(username=result["username"])
        return {**result, **token}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/approve/{username}")
def approve(
    username: str,
    x_admin_key: str | None = Header(default=None),
) -> dict:
    if not settings.admin_approval_key:
        raise HTTPException(status_code=500, detail="ADMIN_APPROVAL_KEY is not configured.")
    if x_admin_key != settings.admin_approval_key:
        raise HTTPException(status_code=401, detail="Invalid admin approval key.")

    try:
        return approve_user(username)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

