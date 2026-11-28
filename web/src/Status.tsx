import { shortDay } from "./format";

/** When the data was last refreshed: the site reads a daily snapshot, so say how fresh it is. */
export function AsOf({ date }: { date?: string | null }) {
  if (!date) return null;
  return <p className="status">Data as of {shortDay(date.slice(0, 10))}; it refreshes every morning.</p>;
}

export function Status({ loading, error, what }: { loading: boolean; error: string | null; what: string }) {
  if (error) {
    return (
      <p className="status status-error" role="alert">
        Couldn't load {what}: {error}. Reload the page to try again.
      </p>
    );
  }
  if (loading) return <p className="status" aria-live="polite">Loading {what}…</p>;
  return null;
}
