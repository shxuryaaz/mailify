"""Learning loop (Part 7). The signal is free: every edit before send is a
correction, every reject is a softer signal. We capture them, and — batched, not
per-edit — re-distill the bucket's profile once enough new signal accumulates.

Design guarantees the brief asked for:
  * Capture in the action handlers (record_edit / record_reject).
  * Re-distill is BATCHED: only fires at REDISTILL_THRESHOLD unconsumed rows, so
    one weird one-off email can't move the profile.
  * VERSIONED writes: a re-distill appends a new style_profiles row (version+1),
    never overwrites — the owner can see the evolution and roll back.
  * DRIFT GUARD: the re-distill prompt is anchored to the current profile and
    only adjusts it; if the model reports no repeated pattern (changed=False) we
    do NOT write a new version at all.
"""

from __future__ import annotations

import logging

from ..config import REDISTILL_THRESHOLD
from ..db import db
from ..llm.openai_client import redistill_profile

log = logging.getLogger("mailify.learning")

_BUCKET_LABELS = {
    "close_internal": "close/internal — people the owner emails a lot",
    "external_professional": "external/professional — investors, partners, semi-formal",
    "cold_stranger": "cold/stranger — first contact",
}


async def record_edit(*, user_id: str, draft_id: str, bucket: str,
                      original_body: str, final_body: str) -> None:
    """The core learning signal: the diff between what the model wrote and what
    the owner actually sent. Only stored when they actually differ."""
    if original_body.strip() == final_body.strip():
        return
    await db.profilefeedback.create(data={
        "userId": user_id,
        "bucket": bucket,
        "draftId": draft_id,
        "originalBody": original_body,
        "finalBody": final_body,
        "signalType": "edit",
    })
    await maybe_redistill(user_id, bucket)


async def record_reject(*, user_id: str, draft_id: str, bucket: str,
                        original_body: str) -> None:
    """A reject means: wrong to draft this, or wrong tone. Softer signal, but
    still signal."""
    await db.profilefeedback.create(data={
        "userId": user_id,
        "bucket": bucket,
        "draftId": draft_id,
        "originalBody": original_body,
        "finalBody": "",
        "signalType": "reject",
    })
    await maybe_redistill(user_id, bucket)


async def maybe_redistill(user_id: str, bucket: str) -> bool:
    """Trigger a re-distill iff the bucket has accumulated enough unconsumed
    feedback. Returns True if a new profile version was written."""
    unconsumed = await db.profilefeedback.find_many(
        where={"userId": user_id, "bucket": bucket, "consumed": False},
        order={"createdAt": "asc"},
    )
    if len(unconsumed) < REDISTILL_THRESHOLD:
        return False

    current = await db.styleprofile.find_first(
        where={"userId": user_id, "bucket": bucket},
        order={"version": "desc"},
    )
    if not current:
        log.warning("redistill: no base profile for user=%s bucket=%s", user_id, bucket)
        return False

    feedback = [{
        "signal_type": f.signalType,
        "original_body": f.originalBody,
        "final_body": f.finalBody,
    } for f in unconsumed]

    out = await redistill_profile(
        bucket_label=_BUCKET_LABELS.get(bucket, bucket),
        current_profile=current.profileText,
        feedback=feedback,
    )

    ids = [f.id for f in unconsumed]

    if not out["changed"]:
        # Drift guard held: no repeated pattern worth adjusting. Mark the batch
        # consumed so we don't re-run on the same evidence, but keep the profile.
        await db.profilefeedback.update_many(
            where={"id": {"in": ids}}, data={"consumed": True}
        )
        log.info("redistill: no change user=%s bucket=%s notes=%s",
                 user_id, bucket, out["notes"])
        return False

    new_version = current.version + 1
    await db.styleprofile.create(data={
        "userId": user_id,
        "bucket": bucket,
        "version": new_version,
        "profileText": out["profile_text"],
        "source": "redistill",
        "sampleCount": len(feedback),
    })
    await db.profilefeedback.update_many(where={"id": {"in": ids}}, data={"consumed": True})
    log.info("redistill: wrote version=%s user=%s bucket=%s notes=%s",
             new_version, user_id, bucket, out["notes"])
    return True
