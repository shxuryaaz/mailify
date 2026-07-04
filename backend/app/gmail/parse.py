"""Pull the fields the pipeline needs out of a Gmail message resource:
headers, a plaintext body, and a compact thread rendering for the LLM."""

from __future__ import annotations

import base64
from typing import Any


def _header(payload: dict[str, Any], name: str) -> str:
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode(data: str) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _extract_text(payload: dict[str, Any]) -> str:
    """Walk the MIME tree; prefer text/plain, fall back to stripped text/html."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    if mime == "text/plain" and body.get("data"):
        return _decode(body["data"])
    if mime.startswith("multipart/"):
        # prefer plain, then anything with text
        parts = payload.get("parts", [])
        for want in ("text/plain", "text/html"):
            for part in parts:
                if part.get("mimeType") == want and part.get("body", {}).get("data"):
                    txt = _decode(part["body"]["data"])
                    return _strip_html(txt) if want == "text/html" else txt
        # nested multipart
        for part in parts:
            txt = _extract_text(part)
            if txt:
                return txt
    if mime == "text/html" and body.get("data"):
        return _strip_html(_decode(body["data"]))
    return ""


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_message(msg: dict[str, Any]) -> dict[str, Any]:
    payload = msg.get("payload", {})
    return {
        "id": msg.get("id", ""),
        "thread_id": msg.get("threadId", ""),
        "from": _header(payload, "From"),
        "to": _header(payload, "To"),
        "subject": _header(payload, "Subject"),
        "message_id_header": _header(payload, "Message-ID"),
        "references": _header(payload, "References"),
        "snippet": msg.get("snippet", ""),
        "body": _extract_text(payload),
        "label_ids": msg.get("labelIds", []),
    }


def sender_email(from_header: str) -> str:
    """Extract bare address from a 'Name <addr@x.com>' header."""
    import re
    m = re.search(r"<([^>]+)>", from_header)
    return (m.group(1) if m else from_header).strip().lower()
