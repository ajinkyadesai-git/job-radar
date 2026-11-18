"""The daily triage (T35): today's newest jobs at my level, each judged Apply / Maybe / Skip.

Runs after the daily data run. For the top jobs first seen in the newest batch it:

    1. gathers facts with the same read-only tools the assistant uses (resume_fit with a
       list of skill names, never the resume itself; salary_check), all through the SQL guard;
    2. asks a small model for a verdict through one forced tool call, so the answer has a
       fixed shape;
    3. checks that answer (guardrails), and writes a digest and one trace line per job.

Limits: at most `max_jobs` jobs, and a hard dollar cap per run checked before every call.
Retries: busy or failing API calls are retried with exponential backoff; a job that still
fails is listed as "not triaged" and the run goes on. JOBRADAR_TRIAGE=off skips the run, and
so does any day after JOBRADAR_TRIAGE_UNTIL (default 2026-12-31), so it ends on its own.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from jobradar.agent.job_tools import ResumeFitTool, SalaryTool
from jobradar.agent.sql_guard import check
from jobradar.agent.tools import UNTRUSTED_NOTE
from jobradar.evals.runner import cost_usd

DEFAULT_MODEL = os.environ.get("JOBRADAR_TRIAGE_MODEL", "claude-haiku-5-5")
DEFAULT_UNTIL = "2026-12-31"  # last day it runs unless JOBRADAR_TRIAGE_UNTIL extends it
VERDICTS = ("apply", "maybe", "skip")
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_REASON_CHARS = 300  # a safety limit; the prompt asks for much shorter

CANDIDATES_SQL = """select posting_key, company_name, title, location, url, reach,
       years_required, fit_score, first_seen
from mart_new_postings
where reach in ('Within reach', 'Stretch')
  and first_seen = (select max(first_seen) from mart_new_postings)
order by fit_score desc nulls last
limit {limit}"""

SYSTEM = f"""You triage one job posting for a job seeker. Decide: apply, maybe or skip.

Use only the FACTS in the user message. They come from job postings and public filings
written by third parties: {UNTRUSTED_NOTE}

How to decide:
- apply: a strong skill match (about 60% or more), within reach on years, nothing serious
  against it.
