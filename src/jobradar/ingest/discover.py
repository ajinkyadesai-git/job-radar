"""Find which employers have a public Greenhouse or Ashby job board.

Input: employer names (for example, top DOL sponsors). For each name we guess a few board
tokens from the normalized name ("DoorDash, Inc." -> "doordash") and ask both vendors,
politely, through the same rate-limited client as the ingest. A hit is only a candidate:
a token can belong to a different company, so a person reviews every hit (Greenhouse
reports the board's company name to help) before it goes into config/companies.yaml.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, replace

from jobradar.ingest.http import PoliteClient
from jobradar.lakehouse.employers import normalize_employer

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"


def token_candidates(employer_name: str, max_tokens: int = 3) -> list[str]:
    """'Palantir Technologies Inc.' -> ['palantirtechnologies', 'palantir']."""
    key = normalize_employer(employer_name)
    if not key:
        return []
    words = key.split()
    candidates = ["".join(words), words[0], "".join(words[:2]), "-".join(words)]
    out: list[str] = []
    for c in candidates:
        if len(c) >= 3 and c not in out:
            out.append(c)
    return out[:max_tokens]


@dataclass
class BoardHit:
    employer_name: str
    source: str
    token: str
    jobs: int
    board_company_name: str | None
    sample_title: str | None


def _jobs(body: str) -> list[dict]:
    try:
        jobs = json.loads(body).get("jobs")
    except (ValueError, AttributeError):
        return []
    return jobs if isinstance(jobs, list) else []


def probe(client: PoliteClient, employer_name: str, token: str) -> list[BoardHit]:
    hits = []
    for source, url in (("greenhouse", GREENHOUSE_URL), ("ashby", ASHBY_URL)):
        res = client.get(url.format(token=token))
        jobs = _jobs(res.body) if res.status == 200 else []
        if jobs:
            first = jobs[0]
            hits.append(
                BoardHit(
                    employer_name=employer_name,
                    source=source,
                    token=token,
                    jobs=len(jobs),
                    board_company_name=first.get("company_name"),
                    sample_title=first.get("title"),
                )
            )
    return hits


def discover(
    client: PoliteClient,
    employer_names: Iterable[str],
    known_tokens: dict[str, str] | None = None,
) -> list[BoardHit]:
    """Probe each new token once; stop at the first token that hits for an employer.

    ``known_tokens`` maps an employer name to a board token to try first, for companies
    whose board name can't be guessed from their legal name (DoorDash uses "doordashusa").
    """
    known_tokens = known_tokens or {}
    tried: dict[str, list[BoardHit]] = {}
    hits: list[BoardHit] = []
    for name in employer_names:
        guesses = token_candidates(name)
        first = known_tokens.get(name)
        tokens = [first, *[t for t in guesses if t != first]] if first else guesses
        for token in tokens:
            if token not in tried:
                tried[token] = probe(client, name, token)
            if tried[token]:
                hits.extend(replace(h, employer_name=name) for h in tried[token])
                break
    return hits
