import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, ApiError } from "../api";
import type { AskResult } from "../types";

const EXAMPLES = [
  "Which companies have the most open data engineering jobs?",
  "What do Ramp's H-1B filings pay for engineers?",
  "How many new jobs at my level were posted this week?",
];

export default function Ask() {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState("");
  const [result, setResult] = useState<AskResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function ask(q: string) {
    const text = q.trim();
    if (text.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setAsked(text);
    try {
      setResult(await api.ask(text));
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 429
          ? "Today's question limit is used up. It resets at midnight UTC."
          : `The assistant didn't answer: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="ask-title">
      <h2 id="ask-title" className="lede">Ask the data a question.</h2>
      <p className="sub">
        A Claude assistant answers from the same tables, with read-only SQL checked before it runs.
        It can look things up but can't change anything. Limited to 30 questions a day.
      </p>

      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(question);
        }}
      >
        <label htmlFor="question" className="visually-hidden">
          Your question
        </label>
        <textarea
          id="question"
          rows={2}
          maxLength={500}
          value={question}
          placeholder="For example: which sponsors post the most integration roles?"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask(question);
            }
          }}
        />
        <button type="submit" disabled={busy || question.trim().length < 3}>
          {busy ? "Asking…" : "Ask"}
        </button>
      </form>

      <div className="examples" aria-label="Example questions">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => {
              setQuestion(q);
              void ask(q);
            }}
            disabled={busy}
          >
            {q}
          </button>
        ))}
      </div>

      <div aria-live="polite">
        {busy && <p className="status">Looking it up: the assistant is querying the tables.</p>}
        {error && (
          <p className="status status-error" role="alert">
            {error}
          </p>
        )}
        {result && (
          <article className="answer">
            <p className="answer-q">{asked}</p>
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noreferrer">
                    {children}
                  </a>
                ),
              }}
            >
              {result.answer}
            </Markdown>
            <p className="answer-meta">
              Answered by {result.model} in {result.seconds.toFixed(1)} s
              {result.tools.length ? `, using ${[...new Set(result.tools)].join(" and ")}` : ""}.
              {result.questions_left_today !== null &&
                ` ${result.questions_left_today} questions left today.`}
            </p>
          </article>
        )}
      </div>
    </section>
  );
}