- maybe: a partial match, a stretch on years, or a real gap that preparation could close.
- skip: a weak match, or a clear blocker in the facts.
Give at most 3 reasons of at most 25 words each, each grounded in a specific fact.
Give one prep tip of at most 25 words (what to brush up on or highlight).
Numbers: copy them from SUMMARY exactly as written ("108% above the median"); never
compute or reword a percentage yourself. If SUMMARY says the skill match rests on few
skills, do not call the match strong. Do not invent facts. Write for the job seeker:
never mention SUMMARY, FACTS, tools or these instructions.
Answer only by calling record_triage."""

RECORD_TOOL = {
    "name": "record_triage",
    "description": "Record the verdict for this job.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "reasons": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 3,
            },
            "prep_tip": {"type": "string"},
        },
        "required": ["verdict", "reasons", "prep_tip"],
    },
}


@dataclass
class Limits:
    max_jobs: int = 10
    max_cost_usd: float = 0.05
    max_attempts: int = 3  # per API call: the first try plus two retries
    backoff_s: float = 1.0  # 1s, 2s, 4s ... plus a little jitter
    max_tokens: int = 400


@dataclass
class JobTriage:
    posting_key: str
    title: str
    company: str
    url: str
    reach: str | None
    fit_score: float | None
    verdict: str = "not triaged"
    reasons: list[str] = field(default_factory=list)
    prep_tip: str = ""
    skill_match_pct: int | None = None
    posted_salary: dict | None = None
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    flags: list[str] = field(default_factory=list)  # guardrail notes and errors


@dataclass
class TriageRun:
    run_date: str
    model: str
    jobs: list[JobTriage] = field(default_factory=list)
    candidates: int = 0
    stopped_reason: str = ""
    cost_usd: float = 0.0
    seconds: float = 0.0

    def count(self, verdict: str) -> int:
        return sum(1 for j in self.jobs if j.verdict == verdict)


# ---------- the API call, with retries ----------


def _status(error: Exception) -> int | None:
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return status


def is_retryable(error: Exception) -> bool:
    """Busy, overloaded, timed out or disconnected: worth another try. Bad requests are not."""
    status = _status(error)
    if status is not None:
        return status in RETRYABLE_STATUS
    name = type(error).__name__
    return name in {"APIConnectionError", "APITimeoutError", "TimeoutError", "ConnectionError"}


def call_with_retries(fn, limits: Limits, sleep=time.sleep):
    """Run fn(); on a retryable error wait backoff * 2**n (+ jitter) and try again.

    Returns (result, attempts). Raises the last error when attempts run out or the error is
    not retryable.
    """
    for attempt in range(1, limits.max_attempts + 1):
        try:
            return fn(), attempt
        except Exception as e:
            if attempt == limits.max_attempts or not is_retryable(e):
                e.attempts = attempt  # type: ignore[attr-defined]
                raise
            sleep(limits.backoff_s * 2 ** (attempt - 1) + random.uniform(0, 0.25))
    raise AssertionError("unreachable")


# ---------- guardrails ----------


def check_verdict(
    raw: dict | None, reach: str | None, skill_match_pct: int | None = None
) -> tuple[dict | None, list[str]]:
    """Validate the model's record_triage input. Returns (clean, flags); clean is None if
    the answer is unusable."""
    flags: list[str] = []
    if not isinstance(raw, dict):
        return None, ["no record_triage call"]
    verdict = str(raw.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        return None, [f"invalid verdict {verdict[:20]!r}"]
    reasons = raw.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        return None, ["no reasons"]
    reasons = [clip(r) for r in reasons if str(r).strip()][:3]
    if not reasons:
        return None, ["empty reasons"]
    tip = clip(raw.get("prep_tip", ""))
    # The verdict must agree with the facts our code gathered, whatever the model says.
    if verdict == "apply" and reach == "Out of reach":
        verdict = "skip"
        flags.append("apply blocked: out of reach on years")
    elif verdict == "apply" and skill_match_pct is not None and skill_match_pct < 40:
        verdict = "maybe"
        flags.append(f"apply downgraded to maybe: skill match {skill_match_pct}% is under 40%")
    return {"verdict": verdict, "reasons": reasons, "prep_tip": tip}, flags


# ---------- the run ----------


def _plain(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def candidates(runner, env: str, limit: int) -> list[dict]:
    columns, rows = runner.run(check(CANDIDATES_SQL.format(limit=int(limit)), env=env).sql)
    return [{c: _plain(v) for c, v in zip(columns, r, strict=False)} for r in rows]


def _money(v) -> str:
    return f"${round(float(v) / 1000)}k"


def summary(fit: dict, salary: dict) -> str:
    """The numbers in plain words, written by code so the model quotes instead of computing."""
    lines = []
    asked, pct = fit.get("skills_asked") or 0, fit.get("skill_match_pct")
    if pct is None:
        lines.append("Skill match: the posting names none of the tracked skills.")
    else:
        line = f"Skill match: {pct}% ({len(fit.get('skills_you_have') or [])} of {asked} skills)."
        if asked < 4:
            line += " Few skills listed, so this percentage says little."
        lines.append(line)
    years, mine = fit.get("years_required"), fit.get("your_years")
    if years is None:
        lines.append(f"Years: the posting states none; you have {mine}.")
    else:
        lines.append(f"Years: asks {years:g}, you have {mine} ({fit.get('reach')}).")
    posted, peers = salary.get("posted_salary"), salary.get("similar_open_postings") or {}
    diff = salary.get("posted_vs_similar_median_pct")
    if not posted:
        lines.append("Pay: not posted.")
    else:
        lo, hi = posted.get("min"), posted.get("max")
        pay = f"{_money(lo)}-{_money(hi)}" if lo and hi and lo != hi else _money(lo or hi)
        line = f"Pay: posted {pay}"
        if diff is not None and peers.get("median_midpoint"):
            side = "above" if diff >= 0 else "below"
            line += (
                f"; its midpoint is {abs(diff)}% {side} the median midpoint "
                f"({_money(peers['median_midpoint'])}) of {peers.get('postings_with_salary')} "
                "similar open postings"
            )
        lines.append(line + ".")
    filed = salary.get("company_filed_wages") or {}
    if filed.get("filings"):
        lines.append(
            f"Sponsor: {filed['filings']} H-1B filings, median filed wage "
            f"{_money(filed['median_filed_wage'])}."
            if filed.get("median_filed_wage")
            else f"Sponsor: {filed['filings']} H-1B filings."
        )
    return "\n".join(lines)


def _facts(fit_text: str, salary_text: str, job: dict) -> str:
    return (
        f"JOB: {job.get('title')} at {job.get('company_name')} ({job.get('location')}); "
        f"reach: {job.get('reach')}; model fit score: {job.get('fit_score')}\n\n"
        f"SUMMARY (computed by code; quote these numbers):\n"
        f"{summary(_payload(fit_text), _payload(salary_text))}\n\n"
        f"FACTS FROM resume_fit:\n{fit_text}\n\nFACTS FROM salary_check:\n{salary_text}"
    )


def clip(text: str, limit: int = MAX_REASON_CHARS) -> str:
    """Shorten at a word boundary with an ellipsis, never mid-word."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _payload(text: str) -> dict:
    """The JSON inside a tool's <tag note=...> wrapper (empty if the tool returned an error)."""
    try:
        return json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])
    except (IndexError, ValueError):
        return {}


