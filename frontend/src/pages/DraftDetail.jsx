import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../api.js";

// The whole draft is shown, always. The owner reads before tapping — the model
// can be confidently wrong on a price, a date, or whether the meeting is wanted,
// even when the voice is perfect. Edit is inline; Approve sends as-is.
export default function DraftDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [draft, setDraft] = useState(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getDraft(id)
      .then((d) => {
        setDraft(d);
        setBody(d.draftBody);
      })
      .catch(() => setError("Draft not found"));
  }, [id]);

  const flash = (msg) => {
    setToast(msg);
    setTimeout(() => nav("/", { replace: true }), 900);
  };

  const onApprove = async () => {
    if (busy || !draft) return;
    setBusy(true);
    try {
      const edited = body.trim() !== draft.draftBody.trim();
      // If the owner changed the body, edit-then-send captures the learning
      // signal; otherwise approve sends the draft as-is.
      if (edited) {
        await api.editAndSend(id, body);
        flash("Sent your edited reply");
      } else {
        await api.approve(id);
        flash("Sent");
      }
    } catch (e) {
      setBusy(false);
      setToast("Couldn't send — try again");
      setTimeout(() => setToast(null), 1800);
    }
  };

  const onReject = async () => {
    if (busy || !draft) return;
    setBusy(true);
    try {
      await api.reject(id);
      flash("Rejected & trashed");
    } catch (e) {
      setBusy(false);
      setToast("Couldn't reject — try again");
      setTimeout(() => setToast(null), 1800);
    }
  };

  if (error) {
    return (
      <div className="shell">
        <div className="center">
          <div className="empty-emoji">🗑️</div>
          <div className="muted">{error}. It may have already been handled.</div>
          <button className="btn btn-ghost" onClick={() => nav("/")}>Back to inbox</button>
        </div>
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="shell">
        <div className="center"><div className="spinner" /></div>
      </div>
    );
  }

  const edited = body.trim() !== draft.draftBody.trim();

  return (
    <div className="shell">
      <div className="topbar">
        <button className="back" onClick={() => nav("/")}>← Inbox</button>
        <span className="pill">importance {draft.importance}</span>
      </div>

      {/* The incoming email — read this before you tap. */}
      <div className="incoming">
        <div className="meta">
          <b>{draft.incomingFrom}</b>
        </div>
        <div className="meta" style={{ marginTop: 2 }}>{draft.subject}</div>
        <div className="body">{draft.incomingSnippet}</div>
      </div>

      <div className="draft-label"><span className="dot" style={{
        width: 7, height: 7, borderRadius: "50%", background: "var(--accent)", display: "inline-block"
      }} /> Your draft reply</div>

      <textarea
        className="draft-body"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        spellCheck
      />
      <p className="hint">
        {edited
          ? "You edited this. Sending will save the change and teach Mailify your voice."
          : "Read it over — the tone may be perfect but a fact (a date, a price, a yes/no) can still be wrong. Tap the body to edit."}
      </p>

      <div className="actions">
        <button className="btn btn-danger" onClick={onReject} disabled={busy}>Reject</button>
        <button className="btn btn-primary" onClick={onApprove} disabled={busy}>
          {edited ? "Send edited" : "Approve & send"}
        </button>
      </div>

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
