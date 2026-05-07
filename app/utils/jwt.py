from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.utils.settings import settings


def create_access_token(*, username: str) -> dict[str, Any]:
    if not settings.jwt_secret_key:
        raise RuntimeError("JWT_SECRET_KEY is not configured.")

    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=settings.jwt_exp_hours)
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_seconds": settings.jwt_exp_hours * 3600,
        "expires_at": exp.isoformat(),
    }


def verify_access_token(token: str) -> dict[str, Any]:
    if not settings.jwt_secret_key:
        raise RuntimeError("JWT_SECRET_KEY is not configured.")
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])

