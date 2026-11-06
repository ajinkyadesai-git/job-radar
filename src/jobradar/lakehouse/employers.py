"""Employer name matching between job boards and DOL filings.

Job boards say "Stripe"; DOL filings say "Stripe, Inc." or a legal name such as
"Maplebear Inc." (Instacart). Matching runs in three steps, each measured:

1. Normalize both sides with ``normalize_employer`` (case, punctuation, legal suffixes).
2. Exact match on the normalized name (or the filing's "doing business as" name).
3. A hand-checked alias file, ``config/employer_aliases.csv``, for the rest. Fuzzy matching
   only *suggests* candidates for a person to approve; it never matches on its own.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

# Legal-form words dropped from the end of a name. Words that can tell two companies apart
# ("labs", "technologies", "holdings") are kept on purpose.
LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "lp",
        "llp",
        "plc",
        "pbc",
        "pc",
    }
)
_DBA_RE = re.compile(r"\b(?:d/?b/?a|doing business as)\b", re.IGNORECASE)
_JOINERS_RE = re.compile(r"[.'’]")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_employer(name: str | None) -> str | None:
    """Lowercase, no punctuation, no legal suffix: 'Stripe, Inc.' -> 'stripe'."""
    if not name:
        return None
    text = _DBA_RE.split(name)[0].lower().replace("&", " and ")
    text = _JOINERS_RE.sub("", text)  # L.L.C. -> llc, O'Brien -> obrien
    tokens = _NON_ALNUM_RE.sub(" ", text).split()
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens) or None


def company_keys(slug: str, name: str) -> set[str]:
    """Normalized names a tracked company is known by on its own job board."""
    keys = {normalize_employer(name), normalize_employer(slug.replace("-", " "))}
    return {k for k in keys if k}


ALIAS_COLUMNS = ("company_slug", "dol_employer_name", "status", "reason")
ALIAS_STATUSES = ("proposed", "approved", "rejected")


@dataclass(frozen=True)
class EmployerAlias:
    company_slug: str
    dol_employer_name: str
    status: str
    reason: str

    @property
    def normalized(self) -> str | None:
        return normalize_employer(self.dol_employer_name)


def load_aliases(path: str | Path, known_slugs: set[str] | None = None) -> list[EmployerAlias]:
    """Read and validate the alias file; raise ValueError on any bad row."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != ALIAS_COLUMNS:
            raise ValueError(f"{path}: columns must be {', '.join(ALIAS_COLUMNS)}")
        rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
    aliases = [EmployerAlias(**row) for row in rows]
    seen: dict[str, str] = {}
    for a in aliases:
        if a.status not in ALIAS_STATUSES:
            raise ValueError(f"{a.company_slug}: status must be one of {ALIAS_STATUSES}")
        if known_slugs is not None and a.company_slug not in known_slugs:
            raise ValueError(f"unknown company_slug {a.company_slug!r}")
        if not a.normalized:
            raise ValueError(f"{a.company_slug}: empty dol_employer_name")
        if a.status == "approved":
            other = seen.setdefault(a.normalized, a.company_slug)
            if other != a.company_slug:
                name = a.dol_employer_name
                raise ValueError(f"{name!r} approved for {other} and {a.company_slug}")
    return aliases