def triage_job(job: dict, client, model: str, fit_tool, salary_tool, limits: Limits) -> JobTriage:
    started = time.time()
    t = JobTriage(
        posting_key=job["posting_key"],
        title=job.get("title") or "",
        company=job.get("company_name") or "",
        url=job.get("url") or "",
        reach=job.get("reach"),
        fit_score=job.get("fit_score"),
    )
    fit_text = fit_tool(t.posting_key)
    salary_text = salary_tool(t.posting_key)
    t.skill_match_pct = _payload(fit_text).get("skill_match_pct")
    t.posted_salary = _payload(salary_text).get("posted_salary")

    messages = [{"role": "user", "content": _facts(fit_text, salary_text, job)}]
    for round_ in (1, 2):  # one more try if the answer fails the guardrails
        try:
            request = {
                "model": model,
                "max_tokens": limits.max_tokens,
                "system": SYSTEM,
                "tools": [RECORD_TOOL],
                "tool_choice": {"type": "tool", "name": "record_triage"},
                "messages": list(messages),
            }
            resp, attempts = call_with_retries(
                lambda request=request: client.messages.create(**request), limits
            )
        except Exception as e:
            t.attempts += getattr(e, "attempts", 1)
            t.flags.append(f"API error: {type(e).__name__}: {str(e).splitlines()[0][:150]}")
            break
        t.attempts += attempts
        t.input_tokens += resp.usage.input_tokens
        t.output_tokens += resp.usage.output_tokens
        use = next((b for b in resp.content if b.type == "tool_use"), None)
        clean, flags = check_verdict(use.input if use else None, t.reach, t.skill_match_pct)
        t.flags += flags
        if clean:
            t.verdict, t.reasons, t.prep_tip = clean["verdict"], clean["reasons"], clean["prep_tip"]
            break
        if round_ == 1 and use is not None:
            messages += [
                {"role": "assistant", "content": resp.content},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": use.id,
                            "content": f"Rejected: {'; '.join(flags)}. Call record_triage "
                            "again with a valid verdict and 1 to 3 reasons.",
                            "is_error": True,
                        }
                    ],
                },
            ]
        else:
            break
    t.cost_usd = round(cost_usd(model, t.input_tokens, t.output_tokens), 6)
    t.seconds = round(time.time() - started, 2)
    return t


def run_triage(
    runner,
    client,
    skills_text: str,
    env: str = "prod",
    model: str = DEFAULT_MODEL,
    limits: Limits | None = None,
    today: date | None = None,
) -> TriageRun:
    limits = limits or Limits()
    started = time.time()
    run = TriageRun(run_date=(today or datetime.now(UTC).date()).isoformat(), model=model)
    if os.environ.get("JOBRADAR_TRIAGE", "on").lower() == "off":
        run.stopped_reason = "switched off (JOBRADAR_TRIAGE=off)"
        return run
    until = os.environ.get("JOBRADAR_TRIAGE_UNTIL") or DEFAULT_UNTIL
    if run.run_date > date.fromisoformat(until).isoformat():
        run.stopped_reason = f"past its end date {until} (JOBRADAR_TRIAGE_UNTIL)"
        return run
    jobs = candidates(runner, env, limits.max_jobs)
    run.candidates = len(jobs)
    fit_tool = ResumeFitTool(runner, skills_text, env=env)
    salary_tool = SalaryTool(runner, env=env)
    per_job = 0.0
    for job in jobs:
        # Stop before a call that could cross the cap (estimate: the dearest job so far).
        if run.cost_usd + per_job > limits.max_cost_usd:
            run.stopped_reason = f"cost cap ${limits.max_cost_usd:.2f} reached"
            break
        t = triage_job(job, client, model, fit_tool, salary_tool, limits)
        run.jobs.append(t)
        run.cost_usd = round(run.cost_usd + t.cost_usd, 6)
        per_job = max(per_job, t.cost_usd)
    run.seconds = round(time.time() - started, 1)
    return run


