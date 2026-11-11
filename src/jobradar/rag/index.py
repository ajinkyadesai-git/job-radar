"""Build and query the search index over job descriptions.

Embeddings run locally with a small open-source model (BAAI/bge-small-en-v1.5 through
fastembed, ONNX, no GPU, $0). Vectors are normalized, so FAISS inner product is cosine
similarity. The index lives in data/rag/ (git-ignored) and is rebuilt with `jobradar rag-index`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from jobradar.rag.chunks import Chunk, chunk_posting

MODEL_NAME = "BAAI/bge-small-en-v1.5"
# bge models work best when the search text (not the passages) carries this instruction.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
INDEX_DIR = Path("data/rag")
META_COLUMNS = [
    "posting_key", "company", "title", "location", "url", "role_family", "seniority",
    "is_target_level", "has_visa_blocker", "years_required", "is_sponsor", "fit_score",
    "first_seen",
]  # fmt: skip


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


class FastEmbedder:
    def __init__(self, model_name: str = MODEL_NAME):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(list(self.model.embed(texts, batch_size=64)), dtype="float32")


def _normalize(v: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norms == 0, 1, norms)


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def build_index(
    postings: pd.DataFrame,
    embedder: Embedder,
    out_dir: Path = INDEX_DIR,
    progress: Callable[[int, int], None] | None = None,
    batch: int = 2000,
) -> dict:
    """postings: META_COLUMNS plus description_text. Writes index.faiss, chunks, vectors, meta.

    Incremental: passages whose exact text was embedded in the previous build reuse their
    saved vector, so a daily rebuild only embeds new or changed postings.
    """
    import faiss

    chunks: list[Chunk] = []
    for r in postings.itertuples(index=False):
        chunks.extend(chunk_posting(r.posting_key, r.title, r.company, r.description_text))
    hashes = [_text_hash(c.text) for c in chunks]

    cached: dict[str, np.ndarray] = {}
    if (out_dir / "chunks.parquet").exists() and (out_dir / "index.faiss").exists():
        old = pd.read_parquet(out_dir / "chunks.parquet")
        old_hashes = old["hash"] if "hash" in old.columns else old["text"].map(_text_hash)
        if (out_dir / "vectors.npy").exists():
            old_vectors = np.load(out_dir / "vectors.npy")
        else:  # an index built before vectors were saved: read them back from FAISS
            old_index = faiss.read_index(str(out_dir / "index.faiss"))
            old_vectors = old_index.reconstruct_n(0, old_index.ntotal)
        if len(old_vectors) == len(old_hashes):
            cached = dict(zip(old_hashes, old_vectors, strict=True))

    todo = [i for i, h in enumerate(hashes) if h not in cached]
    new_vectors: dict[int, np.ndarray] = {}
    for start in range(0, len(todo), batch):
        ids = todo[start : start + batch]
        embedded = _normalize(embedder.embed([chunks[i].text for i in ids]))
        new_vectors.update(zip(ids, embedded, strict=True))
        if progress:
            progress(min(start + batch, len(todo)), len(todo))
    vectors = np.vstack(
        [new_vectors[i] if i in new_vectors else cached[h] for i, h in enumerate(hashes)]
    ).astype("float32")

    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    out_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out_dir / "index.faiss"))
    np.save(out_dir / "vectors.npy", vectors)
    frame = pd.DataFrame([c.__dict__ for c in chunks]).assign(hash=hashes)
    frame.to_parquet(out_dir / "chunks.parquet")
    postings[META_COLUMNS].to_parquet(out_dir / "postings.parquet")
    info = {
        "model": MODEL_NAME,
        "postings": len(postings),
        "chunks": len(chunks),
        "embedded": len(todo),
        "reused": len(chunks) - len(todo),
    }
    (out_dir / "index.json").write_text(json.dumps(info))
    return info


@dataclass
class Hit:
    posting_key: str
    company: str
    title: str
    url: str
    score: float
    passage: str
    location: str | None = None
    years_required: float | None = None
    fit_score: float | None = None


class SearchIndex:
    def __init__(self, embedder: Embedder, folder: Path = INDEX_DIR):
        import faiss

        self.embedder = embedder
        self.index = faiss.read_index(str(folder / "index.faiss"))
        self.chunks = pd.read_parquet(folder / "chunks.parquet")
        self.postings = pd.read_parquet(folder / "postings.parquet").set_index("posting_key")

    def search(self, query: str, k: int = 8, my_level_only: bool = True) -> list[Hit]:
        """Best passages for the query, at most one per posting, best first."""
        q = _normalize(self.embedder.embed([QUERY_PREFIX + query]))
        scores, ids = self.index.search(q, min(len(self.chunks), k * 10))
        hits: list[Hit] = []
        seen: set[str] = set()
        for score, i in zip(scores[0], ids[0], strict=True):
            if i < 0:
                continue
            c = self.chunks.iloc[int(i)]
            key = c["posting_key"]
            if key in seen or key not in self.postings.index:
                continue
            p = self.postings.loc[key]
            if my_level_only and (not bool(p["is_target_level"]) or bool(p["has_visa_blocker"])):
                continue
            seen.add(key)
            passage = c["text"].split("\n", 1)[-1]
            hits.append(
                Hit(
                    key, p["company"], p["title"], p["url"], round(float(score), 3), passage,
                    p.get("location"),
                    None if pd.isna(p.get("years_required")) else float(p["years_required"]),
                    None if pd.isna(p.get("fit_score")) else round(float(p["fit_score"]), 2),
                )
            )  # fmt: skip
            if len(hits) >= k:
                break
        return hits


def fetch_open_postings(env: str = "prod", connection=None) -> pd.DataFrame:
    """Open US postings at sponsors, with the text to index (read-only query)."""
    from jobradar.fit.features import _connect, gold_table

    own = connection is None
    connection = connection or _connect()
    cols = [*META_COLUMNS, "description_text"]
    try:
        with connection.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(cols)} FROM {gold_table(env)} "
                "WHERE is_open AND is_us AND is_sponsor"
            )
            return pd.DataFrame(cur.fetchall(), columns=cols)
    finally:
        if own:
            connection.close()
