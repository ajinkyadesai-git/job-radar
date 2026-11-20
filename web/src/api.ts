import type { AskResult, Employer, Insights, Job } from "./types";

// Same-origin /api: the dev server (vite.config.ts) or CloudFront adds the API key.
async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
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
  today: (params: { reach?: string; role_family?: string; limit?: number }) => {
    const q = new URLSearchParams({ limit: String(params.limit ?? 50) });
    if (params.reach) q.set("reach", params.reach);
    if (params.role_family) q.set("role_family", params.role_family);
    return call<{ count: number; jobs: Job[] }>(`/jobs/today?${q}`);
  },
  employers: () => call<{ count: number; employers: Employer[] }>("/employers"),
  insights: () => call<Insights>("/insights"),
  ask: (question: string) =>
    call<AskResult>("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),
};
