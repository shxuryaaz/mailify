"""FastAPI dependencies: resolve the current user from our session JWT."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from prisma.models import User

from .db import db
from .security import verify_jwt


async def current_user(authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = verify_jwt(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = await db.user.find_unique(where={"id": payload["sub"]})
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user
