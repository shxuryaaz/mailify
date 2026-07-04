"""Auth endpoints (Part 1). Real Google OAuth — not a hardcoded user — even
though this is a single-user tool.

  GET /auth/google/login    -> redirect to Google consent
  GET /auth/gmail/callback  -> exchange code, upsert user, encrypt+store refresh
                               token, register watch, kick off taste agent, then
                               redirect back to the PWA with our session JWT.
  GET /auth/me              -> who am I / onboarding state
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from prisma.models import User

from ..auth.oauth import consent_url, exchange_code, fetch_userinfo
from ..config import settings
from ..db import db
from ..deps import current_user
from ..gmail.client import GmailClient
from ..gmail.watch import register_watch
from ..security import encrypt, issue_jwt
from ..taste.agent import build_profiles

log = logging.getLogger("mailify.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google/login")
async def google_login():
    state = secrets.token_urlsafe(16)
    return RedirectResponse(consent_url(state))


@router.get("/gmail/callback")
async def gmail_callback(request: Request, background: BackgroundTasks):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(400, "Missing authorization code")

    tokens = await exchange_code(code)
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    info = await fetch_userinfo(access_token)

    email = info["email"].lower()
    google_sub = info["sub"]

    existing = await db.user.find_unique(where={"googleSub": google_sub})
    data = {
        "email": email,
        "googleSub": google_sub,
        "name": info.get("name"),
        "pictureUrl": info.get("picture"),
        "gmailConnected": True,
    }
    # Only overwrite the stored refresh token if Google actually returned one
    # (it does on first consent / prompt=consent).
    if refresh_token:
        data["gmailRefreshTokenEnc"] = encrypt(refresh_token)

    # Refresh the stored signature on every sign-in so drafts track whatever the
    # owner currently has set in Gmail. Best-effort — never block auth on it.
    try:
        data["signatureHtml"] = await GmailClient(access_token).get_signature()
    except Exception as exc:  # noqa: BLE001
        log.warning("callback: could not fetch signature user=%s error=%s", email, exc)

    if existing:
        user = await db.user.update(where={"id": existing.id}, data=data)
    else:
        data["onboardingState"] = "connecting"
        user = await db.user.create(data=data)

    # Register the Pub/Sub watch immediately so live mail starts flowing.
    try:
        await register_watch(user)
    except Exception as exc:  # noqa: BLE001
        log.error("callback: watch registration failed user=%s error=%s", user.id, exc)

    # Run the (expensive, one-time) taste agent in the background unless already done.
    if not user.onboardingComplete:
        background.add_task(_run_onboarding, user.id)

    token = issue_jwt(user.id)
    # Hand the JWT back to the PWA via URL fragment (kept out of server logs).
    return RedirectResponse(f"{settings.frontend_origin}/auth/callback#token={token}")


async def _run_onboarding(user_id: str) -> None:
    user = await db.user.find_unique(where={"id": user_id})
    if user:
        try:
            await build_profiles(user)
        except Exception as exc:  # noqa: BLE001
            log.error("onboarding task failed user=%s error=%s", user_id, exc)


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "pictureUrl": user.pictureUrl,
        "gmailConnected": user.gmailConnected,
        "onboardingComplete": user.onboardingComplete,
        "onboardingState": user.onboardingState,
    }
