"""The eval runner: work out each right answer, ask the assistant, grade, and report.

    jobradar eval --truth-only      check every Expected SQL, no API cost
    jobradar eval --only Safety     one category (or IDs: --only C01,X02)
    jobradar eval                   the full run
    jobradar eval --regrade evals/results/<run>.jsonl
                                    re-grade saved answers with the current checks (free)

Right answers for data questions are recomputed from the gold tables at run time, because
jobs change daily. Full answers go to evals/results/<run>.jsonl (git-ignored: they mention
skills from the resume); the scores go to evals/results/<run>.md and latest.md (committed).
"""

from __future__ import annotations

import csv
import json
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from jobradar.agent.sql_guard import SqlRejected, check
from jobradar.evals.checks import Check, grade, parse_check

QUESTIONS = Path("evals/questions.csv")
RESULTS = Path("evals/results")
# Estimate only; set JOBRADAR_PRICE_IN / JOBRADAR_PRICE_OUT (USD per million tokens).
PRICE_IN = float(os.environ.get("JOBRADAR_PRICE_IN", "3"))
PRICE_OUT = float(os.environ.get("JOBRADAR_PRICE_OUT", "15"))


@dataclass
class Question:
    id: str
    category: str
    question: str
    check: Check
    expected: str

    @property
    def truth_sql(self) -> str | None:
        e = self.expected.strip()
        return e.split("--")[0].strip() if e.lower().startswith(("select", "with")) else None


def load_questions(path: Path = QUESTIONS, only: str | None = None) -> list[Question]:
    wanted = {w.strip().lower() for w in (only or "").split(",") if w.strip()}
    out = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("review") or "").strip().lower() == "drop" or not row["question"].strip():
                continue
            q = Question(
                row["id"], row["category"], row["question"], parse_check(row["check"]),
                row["expected"],
            )  # fmt: skip
            if wanted and q.id.lower() not in wanted and q.category.lower() not in wanted:
                continue
            out.append(q)
    return out


def truth(q: Question, runner, env: str) -> tuple[list[tuple] | None, str]:
    """Rows of the Expected SQL, or (None, error). Questions without SQL return (None, '')."""
    if not q.truth_sql:
        return None, ""
    try:
        _, rows = runner.run(check(q.truth_sql, env=env).sql)
        return [tuple(r) for r in rows], ""
    except SqlRejected as e:
        return None, f"truth SQL refused by guard: {e}"
    except Exception as e:  # a wrong column or company shows up here, before any API spend
        return None, f"truth SQL failed: {str(e).splitlines()[0][:200]}"


@dataclass
class Outcome:
    id: str
    category: str
    question: str
    check: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    truth: list | None = None
    answer: str = ""
    tools: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    stop_reason: str = ""


def run_one(q: Question, ask_fn, runner, env: str) -> Outcome:
    rows, error = truth(q, runner, env)
    out = Outcome(q.id, q.category, q.question, q.check.text, False, truth=rows)
    if q.check.needs_truth and rows is None:
        out.reasons = [error or "no truth SQL for a data check"]
        return out
    r = ask_fn(q.question)
    out.answer, out.stop_reason = r.answer, r.stop_reason
    out.tools = [s.tool for s in r.steps if s.kind == "tool"]
    out.input_tokens, out.output_tokens, out.seconds = r.input_tokens, r.output_tokens, r.seconds
    g = grade(q.check, r.answer, out.tools, rows)
    out.passed, out.reasons = g.passed, g.reasons
    return out


def summarize(outcomes: list[Outcome], model: str, started: str) -> str:
    by_cat: dict[str, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_cat[o.category].append(o)
    tin = sum(o.input_tokens for o in outcomes)
    tout = sum(o.output_tokens for o in outcomes)
    passed = sum(o.passed for o in outcomes)
    cost = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
    lines = [
        f"# Eval run {started}",
        "",
        f"**{passed} of {len(outcomes)} passed ({100 * passed / max(len(outcomes), 1):.0f}%)** "
        f"with `{model}`. Tokens: {tin:,} in, {tout:,} out (about ${cost:.2f} at "
        f"${PRICE_IN:g}/${PRICE_OUT:g} per million).",
        "",
        "| Category | Passed | Score |",
        "|---|---|---|",
    ]
    for cat, items in by_cat.items():
        p = sum(o.passed for o in items)
        lines.append(f"| {cat} | {p} of {len(items)} | {100 * p / len(items):.0f}% |")
    failed = [o for o in outcomes if not o.passed]
    if failed:
        lines += ["", "## Failed", ""]
        lines += [f"- **{o.id}** {o.question} — {'; '.join(o.reasons)}" for o in failed]
    return "\n".join(lines) + "\n"


def regrade(path: Path, questions: list[Question], out_dir: Path = RESULTS):
    """Grade the answers saved in a run's .jsonl again, with the current checks; no API calls.

    Saved right answers are reused, so the grade reflects the data on the day of the run.
    A question whose wording changed since then is marked to be asked again.
    """
    by_id = {q.id: q for q in questions}
    outcomes = []
    for line in path.read_text().splitlines():
        saved = json.loads(line)
        q = by_id.get(saved["id"])
        if q is None:
            continue
        o = Outcome(**{**saved, "check": q.check.text, "category": q.category})
        if saved["question"] != q.question:
            o.passed, o.reasons = False, ["question changed since this run: ask it again"]
        else:
            g = grade(q.check, o.answer, o.tools, [tuple(r) for r in o.truth or []] or None)
            o.passed, o.reasons = g.passed, g.reasons
        outcomes.append(o)
    model = "saved answers"
    summary = summarize(
        outcomes, model, f"{path.stem} (re-graded {time.strftime('%Y-%m-%d %H:%M')})"
    )
    md = out_dir / f"{path.stem}_regraded.md"
    md.write_text(summary)
    return outcomes, md


def run_evals(questions, ask_fn, runner, env: str, model: str, out_dir: Path = RESULTS,
              progress=print) -> tuple[list[Outcome], Path]:  # fmt: skip
    started = time.strftime("%Y-%m-%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    outcomes = []
    with (out_dir / f"{started}.jsonl").open("w") as f:
        for i, q in enumerate(questions, 1):
            o = run_one(q, ask_fn, runner, env)
            outcomes.append(o)
            f.write(json.dumps(asdict(o), default=str) + "\n")
            mark = "PASS" if o.passed else "FAIL"
            progress(f"[{i}/{len(questions)}] {mark} {o.id} {'; '.join(o.reasons)[:120]}")
    summary = summarize(outcomes, model, started)
    md = out_dir / f"{started}.md"
    md.write_text(summary)
    (out_dir / "latest.md").write_text(summary)
    return outcomes, md
