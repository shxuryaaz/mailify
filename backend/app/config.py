"""Central configuration for Mailify. Everything external is an env var — nothing
about credentials or infra is hardcoded. The two product decisions the owner
reserved for himself (DRAFT_MODE, REDISTILL_THRESHOLD) live here as named
constants that everything downstream reads."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


# ─────────────────────────────────────────────────────────────────────────────
# The one decision the owner left open (Part 4).
#
#   "reply_worthy"      → draft for anything the model flags worth replying to.
#   "high_priority_only" → only draft when importance is high.
#
# Flip this single constant; the pipeline (app/pipeline/process.py) is the only
# reader and gates purely on it. Importance still rides on every draft for
# ordering regardless of the mode, and — critically — notifications fire either
# way (a buried important email is the expensive failure).
# ─────────────────────────────────────────────────────────────────────────────
DRAFT_MODE: str = os.getenv("DRAFT_MODE", "reply_worthy")

# importance (0..100) at/above which "high_priority_only" mode will draft.
HIGH_PRIORITY_THRESHOLD: int = int(os.getenv("HIGH_PRIORITY_THRESHOLD", "70"))

# Learning loop (Part 7): re-distill a bucket's profile once it accumulates this
# many *unconsumed* feedback rows. Start at 5. Batched on purpose — reacting per
# edit overfits to one weird email.
REDISTILL_THRESHOLD: int = int(os.getenv("REDISTILL_THRESHOLD", "5"))

# Taste agent (Part 2): how many sent messages to sample at onboarding.
ONBOARDING_SENT_SAMPLE: int = int(os.getenv("ONBOARDING_SENT_SAMPLE", "300"))

# Bucket identifiers — used as DB keys and in prompts. Keep in sync with the
# taste agent and the pipeline's bucket inference.
BUCKET_CLOSE = "close_internal"
BUCKET_EXTERNAL = "external_professional"
BUCKET_COLD = "cold_stranger"
BUCKETS = (BUCKET_CLOSE, BUCKET_EXTERNAL, BUCKET_COLD)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "Mailify"
    environment: str = os.getenv("ENVIRONMENT", "development")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

    # Neon / Postgres (Prisma reads DATABASE_URL itself)
    database_url: str = os.getenv("DATABASE_URL", "")

    # OpenAI
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")

    # Crypto — Fernet key encrypts the Gmail refresh token at rest; JWT secret
    # signs our own session tokens.
    fernet_key: str = os.getenv("FERNET_KEY", "")
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    jwt_ttl_hours: int = int(os.getenv("JWT_TTL_HOURS", "720"))  # 30 days

    # Google OAuth (app sign-in + Gmail authorization share the client)
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/gmail/callback"
    )

    # Gmail Pub/Sub push
    gmail_pubsub_topic: str = os.getenv("GMAIL_PUBSUB_TOPIC", "")
    # Shared secret appended as ?token=... to the push subscription so we can
    # reject spoofed calls to /gmail/webhook without a full JWT verify.
    pubsub_verification_token: str = os.getenv("PUBSUB_VERIFICATION_TOKEN", "")

    # Web Push (VAPID)
    vapid_public_key: str = os.getenv("VAPID_PUBLIC_KEY", "")
    vapid_private_key: str = os.getenv("VAPID_PRIVATE_KEY", "")
    vapid_subject: str = os.getenv("VAPID_SUBJECT", "mailto:you@example.com")

    # Cron auth — the daily watch-renewal endpoint checks this bearer.
    cron_secret: str = os.getenv("CRON_SECRET", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Gmail OAuth scopes: read messages, create/send drafts, and register a watch().
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",  # create/update/send drafts
    "https://www.googleapis.com/auth/gmail.modify",   # trash, watch
    "https://www.googleapis.com/auth/gmail.settings.basic",  # read the user's signature
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
