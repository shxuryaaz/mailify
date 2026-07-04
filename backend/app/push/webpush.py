"""Web Push over VAPID (Part 5). Payload carries the draft id so the tap
deep-links straight to the draft. Dead subscriptions (HTTP 410 Gone) are pruned.

Sends run in a thread since pywebpush is synchronous; one bad endpoint never
blocks the others.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pywebpush import WebPushException, webpush

from ..config import settings
from ..db import db

log = logging.getLogger("mailify.push")


def _vapid_claims() -> dict[str, str]:
    return {"sub": settings.vapid_subject}


def _send_one(subscription_info: dict[str, Any], payload: str) -> int:
    """Blocking send. Returns the HTTP status code, or raises WebPushException."""
    resp = webpush(
        subscription_info=subscription_info,
        data=payload,
        vapid_private_key=settings.vapid_private_key,
        vapid_claims=_vapid_claims(),
    )
    return resp.status_code


async def notify_user(user_id: str, *, title: str, body: str, data: dict[str, Any]) -> None:
    if not settings.vapid_private_key:
        log.warning("push: VAPID not configured; skipping notify for user=%s", user_id)
        return

    subs = await db.pushsubscription.find_many(where={"userId": user_id})
    if not subs:
        log.info("push: no subscriptions for user=%s", user_id)
        return

    payload = json.dumps({"title": title, "body": body, "data": data})

    for sub in subs:
        info = sub.subscription  # stored as JSON (endpoint + keys)
        try:
            await asyncio.to_thread(_send_one, info, payload)
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                # Gone — prune the dead subscription.
                await db.pushsubscription.delete(where={"id": sub.id})
                log.info("push: pruned dead subscription id=%s status=%s", sub.id, status)
            else:
                log.error("push: send failed sub=%s status=%s error=%s",
                          sub.id, status, exc)
