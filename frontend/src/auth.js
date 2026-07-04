// Session token storage. The backend hands us a JWT via the OAuth callback URL
// fragment; we persist it and attach it to every API call.

const KEY = "mailify_token";

export function getToken() {
  return localStorage.getItem(KEY);
}

export function setToken(token) {
  localStorage.setItem(KEY, token);
}

export function clearToken() {
  localStorage.removeItem(KEY);
}

export function isAuthed() {
  return Boolean(getToken());
}
