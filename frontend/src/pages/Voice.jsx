import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api.js";

// The three relationship buckets, in the order we show them, with human labels.
const BUCKETS = [
  {
    key: "close_internal",
    title: "Close / internal",
    sub: "People you email a lot — cofounders, teammates, close contacts",
  },
  {
    key: "external_professional",
    title: "External / professional",
    sub: "Investors, partners, customers — semi-formal",
  },
  {
    key: "cold_stranger",
    title: "Cold / first contact",
    sub: "People you're emailing for the very first time",
  },
];

const SOURCE_LABEL = {
  onboarding: "learned from your sent mail",
  redistill: "refined from your edits",
  manual: "edited by you",
};

function sourceLabel(source) {
  if (source?.startsWith("rollback")) return "restored";
  return SOURCE_LABEL[source] || source;
}

function BucketCard({ meta, versions, onSaved }) {
  const newest = versions[0];
  const history = versions.slice(1);
  const [text, setText] = useState(newest?.profileText || "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  // Keep the editor in sync if the profile is reloaded from the server.
  useEffect(() => {
    setText(newest?.profileText || "");
  }, [newest?.version, newest?.profileText]);

  const dirty = text.trim() && text.trim() !== (newest?.profileText || "").trim();

  const save = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      await api.editProfile(meta.key, text.trim());
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
      await onSaved();
    } catch (_) {
      /* surface nothing fancy; leave text as-is so they can retry */
    } finally {
      setSaving(false);
    }
  };

  const restore = async (version) => {
    if (saving) return;
    setSaving(true);
    try {
      await api.rollbackProfile(meta.key, version);
      await onSaved();
      setShowHistory(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="voice-card">
      <div className="voice-head">
        <div>
          <div className="voice-title">{meta.title}</div>
          <div className="voice-sub">{meta.sub}</div>
        </div>
        {newest && (
          <span className="pill voice-badge">v{newest.version} · {sourceLabel(newest.source)}</span>
        )}
      </div>

      <textarea
        className="voice-textarea"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="No profile yet for this bucket."
        rows={6}
      />

      <div className="voice-actions">
        {history.length > 0 && (
          <button className="pill pill-btn" onClick={() => setShowHistory((v) => !v)}>
            {showHistory ? "Hide history" : `History · ${history.length}`}
          </button>
        )}
        <div style={{ flex: 1 }} />
        {saved && <span className="voice-saved">Saved ✓</span>}
        <button
          className="btn btn-primary voice-save"
          onClick={save}
          disabled={!dirty || saving}
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>

      {showHistory && (
        <div className="voice-history">
          {history.map((v) => (
            <div key={v.version} className="voice-hist-row">
              <div className="voice-hist-meta">
                <span className="pill">v{v.version} · {sourceLabel(v.source)}</span>
              </div>
              <div className="voice-hist-text">{v.profileText}</div>
              <button className="pill pill-btn" onClick={() => restore(v.version)}>
                Restore
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Voice() {
  const nav = useNavigate();
  const [profiles, setProfiles] = useState(null);
  const [error, setError] = useState(false);

  const load = async () => {
    try {
      setProfiles(await api.listProfiles());
    } catch (_) {
      setError(true);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="shell">
      <div className="topbar">
        <button className="pill pill-btn" onClick={() => nav("/")}>← Inbox</button>
        <span className="pill">Your voice</span>
      </div>

      <div className="section-label">How Mailify writes as you</div>
      <p className="muted" style={{ marginTop: 0 }}>
        These are the style profiles Mailify drafts from — one per kind of contact.
        Edit any of them and the next draft uses your version. Mailify keeps learning
        from your edits on top of it.
      </p>

      {profiles === null && !error && (
        <div className="center"><div className="spinner" /></div>
      )}

      {error && (
        <div className="center">
          <div className="empty-emoji">⚠️</div>
          <div className="muted">Couldn't load your voice profiles.</div>
        </div>
      )}

      {profiles &&
        BUCKETS.map((meta) => (
          <BucketCard
            key={meta.key}
            meta={meta}
            versions={profiles[meta.key] || []}
            onSaved={load}
          />
        ))}
    </div>
  );
}
