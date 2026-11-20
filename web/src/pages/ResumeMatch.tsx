import { useState } from "react";
import { api } from "../api";
import { payRange, plural, shortDay } from "../format";
import { findSkills, guessYears, readResume, type SkillVocab } from "../resume";
import type { MatchJob } from "../types";
import { FitMeter } from "./FitMeter";

const MAX_SKILLS = 40;

/** "Match my resume": read in the browser, send only skill names and years. */
export function ResumeMatch({
  onResults,
  startOpen = false,
}: {
  onResults: (jobs: MatchJob[] | null) => void;
  startOpen?: boolean;
}) {
  const [open, setOpen] = useState(startOpen);
  const [vocab, setVocab] = useState<SkillVocab | null>(null);
  const [skills, setSkills] = useState<string[]>([]);
  const [years, setYears] = useState("");
  const [paste, setPaste] = useState("");
  const [busy, setBusy] = useState<"" | "reading" | "matching">("");
  const [error, setError] = useState<string | null>(null);
  const [read, setRead] = useState(false);

  async function loadVocab(): Promise<SkillVocab> {
    if (vocab) return vocab;
    const v = await api.skills();
    setVocab(v);
    return v;
  }

  async function useText(text: string) {
    const v = await loadVocab();
    const found = findSkills(text, v);
    setSkills(found.slice(0, MAX_SKILLS));
    const y = guessYears(text);
    if (y !== null) setYears(String(y));
    setRead(true);
    if (!found.length) setError("No tracked skills found. Add some below, or try another file.");
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy("reading");
    setError(null);
    try {
      await useText(await readResume(file));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  async function onPaste() {
    if (paste.trim().length < 20) return;
    setBusy("reading");
    setError(null);
    try {
      await useText(paste);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  async function findMatches() {
    const y = Number(years);
    if (!skills.length || !Number.isInteger(y) || y < 0 || y > 30) return;
    setBusy("matching");
    setError(null);
    try {
      const result = await api.match({ skills, years: y });
      onResults(result.jobs);
      if (!result.jobs.length) {
        setError("No fresh jobs match these skills yet. Add related skills or try again tomorrow.");
      }
    } catch (e) {
      setError(`Matching didn't work: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy("");
    }
  }

  if (!open) {
    return (
      <div className="match-invite">
        <p>
          Looking for yourself? Upload your resume to rank the last two weeks of jobs at H-1B
          sponsors by your skills.
        </p>
        <button type="button" onClick={() => setOpen(true)}>
          Match my resume
        </button>
      </div>
    );
  }

  const addable = (vocab?.skills ?? []).map((s) => s.name).filter((n) => !skills.includes(n));

  return (
    <div className="match-panel" aria-labelledby="match-title">
      <h3 id="match-title">Match my resume</h3>
      <p className="privacy">
        Your resume is read in this browser and never uploaded. Only the skill names below and your
        years of experience are sent, and nothing is stored.
      </p>

      <div className="match-inputs">
        <label className="file">
          Resume file (PDF, Word or text)
          <input
            type="file"
            accept=".pdf,.docx,.txt,.md,application/pdf,text/plain"
            onChange={(e) => void onFile(e.target.files?.[0])}
            disabled={busy !== ""}
          />
        </label>
        <details>
          <summary>Or paste the text</summary>
          <textarea rows={5} value={paste} onChange={(e) => setPaste(e.target.value)} />
          <button type="button" onClick={() => void onPaste()} disabled={busy !== ""}>
            Read pasted text
          </button>
        </details>
      </div>

      {busy === "reading" && <p className="status">Reading your resume…</p>}

      {read && (
        <>
          <fieldset className="skills">
            <legend>{plural(skills.length, "skill")} found. Remove any that don't apply.</legend>
            <ul>
              {skills.map((s) => (
                <li key={s}>
                  <button
                    type="button"
                    className="chip"
                    aria-label={`Remove ${s}`}
                    onClick={() => setSkills(skills.filter((x) => x !== s))}
                  >
                    {s} <span aria-hidden="true">×</span>
                  </button>
                </li>
              ))}
            </ul>
            <label>
              Add a skill
              <select
                value=""
                onChange={(e) =>
                  e.target.value &&
                  skills.length < MAX_SKILLS &&
                  setSkills([...skills, e.target.value].sort((a, b) => a.localeCompare(b)))
                }
              >
                <option value="">Choose…</option>
                {addable.map((n) => (
                  <option key={n}>{n}</option>
                ))}
              </select>
            </label>
          </fieldset>

          <div className="match-go">
            <label>
              Years of experience
              <input
                type="number"
                min={0}
                max={30}
                value={years}
                onChange={(e) => setYears(e.target.value)}
                inputMode="numeric"
              />
            </label>
            <button
              type="button"
              className="primary"
              onClick={() => void findMatches()}
              disabled={busy !== "" || !skills.length || years === ""}
            >
              {busy === "matching" ? "Finding matches…" : "Find my matches"}
            </button>
          </div>
        </>
      )}

      {error && (
        <p className="status status-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function MatchList({
  jobs,
  onBack,
  backLabel,
}: {
  jobs: MatchJob[];
  onBack: () => void;
  backLabel: string;
}) {
  return (
    <section aria-labelledby="matches-title">
      <div className="matches-head">
        <h2 id="matches-title" className="lede">
          {`Your ${plural(jobs.length, "best match", "best matches")} from the last two weeks.`}
        </h2>
        <button type="button" className="link" onClick={onBack}>
          {backLabel}
        </button>
      </div>
      <p className="sub">
        Ranked by the share of each job's listed skills you have. Reach compares the years a job
        asks for with yours.
      </p>
      <ol className="jobs">
        {jobs.map((j) => (
          <li key={j.posting_key} className="job">
            <div className="job-main">
              <a className="job-title" href={j.url} target="_blank" rel="noreferrer">
                {j.title}
              </a>
              <span className="job-where">
                <strong>{j.company_name}</strong>
                {j.location ? `, ${j.location}` : ""}
              </span>
              {j.missing.length > 0 && (
                <span className="job-missing">Also asks for: {j.missing.join(", ")}</span>
              )}
            </div>
            <dl className="job-facts">
              <div>
                <dt>Reach</dt>
                <dd className={j.reach === "Within reach" ? "reach-in" : "reach-stretch"}>
                  {j.reach}
                  {j.years_required ? ` (${j.years_required} yrs)` : ""}
                </dd>
              </div>
              <div>
                <dt>Posted pay</dt>
                <dd>{payRange(j.salary_min_yearly_usd, j.salary_max_yearly_usd)}</dd>
              </div>
              <div>
                <dt>H-1B filings</dt>
                <dd>{j.company_lca_filings?.toLocaleString("en-US") ?? "None found"}</dd>
              </div>
              <div>
                <dt>First seen</dt>
                <dd>{shortDay(String(j.first_seen).slice(0, 10))}</dd>
              </div>
              <div>
                <dt>Your match</dt>
                <dd>
                  <FitMeter score={j.match_pct / 100} label="Your match" />
                  <span className="match-of">
                    {j.matched.length} of {j.matched.length + j.missing.length} skills
                  </span>
                </dd>
              </div>
            </dl>
          </li>
        ))}
      </ol>
    </section>
  );
}
