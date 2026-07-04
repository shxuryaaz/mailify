"""Single shared Prisma client. Connected on FastAPI startup, disconnected on
shutdown (see app/main.py)."""

from __future__ import annotations

from prisma import Prisma

db = Prisma()


async def connect() -> None:
    if not db.is_connected():
        await db.connect()


async def disconnect() -> None:
    if db.is_connected():
        await db.disconnect()
