import React, { useEffect, useState } from "react";
import { Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { api } from "./api.js";
import { isAuthed, setToken, clearToken } from "./auth.js";
import Landing from "./pages/Landing.jsx";
import Onboarding from "./pages/Onboarding.jsx";
import Inbox from "./pages/Inbox.jsx";
import DraftDetail from "./pages/DraftDetail.jsx";
import Voice from "./pages/Voice.jsx";

// Grabs the JWT from the OAuth callback fragment (#token=...) and redirects in.
function AuthCallback() {
  const nav = useNavigate();
  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.slice(1));
    const token = hash.get("token");
    if (token) {
      setToken(token);
      nav("/", { replace: true });
    } else {
      nav("/welcome", { replace: true });
    }
  }, [nav]);
  return (
    <div className="center">
      <div className="spinner" />
      <div className="muted">Signing you in…</div>
    </div>
  );
}

// Route guard: authed users land in the app; onboarding gates the inbox until
// the taste agent finishes.
function Gate() {
  const nav = useNavigate();
  const [me, setMe] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    if (!isAuthed()) {
      nav("/welcome", { replace: true });
      return;
    }
    api.me().then(setMe).catch(() => {
      clearToken();
      setErr(true);
      nav("/welcome", { replace: true });
    });
  }, [nav]);

  if (err) return null;
  if (!me) {
    return (
      <div className="center">
        <div className="spinner" />
      </div>
    );
  }
  if (!me.onboardingComplete) return <Onboarding me={me} />;
  return <Inbox me={me} />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/welcome" element={<Landing />} />
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route path="/draft/:id" element={<DraftDetail />} />
      <Route path="/voice" element={isAuthed() ? <Voice /> : <Navigate to="/welcome" replace />} />
      <Route path="/" element={<Gate />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
