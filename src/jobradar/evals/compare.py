"""Compare two eval runs side by side: accuracy, speed and estimated cost (T41).

Used to compare models (Sonnet vs Haiku) or providers (Claude API vs Bedrock) on the
same questions. Only the
questions both runs answered are compared. No API calls: it reads the saved .jsonl files.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from jobradar.evals.runner import cost_usd, price_for


def _load(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {r["id"]: r for r in rows}


def _label(rows: dict[str, dict], path: Path) -> str:
    models = {r.get("model") for r in rows.values() if r.get("model")}
    return models.pop() if len(models) == 1 else path.stem


def _cost(rows, label: str) -> float:
    tin = sum(r["input_tokens"] for r in rows)
    tout = sum(r["output_tokens"] for r in rows)
    return cost_usd(label, tin, tout)


def compare_runs(a_path: Path, b_path: Path) -> str:
    a, b = _load(a_path), _load(b_path)
    ids = [i for i in a if i in b]
    if not ids:
        raise SystemExit("the two runs have no questions in common")
    la, lb = _label(a, a_path), _label(b, b_path)
    A, B = [a[i] for i in ids], [b[i] for i in ids]

    def stats(rows, label):
        secs = [r["seconds"] for r in rows]
        return {
            "passed": sum(r["passed"] for r in rows),
            "median_s": statistics.median(secs),
            "p90_s": sorted(secs)[max(0, round(0.9 * len(secs)) - 1)],
            "tokens_in": sum(r["input_tokens"] for r in rows),
            "tokens_out": sum(r["output_tokens"] for r in rows),
            "cost": _cost(rows, label),
        }

    sa, sb = stats(A, la), stats(B, lb)
    (ia, oa), (ib, ob) = price_for(la), price_for(lb)
    n = len(ids)
    lines = [
        f"# Comparison: {la} vs {lb}",
        "",
        f"Same {n} questions, same assistant, same tools and checks. Cost is estimated from "
        f"list prices per million input / output tokens: {la} ${ia:g} / ${oa:g}, "
        f"{lb} ${ib:g} / ${ob:g}.",
        "",
        f"| | {la} | {lb} |",
        "|---|---|---|",
        f"| Passed | {sa['passed']} of {n} | {sb['passed']} of {n} |",
        f"| Median seconds per question | {sa['median_s']:.1f} | {sb['median_s']:.1f} |",
        f"| Slowest 10% (p90 seconds) | {sa['p90_s']:.1f} | {sb['p90_s']:.1f} |",
        f"| Tokens in / out | {sa['tokens_in']:,} / {sa['tokens_out']:,} | "
        f"{sb['tokens_in']:,} / {sb['tokens_out']:,} |",
        f"| Estimated cost | ${sa['cost']:.2f} | ${sb['cost']:.2f} |",
        "",
        "## By category",
        "",
        f"| Category | {la} | {lb} |",
        "|---|---|---|",
    ]
    by_cat = defaultdict(list)
    for i in ids:
        by_cat[a[i]["category"]].append(i)
    for cat, cat_ids in by_cat.items():
        pa = sum(a[i]["passed"] for i in cat_ids)
        pb = sum(b[i]["passed"] for i in cat_ids)
        lines.append(f"| {cat} | {pa} of {len(cat_ids)} | {pb} of {len(cat_ids)} |")
    differ = [i for i in ids if a[i]["passed"] != b[i]["passed"]]
    lines += ["", "## Questions where they differ", ""]
    if not differ:
        lines.append("None: both passed and failed the same questions.")
    for i in differ:
        winner = la if a[i]["passed"] else lb
        loser_reasons = "; ".join((b[i] if a[i]["passed"] else a[i])["reasons"])
        lines.append(f"- **{i}** {a[i]['question']}: passed on {winner} only ({loser_reasons})")
    return "\n".join(lines) + "\n"
