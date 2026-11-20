// Privacy-safe usage counts (CR19): one "visit" per browser session plus the tabs opened.
// Sent: the event name and, for a visit, the site you came from (host name only).
// Not sent: anything about you. The owner's own use is not counted.
import { api } from "./api";
import { currentOwnerKey } from "./owner";

const SESSION_FLAG = "jobradar.visit";

/** Where the visit came from: the GitHub Pages link passes it as ?ref=, else the browser's. */
export function referrerHost(search: string, documentReferrer: string, ownHost: string): string {
  const fromLink = new URLSearchParams(search).get("ref");
  if (fromLink) return fromLink;
  try {
    const host = new URL(documentReferrer).hostname;
    return host === ownHost ? "" : host;
  } catch {
    return "";
  }
}

export function trackVisit(): void {
  if (currentOwnerKey()) return;
  try {
    if (window.sessionStorage.getItem(SESSION_FLAG)) return;
    window.sessionStorage.setItem(SESSION_FLAG, "1");
  } catch {
    /* storage blocked: count it anyway */
  }
  const ref = referrerHost(window.location.search, document.referrer, window.location.hostname);
  void api.track("visit", ref || undefined);
}

export function trackTab(id: string): void {
  if (currentOwnerKey()) return;
  if (["today", "employers", "insights", "ask"].includes(id)) void api.track(`tab:${id}`);
}
