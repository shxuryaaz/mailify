"""The live pipeline (Part 4). For each newly-arrived message:

  fetch thread context
   -> pick the newest style profile for the sender's bucket
   -> ONE OpenAI call -> {importance, should_draft, draft_body}
   -> if should_draft (gated by DRAFT_MODE): create a NATIVE Gmail draft + a
      `drafts` row (status pending)
   -> fire push  (notifications ALWAYS fire when we draft; importance never
      decides whether the owner is notified)

Dedupe is enforced up front against `processed_messages` (Pub/Sub is at-least-once).
"""

from __future__ import annotations

import logging
import uuid

from prisma.errors import UniqueViolationError
from prisma.models import User

from ..config import (BUCKET_CLOSE, BUCKET_COLD, BUCKET_EXTERNAL, DRAFT_MODE,
                      HIGH_PRIORITY_THRESHOLD)
from ..db import db
from ..gmail.client import GmailClient
from ..gmail.parse import parse_message, sender_email
from ..llm.openai_client import draft_reply
from ..push.webpush import notify_user

log = logging.getLogger("mailify.pipeline")

CLOSE_FREQUENCY_MIN = 5


async def _already_processed(user_id: str, message_id: str) -> bool:
    """Claim the message id. First writer wins; a duplicate push hits the unique
    constraint and is skipped. Returns True if this is a duplicate."""
    try:
        await db.processedmessage.create(
            data={"userId": user_id, "gmailMessageId": message_id}
        )
        return False
    except UniqueViolationError:
        return True


async def _infer_bucket(user: User, gmail: GmailClient, sender_addr: str) -> str:
    owner_domain = user.email.split("@")[-1].lower() if "@" in user.email else ""
    domain = sender_addr.split("@")[-1] if "@" in sender_addr else ""
    if domain and domain == owner_domain:
        return BUCKET_CLOSE
    # Familiarity probe: how much prior mail from this address? One cheap search.
    try:
        prior = await gmail.list_messages(f"from:{sender_addr}", 6)
    except Exception:  # noqa: BLE001
        prior = []
    if len(prior) <= 1:
        return BUCKET_COLD
    if len(prior) >= CLOSE_FREQUENCY_MIN:
        return BUCKET_CLOSE
    return BUCKET_EXTERNAL


async def _newest_profile(user_id: str, bucket: str) -> str:
    """Draft time ALWAYS reads the newest profile version for the bucket, so
    learning-loop improvements apply automatically to the next email."""
    prof = await db.styleprofile.find_first(
        where={"userId": user_id, "bucket": bucket},
        order={"version": "desc"},
    )
    return prof.profileText if prof else ""


def _should_draft(should_draft_flag: bool, importance: int) -> bool:
    """Apply DRAFT_MODE. Everything downstream reads this — behavior is not
    hardcoded anywhere else."""
    if not should_draft_flag:
        return False
    if DRAFT_MODE == "high_priority_only":
        return importance >= HIGH_PRIORITY_THRESHOLD
    # default "reply_worthy": draft anything the model flagged worth replying to
    return True


async def process_message(user: User, message_id: str) -> None:
    if await _already_processed(user.id, message_id):
        log.info("dedupe: skip already-processed message=%s user=%s", message_id, user.id)
        return

    gmail = await GmailClient.for_user(user)
    raw = await gmail.get_message(message_id)
    msg = parse_message(raw)

    # Ignore mail the owner sent themselves (belt-and-suspenders with history filter).
    from_addr = sender_email(msg["from"])
    if from_addr == user.email.lower():
        return

    bucket = await _infer_bucket(user, gmail, from_addr)
    profile = await _newest_profile(user.id, bucket)

    thread_text = _render_thread(msg)
    result = await draft_reply(style_profile=profile, thread_text=thread_text, sender=msg["from"])
    importance = result["importance"]
    do_draft = _should_draft(result["should_draft"], importance)

    log.info("pipeline: msg=%s bucket=%s importance=%s should_draft(model)=%s do_draft=%s",
             message_id, bucket, importance, result["should_draft"], do_draft)

    if not do_draft:
        # Nothing to approve, so nothing to notify about. (Notifications are for
        # drafts awaiting a tap; a non-drafted email is not buried — it's just in
        # the normal inbox.)
        return

    idempotency_key = str(uuid.uuid4())
    reply_subject = _reply_subject(msg["subject"])

    # Create the NATIVE Gmail draft first, so approve becomes "send this existing
    # draft". If the draft row write fails after this, the orphan draft is
    # harmless (it just sits in Gmail).
    gmail_draft = await gmail.create_draft(
        thread_id=msg["thread_id"],
        to=msg["from"],
        subject=reply_subject,
        body=result["draft_body"],
        in_reply_to=msg["message_id_header"] or None,
        references=(msg["references"] + " " + msg["message_id_header"]).strip() or None,
    )
    gmail_draft_id = gmail_draft.get("id", "")

    draft_row = await db.draft.create(data={
        "userId": user.id,
        "gmailMessageId": message_id,
        "gmailThreadId": msg["thread_id"],
        "gmailDraftId": gmail_draft_id,
        "bucket": bucket,
        "importance": importance,
        "shouldDraft": True,
        "status": "pending",
        "draftBody": result["draft_body"],
        "subject": reply_subject,
        "incomingFrom": msg["from"],
        "incomingSnippet": msg["snippet"][:400],
        "idempotencyKey": idempotency_key,
    })

    # Notify — deep-links to this draft via its id.
    await notify_user(
        user.id,
        title=f"Draft ready — {_short_sender(msg['from'])}",
        body=(msg["subject"] or "(no subject)")[:120],
        data={"draftId": draft_row.id, "url": f"/draft/{draft_row.id}"},
    )


def _render_thread(msg: dict) -> str:
    return (
        f"From: {msg['from']}\n"
        f"Subject: {msg['subject']}\n\n"
        f"{msg['body'] or msg['snippet']}"
    )


def _reply_subject(subject: str) -> str:
    subject = subject or ""
    return subject if subject.lower().startswith("re:") else f"Re: {subject}".strip()


def _short_sender(from_header: str) -> str:
    name = from_header.split("<")[0].strip().strip('"')
    return name or sender_email(from_header)
