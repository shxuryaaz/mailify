import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The service worker (public/sw.js) is served as a static asset at the root so
// it can control the whole PWA scope. No SW plugin needed — it's hand-written
// for push, which is the fiddly part on iOS.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
