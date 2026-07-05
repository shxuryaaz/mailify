"""OpenAI wrapper for Mailify's three LLM jobs:

  1. distill_profile   — onboarding taste agent, one call per bucket (Part 2)
  2. draft_reply       — the live pipeline's single call: {importance, should_draft,
                         draft_body} as strict JSON (Part 4)
  3. redistill_profile — the learning loop's batched, drift-guarded sharpen (Part 7)

All three use the async OpenAI client with JSON-mode responses so we never hand
free-text back to the caller. The model id is a config constant (settings.openai_model).
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI

from ..config import settings

_client: AsyncOpenAI | None = None


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def _json_chat(system: str, user: str, *, max_tokens: int = 1200) -> dict[str, Any]:
    """One JSON-mode chat call. Returns the parsed object (or raises)."""
    resp = await client().chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        temperature=0.4,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    return json.loads(content)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Taste agent — distill a compact style profile for one bucket.
# ─────────────────────────────────────────────────────────────────────────────
DISTILL_SYSTEM = """You analyze how one specific person writes emails, so an AI can \
later draft replies that sound exactly like them.

You are given a batch of emails THIS PERSON SENT to one relationship bucket \
(e.g. close/internal colleagues, external/professional contacts, or cold/first-contact).

Produce a SHORT style profile — a description, not a transcript. Capture only what a \
ghost-writer would need:
- typical length (very short / short / medium / long)
- formality and register
- whether they open with a greeting or dive straight in
- typical sign-off
- how they say no / push back
- how they hedge, or whether they don't
- any recurring quirks (lowercase, dashes, emoji, one-liners, etc.)

Keep it under ~150 words. Return JSON: {"profile_text": "..."}."""


# Lines that mark the start of a quoted reply chain. The owner's *own* writing is
# above these; everything below is someone else's email we don't want polluting a
# style profile (and, more urgently, what balloons a sent email to tens of
# thousands of tokens). We cut at the FIRST of these — once quoting begins,
# nothing below is the owner's own voice.
_QUOTE_MARKERS = re.compile(
    r"^\s*("
    r"On\b.*\bwrote:\s*$"          # Gmail/Apple attribution: "On <date> X wrote:"
    r"|.*\bwrote:\s*$"             # …even when the date line soft-wraps first
    r"|-{2,}\s*Original Message\s*-{2,}"   # Outlook
    r"|_{5,}"                       # Outlook horizontal rule before header block
    r"|From:\s*.+<[^>]+>\s*$"       # a real quoted 'From: Name <addr>' header line
    r"|(?:Sent|Date|To|Cc|Subject):\s.+"   # rest of the quoted header block
    r"|Sent from my \w+"           # mobile signature that precedes the quote
    r")",
    re.IGNORECASE,
)


def _own_text(body: str) -> str:
    """Keep only what the owner actually typed: everything above the first quoted
    reply. Cut at a quote marker OR the first '>'-quoted line — for HTML emails the
    quoted block has no '>' prefix, so the marker is the only signal; for plaintext
    the '>' is, so we honor whichever comes first."""
    kept: list[str] = []
    for ln in body.splitlines():
        if _QUOTE_MARKERS.match(ln) or ln.lstrip().startswith(">"):
            break
        kept.append(ln)
    return "\n".join(kept).strip()


# Backstop caps so a few pathologically long emails can't blow past the model's
# context window (~128k tokens ≈ 4 chars/token). With quotes stripped, 4000 chars
# is a very generous ceiling for one person's own writing in a single email.
_DISTILL_PER_EMAIL_CHARS = 4000
_DISTILL_TOTAL_CHARS = 240_000


async def distill_profile(bucket_label: str, sent_samples: list[str]) -> str:
    packed: list[str] = []
    used = 0
    for raw in sent_samples[:80]:
        s = _own_text(raw)[:_DISTILL_PER_EMAIL_CHARS]
        if not s:
            continue
        if used + len(s) > _DISTILL_TOTAL_CHARS:
            break
        packed.append(s)
        used += len(s)
    joined = "\n\n---\n\n".join(packed)
    user = f"Relationship bucket: {bucket_label}\n\nEmails they sent:\n\n{joined}"
    out = await _json_chat(DISTILL_SYSTEM, user, max_tokens=600)
    return (out.get("profile_text") or "").strip()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Live pipeline — the single draft call. Strict JSON contract.
# ─────────────────────────────────────────────────────────────────────────────
DRAFT_SYSTEM = """You are the drafting engine for a human-in-the-loop email agent. \
The owner reads and approves every draft before it sends — so draft in their voice, \
but never invent facts (prices, dates, commitments) you don't have. If a fact is \
needed and unknown, leave a clearly bracketed placeholder like [confirm date].

