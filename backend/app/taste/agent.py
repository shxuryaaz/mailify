"""Taste agent (Part 2). Runs ONCE at onboarding. Reads ~300 sent emails,
buckets them by recipient relationship, and distills one compact style profile
per bucket into Neon as version 1. This is the expensive step — draft time never
re-reads sent mail; it reads the stored profile.

Bucketing heuristic (no LLM needed for the split — send frequency + first-contact
signal do it): count how often the owner has emailed each address.
  - close_internal        : addresses emailed frequently, or on the owner's own domain
  - cold_stranger         : addresses emailed exactly once (first contact)
  - external_professional : everyone in between
The LLM then captures the *tone* of each bucket during distillation.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict

from prisma.models import User

from ..config import (BUCKET_CLOSE, BUCKET_COLD, BUCKET_EXTERNAL,
                      ONBOARDING_SENT_SAMPLE, settings)
from ..db import db
from ..gmail.client import GmailClient
from ..gmail.parse import parse_message, sender_email
from ..llm.openai_client import distill_profile

log = logging.getLogger("mailify.taste")

CLOSE_FREQUENCY_MIN = 5  # emailed this often -> close/internal
_BUCKET_LABELS = {
    BUCKET_CLOSE: "close/internal — people the owner emails a lot",
    BUCKET_EXTERNAL: "external/professional — investors, partners, semi-formal",
    BUCKET_COLD: "cold/stranger — first contact",
}


def _recipient(to_header: str) -> str:
    # First address on the To line is a good enough proxy for the relationship.
    first = to_header.split(",")[0] if to_header else ""
    return sender_email(first)


def _bucket_for(addr: str, freq: int, owner_domain: str) -> str:
    if not addr:
        return BUCKET_EXTERNAL
    domain = addr.split("@")[-1] if "@" in addr else ""
    if domain and domain == owner_domain:
        return BUCKET_CLOSE
    if freq >= CLOSE_FREQUENCY_MIN:
        return BUCKET_CLOSE
    if freq <= 1:
        return BUCKET_COLD
    return BUCKET_EXTERNAL


async def build_profiles(user: User) -> dict:
    """Full onboarding run. Idempotent-ish: writes fresh version-1 profiles.
    Sets onboardingState as it progresses so the UI can show 'building your voice'."""
    await db.user.update(where={"id": user.id}, data={"onboardingState": "profiling"})
    owner_domain = user.email.split("@")[-1].lower() if "@" in user.email else ""

    try:
        gmail = await GmailClient.for_user(user)
        sent_ids = await gmail.list_messages("in:sent", ONBOARDING_SENT_SAMPLE)
        log.info("taste: fetched %s sent ids for user=%s", len(sent_ids), user.id)

        # Publish the total up front so the setup screen can show a real bar, and
        # reset the counter (this run starts fresh).
        total = len(sent_ids)
        await db.user.update(where={"id": user.id},
                             data={"onboardingTotal": total, "onboardingProcessed": 0})

        # Fetch bodies (bounded concurrency to be gentle on Gmail quota). Flush the
        # processed count to the DB every few emails so the frontend poll sees it
        # climb — not on every email (that'd be ~300 needless writes).
        sem = asyncio.Semaphore(8)
        progress = {"done": 0}
        lock = asyncio.Lock()
        PROGRESS_FLUSH_EVERY = 10

        async def _fetch(mid: str):
            async with sem:
                try:
                    result = parse_message(await gmail.get_message(mid))
                except Exception:  # noqa: BLE001
                    result = None
            async with lock:
                progress["done"] += 1
                done = progress["done"]
            if done % PROGRESS_FLUSH_EVERY == 0 or done == total:
                await db.user.update(where={"id": user.id},
                                     data={"onboardingProcessed": done})
            return result

        parsed = [p for p in await asyncio.gather(*(_fetch(m) for m in sent_ids)) if p]

        # Frequency per recipient.
        freq: Counter[str] = Counter()
        for p in parsed:
            addr = _recipient(p["to"])
            if addr:
                freq[addr] += 1

        # Group bodies by bucket.
        by_bucket: dict[str, list[str]] = defaultdict(list)
        for p in parsed:
            addr = _recipient(p["to"])
            body = (p["body"] or p["snippet"] or "").strip()
            if not body:
                continue
            bucket = _bucket_for(addr, freq.get(addr, 0), owner_domain)
            by_bucket[bucket].append(body)

        # Distill each bucket that has any material. Buckets with no samples get a
        # sensible default so draft time always finds a profile.
        results: dict[str, str] = {}
        for bucket, label in _BUCKET_LABELS.items():
            samples = by_bucket.get(bucket, [])
            if samples:
                profile_text = await distill_profile(label, samples)
            else:
                profile_text = _default_profile(bucket)
            await db.styleprofile.create(data={
                "userId": user.id,
                "bucket": bucket,
                "version": 1,
                "profileText": profile_text,
                "source": "onboarding",
                "sampleCount": len(samples),
            })
            results[bucket] = profile_text
            log.info("taste: distilled bucket=%s samples=%s user=%s",
                     bucket, len(samples), user.id)

        await db.user.update(where={"id": user.id},
                             data={"onboardingState": "ready", "onboardingComplete": True})
        return {"buckets": {b: len(by_bucket.get(b, [])) for b in _BUCKET_LABELS}}

    except Exception as exc:  # noqa: BLE001
        log.error("taste: onboarding failed user=%s error=%s", user.id, exc, exc_info=True)
        await db.user.update(where={"id": user.id}, data={"onboardingState": "error"})
        raise


def _default_profile(bucket: str) -> str:
    return {
        BUCKET_CLOSE: "Warm, brief, and informal. Often skips a greeting and dives in. "
                      "Short sentences, casual sign-off or none.",
        BUCKET_EXTERNAL: "Professional and clear, moderately formal. Opens with a brief "
                         "greeting, gets to the point, polite sign-off.",
        BUCKET_COLD: "Courteous and concise first-contact tone. Clear greeting, states "
                     "purpose plainly, formal sign-off.",
    }[bucket]
