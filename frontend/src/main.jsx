import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import { registerServiceWorker } from "./push.js";
import "./styles.css";

// Register the service worker up front so push can attach later.
registerServiceWorker().catch(() => {});

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
