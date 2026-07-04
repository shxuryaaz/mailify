"""Pub/Sub push receiver (Part 4 risk #1).

Google posts a base64-wrapped {emailAddress, historyId} envelope here. We:
  * verify the shared token (set on the push subscription as ?token=...),
  * decode the notification,
  * reconcile via historyId to get the actually-new message ids,
  * hand each to the pipeline (which dedupes against processed_messages).

We always return 200 quickly so Pub/Sub doesn't hammer us with retries; the
heavy work runs in a background task.
"""

from __future__ import annotations

import base64
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ..config import settings
from ..db import db
from ..gmail.history import collect_new_message_ids
from ..pipeline.process import process_message

log = logging.getLogger("mailify.webhook")
router = APIRouter(tags=["webhook"])


@router.post("/gmail/webhook")
async def gmail_webhook(request: Request, background: BackgroundTasks):
    # Shared-secret check — the push subscription is configured with ?token=...
    if settings.pubsub_verification_token:
        if request.query_params.get("token") != settings.pubsub_verification_token:
            raise HTTPException(403, "Bad verification token")

    envelope = await request.json()
    message = (envelope or {}).get("message", {})
    data_b64 = message.get("data")
    if not data_b64:
        # Pub/Sub sometimes sends control messages with no data.
        return {"status": "ignored"}

    try:
        decoded = json.loads(base64.b64decode(data_b64).decode())
    except Exception:  # noqa: BLE001
        log.warning("webhook: undecodable data payload")
        return {"status": "ignored"}

    email = (decoded.get("emailAddress") or "").lower()
    history_id = int(decoded.get("historyId", 0) or 0)
    if not email or not history_id:
        return {"status": "ignored"}

    user = await db.user.find_unique(where={"email": email})
    if not user or not user.gmailConnected:
        log.info("webhook: no connected user for %s", email)
        return {"status": "ignored"}

    background.add_task(_reconcile_and_process, user.id, history_id)
    return {"status": "accepted"}


async def _reconcile_and_process(user_id: str, history_id: int) -> None:
    user = await db.user.find_unique(where={"id": user_id})
    if not user:
        return
    try:
        message_ids = await collect_new_message_ids(user, history_id)
    except Exception as exc:  # noqa: BLE001
        log.error("webhook: reconciliation failed user=%s error=%s", user_id, exc, exc_info=True)
        return

    for mid in message_ids:
        try:
            await process_message(user, mid)
        except Exception as exc:  # noqa: BLE001
            log.error("webhook: processing failed user=%s message=%s error=%s",
                      user_id, mid, exc, exc_info=True)
