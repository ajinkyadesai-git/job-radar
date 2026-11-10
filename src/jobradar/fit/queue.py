"""Pick tomorrow's postings to label: active learning.

Labeling at random wastes your time: about 1 in 7 postings is a yes, so the model sees few
examples of what you want. Instead the queue mixes three kinds of postings:

- likely yes: the model's highest scores. Confirms or corrects what it thinks you want.
- unsure: scores nearest 0.5. Each label here teaches the model the most.
- random: keeps an honest sample, so the model can't only learn from its own picks.

Rows are shuffled before you see them, so the order doesn't hint at the model's guess.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SHEET_COLUMNS = ["source", "posting_id", "company", "title", "location", "url", "role_family"]


def build_queue(
    candidates: pd.DataFrame,
    scores: np.ndarray,
    labeled_keys,
    n: int = 40,
    seed: int = 0,
    share_likely: float = 0.5,
    share_unsure: float = 0.3,
) -> pd.DataFrame:
    """candidates: open postings with posting_key and SHEET_COLUMNS fields; scores: P(apply)."""
    df = candidates.assign(score=np.asarray(scores, dtype=float))
    df = df[~df["posting_key"].isin(set(labeled_keys))].drop_duplicates("posting_key")
    n = min(n, len(df))
    n_likely, n_unsure = int(round(n * share_likely)), int(round(n * share_unsure))
    likely = df.nlargest(n_likely, "score").assign(pick="likely yes")
    rest = df.drop(likely.index)
    unsure = rest.assign(gap=(rest["score"] - 0.5).abs()).nsmallest(n_unsure, "gap")
    unsure = unsure.drop(columns="gap").assign(pick="unsure")
    rest = rest.drop(unsure.index)
    n_random = n - len(likely) - len(unsure)
    random = rest.sample(n=min(n_random, len(rest)), random_state=seed).assign(pick="random")
    queue = pd.concat([likely, unsure, random]).sample(frac=1, random_state=seed)
    return queue.reset_index(drop=True)


def split_posting_key(df: pd.DataFrame) -> pd.DataFrame:
    parts = df["posting_key"].str.split(":", n=1, expand=True)
    return df.assign(source=parts[0], posting_id=parts[1])
