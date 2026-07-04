"""Crypto helpers: Fernet encryption for the Gmail refresh token at rest, and
JWT issue/verify for our own single-user session tokens."""

from __future__ import annotations

import datetime as dt
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import settings


def _fernet() -> Fernet:
    if not settings.fernet_key:
        raise RuntimeError(
            "FERNET_KEY is not set. Run `python -m app.scripts.gen_keys` and put it in .env."
        )
    return Fernet(settings.fernet_key.encode())


def encrypt(plaintext: str) -> str:
    """Encrypt a secret (e.g. Gmail refresh token) for storage in Neon."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:  # rotated key or corrupted value
        raise RuntimeError("Failed to decrypt stored token — FERNET_KEY changed?") from exc


def issue_jwt(user_id: str) -> str:
    now = dt.datetime.now(tz=dt.timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + dt.timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_jwt(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
