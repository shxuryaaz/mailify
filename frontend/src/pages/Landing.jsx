import React from "react";
import { api } from "../api.js";

// Landing / sign-in. The Spline scene is a full-bleed animated background behind
// a dark scrim so the hero text stays readable. This is the only screen that
// uses Spline — the working views stay clean and fast.
export default function Landing() {
  return (
    <div className="landing">
      <iframe
        className="spline"
        title="Mailify background"
        src="https://my.spline.design/splinewavebg-TGjBbOmLn9C9hJzpJVK5kjgg/"
        frameBorder="0"
      />
      <div className="scrim" />
      <div className="hero">
        <div className="eyebrow" aria-label="Mailify">
          <svg
            width="34" height="34" viewBox="0 0 24 24" fill="none"
            stroke="#ffffff" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"
          >
            <rect x="2.5" y="5" width="19" height="14" rx="2.6" />
            <path d="M3.2 7 12 13l8.8-6" />
          </svg>
        </div>
        <h1>Your inbox, drafted in your voice.</h1>
        <p>
          Mailify watches your Gmail, writes replies that sound like you, and pings your
          phone. Nothing sends without your tap.
        </p>
        <a className="btn btn-primary btn-block" href={api.loginUrl()}>
          Continue with Google
        </a>
      </div>
    </div>
  );
}
