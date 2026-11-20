import { useState } from "react";
import { api, ApiError } from "../api";
import { saveOwnerKey } from "../owner";

/** Reached only at /#me (not linked anywhere). Checks the passphrase with the API first. */
export default function Unlock({ onUnlocked }: { onUnlocked: () => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function unlock() {
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.me(value);
      saveOwnerKey(value);
      setValue("");
      onUnlocked();
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? "That passphrase isn't right."
          : `Couldn't check it: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="unlock-title" className="unlock">
      <h2 id="unlock-title" className="lede">Owner view</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void unlock();
        }}
      >
        <label htmlFor="passphrase">Owner passphrase</label>
        <input
          id="passphrase"
          type="password"
          autoComplete="current-password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button type="submit" disabled={busy || !value}>
          {busy ? "Checking…" : "Unlock"}
        </button>
      </form>
      {error && (
        <p className="status status-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
