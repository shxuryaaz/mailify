"""Google OAuth 2.0 helpers. One consent flow does double duty (Part 1):
identity (Google Sign-In) AND Gmail authorization (read, drafts, watch). We ask
for offline access + consent prompt so Google returns a refresh token, which we
store encrypted."""

from __future__ import annotations

import urllib.parse
from typing import Any

import httpx

from ..config import GMAIL_SCOPES, settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def consent_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",     # -> refresh token
        "prompt": "consent",          # force refresh token even on re-auth
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str) -> dict[str, Any]:
    """Trade the authorization code for access + refresh tokens."""
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> str:
    """Exchange a stored refresh token for a fresh short-lived access token.
    Called on every Gmail API interaction — access tokens are never persisted."""
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def fetch_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()
