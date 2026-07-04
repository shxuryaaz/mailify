// PWA push wiring — the fiddliest part of the build, and doubly so on iOS.
//
// iOS rules (16.4+):
//   * Notifications/Push exist ONLY when the app is installed to the home screen
//     (display-mode: standalone). A Safari tab cannot subscribe.
//   * There is no beforeinstallprompt on iOS — the user installs manually via
//     Share → Add to Home Screen. We detect standalone mode and, if not
//     installed, show instructions instead of a broken permission button.

import { api } from "./api.js";

export function isStandalone() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true // iOS Safari
  );
}

export function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
}

export function pushSupported() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return null;
  return navigator.serviceWorker.register("/sw.js", { scope: "/" });
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

// Returns a status string so the UI can explain exactly what's blocking push.
export async function enablePush() {
  if (!pushSupported()) return "unsupported";

  // On iOS, push is a no-op until the PWA is installed to the home screen.
  if (isIOS() && !isStandalone()) return "needs-install";

  const permission = await Notification.requestPermission();
  if (permission !== "granted") return "denied";

  const reg = (await navigator.serviceWorker.getRegistration()) || (await registerServiceWorker());
  await navigator.serviceWorker.ready;

  // Prefer the server's key; fall back to the build-time env key.
  let vapidPublic = import.meta.env.VITE_VAPID_PUBLIC_KEY;
  try {
    const { publicKey } = await api.vapidKey();
    if (publicKey) vapidPublic = publicKey;
  } catch (_) {
    /* use env fallback */
  }
  if (!vapidPublic) return "no-key";

  const existing = await reg.pushManager.getSubscription();
  const subscription =
    existing ||
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidPublic),
    }));

  await api.subscribe(subscription.toJSON());
  return "subscribed";
}
