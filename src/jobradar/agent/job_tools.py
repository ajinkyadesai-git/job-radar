"""Two tools about one posting: how the user's resume fits it, and what it pays.

resume_fit compares the resume (read on the laptop) with a posting's description using the
fixed skill list in skills.py. Only skill names and the posting's own text go to the model;
the resume text itself is never sent anywhere.

salary_check puts a posting's posted salary next to what similar open postings post and
what the same company filed on H-1B paperwork (LCA) for similar job titles.

Both build their SQL from fixed templates. The only values put into the SQL are checked
against strict patterns first (posting keys, company slugs, category names, and title words
reduced to plain letters), and every query still goes through the SQL guard.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal

from jobradar.agent.skills import context, find_skills
from jobradar.agent.sql_guard import check
from jobradar.agent.tools import UNTRUSTED_NOTE, Runner, ToolCall

POSTING_KEY = re.compile(r"^[a-z]+:[A-Za-z0-9_.-]{1,80}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}$")
CATEGORY = re.compile(r"^[A-Za-z0-9 /&+-]{1,40}$")

MY_YEARS = int(os.environ.get("JOBRADAR_MY_YEARS", "3"))
STRETCH_YEARS = 2
MAX_GAPS = 8

_POSTING_KEY_PROP = {
    "posting_key": {
        "type": "string",
        "description": "The posting's key, like 'greenhouse:12345' (from search_job_text "
        "results or the posting_key column)",
    }
}

RESUME_FIT_TOOL = {
    "name": "resume_fit",
    "description": (
        "Compare the user's resume with one job posting. Returns the skills the posting asks "
        "for, which of them the resume shows (match %), the gaps with a quote from the "
        "posting for each, and years required against the user's years. Use it when the "
        "user asks how well they fit a job, what they are missing, or how to prepare."
    ),
    "input_schema": {
        "type": "object",
        "properties": _POSTING_KEY_PROP,
        "required": ["posting_key"],
    },
}

SALARY_TOOL = {
    "name": "salary_check",
    "description": (
        "What one job posting pays compared with the market: its posted salary range, the "
        "posted salaries of similar open US postings (same role family and seniority), and "
        "the wages this company filed on H-1B paperwork for similar job titles. Use it when "
        "the user asks whether a salary is fair, what to ask for, or what a role pays."
    ),
    "input_schema": {
        "type": "object",
        "properties": _POSTING_KEY_PROP,
        "required": ["posting_key"],
    },
}

# Words that say level or team, not the job itself: dropped when matching titles.
_TITLE_NOISE = {
    "senior", "sr", "junior", "jr", "lead", "staff", "principal", "associate", "entry",
    "level", "mid", "i", "ii", "iii", "iv", "v", "and", "of", "the", "for", "to", "with",
    "a", "an", "in", "on", "remote", "hybrid", "contract", "new", "grad",
}  # fmt: skip


def core_title_words(title: str | None) -> list[str]:
    """'Senior Data Engineer, Payments (Remote)' -> ['data', 'engineer'].

    Cuts the title at the first comma, bracket or dash (team names and locations follow
    those), drops level words, and keeps plain lowercase letters only, so the words are
    safe to put in a SQL LIKE pattern.
    """
    head = re.split(r",|;|\(|\[|\s[-–|]\s|\s/\s|:", title or "", maxsplit=1)[0]
    words = re.findall(r"[a-z]+", head.lower())
    return [w for w in words if w not in _TITLE_NOISE and len(w) > 1][:4]


def reach(years_required: float | None, my_years: int = MY_YEARS) -> str:
    if years_required is None:
        return "Not stated"
    if years_required <= my_years:
        return "Within reach"
    if years_required <= my_years + STRETCH_YEARS:
        return "Stretch"
    return "Out of reach"


def _num(v):
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        return round(v)
    return v


def _wrap(tag: str, payload: dict) -> str:
    body = json.dumps(payload, default=str, ensure_ascii=False)
    return f'<{tag} note="{UNTRUSTED_NOTE}">\n{body}\n</{tag}>'


def _rows(runner: Runner, env: str, sql: str) -> list[dict]:
    columns, rows = runner.run(check(sql, env=env).sql)
    return [dict(zip(columns, r, strict=False)) for r in rows]


def _posting(runner: Runner, env: str, key: str) -> dict | None:
    rows = _rows(
        runner,
        env,
        f"""select posting_key, company, company_name, title, url, location, role_family,
                   seniority, is_open, years_required, fit_score, salary_min_yearly_usd,
                   salary_max_yearly_usd, description_text
            from fct_postings where posting_key = '{key}'""",
    )
    return rows[0] if rows else None


class _Base:
    calls: list[ToolCall]
    runner: Runner
    env: str
    name = ""

    def _lookup(self, posting_key: str) -> tuple[dict | None, str | None]:
        key = (posting_key or "").strip()
        if not POSTING_KEY.match(key):
            self.calls.append(ToolCall(f"{self.name}: {key}", False, "bad posting_key"))
            return None, (
                f"'{key[:80]}' is not a posting key. Keys look like 'greenhouse:12345'; get "
                "them from search_job_text results or select posting_key with run_sql."
            )
        try:
            posting = _posting(self.runner, self.env, key)
        except Exception as e:  # Databricks errors go back to the model, not up the stack
            msg = str(e).splitlines()[0][:300]
            self.calls.append(ToolCall(f"{self.name}: {key}", False, f"error: {msg}"))
            return None, f"Lookup failed in Databricks: {msg}"
        if posting is None:
            self.calls.append(ToolCall(f"{self.name}: {key}", False, "not found"))
            return None, f"No posting with key {key}."
        return posting, None


@dataclass
class ResumeFitTool(_Base):
    runner: Runner
    resume_text: str
    env: str = "prod"
    my_years: int = MY_YEARS
    calls: list[ToolCall] = field(default_factory=list)
    name = "resume_fit"

    def __post_init__(self) -> None:
        self.resume_skills = find_skills(self.resume_text, implied=True)

    def __call__(self, posting_key: str) -> str:
        posting, error = self._lookup(posting_key)
        if error:
            return error
        text = posting.get("description_text") or ""
        wanted = find_skills(f"{posting.get('title') or ''}\n{text}")
        have = [s for s in sorted(wanted, key=wanted.get, reverse=True) if s in self.resume_skills]
        gaps = [s for s in sorted(wanted, key=wanted.get, reverse=True) if s not in have]
        years = posting.get("years_required")
        years = float(years) if years is not None else None
        payload = {
            "posting_key": posting["posting_key"],
            "title": posting.get("title"),
            "company": posting.get("company_name") or posting.get("company"),
            "url": posting.get("url"),
            "is_open": posting.get("is_open"),
            "fit_score": posting.get("fit_score"),
            "skill_match_pct": round(100 * len(have) / len(wanted)) if wanted else None,
            "skills_asked": len(wanted),
            "skills_you_have": have,
            "gaps": [
                {"skill": s, "mentions": wanted[s], "posting_says": context(text, s)}
                for s in gaps[:MAX_GAPS]
            ],
            "more_gaps": gaps[MAX_GAPS:],
            "years_required": years,
            "your_years": self.my_years,
            "reach": reach(years, self.my_years),
            "method": "skills from a fixed list of about 90 tools and practices, found by "
            "keyword in the resume and the posting; skills outside the list are not counted",
        }
        self.calls.append(
            ToolCall(
                f"resume_fit: {posting['posting_key']}",
                True,
                f"{len(have)}/{len(wanted)} skills, {len(gaps)} gaps",
            )
        )
        return _wrap("resume_fit_result", payload)


@dataclass
class SalaryTool(_Base):
    runner: Runner
    env: str = "prod"
    calls: list[ToolCall] = field(default_factory=list)
    name = "salary_check"

    def __call__(self, posting_key: str) -> str:
        posting, error = self._lookup(posting_key)
        if error:
            return error
        lo, hi = posting.get("salary_min_yearly_usd"), posting.get("salary_max_yearly_usd")
        payload: dict = {
            "posting_key": posting["posting_key"],
            "title": posting.get("title"),
            "company": posting.get("company_name") or posting.get("company"),
            "url": posting.get("url"),
            "posted_salary": {"min": _num(lo), "max": _num(hi)} if lo or hi else None,
        }
        notes = []
        try:
            payload["similar_open_postings"] = self._peers(posting)
            payload["company_filed_wages"] = self._company(posting)
            payload["similar_title_filings"], words = self._titles(posting)
        except Exception as e:
            msg = str(e).splitlines()[0][:300]
            self.calls.append(ToolCall(f"salary_check: {posting_key}", False, f"error: {msg}"))
            return f"Salary lookup failed in Databricks: {msg}"
        payload["title_words_matched"] = words
        peers = payload["similar_open_postings"]
        if (lo or hi) and peers and peers.get("median_midpoint"):
            mid = (float(lo or hi) + float(hi or lo)) / 2
            pct = round(100 * (mid / peers["median_midpoint"] - 1))
            payload["posted_vs_similar_median_pct"] = pct
        if not (lo or hi):
            notes.append("this posting does not state a salary")
        notes.append(
            "posted salary = range in job postings; filed wage = the wage on the company's "
            "H-1B (LCA) filing, which is a floor offered to that worker, not a range"
        )
        payload["notes"] = notes
        self.calls.append(ToolCall(f"salary_check: {posting['posting_key']}", True, "ok"))
        return _wrap("salary_result", payload)

    def _peers(self, p: dict) -> dict | None:
        family, level = p.get("role_family"), p.get("seniority")
        if not family or not CATEGORY.match(family):
            return None
        level_filter = f"and seniority = '{level}'" if level and CATEGORY.match(level) else ""
        rows = _rows(
            self.runner,
            self.env,
            f"""with s as (
                  select (salary_min_yearly_usd
                          + coalesce(salary_max_yearly_usd, salary_min_yearly_usd)) / 2 as mid
                  from fct_postings
                  where is_open and is_us and role_family = '{family}' {level_filter}
                    and salary_min_yearly_usd is not null)
                select count(*) as postings,
                       percentile_approx(mid, 0.25) as p25, percentile_approx(mid, 0.5) as p50,
                       percentile_approx(mid, 0.75) as p75
                from s""",
        )
        r = rows[0] if rows else {}
        if not r.get("postings"):
            return None
        return {
            "role_family": family,
            "seniority": level if level_filter else "any",
            "postings_with_salary": r["postings"],
            "p25_midpoint": _num(r["p25"]),
            "median_midpoint": _num(r["p50"]),
            "p75_midpoint": _num(r["p75"]),
        }

    def _company(self, p: dict) -> dict | None:
        slug = p.get("company")
        if not slug or not SLUG.match(slug):
            return None
        rows = _rows(
            self.runner,
            self.env,
            f"select filings, certified_rate, median_filed_wage from dim_employer "
            f"where company = '{slug}'",
        )
        if not rows or not rows[0].get("filings"):
            return None
        r = rows[0]
        return {
            "filings": r["filings"],
            "certified_rate": float(r["certified_rate"]) if r["certified_rate"] else None,
            "median_filed_wage": _num(r["median_filed_wage"]),
        }

    def _titles(self, p: dict) -> tuple[list[dict], list[str]]:
        slug = p.get("company")
        words = core_title_words(p.get("title"))
        if not slug or not SLUG.match(slug) or not words:
            return [], words
        # All title words first; if no filing has them all, the last two words (the job
        # itself, e.g. "integration engineer"). A single word like "engineer" is too broad.
        attempts = [words] + ([words[-2:]] if len(words) > 2 else [])
        rows: list[dict] = []
        for used in attempts:
            likes = " and ".join(f"lower(job_title) like '%{w}%'" for w in used)
            rows = _rows(
                self.runner,
                self.env,
                f"""select job_title, soc_title, count(*) as filings,
                           percentile_approx(wage_from_yearly, 0.5) as median_filed_wage,
                           min(wage_from_yearly) as min_filed_wage,
                           max(wage_from_yearly) as max_filed_wage,
                           max(fiscal_year) as latest_fiscal_year
                    from fct_lca
                    where company = '{slug}' and is_certified and {likes}
                    group by job_title, soc_title
                    order by filings desc
                    limit 8""",
            )
            if rows:
                break
        return [{k: _num(v) for k, v in r.items()} for r in rows], used
