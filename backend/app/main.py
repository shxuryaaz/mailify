"""Mailify FastAPI app entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import connect, disconnect
from .routers import auth, cron, drafts, gmail_webhook, profiles, push

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    yield
    await disconnect()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every response carries the app name in a header (brief: "Mailify everywhere").
@app.middleware("http")
async def add_app_header(request, call_next):
    response = await call_next(request)
    response.headers["X-Mailify"] = settings.app_name
    return response


@app.get("/")
async def root():
    return {"app": settings.app_name, "status": "ok"}


@app.get("/healthz")
async def healthz():
    return {"status": "healthy"}


app.include_router(auth.router)
app.include_router(gmail_webhook.router)
app.include_router(drafts.router)
app.include_router(push.router)
app.include_router(profiles.router)
app.include_router(cron.router)
