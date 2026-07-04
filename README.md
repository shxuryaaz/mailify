# Mailify

An AI email agent. It watches your Gmail, drafts replies in your voice, pushes them to
your phone, and you approve / reject / edit before anything sends. Human-in-the-loop —
**nothing goes out without your tap.**

```
Gmail  ──push──▶  FastAPI (Render)  ──1 Claude call──▶  native Gmail draft + DB row
                        │                                          │
                        └──────────── Web Push (VAPID) ────────────┘
                                          │
                                   Installed PWA (Vercel)
                              Approve · Reject · Edit → send
```

- **Backend:** FastAPI on Render
- **DB:** Neon (Postgres) via Prisma
- **Frontend:** React + Vite on Vercel, installable PWA
- **LLM:** OpenAI API (your own key)
- **Email:** Gmail API + Gmail Pub/Sub push
- **Push:** Web Push (VAPID) to the installed PWA

## Layout

```
mailify/
  backend/    FastAPI app, Prisma schema, cron jobs, Render config
  frontend/   React + Vite PWA, service worker, manifest
```

## Quickstart

See [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md).
The short version:

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in the values (see below)
python -m app.scripts.gen_keys  # prints a fresh VAPID keypair + Fernet key
prisma generate && prisma db push
uvicorn app.main:app --reload

# frontend
cd frontend
npm install
cp .env.example .env            # point VITE_API_BASE at the backend
npm run dev
```

## What you must supply (the secrets)

Everything external is behind env vars — nothing is hardcoded. You need:

| Secret | Where it comes from |
| --- | --- |
| `DATABASE_URL` | Neon connection string |
| `OPENAI_API_KEY` | OpenAI API |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google Cloud OAuth client |
| `GMAIL_PUBSUB_TOPIC` | Google Cloud Pub/Sub topic the watch pushes to |
| `PUBSUB_VERIFICATION_TOKEN` | shared secret you set on the push subscription |
| `FERNET_KEY` | `python -m app.scripts.gen_keys` |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` | `python -m app.scripts.gen_keys` |
| `JWT_SECRET` | any long random string |

The Google Cloud setup (OAuth consent screen, Pub/Sub topic + push subscription pointed
at `POST /gmail/webhook`, and granting the Gmail service account publish rights) is
documented in [backend/README.md](backend/README.md).

## The one decision left to you

`DRAFT_MODE` in [backend/app/config.py](backend/app/config.py) — defaults to
`"reply_worthy"`. Flip to `"high_priority_only"` in that one constant. Everything
downstream reads the flag.
