"""Gmail watch() registration + renewal (Part 1 risk #2).

A watch expires ~7 days after registration and Gmail gives NO error when it
lapses — push just silently stops and the whole product dies. So: register on
connect, re-arm daily via cron, and LOG LOUDLY on any renewal failure.
"""

from __future__ import annotations

import logging

from prisma.models import User

from ..config import settings
from ..db import db
from .client import GmailClient

log = logging.getLogger("mailify.watch")


async def register_watch(user: User) -> dict:
    """(Re)register the mailbox watch and persist historyId + expiration.

    Called at onboarding and by the daily cron. Storing the historyId here gives
    reconciliation a floor to diff from on the first push."""
    if not settings.gmail_pubsub_topic:
        raise RuntimeError("GMAIL_PUBSUB_TOPIC is not configured")

    gmail = await GmailClient.for_user(user)
    result = await gmail.watch(settings.gmail_pubsub_topic)
    history_id = int(result["historyId"])
    expiration = int(result["expiration"])  # ms epoch

    await db.user.update(
        where={"id": user.id},
        data={
            "gmailHistoryId": history_id,
            "watchExpiration": expiration,
            "watchTopic": settings.gmail_pubsub_topic,
        },
    )
    log.info("watch registered user=%s historyId=%s expiration=%s",
             user.id, history_id, expiration)
    return result


async def renew_all_watches() -> dict:
    """Daily cron entrypoint. Re-arm every connected mailbox. Any failure is
    logged at ERROR — a lapsed watch is a silent death, so we never swallow it
    quietly."""
    users = await db.user.find_many(where={"gmailConnected": True})
    ok, failed = 0, 0
    for user in users:
        try:
            await register_watch(user)
            ok += 1
        except Exception as exc:  # noqa: BLE001 — must be loud, must continue
            failed += 1
            log.error("WATCH RENEWAL FAILED user=%s email=%s error=%s — "
                      "Gmail push will silently die if this keeps failing.",
                      user.id, user.email, exc, exc_info=True)
    log.info("watch renewal sweep complete ok=%s failed=%s", ok, failed)
    return {"renewed": ok, "failed": failed}
