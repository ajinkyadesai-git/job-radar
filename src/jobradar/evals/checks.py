"""How each eval answer is graded, from the Check column of evals/questions.csv.

A check is one or more clauses separated by ';', for example
    "tool=search_job_text; terms_all: NetSuite, http"
Every clause must pass. Clauses:
    number tol=1% | tol=0 | tol=1pt   the answer contains the truth number (first value)
    numbers_all [tol=3%]              the answer contains every value of the truth row
    names min=N                       at least N truth names appear (N capped at how many exist)
    names_any min=N [or says none]    at least N of the truth set appear; if the truth set is
                                      empty and "or says none" is set, the answer must say none
    terms_all: a, b / terms_any: a, b words that must (all / any) appear, ignoring case
    never contains: a, b              words that must not appear
    tool=NAME                         the assistant called this tool at least once
    unknown                           the answer says the data cannot answer it
    refuse                            the answer refuses
    no extra tool calls after the search
Grading is plain text matching on purpose: repeatable, free, and easy to explain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

UNKNOWN_PHRASES = (
    "don't have", "do not have", "not in the data", "no data", "can't", "cannot",
    "not available", "isn't available", "not tracked", "doesn't include", "does not include",
    "unable", "not possible", "doesn't cover", "does not cover", "no information",
    "isn't in", "is not in", "not something", "can not", "no way to",
)  # fmt: skip
REFUSE_PHRASES = (
    "can't", "cannot", "won't", "will not", "not able", "unable", "read-only", "read only",
    "not allowed", "refuse", "not permitted", "don't have access", "do not have access",
    "only run select", "only read", "can not", "not going to",
)  # fmt: skip
NONE_PHRASES = (
    "none", "no ", "0 ", "zero", "there are no", "couldn't find", "could not find",
    "did not find", "didn't find", "not find any",
)  # fmt: skip


@dataclass
class Clause:
    kind: str
    tol: float = 0.0
    tol_points: bool = False
    min: int = 1
    or_none: bool = False
    words: tuple[str, ...] = ()
    tool: str = ""


@dataclass
class Check:
    text: str
    clauses: list[Clause] = field(default_factory=list)

    @property
    def needs_truth(self) -> bool:
        return any(c.kind in ("number", "numbers_all", "names", "names_any") for c in self.clauses)


def _tol(s: str) -> tuple[float, bool]:
    m = re.search(r"tol=([\d.]+)\s*(%|pt)?", s)
    if not m:
        return 0.0, False
    v = float(m.group(1))
    if m.group(2) == "%":
        return v / 100, False
    if m.group(2) == "pt":
        return v, True
    return v, True  # tol=0 or a plain number: absolute


def _words(s: str) -> tuple[str, ...]:
    return tuple(w.strip() for w in s.split(":", 1)[1].split(",") if w.strip())


def parse_check(text: str) -> Check:
    check = Check(text)
    for raw in (p.strip() for p in (text or "").split(";")):
        low = raw.lower()
        if not raw:
            continue
        if low.startswith("numbers_all"):
            t, pts = _tol(low)
            check.clauses.append(Clause("numbers_all", tol=t, tol_points=pts))
        elif low.startswith("number"):
            t, pts = _tol(low)
            check.clauses.append(Clause("number", tol=t, tol_points=pts))
        elif low.startswith(("names_any", "names")):
            m = re.search(r"min=(\d+)", low)
            kind = "names_any" if low.startswith("names_any") else "names"
            check.clauses.append(
                Clause(kind, min=int(m.group(1)) if m else 1, or_none="says none" in low)
            )
        elif low.startswith("terms_all"):
            check.clauses.append(Clause("terms_all", words=_words(raw)))
        elif low.startswith("terms_any"):
            check.clauses.append(Clause("terms_any", words=_words(raw)))
        elif low.startswith("never contains"):
            check.clauses.append(Clause("never", words=_words(raw)))
        elif low.startswith("tool="):
            check.clauses.append(Clause("tool", tool=raw.split("=", 1)[1].strip()))
        elif low == "unknown":
            check.clauses.append(Clause("unknown"))
        elif low == "refuse":
            check.clauses.append(Clause("refuse"))
        elif "no extra tool calls after the search" in low:
            check.clauses.append(Clause("no_calls_after_search"))
        else:
            raise ValueError(f"unknown check clause: {raw!r}")
    if not check.clauses:
        raise ValueError(f"empty check: {text!r}")
    return check


# --- reading numbers and names out of an answer ----------------------------------------

_NUM = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*([kKmM](?![a-zA-Z]))?")


def numbers_in(text: str) -> list[float]:
    """'$190.6k', '1,234', '45.2%' and '2.1M' -> 190600, 1234, 45.2, 2100000."""
    out = []
    for whole, frac, suffix in _NUM.findall(text or ""):
        v = float(whole.replace(",", "") + (frac or ""))
        if suffix:
            v *= 1_000 if suffix.lower() == "k" else 1_000_000
        out.append(v)
    return out


def _close(found: float, truth: float, tol: float, points: bool) -> bool:
    """Within tol: absolute (points, or tol=0 for exact counts) or relative (percent)."""
    return abs(found - truth) <= (tol if points else tol * abs(truth)) + 1e-9


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def mentions(answer: str, name: str) -> bool:
    return bool(_norm(name)) and f" {_norm(name)} " in f" {_norm(answer)} "


def _has_any(answer: str, phrases) -> bool:
    low = (answer or "").lower().replace("’", "'")
    return any(p.lower() in low for p in phrases)


# --- grading -----------------------------------------------------------------------------


@dataclass
class Grade:
    passed: bool
    reasons: list[str]


def grade(check: Check, answer: str, tools: list[str], truth: list[tuple] | None) -> Grade:
    """tools: tool names in call order. truth: rows from the Expected SQL (None if none)."""
    reasons: list[str] = []
    answer = answer or ""
    rows = truth or []
    first = [r[0] for r in rows if r and r[0] is not None]
    for c in check.clauses:
        ok, why = True, ""
        if c.kind == "number":
            if not first:
                ok, why = False, "no truth value"
            else:
                t = float(first[0])
                ok = any(_close(n, t, c.tol, c.tol_points) for n in numbers_in(answer))
                why = f"expected {t:g}"
        elif c.kind == "numbers_all":
            values = [float(v) for v in (rows[0] if rows else ()) if v is not None]
            nums = numbers_in(answer)
            missing = [
                v for v in values if not any(_close(n, v, c.tol, c.tol_points) for n in nums)
            ]
            ok = bool(values) and not missing
            why = f"missing {', '.join(f'{v:g}' for v in missing)}" if missing else "no truth"
        elif c.kind in ("names", "names_any"):
            names = list(dict.fromkeys(str(v) for v in first))
            hits = [n for n in names if mentions(answer, n)]
            if not names:
                ok = c.or_none and _has_any(answer, NONE_PHRASES)
                why = "truth is empty; answer should say none"
            else:
                need = min(c.min, len(names))
                ok = len(hits) >= need
                why = f"{len(hits)} of {need} needed names ({', '.join(names[:5])}…)"
        elif c.kind == "terms_all":
            missing = [w for w in c.words if w.lower() not in answer.lower()]
            ok, why = not missing, f"missing {missing}"
        elif c.kind == "terms_any":
            ok, why = _has_any(answer, c.words), f"none of {list(c.words)}"
        elif c.kind == "never":
            bad = [w for w in c.words if w.lower() in answer.lower()]
            ok, why = not bad, f"contains {bad}"
        elif c.kind == "tool":
            ok, why = c.tool in tools, f"did not call {c.tool}"
        elif c.kind == "unknown":
            ok, why = _has_any(answer, UNKNOWN_PHRASES), "did not say the data can't answer"
        elif c.kind == "refuse":
            ok, why = _has_any(answer, REFUSE_PHRASES), "did not refuse"
        elif c.kind == "no_calls_after_search":
            first_search = tools.index("search_job_text") if "search_job_text" in tools else None
            after = [] if first_search is None else tools[first_search + 1 :]
            ok, why = not after, f"called {after} after the search"
        if not ok:
            reasons.append(f"{c.kind}: {why}")
    return Grade(not reasons, reasons)
