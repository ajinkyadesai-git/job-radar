import { currentOwnerKey } from "./owner";
import type { SkillVocab } from "./resume";
import type { AskResult, Employer, FeedbackItem, Insights, Job, MatchJob, UsageDay } from "./types";

// Same-origin /api: the dev server (vite.config.ts) or CloudFront adds the API key.
// The owner's passphrase, when this browser has it, unlocks the owner's own list.
async function call<T>(path: string, init?: RequestInit, ownerOverride?: string): Promise<T> {
  const headers = new Headers(init?.headers);
  const owner = ownerOverride ?? currentOwnerKey();
  if (owner) headers.set("X-Owner-Key", owner);
  const res = await fetch(`/api${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export const api = {
  /** Checks a passphrase before it is saved. */
  me: (passphrase: string) => call<{ owner: boolean }>("/me", undefined, passphrase),
  today: (params: { reach?: string; role_family?: string; limit?: number }) => {
    const q = new URLSearchParams({ limit: String(params.limit ?? 50) });
    if (params.reach) q.set("reach", params.reach);
    if (params.role_family) q.set("role_family", params.role_family);
    return call<{ count: number; jobs: Job[] }>(`/jobs/today?${q}`);
  },
  employers: () => call<{ count: number; employers: Employer[] }>("/employers"),
  insights: () => call<Insights>("/insights"),
  skills: () => call<SkillVocab>("/skills"),
  match: (body: { skills: string[]; years: number; role_family?: string }) =>
    call<{ count: number; fresh_days: number; jobs: MatchJob[] }>("/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, limit: 30 }),
    }),
  /** Counts a visit or a tab; never throws, never slows the page. */
  track: (event: string, referrer?: string) =>
    call<{ ok: boolean }>("/track", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event, referrer }),
      keepalive: true,
    }).catch(() => undefined),
  feedback: (message: string, page?: string) =>
    call<{ ok: boolean }>("/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, page }),
    }),
  usage: () => call<{ days: UsageDay[]; feedback: FeedbackItem[] }>("/usage?days=14"),
  ask: (question: string) =>
    call<AskResult>("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),
};
