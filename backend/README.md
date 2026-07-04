# Mailify — Backend (FastAPI + Prisma/Neon)

## Run locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
python -m app.scripts.gen_keys      # prints FERNET/JWT/VAPID/PUBSUB/CRON secrets → paste into .env

# point DATABASE_URL at Neon, then:
prisma generate
prisma db push                       # creates the tables in Neon

uvicorn app.main:app --reload
```

## Google Cloud setup (one time)

1. **OAuth client** — Create an OAuth 2.0 Web client. Authorized redirect URI =
   `GOOGLE_REDIRECT_URI` (e.g. `http://localhost:8000/auth/gmail/callback`, and your
   Render URL in prod). Put the client id/secret in `.env`. Enable the **Gmail API**.
2. **Pub/Sub topic** — Create a topic; set `GMAIL_PUBSUB_TOPIC` =
   `projects/<project>/topics/<topic>`. Grant Gmail permission to publish:
   give `gmail-api-push@system.gserviceaccount.com` the **Pub/Sub Publisher** role on the topic.
3. **Push subscription** — Create a *push* subscription on that topic with endpoint
   `https://<your-api>/gmail/webhook?token=<PUBSUB_VERIFICATION_TOKEN>`.

Once a user connects Gmail, the backend calls `watch()` automatically and the daily
cron re-arms it (watches expire ~7 days, silently — see `app/gmail/watch.py`).

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/auth/google/login` | Start Google OAuth (sign-in + Gmail) |
| GET | `/auth/gmail/callback` | OAuth callback → stores encrypted refresh token, registers watch, runs taste agent |
| GET | `/auth/me` | Current user + onboarding state |
| POST | `/gmail/webhook` | Pub/Sub push receiver (historyId reconciliation + dedupe) |
| GET | `/drafts` | Pending drafts, newest/most-important first |
| GET | `/drafts/{id}` | One draft + the incoming email |
| POST | `/drafts/{id}/approve` | Send the existing native Gmail draft (idempotent) |
| POST | `/drafts/{id}/reject` | Trash the draft + capture reject signal |
| PATCH | `/drafts/{id}` | Edit body then send + capture the edit diff |
| GET | `/push/vapid-public-key` | VAPID public key for the service worker |
| POST | `/push/subscribe` | Store a PWA push subscription |
| GET | `/profiles` | All style-profile versions (watch your voice evolve) |
| POST | `/profiles/rollback` | Roll a bucket back to an earlier version |
| POST | `/cron/renew-watches` | Daily watch renewal (bearer-protected) |

## Where the risk lives (and where it's handled)

1. **historyId reconciliation** — `app/gmail/history.py` (diff from durable floor; 404 → re-arm).
2. **Watch renewal not dying silently** — `app/gmail/watch.py` (`renew_all_watches` logs ERROR on any failure).
3. **Send idempotency** — `app/routers/drafts.py` (`_claim_pending` atomically flips `pending`→terminal; a double-tap loses the race).
4. **Dedupe** — `app/pipeline/process.py` (`_already_processed` claims the id via a unique constraint).
