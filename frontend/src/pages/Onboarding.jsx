import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";

// Onboarding progress. The taste agent runs server-side after OAuth; we poll
// /auth/me and show a "building your voice" state until it's ready.
const STATES = {
  new: 0,
  connecting: 1,
  profiling: 2,
  ready: 3,
  error: -1,
};

export default function Onboarding({ me }) {
  const nav = useNavigate();
  const [state, setState] = useState(me.onboardingState || "profiling");

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const fresh = await api.me();
        if (!alive) return;
        setState(fresh.onboardingState);
        if (fresh.onboardingComplete) {
          nav("/", { replace: true });
        }
      } catch (_) {
        /* keep polling */
      }
    };
    const id = setInterval(tick, 2500);
    tick();
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [nav]);

  const step = STATES[state] ?? 2;
  const failed = state === "error";

  const rows = [
    { n: 1, t: "Signed in with Google", s: me.email, done: true },
    { n: 2, t: "Connected Gmail", s: "Reading, drafts & push authorized", done: step >= 1 },
    {
      n: 3,
      t: failed ? "Voice profile failed" : "Building your voice profile",
      s: failed
        ? "Something went wrong — try reconnecting."
        : "Reading your sent mail and learning how you write",
      done: step >= 3,
      active: !failed && step < 3,
    },
  ];

  return (
    <div className="shell">
      <div className="topbar">
        <div className="wordmark"><span className="dot" />Mailify</div>
        <span className="pill">Setup</span>
      </div>

      <div className="center">
        {!failed && <div className="spinner" />}
        <h2 className="display" style={{ fontSize: 26, marginTop: 6 }}>
          {failed ? "We hit a snag" : "Learning your voice"}
        </h2>
        <p className="muted">
          {failed
            ? "The taste agent couldn't finish. Reconnect Gmail to retry."
            : "This happens once. Mailify reads a few hundred of your sent emails and builds a style profile for each kind of contact."}
        </p>

        <div className="steps">
          {rows.map((r) => (
            <div key={r.n} className={`step ${r.done ? "done" : ""} ${r.active ? "active" : ""}`}>
              <div className="num">{r.done ? "✓" : r.n}</div>
              <div className="t">
                {r.t}
                <small>{r.s}</small>
              </div>
            </div>
          ))}
        </div>

        {failed && (
          <a className="btn btn-primary" href={api.loginUrl()} style={{ marginTop: 20 }}>
            Reconnect Gmail
          </a>
        )}
      </div>
    </div>
  );
}
