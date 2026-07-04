import { getToken, clearToken } from "./auth.js";

const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function request(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    clearToken();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  base: BASE,
  me: () => request("/auth/me"),
  listDrafts: () => request("/drafts"),
  listSent: () => request("/drafts/sent"),
  getDraft: (id) => request(`/drafts/${id}`),
  approve: (id) => request(`/drafts/${id}/approve`, { method: "POST" }),
  reject: (id) => request(`/drafts/${id}/reject`, { method: "POST" }),
  editAndSend: (id, draft_body) => request(`/drafts/${id}`, { method: "PATCH", body: { draft_body } }),
  vapidKey: () => request("/push/vapid-public-key"),
  subscribe: (subscription) => request("/push/subscribe", { method: "POST", body: { subscription } }),
  loginUrl: () => `${BASE}/auth/google/login`,
};
