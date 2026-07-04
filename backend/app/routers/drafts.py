"""Draft actions (Part 4). This is where send-idempotency (risk #3) and the
learning-loop capture (Part 7) live.

  GET   /drafts                 -> pending list, newest/most-important first
  GET   /drafts/{id}            -> full draft + incoming email
  POST  /drafts/{id}/approve    -> send the existing native Gmail draft, set sent
  POST  /drafts/{id}/reject     -> trash the draft, set rejected, capture reject
  PATCH /drafts/{id}            -> edit body then send; capture the edit diff
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from prisma.models import User
from pydantic import BaseModel

from ..db import db
from ..deps import current_user
from ..gmail.client import GmailClient
from ..learning.loop import record_edit, record_reject

log = logging.getLogger("mailify.drafts")
router = APIRouter(prefix="/drafts", tags=["drafts"])


class PatchBody(BaseModel):
    draft_body: str


def _view(d) -> dict:
    return {
        "id": d.id,
        "status": d.status,
        "importance": d.importance,
        "bucket": d.bucket,
        "subject": d.subject,
        "incomingFrom": d.incomingFrom,
        "incomingSnippet": d.incomingSnippet,
        "draftBody": d.draftBody,
        "createdAt": d.createdAt.isoformat(),
    }


@router.get("")
async def list_drafts(user: User = Depends(current_user)):
    drafts = await db.draft.find_many(
        where={"userId": user.id, "status": "pending"},
        order=[{"importance": "desc"}, {"createdAt": "desc"}],
    )
    return [_view(d) for d in drafts]


async def _get_owned(draft_id: str, user: User):
    d = await db.draft.find_unique(where={"id": draft_id})
    if not d or d.userId != user.id:
        raise HTTPException(404, "Draft not found")
    return d


@router.get("/{draft_id}")
async def get_draft(draft_id: str, user: User = Depends(current_user)):
    return _view(await _get_owned(draft_id, user))


async def _claim_pending(draft_id: str, user_id: str, next_status: str) -> bool:
    """Atomically flip pending -> next_status. Only one caller wins, so a
    double-tap can't double-send. Returns True if THIS call won the claim."""
    updated = await db.draft.update_many(
        where={"id": draft_id, "userId": user_id, "status": "pending"},
        data={"status": next_status},
    )
    return updated > 0


@router.post("/{draft_id}/approve")
async def approve_draft(draft_id: str, user: User = Depends(current_user)):
    d = await _get_owned(draft_id, user)
    if d.status == "sent":
        return {"status": "sent", "note": "already sent"}  # idempotent no-op

    # Claim the row: pending -> approved. Losers of the race bail here.
    if not await _claim_pending(draft_id, user.id, "approved"):
        # Re-read to report the real terminal state.
        d = await _get_owned(draft_id, user)
        if d.status == "sent":
            return {"status": "sent", "note": "already sent"}
        raise HTTPException(409, f"Draft not sendable (status={d.status})")

    try:
        gmail = await GmailClient.for_user(user)
        await gmail.send_draft(d.gmailDraftId)
        await db.draft.update(where={"id": draft_id}, data={"status": "sent"})
        log.info("approve: sent draft=%s user=%s", draft_id, user.id)
        return {"status": "sent"}
    except Exception as exc:  # noqa: BLE001
        await db.draft.update(where={"id": draft_id}, data={"status": "failed"})
        log.error("approve: send failed draft=%s error=%s", draft_id, exc, exc_info=True)
        raise HTTPException(502, "Failed to send draft")


@router.post("/{draft_id}/reject")
async def reject_draft(draft_id: str, user: User = Depends(current_user)):
    d = await _get_owned(draft_id, user)
    if not await _claim_pending(draft_id, user.id, "rejected"):
        raise HTTPException(409, f"Draft not rejectable (status={d.status})")

    # Trash the native Gmail draft (best-effort — DB state is the source of truth).
    if d.gmailDraftId:
        try:
            gmail = await GmailClient.for_user(user)
            await gmail.delete_draft(d.gmailDraftId)
        except Exception as exc:  # noqa: BLE001
            log.warning("reject: could not delete gmail draft=%s error=%s", d.gmailDraftId, exc)

    # Capture the reject as learning signal (Part 7).
    await record_reject(user_id=user.id, draft_id=d.id, bucket=d.bucket,
                        original_body=d.draftBody)
    log.info("reject: draft=%s user=%s", draft_id, user.id)
    return {"status": "rejected"}


@router.patch("/{draft_id}")
async def edit_and_send(draft_id: str, body: PatchBody, user: User = Depends(current_user)):
    d = await _get_owned(draft_id, user)
    original_body = d.draftBody
    final_body = body.draft_body

    # Claim first so an edit-send can't race an approve.
    if not await _claim_pending(draft_id, user.id, "approved"):
        raise HTTPException(409, f"Draft not sendable (status={d.status})")

    try:
        gmail = await GmailClient.for_user(user)
        # Update the native draft with the edited body, then send it.
        await gmail.update_draft(
            d.gmailDraftId,
            thread_id=d.gmailThreadId,
            to=d.incomingFrom,
            subject=d.subject,
            body=final_body,
        )
        await gmail.send_draft(d.gmailDraftId)
        await db.draft.update(where={"id": draft_id},
                              data={"status": "sent", "draftBody": final_body})
    except Exception as exc:  # noqa: BLE001
        await db.draft.update(where={"id": draft_id}, data={"status": "failed"})
        log.error("edit: send failed draft=%s error=%s", draft_id, exc, exc_info=True)
        raise HTTPException(502, "Failed to send edited draft")

    # The diff between what the model wrote and what the owner actually sent is
    # the core learning signal — capture it (only if they differ).
    await record_edit(user_id=user.id, draft_id=d.id, bucket=d.bucket,
                      original_body=original_body, final_body=final_body)
    log.info("edit: sent draft=%s user=%s", draft_id, user.id)
    return {"status": "sent"}
