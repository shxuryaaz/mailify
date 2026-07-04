/* Mailify service worker — push is the fiddly part, especially on iOS.
 *
 * iOS reality (16.4+): web push only fires when the PWA is INSTALLED to the
 * home screen. A Safari tab never receives push. The install + permission flow
 * lives in the app UI (src/push.js); this worker only has to receive the push
 * and route the tap to the right draft.
 */

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (e) {
    payload = { title: "Mailify", body: event.data ? event.data.text() : "" };
  }

  const title = payload.title || "Mailify";
  const data = payload.data || {};
  const options = {
    body: payload.body || "",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    // The draft id rides along so the tap deep-links straight to the draft.
    data: { url: data.url || "/", draftId: data.draftId || null },
    tag: data.draftId ? `draft-${data.draftId}` : "mailify",
    renotify: true,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || "/";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      // Focus an existing window and navigate it, else open a new one.
      for (const client of clients) {
        if ("focus" in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});