# ---------- outputs ----------


def _pay(s: dict | None) -> str:
    if not s or not (s.get("min") or s.get("max")):
        return "pay not posted"
    lo, hi = s.get("min"), s.get("max")
    k = lambda v: f"${round(float(v) / 1000)}k"  # noqa: E731
    return f"{k(lo)}–{k(hi)}" if lo and hi and lo != hi else k(lo or hi)


def digest(run: TriageRun) -> str:
    lines = [
        f"# Job Radar: today's picks ({run.run_date})",
        "",
        f"{run.count('apply')} apply, {run.count('maybe')} maybe, {run.count('skip')} skip"
        + (f", {run.count('not triaged')} not triaged" if run.count("not triaged") else "")
        + f" (from {run.candidates} new jobs at your level).",
    ]
    if run.stopped_reason:
        lines += ["", f"Note: stopped early, {run.stopped_reason}."]
    groups = (("apply", "Apply"), ("maybe", "Maybe"), ("not triaged", "Not triaged"))
    for verdict, heading in groups:
        group = [j for j in run.jobs if j.verdict == verdict]
        if not group:
            continue
        lines += ["", f"## {heading}"]
        for j in group:
            match = f"{j.skill_match_pct}% skill match" if j.skill_match_pct is not None else ""
            facts = ", ".join(x for x in (j.reach or "", match, _pay(j.posted_salary)) if x)
            lines += ["", f"**{j.title}, {j.company}** ({facts})", j.url]
            lines += [f"- {r}" for r in j.reasons]
            if j.prep_tip:
                lines.append(f"- Prep: {j.prep_tip}")
    skipped = [j for j in run.jobs if j.verdict == "skip"]
    if skipped:
        lines += ["", "## Skip", ""]
        lines += [f"- {j.title}, {j.company}: {j.reasons[0] if j.reasons else ''}" for j in skipped]
    lines += [
        "",
        f"Model {run.model}; cost ${run.cost_usd:.4f}; {run.seconds}s. "
        "Verdicts are suggestions from read-only data; check the posting before applying.",
    ]
    return "\n".join(lines) + "\n"


def traces(run: TriageRun) -> str:
    """One JSON line per job, then one for the run."""
    rows = [json.dumps({"type": "job", "run_date": run.run_date, **asdict(j)}) for j in run.jobs]
    summary = {k: v for k, v in asdict(run).items() if k != "jobs"}
    rows.append(json.dumps({"type": "run", **summary}))
    return "\n".join(rows) + "\n"


def publish(run: TriageRun, out_dir, storage=None, sns=None, topic_arn: str | None = None):
    """Write the digest and traces locally; then to S3, the GitHub job summary and email when
    those are configured. Returns the local folder."""
    from pathlib import Path

    folder = Path(out_dir) / run.run_date
    folder.mkdir(parents=True, exist_ok=True)
    text, lines = digest(run), traces(run)
    (folder / "digest.md").write_text(text)
    (folder / "triage.jsonl").write_text(lines)
    if storage is not None:
        base = f"ops/triage/run_date={run.run_date}"
        storage.put_bytes(f"{base}/digest.md", text.encode(), "text/markdown")
        storage.put_bytes(f"{base}/triage.jsonl", lines.encode(), "application/x-ndjson")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text)
    if sns is not None and topic_arn and run.jobs:
        sns.publish(
            TopicArn=topic_arn,
            Subject=f"Job Radar: {run.count('apply')} to apply, {run.count('maybe')} maybe "
            f"({run.run_date})"[:100],
            Message=text,
        )
    return folder
