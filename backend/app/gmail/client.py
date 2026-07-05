"""Thin async Gmail REST client (httpx). We deliberately avoid the sync
google-api-python-client so nothing blocks the event loop. An instance holds a
short-lived access token minted from the user's encrypted refresh token."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from html import escape
from typing import Any

import httpx
from prisma.models import User

from ..auth.oauth import refresh_access_token
from ..security import decrypt

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailClient:
    def __init__(self, access_token: str):
        self._token = access_token

    # -- construction ---------------------------------------------------------
    @classmethod
    async def for_user(cls, user: User) -> "GmailClient":
        if not user.gmailRefreshTokenEnc:
            raise RuntimeError(f"User {user.id} has no Gmail refresh token")
        access = await refresh_access_token(decrypt(user.gmailRefreshTokenEnc))
        return cls(access)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _request(self, method: str, path: str, **kw) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.request(method, f"{GMAIL_API}{path}", headers=self._headers(), **kw)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    # -- profile / watch ------------------------------------------------------
    async def get_profile(self) -> dict[str, Any]:
        return await self._request("GET", "/profile")

    async def get_signature(self) -> str:
        """The owner's Gmail signature HTML (from settings). Returns the primary
        sendAs's signature, or the first non-empty one, or '' if none is set."""
        data = await self._request("GET", "/settings/sendAs")
        send_as = data.get("sendAs", [])
        primary = next((s for s in send_as if s.get("isPrimary")), None)
        if primary and primary.get("signature"):
            return primary["signature"]
        return next((s["signature"] for s in send_as if s.get("signature")), "")

    async def watch(self, topic_name: str) -> dict[str, Any]:
        """Register a Pub/Sub watch on the mailbox. Returns {historyId, expiration}."""
        return await self._request(
            "POST", "/watch",
            json={"topicName": topic_name, "labelIds": ["INBOX"], "labelFilterBehavior": "include"},
        )

    async def stop_watch(self) -> None:
        await self._request("POST", "/stop")

    # -- history (reconciliation) --------------------------------------------
    async def history_list(self, start_history_id: int, page_token: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "startHistoryId": str(start_history_id),
            "historyTypes": "messageAdded",
            "labelId": "INBOX",
        }
        if page_token:
            params["pageToken"] = page_token
        return await self._request("GET", "/history", params=params)

    # -- messages -------------------------------------------------------------
    async def list_messages(self, q: str, max_results: int) -> list[str]:
        """Return up to `max_results` message ids matching a Gmail search `q`
        (e.g. 'in:sent'), paging as needed."""
        ids: list[str] = []
        page_token: str | None = None
        while len(ids) < max_results:
            params: dict[str, Any] = {"q": q, "maxResults": min(500, max_results - len(ids))}
            if page_token:
                params["pageToken"] = page_token
            page = await self._request("GET", "/messages", params=params)
            ids.extend(m["id"] for m in page.get("messages", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        return ids[:max_results]

    async def get_message(self, message_id: str, fmt: str = "full") -> dict[str, Any]:
        return await self._request("GET", f"/messages/{message_id}", params={"format": fmt})

    async def get_thread(self, thread_id: str, fmt: str = "full") -> dict[str, Any]:
        """The whole conversation, messages oldest-first, so the drafting model
        sees every prior turn — not just the latest incoming message."""
        return await self._request("GET", f"/threads/{thread_id}", params={"format": fmt})

    async def trash_message(self, message_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/messages/{message_id}/trash")

    # -- drafts ---------------------------------------------------------------
    async def create_draft(
        self, *, thread_id: str, to: str, subject: str, body: str,
        in_reply_to: str | None = None, references: str | None = None,
        signature_html: str | None = None,
    ) -> dict[str, Any]:
        """Create a NATIVE Gmail draft (shows up in the user's real Gmail).
        Returns the draft resource including its id."""
        raw = _build_raw(to=to, subject=subject, body=body,
                         in_reply_to=in_reply_to, references=references,
                         signature_html=signature_html)
        return await self._request(
            "POST", "/drafts",
            json={"message": {"raw": raw, "threadId": thread_id}},
        )

    async def update_draft(
        self, draft_id: str, *, thread_id: str, to: str, subject: str, body: str,
        in_reply_to: str | None = None, references: str | None = None,
        signature_html: str | None = None,
    ) -> dict[str, Any]:
        raw = _build_raw(to=to, subject=subject, body=body,
                         in_reply_to=in_reply_to, references=references,
                         signature_html=signature_html)
        return await self._request(
            "PUT", f"/drafts/{draft_id}",
            json={"message": {"raw": raw, "threadId": thread_id}},
        )

    async def send_draft(self, draft_id: str) -> dict[str, Any]:
        """Send an existing native draft. Approve == send-this-existing-draft."""
        return await self._request("POST", "/drafts/send", json={"id": draft_id})

    async def delete_draft(self, draft_id: str) -> None:
        await self._request("DELETE", f"/drafts/{draft_id}")


def _build_raw(
    *, to: str, subject: str, body: str,
    in_reply_to: str | None = None, references: str | None = None,
    signature_html: str | None = None,
) -> str:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    # No signature -> keep the historical plain-text message untouched.
    if not signature_html:
        msg.set_content(body)
        return base64.urlsafe_b64encode(msg.as_bytes()).decode()

    # With a signature we send multipart/alternative: a plain-text part (the
    # reply body, signature omitted) plus an HTML part carrying the reply and the
    # owner's real HTML signature (logo, links, formatting intact).
    msg.set_content(body)
    body_html = escape(body).replace("\n", "<br>\n")
    html = f"<div>{body_html}</div><br>\n{signature_html}"
    msg.add_alternative(html, subtype="html")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()
