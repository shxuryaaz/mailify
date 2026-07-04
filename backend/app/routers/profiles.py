"""Style-profile inspection + rollback (Part 7). Versions are append-only, so
'rollback' is just writing a new version whose text is copied from an older one."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from prisma.models import User
from pydantic import BaseModel

from ..config import BUCKETS
from ..db import db
from ..deps import current_user

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("")
async def list_profiles(user: User = Depends(current_user)):
    """All versions for every bucket, newest first — the owner can watch the
    voice model evolve."""
    out: dict[str, list] = {}
    for bucket in BUCKETS:
        rows = await db.styleprofile.find_many(
            where={"userId": user.id, "bucket": bucket},
            order={"version": "desc"},
        )
        out[bucket] = [{
            "version": r.version,
            "source": r.source,
            "sampleCount": r.sampleCount,
            "profileText": r.profileText,
            "createdAt": r.createdAt.isoformat(),
        } for r in rows]
    return out


class EditBody(BaseModel):
    bucket: str
    profileText: str


@router.post("/edit")
async def edit_profile(body: EditBody, user: User = Depends(current_user)):
    """Owner hand-edits their voice for a bucket. Appended as a new 'manual'
    version — because draft time and the learning loop both read the newest
    version, the edit takes effect on the next draft and becomes the anchor the
    loop refines from. Never overwrites history."""
    if body.bucket not in BUCKETS:
        raise HTTPException(400, "Unknown bucket")
    text = body.profileText.strip()
    if not text:
        raise HTTPException(400, "Profile text cannot be empty")
    newest = await db.styleprofile.find_first(
        where={"userId": user.id, "bucket": body.bucket}, order={"version": "desc"}
    )
    new_version = (newest.version if newest else 0) + 1
    created = await db.styleprofile.create(data={
        "userId": user.id,
        "bucket": body.bucket,
        "version": new_version,
        "profileText": text,
        "source": "manual",
        "sampleCount": newest.sampleCount if newest else 0,
    })
    return {"bucket": body.bucket, "version": created.version, "profileText": text,
            "source": created.source, "createdAt": created.createdAt.isoformat()}


class RollbackBody(BaseModel):
    bucket: str
    version: int


@router.post("/rollback")
async def rollback(body: RollbackBody, user: User = Depends(current_user)):
    if body.bucket not in BUCKETS:
        raise HTTPException(400, "Unknown bucket")
    target = await db.styleprofile.find_first(
        where={"userId": user.id, "bucket": body.bucket, "version": body.version}
    )
    if not target:
        raise HTTPException(404, "Version not found")
    newest = await db.styleprofile.find_first(
        where={"userId": user.id, "bucket": body.bucket}, order={"version": "desc"}
    )
    new_version = (newest.version if newest else 0) + 1
    created = await db.styleprofile.create(data={
        "userId": user.id,
        "bucket": body.bucket,
        "version": new_version,
        "profileText": target.profileText,
        "source": f"rollback:v{body.version}",
        "sampleCount": target.sampleCount,
    })
    return {"bucket": body.bucket, "newVersion": created.version, "restoredFrom": body.version}
