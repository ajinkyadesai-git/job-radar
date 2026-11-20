import { useState } from "react";
import { api, ApiError } from "./api";

/** "Send feedback": a short message to the owner. Only the message and the tab are kept. */
export function Feedback({ page }: { page: string }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [state, setState] = useState<"" | "sending" | "sent">("");
  const [error, setError] = useState<string | null>(null);

  async function send() {
    setState("sending");
    setError(null);
    try {
      const tab = ["today", "employers", "insights", "ask"].includes(page) ? page : undefined;
      await api.feedback(text.trim(), tab);
      setState("sent");
      setText("");
    } catch (e) {
      setState("");
      setError(e instanceof ApiError && e.status === 429 ? e.message : "Couldn't send it. Try again in a minute.");
    }
  }

  if (state === "sent") {
    return <p className="feedback-done">Thanks, your feedback was sent.</p>;
  }
  if (!open) {
    return (
      <button type="button" className="link" onClick={() => setOpen(true)}>
        Send feedback
      </button>
    );
  }
  return (
    <form
      className="feedback"
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
    >
      <label htmlFor="feedback-text">What's missing, wrong or useful?</label>
      <textarea
        id="feedback-text"
        rows={3}
        maxLength={1000}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Only this message is saved. Add an email if you'd like a reply."
      />
      <div className="feedback-actions">
        <button type="submit" className="primary" disabled={state === "sending" || text.trim().length < 3}>
          {state === "sending" ? "Sending…" : "Send feedback"}
        </button>
        <button type="button" className="link" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error && (
        <p className="status status-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
