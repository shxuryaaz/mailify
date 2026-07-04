"""historyId reconciliation (Part 1 risk #1).

Pub/Sub push payloads carry only {emailAddress, historyId} — NOT the new message.
And Pub/Sub is at-least-once, so the same push can arrive twice. We reconcile by
diffing Gmail's history feed from the last historyId we durably advanced to, and
we let `processed_messages` (unique on (userId, gmailMessageId)) absorb any
duplicate so nothing is reprocessed or dropped.

Contract:
  - Never advance the stored historyId past what we've actually enumerated.
  - If the stored historyId is too old (Gmail 404s), fall back to a full re-arm
    so we don't get wedged.
"""

from __future__ import annotations

import logging

import httpx
from prisma.models import User

from ..db import db
from .client import GmailClient

log = logging.getLogger("mailify.history")


async def collect_new_message_ids(user: User, notified_history_id: int) -> list[str]:
    """Enumerate message ids added since the user's stored historyId, then
    advance the stored historyId. Returns candidate ids (dedupe happens later)."""
    start = user.gmailHistoryId
    if start is None:
        # No floor yet (shouldn't happen post-onboarding). Adopt the pushed id
        # and process nothing this round — we can't know what came before it.
        await db.user.update(where={"id": user.id},
                             data={"gmailHistoryId": notified_history_id})
        return []

    gmail = await GmailClient.for_user(user)
    message_ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    max_history = start

    try:
        while True:
            page = await gmail.history_list(start, page_token)
            for record in page.get("history", []):
                max_history = max(max_history, int(record.get("id", max_history)))
                for added in record.get("messagesAdded", []):
                    msg = added.get("message", {})
                    mid = msg.get("id")
                    labels = msg.get("labelIds", [])
                    # Only inbound INBOX mail; skip our own sent/draft noise.
                    if mid and mid not in seen and "INBOX" in labels and "SENT" not in labels:
                        seen.add(mid)
                        message_ids.append(mid)
            page_token = page.get("nextPageToken")
            if not page_token:
                break
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # historyId expired (mailbox went quiet > ~1 week). Re-arm to a fresh
            # floor. We miss whatever slipped through, but we recover cleanly
            # rather than 500-looping every push.
            log.warning("historyId %s expired for user=%s; re-arming floor to %s",
                        start, user.id, notified_history_id)
            await db.user.update(where={"id": user.id},
                                 data={"gmailHistoryId": notified_history_id})
            return []
        raise

    # Advance the durable floor. Use the max of what we enumerated and the pushed
    # id so a push with no new INBOX messages still moves us forward.
    new_floor = max(max_history, notified_history_id)
    await db.user.update(where={"id": user.id}, data={"gmailHistoryId": new_floor})
    return message_ids
