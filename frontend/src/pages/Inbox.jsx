import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { enablePush, isIOS, isStandalone, pushSupported } from "../push.js";

function ImportanceMeter({ value }) {
  return (
    <span className="imp">
      <span className="bar"><span style={{ width: `${value}%` }} /></span>
      {value}
    </span>
  );
}

// A dismissible banner that walks the user through enabling push — including the
// iOS "install to home screen first" reality.
function PushBanner() {
  const [status, setStatus] = useState(null);
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem("mailify_push_dismissed") === "1"
  );

  if (dismissed || !pushSupported()) return null;
  if (status === "subscribed") return null;

  const iosNeedsInstall = isIOS() && !isStandalone();

  const onEnable = async () => {
    const result = await enablePush();
    setStatus(result);
    if (result === "subscribed") {
      // no-op; banner hides
    }
  };

  const dismiss = () => {
    localStorage.setItem("mailify_push_dismissed", "1");
    setDismissed(true);
  };

  return (
    <div className="banner">
      <span className="x">🔔</span>
      <div style={{ flex: 1 }}>
        {iosNeedsInstall ? (
          <>
            <b>Install Mailify to get push.</b> On iPhone, tap the Share icon →{" "}
            <b>Add to Home Screen</b>, then open Mailify from your home screen and enable
            notifications. (iOS only delivers push to installed apps.)
          </>
        ) : status === "denied" ? (
          <>Notifications are blocked. Enable them in your browser settings to get pinged for new drafts.</>
        ) : status === "no-key" ? (
          <>Push isn't configured on the server yet (missing VAPID key).</>
        ) : (
          <>
            <b>Turn on notifications</b> so Mailify can ping you the moment a draft is ready.
          </>
        )}
        {!iosNeedsInstall && status !== "denied" && (
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <button className="btn btn-primary" style={{ padding: "10px 16px" }} onClick={onEnable}>
              Enable notifications
            </button>
            <button className="btn btn-danger" style={{ padding: "10px 14px" }} onClick={dismiss}>
              Later
            </button>
          </div>
        )}
        {iosNeedsInstall && (
          <div style={{ marginTop: 10 }}>
            <button className="btn btn-danger" style={{ padding: "10px 14px" }} onClick={dismiss}>
              Dismiss
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function fmtSent(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export default function Inbox({ me }) {
  const [tab, setTab] = useState("pending"); // "pending" | "sent"
  const [drafts, setDrafts] = useState(null);
  const [sent, setSent] = useState(null);
  const [error, setError] = useState(false);

  const load = async () => {
    try {
      setDrafts(await api.listDrafts());
    } catch (_) {
      setError(true);
    }
  };

  const loadSent = async () => {
    try {
      setSent(await api.listSent());
    } catch (_) {
      setError(true);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 15000); // refresh in case a push arrived
    const onVis = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  // Load the sent log the first time the tab is opened, and whenever it's shown.
  useEffect(() => {
    if (tab === "sent") loadSent();
  }, [tab]);

  return (
    <div className="shell">
      <div className="topbar">
        <div className="wordmark"><span className="dot" />Mailify</div>
        <span className="pill">{me.email}</span>
      </div>

      <PushBanner />

      <div className="tabs">
        <button
          className={`tab ${tab === "pending" ? "tab-active" : ""}`}
          onClick={() => setTab("pending")}
        >
          Pending{drafts ? ` · ${drafts.length}` : ""}
        </button>
        <button
          className={`tab ${tab === "sent" ? "tab-active" : ""}`}
          onClick={() => setTab("sent")}
        >
          Sent{sent ? ` · ${sent.length}` : ""}
        </button>
      </div>

      {tab === "pending" && (
        <>
          {drafts === null && !error && (
            <div className="center"><div className="spinner" /></div>
          )}

          {error && drafts === null && (
            <div className="center">
              <div className="empty-emoji">⚠️</div>
              <div className="muted">Couldn't load drafts. Pull to refresh.</div>
            </div>
          )}

          {drafts && drafts.length === 0 && (
            <div className="center">
              <div className="empty-emoji">✨</div>
              <h2 className="display" style={{ fontSize: 22 }}>You're all caught up</h2>
              <div className="muted">
                New replies will appear here the moment they're drafted. We'll ping you.
              </div>
            </div>
          )}

          {drafts &&
            drafts.map((d) => (
              <Link key={d.id} to={`/draft/${d.id}`} className="draft-item">
                <div className="row">
                  <div className="from">{d.incomingFrom.split("<")[0].replace(/"/g, "").trim() || d.incomingFrom}</div>
                  <ImportanceMeter value={d.importance} />
                </div>
                <div className="subject">{d.subject}</div>
                <div className="preview">{d.draftBody}</div>
                <div style={{ marginTop: 10 }}>
                  <span className="bucket-tag">{d.bucket.replace("_", " · ")}</span>
                </div>
              </Link>
            ))}
        </>
      )}

      {tab === "sent" && (
        <>
          {sent === null && (
            <div className="center"><div className="spinner" /></div>
          )}

          {sent && sent.length === 0 && (
            <div className="center">
              <div className="empty-emoji">📭</div>
              <div className="muted">Nothing sent yet. Approved replies will show up here.</div>
            </div>
          )}

          {sent &&
            sent.map((d) => (
              <div key={d.id} className="draft-item">
                <div className="row">
                  <div className="from">To: {d.incomingFrom.split("<")[0].replace(/"/g, "").trim() || d.incomingFrom}</div>
                  <span className="pill">{fmtSent(d.sentAt)}</span>
                </div>
                <div className="subject">{d.subject}</div>
                <div className="preview">{d.draftBody}</div>
                <div style={{ marginTop: 10 }}>
                  <span className="bucket-tag">{d.bucket.replace("_", " · ")}</span>
                </div>
              </div>
            ))}
        </>
      )}
    </div>
  );
}
