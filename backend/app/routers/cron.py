"""Cron-triggered jobs (Part 1). Protected by a bearer secret so only Render's
cron (or you) can call them.

  POST /cron/renew-watches  -> re-arm every mailbox watch (daily)
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from ..config import settings
from ..gmail.watch import renew_all_watches

router = APIRouter(prefix="/cron", tags=["cron"])


def _authorize(authorization: str | None) -> None:
    expected = f"Bearer {settings.cron_secret}"
    if not settings.cron_secret or authorization != expected:
        raise HTTPException(403, "Forbidden")


@router.post("/renew-watches")
async def renew_watches(authorization: str | None = Header(default=None)):
    _authorize(authorization)
    return await renew_all_watches()
