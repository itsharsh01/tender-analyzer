from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

import bcrypt

from app.models.db import get_db
from app.utils.settings import settings


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_username(username: str) -> str:
    u = (username or "").strip()
    if not _USERNAME_RE.match(u):
        raise ValueError("Username can contain only letters, numbers, underscore, hyphen, and dot.")
    return u


def _validate_password(password: str) -> None:
    if len(password or "") < settings.auth_min_password_length:
        raise ValueError(f"Password must be at least {settings.auth_min_password_length} characters long.")


def _normalize_password_for_bcrypt(password: str) -> str:
    """
    Bcrypt only accepts up to 72 bytes of input. Pre-hash to fixed length so
    arbitrarily long passwords are supported safely.
    """
    return hashlib.sha256((password or "").encode("utf-8")).hexdigest()


def _hash_password(password: str) -> str:
    normalized = _normalize_password_for_bcrypt(password).encode("utf-8")
    return bcrypt.hashpw(normalized, bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    # New scheme (pre-hashed then bcrypt via direct bcrypt library)
    normalized = _normalize_password_for_bcrypt(password)
    try:
        if bcrypt.checkpw(normalized.encode("utf-8"), (password_hash or "").encode("utf-8")):
            return True
    except Exception:
        return False
    return False


def register_user(username: str, password: str) -> dict[str, Any]:
    db = get_db()
    username = _validate_username(username)
    _validate_password(password)

    if db.users.find_one({"username": username}, {"_id": 1}):
        raise ValueError("Username already exists.")

    doc = {
        "username": username,
        "password_hash": _hash_password(password),
        "is_approved": False,
        "created_at": _now(),
        "approved_at": None,
        "last_login_at": None,
    }
    db.users.insert_one(doc)
    return {
        "username": username,
        "is_approved": False,
        "message": "Registered successfully. Awaiting admin approval.",
    }


def login_user(username: str, password: str) -> dict[str, Any]:
    db = get_db()
    username = _validate_username(username)

    user = db.users.find_one({"username": username})
    if not user:
        raise ValueError("Invalid username or password.")

    if not _verify_password(password, user.get("password_hash", "")):
        raise ValueError("Invalid username or password.")

    if not user.get("is_approved", False):
        raise PermissionError("User is not approved yet.")

    db.users.update_one(
        {"username": username},
        {"$set": {"last_login_at": _now()}},
    )

    return {
        "username": username,
        "is_approved": True,
        "message": "Login successful.",
    }


def approve_user(username: str) -> dict[str, Any]:
    db = get_db()
    username = _validate_username(username)

    result = db.users.update_one(
        {"username": username},
        {"$set": {"is_approved": True, "approved_at": _now()}},
    )
    if result.matched_count == 0:
        raise ValueError("User not found.")

    return {"username": username, "is_approved": True, "message": "User approved."}

