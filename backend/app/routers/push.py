"""Push subscription management (Part 5).

  GET  /push/vapid-public-key  -> the key the service worker needs to subscribe
  POST /push/subscribe         -> store a PWA PushSubscription
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from prisma.models import User
from pydantic import BaseModel

from ..config import settings
from ..db import db
from ..deps import current_user

router = APIRouter(prefix="/push", tags=["push"])


class SubscribeBody(BaseModel):
    subscription: dict  # the full PushSubscription JSON (endpoint + keys)


@router.get("/vapid-public-key")
async def vapid_public_key():
    return {"publicKey": settings.vapid_public_key}


@router.post("/subscribe")
async def subscribe(body: SubscribeBody, user: User = Depends(current_user)):
    endpoint = body.subscription.get("endpoint")
    if not endpoint:
        return {"status": "error", "detail": "missing endpoint"}
    # Endpoint is unique — upsert so re-subscribing (new key rotation) is clean.
    await db.pushsubscription.upsert(
        where={"endpoint": endpoint},
        data={
            "create": {"userId": user.id, "endpoint": endpoint, "subscription": body.subscription},
            "update": {"userId": user.id, "subscription": body.subscription},
        },
    )
    return {"status": "subscribed"}
