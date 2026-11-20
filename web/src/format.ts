// Small formatting helpers, kept pure so they are easy to test.

export function money(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "";
  return `$${Math.round(v / 1000)}k`;
}

export function payRange(min: number | null, max: number | null): string {
  // Some boards put 0 in the salary fields; treat anything under $1k a year as not posted.
  min = min && min >= 1000 ? min : null;
  max = max && max >= 1000 ? max : null;
  if (!min && !max) return "Pay not posted";
  if (min && max && Math.round(min / 1000) !== Math.round(max / 1000)) {
    return `${money(min)}–${money(max)}`;
  }
  return money(min ?? max);
}

/** 0–1 fit score as 0–5 lit segments of the signal meter; null = not scored yet. */
export function fitSegments(score: number | null): number | null {
  if (score === null || score === undefined) return null;
  return Math.max(0, Math.min(5, Math.round(score * 5)));
}

export function percent(v: number | null): string {
  return v === null || v === undefined ? "" : `${Math.round(v * 100)}%`;
}

export function shortDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? word : many}`;
}

/** Days of new jobs without the startup spikes (the first loads of newly added companies):
 *  leading days far above the median of the rest are dropped. */
export function steadyDays<T extends { new_jobs: number }>(days: T[]): T[] {
  const sorted = [...days].map((d) => d.new_jobs).sort((a, b) => a - b);
  const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
  let start = 0;
  while (start < days.length - 1 && days[start].new_jobs > 3 * median) start += 1;
  return days.slice(start);
}

export function median(values: number[]): number {
  if (!values.length) return 0;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2);
}
