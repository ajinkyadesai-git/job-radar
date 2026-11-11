import hashlib
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("faiss")

from jobradar.agent.assistant import ask  # noqa: E402
from jobradar.rag.chunks import MAX_CHARS, MAX_CHUNKS_PER_POSTING, chunk_posting  # noqa: E402
from jobradar.rag.index import META_COLUMNS, SearchIndex, build_index  # noqa: E402


class HashEmbedder:
    """Deterministic bag-of-words vectors: shared words mean similar vectors. No model needed."""

    def embed(self, texts):
        out = np.zeros((len(texts), 256), dtype="float32")
        for i, t in enumerate(texts):
            for w in t.lower().replace(",", " ").replace(".", " ").split():
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
        return out


def test_chunks_start_with_title_drop_boilerplate_and_respect_limits():
    desc = "Build NetSuite integrations in Python.\n\nWe are an equal opportunity employer.\n\n" + (
        "Long paragraph about dbt models. " * 80
    )
    chunks = chunk_posting("ashby:1", "Integration Engineer", "ramp", desc)
    assert chunks[0].text.startswith("Integration Engineer at ramp.")
    assert all("equal opportunity" not in c.text for c in chunks)
    assert all(len(c.text) <= MAX_CHARS + 60 for c in chunks)
    assert len(chunks) <= MAX_CHUNKS_PER_POSTING
    assert chunk_posting("ashby:2", "T", "c", None)[0].text == "T at c."


def postings():
    base = {c: None for c in META_COLUMNS}
    rows = [
        {**base, "posting_key": "ashby:n1", "company": "ramp", "title": "Integration Engineer",
         "url": "https://x/n1", "is_target_level": True, "has_visa_blocker": False,
         "description_text": "Build NetSuite and Salesforce integrations with Python and APIs."},
        {**base, "posting_key": "ashby:d1", "company": "modal", "title": "Analytics Engineer",
         "url": "https://x/d1", "is_target_level": True, "has_visa_blocker": False,
         "description_text": "Own dbt models on Snowflake and build Looker dashboards."},
        {**base, "posting_key": "ashby:s1", "company": "acme", "title": "Staff Integration Eng",
         "url": "https://x/s1", "is_target_level": False, "has_visa_blocker": False,
         "description_text": "Lead NetSuite integrations strategy across the company."},
    ]  # fmt: skip
    return pd.DataFrame(rows)


def test_search_finds_the_right_posting_and_respects_level(tmp_path):
    info = build_index(postings(), HashEmbedder(), tmp_path)
    assert info["postings"] == 3 and info["chunks"] == 3
    idx = SearchIndex(HashEmbedder(), tmp_path)
    hits = idx.search("NetSuite integrations Python", k=3)
    assert hits[0].posting_key == "ashby:n1" and "NetSuite" in hits[0].passage
    assert "ashby:s1" not in {h.posting_key for h in hits}  # Staff: not your level
    everyone = idx.search("NetSuite integrations Python", k=3, my_level_only=False)
    assert "ashby:s1" in {h.posting_key for h in everyone}
    assert idx.search("dbt Snowflake Looker", k=1)[0].posting_key == "ashby:d1"


class FakeRunner:
    def run(self, sql):
        return ["n"], [(1,)]

    def describe(self):
        return "schema"


def test_assistant_offers_and_runs_the_search_tool(tmp_path):
    build_index(postings(), HashEmbedder(), tmp_path)
    idx = SearchIndex(HashEmbedder(), tmp_path)
    use = NS(type="tool_use", id="s1", name="search_job_text", input={"query": "NetSuite Python"})
    responses = [
        NS(content=[use], stop_reason="tool_use", usage=NS(input_tokens=10, output_tokens=5)),
        NS(content=[NS(type="text", text="Ramp: https://x/n1")], stop_reason="end_turn",
           usage=NS(input_tokens=10, output_tokens=5)),
    ]  # fmt: skip
    sent = []

    class Client:
        messages = None

        def create(self, **kw):
            sent.append(kw)
            return responses.pop(0)

    client = Client()
    client.messages = client
    r = ask("Which jobs need NetSuite?", client, FakeRunner(), searcher=idx)
    assert [t["name"] for t in sent[0]["tools"]][:2] == ["run_sql", "search_job_text"]
    tool_result = sent[1]["messages"][2]["content"][0]["content"]
    assert tool_result.startswith("<search_result") and "https://x/n1" in tool_result
    assert r.queries[0]["detail"].endswith("postings") and r.answer.startswith("Ramp")


class CountingEmbedder(HashEmbedder):
    def __init__(self):
        self.seen = 0

    def embed(self, texts):
        self.seen += len(texts)
        return super().embed(texts)


def test_rebuild_reuses_vectors_and_embeds_only_new_postings(tmp_path):
    first = CountingEmbedder()
    build_index(postings().iloc[:2], first, tmp_path)
    assert first.seen == 2
    second = CountingEmbedder()
    info = build_index(postings(), second, tmp_path)
    assert second.seen == 1 and info["reused"] == 2 and info["embedded"] == 1
    hits = SearchIndex(HashEmbedder(), tmp_path).search("dbt Snowflake Looker", k=1)
    assert hits[0].posting_key == "ashby:d1"


def test_rebuild_reuses_an_index_saved_without_vectors(tmp_path):
    build_index(postings(), HashEmbedder(), tmp_path)
    (tmp_path / "vectors.npy").unlink()
    chunks = pd.read_parquet(tmp_path / "chunks.parquet").drop(columns="hash")
    chunks.to_parquet(tmp_path / "chunks.parquet")  # what today's first build leaves behind
    again = CountingEmbedder()
    info = build_index(postings(), again, tmp_path)
    assert again.seen == 0 and info["reused"] == 3
