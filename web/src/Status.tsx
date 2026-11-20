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