The owner's name is given to you. Sign off with their actual name — NEVER write a \
[Your Name] placeholder, and never leave the sign-off blank. Match the style profile \
for how they sign off (e.g. first name only for close contacts, full name for formal \
ones); if the profile is silent, use their first name.

You are given: the owner's identity, their style profile for this sender's relationship \
bucket, and the incoming email thread. Decide three things and return them as JSON:

- "importance": integer 0-100. How much this email matters to the owner. Used ONLY for \
  ordering and prioritization — NOT for whether to notify. Be calibrated: newsletters \
  and automated notices are low; a real person asking something time-sensitive is high.
- "should_draft": boolean. True if this email is worth the owner replying to at all \
  (a real message that wants a response). False for no-reply notifications, spam, \
  receipts, FYIs that need no answer.
- "draft_body": string. If should_draft is true, a complete reply in the owner's voice \
  matching the style profile, ready to send after approval. Plain text, no subject line, \
  no "Draft:" preamble. If should_draft is false, an empty string.

Return exactly {"importance": int, "should_draft": bool, "draft_body": str}."""


async def draft_reply(
    *, style_profile: str, thread_text: str, sender: str,
    owner_name: str = "", owner_email: str = "",
) -> dict[str, Any]:
    owner_line = owner_name or owner_email or "(unknown — do NOT guess; use their first name if it appears in the thread)"
    user = (
        f"Owner (you are writing AS this person): {owner_line}"
        + (f" <{owner_email}>" if owner_name and owner_email else "")
        + "\n\n"
        f"Owner's style profile for this sender's bucket:\n{style_profile}\n\n"
        f"Sender: {sender}\n\n"
        f"Incoming thread (most recent last):\n{thread_text}"
    )
    out = await _json_chat(DRAFT_SYSTEM, user, max_tokens=1400)
    # Normalize / defend the contract.
    importance = int(out.get("importance", 0) or 0)
    importance = max(0, min(100, importance))
    should_draft = bool(out.get("should_draft", False))
    draft_body = (out.get("draft_body") or "").strip()
    if not should_draft:
        draft_body = ""
    return {
        "importance": importance,
        "should_draft": should_draft,
        "draft_body": draft_body,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Learning loop — sharpen an existing profile from recent edits/rejects.
#    Drift-guarded: anchored to the current profile, only ADJUSTS it.
# ─────────────────────────────────────────────────────────────────────────────
REDISTILL_SYSTEM = """You refine a person's email STYLE PROFILE using evidence of how \
they actually edited or rejected AI-drafted replies.

Critical rules:
- You are ANCHORED to the CURRENT profile. It was built from hundreds of real sent \
  emails. Only ADJUST it — never rewrite from scratch off a handful of edits.
- Adjust ONLY for patterns that repeat across multiple examples (e.g. they keep cutting \
  the greeting, keep shortening, keep softening a hard no). IGNORE one-off changes and \
  outliers — a run of unusual emails must not nuke a profile.
- Keep it short (under ~150 words), same shape as the input profile.

Each edit example shows what the model wrote (ORIGINAL) and what the owner actually sent \
(FINAL). Each reject shows a draft the owner threw away entirely (signal that the tone or \
the decision to draft was wrong).

Return JSON: {"profile_text": "...", "changed": bool, "notes": "one line on what you \
adjusted, or why you left it unchanged"}."""


async def redistill_profile(
    *, bucket_label: str, current_profile: str, feedback: list[dict[str, str]]
) -> dict[str, Any]:
    lines: list[str] = []
    for i, f in enumerate(feedback, 1):
        if f.get("signal_type") == "reject":
            lines.append(f"[{i}] REJECT — draft discarded:\nORIGINAL: {f.get('original_body','')}")
        else:
            lines.append(
                f"[{i}] EDIT:\nORIGINAL: {f.get('original_body','')}\n"
                f"FINAL (what they sent): {f.get('final_body','')}"
            )
    user = (
        f"Relationship bucket: {bucket_label}\n\n"
        f"CURRENT profile:\n{current_profile}\n\n"
        f"Recent feedback ({len(feedback)} items):\n\n" + "\n\n".join(lines)
    )
    out = await _json_chat(REDISTILL_SYSTEM, user, max_tokens=700)
    new_text = (out.get("profile_text") or "").strip()
    return {
        "profile_text": new_text or current_profile,
        "changed": bool(out.get("changed", False)) and bool(new_text),
        "notes": (out.get("notes") or "").strip(),
    }
