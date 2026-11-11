"""Split job descriptions into short passages that can be searched and quoted."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHARS = 900
MAX_CHUNKS_PER_POSTING = 8
_PARA = re.compile(r"\n\s*\n+")
# Boilerplate that every posting at a company repeats; it adds noise, not meaning.
_BOILERPLATE = re.compile(
    r"(?i)equal (employment )?opportunity|accommodation|e-verify|privacy (notice|policy)"
    r"|benefits (include|package)|401\(k\)|pay transparency|we are an equal"
)


@dataclass(frozen=True)
class Chunk:
    posting_key: str
    n: int  # position within the posting, from 0
    text: str  # what gets embedded: title and company first, then the passage


def chunk_posting(
    posting_key: str, title: str, company: str, description: str | None
) -> list[Chunk]:
    """Paragraphs packed into passages of up to MAX_CHARS, boilerplate dropped.

    Each passage starts with "title at company" so a passage about "the role" still
    matches a search for the job title.
    """
    head = f"{title} at {company}."
    paras = [p.strip() for p in _PARA.split(description or "") if p.strip()]
    paras = [p for p in paras if not _BOILERPLATE.search(p)]
    passages: list[str] = []
    current = ""
    for p in paras:
        while len(p) > MAX_CHARS:  # one very long paragraph: cut at a sentence end if possible
            cut = p.rfind(". ", 0, MAX_CHARS)
            cut = cut + 1 if cut > MAX_CHARS // 2 else MAX_CHARS
            passages.append(p[:cut].strip())
            p = p[cut:].strip()
        if current and len(current) + len(p) + 1 > MAX_CHARS:
            passages.append(current)
            current = p
        else:
            current = f"{current}\n{p}".strip()
    if current:
        passages.append(current)
    if not passages:
        passages = [""]
    return [
        Chunk(posting_key, i, f"{head}\n{text}".strip())
        for i, text in enumerate(passages[:MAX_CHUNKS_PER_POSTING])
    ]
