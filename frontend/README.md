# Mailify — Frontend (React + Vite PWA)

Installable PWA. Dark, premium UI. Spline animated background on the landing/onboarding
screen; the working views (inbox, draft detail) stay clean and fast.

## Run locally

```bash
cd frontend
npm install
cp .env.example .env      # set VITE_API_BASE and VITE_VAPID_PUBLIC_KEY
npm run dev               # http://localhost:5173
```

`npm run build` outputs static assets to `dist/` for Vercel.

## PWA / push notes

- `public/manifest.json` — name **Mailify**, standalone display, maskable icons.
- `public/sw.js` — hand-written service worker: receives push, deep-links the tap to
  `/draft/:id`.
- **iOS reality:** web push only fires when the PWA is **installed to the home screen**
  (iOS 16.4+). A Safari tab won't receive push. `src/push.js` detects standalone mode and
  the inbox shows an install-first banner on iOS instead of a button that would silently
  do nothing.

## Routes

| Route | View |
| --- | --- |
| `/welcome` | Landing + Google sign-in (Spline background) |
| `/auth/callback` | Captures the JWT from the OAuth redirect fragment |
| `/` | Gate → Onboarding progress (taste agent) → Inbox (pending drafts) |
| `/draft/:id` | Full incoming email + draft, with Approve / Reject / Edit |

## Deploy (Vercel)

Set the project root to `frontend/`, build command `npm run build`, output `dist`.
Add `VITE_API_BASE` (your Render URL) and `VITE_VAPID_PUBLIC_KEY` as env vars. `vercel.json`
handles SPA rewrites and the service-worker headers.
