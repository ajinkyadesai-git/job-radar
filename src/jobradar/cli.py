"""Command line entry point.

jobradar ingest                   # pull every enabled board, land raw JSON
jobradar ingest --only crusoe     # one or more company slugs
jobradar ingest --dest local      # write to ./data instead of S3
jobradar verify                   # check each board token responds (no writes)
jobradar dol-upload FILE.xlsx ...  # land DOL LCA disclosure files downloaded in a browser
jobradar discover FILE.csv         # which employers have a public Greenhouse or Ashby board
jobradar databricks-deploy         # create or update the daily Databricks job from its JSON spec
jobradar databricks-run            # start the daily job and wait for it to finish
jobradar fit-train                 # train the fit model on your labels and report precision/recall
jobradar fit-queue                 # pick the next postings to label (likely yes, unsure, random)
jobradar fit-score                 # score open jobs and upload the scores (only) to Databricks
jobradar ask "QUESTION"            # ask the AI assistant; it answers with read-only SQL on gold
jobradar rag-index                 # (re)build the search index over open job descriptions
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date

from dotenv import load_dotenv

from jobradar.config import load_companies
from jobradar.ingest.boards import ADAPTERS, BoardContractError
from jobradar.ingest.http import PoliteClient
from jobradar.ingest.pipeline import run_ingest
from jobradar.ingest.storage import LocalStorage, S3Storage, Storage
from jobradar.settings import Settings, get_settings


def _store(settings: Settings) -> Storage:
    if settings.dest == "local":
        return LocalStorage(settings.local_root)
    if not settings.s3_bucket:
        sys.exit("JOBRADAR_S3_BUCKET is not set (or use --dest local)")
    return S3Storage(settings.s3_bucket, settings.s3_prefix, settings.aws_region)


def _client(settings: Settings) -> PoliteClient:
    return PoliteClient(
        settings.requests_per_second,
        settings.http_timeout_s,
        settings.max_retries,
        settings.user_agent,
    )


def cmd_ingest(args: argparse.Namespace, settings: Settings) -> int:
    companies = load_companies(args.companies or settings.companies_file).enabled(args.only)
    summary = run_ingest(
        companies,
        _client(settings),
        _store(settings),
        env=settings.env,
        load_date=date.fromisoformat(args.load_date) if args.load_date else None,
    )
    counts = dict(summary.counts)
    print(
        json.dumps(
            {"run_id": summary.run_id, "counts": counts, "run_log": summary.runlog_uri}, indent=2
        )
    )
    for r in summary.rows:
        if r.status == "failed":
            print(f"FAILED {r.source}/{r.company}: {r.error_type} {r.error}", file=sys.stderr)
    return 0 if summary.ok else 1


def cmd_verify(args: argparse.Namespace, settings: Settings) -> int:
    companies = load_companies(args.companies or settings.companies_file).enabled(args.only)
    client = _client(settings)
    bad = 0
    print(f"{'company':<22}{'source':<12}{'status':<8}{'jobs':>6}  note")
    for c in companies:
        adapter = ADAPTERS[c.source]
        url, params = adapter.url(c)
        res = client.get(url, params=params)
        jobs, note = "-", ""
        if res.status == 200:
            try:
                n, new = adapter.validate(json.loads(res.body))
                jobs = str(n)
                note = f"new fields: {new}" if new else ""
                if n == 0:
                    note = "0 jobs: token may be wrong or board empty"
            except (ValueError, BoardContractError) as exc:
                note, bad = f"bad payload: {exc}", bad + 1
        else:
            bad += 1
            note = "board not found: check token or vendor" if res.status == 404 else ""
        print(f"{c.slug:<22}{c.source.value:<12}{res.status:<8}{jobs:>6}  {note}")
    return 0 if bad == 0 else 1


def cmd_dol_upload(args: argparse.Namespace, settings: Settings) -> int:
    from dataclasses import asdict

    from jobradar.ingest.dol import LcaFileError, upload_lca_file

    store = _store(settings)
    failed = 0
    for path in args.files:
        try:
            result = upload_lca_file(path, store)
            print(json.dumps(asdict(result)))
        except (LcaFileError, OSError) as exc:
            failed += 1
            print(f"FAILED {path}: {exc}", file=sys.stderr)
    return 1 if failed else 0


def cmd_discover(args: argparse.Namespace, settings: Settings) -> int:
    import csv
    from dataclasses import asdict

    from jobradar.ingest.discover import discover

    with open(args.file, newline="") as f:
        rows = [row for row in csv.DictReader(f) if row.get(args.column)]
    names = [row[args.column] for row in rows]
    # Optional "token" column: a board name to try first, when it can't be guessed.
    known = {r[args.column]: r["token"].strip() for r in rows if (r.get("token") or "").strip()}
    print(
        f"Probing {len(names)} employers on Greenhouse and Ashby (polite, about 1 request a second)"
    )
    hits = discover(_client(settings), names, known)
    fields = ["employer_name", "source", "token", "jobs", "board_company_name", "sample_title"]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(h) for h in hits)
    print(f"{len(hits)} boards found; written to {args.out} for review")
    return 0


def _databricks():
    from jobradar.ops.databricks import DatabricksJobs

    host, token = os.environ.get("DATABRICKS_SERVER_HOSTNAME"), os.environ.get("DATABRICKS_TOKEN")
    if not host or not token:
        sys.exit("Set DATABRICKS_SERVER_HOSTNAME and DATABRICKS_TOKEN (in .env or the environment)")
    return DatabricksJobs(host, token)


def cmd_databricks_deploy(args: argparse.Namespace, settings: Settings) -> int:
    from pathlib import Path

    spec = json.loads(Path(args.spec).read_text())
    job_id, action = _databricks().deploy(spec)
    print(json.dumps({"job": spec["name"], "job_id": job_id, "action": action}))
    return 0


def cmd_databricks_run(args: argparse.Namespace, settings: Settings) -> int:
    from jobradar.ops.databricks import DatabricksError

    client = _databricks()
    job_id = client.find_job(args.job)
    if job_id is None:
        sys.exit(f"No Databricks job named {args.job!r}; run jobradar databricks-deploy first")
    params = dict(p.split("=", 1) for p in args.param)
    run_id = client.run_now(job_id, params)
    print(json.dumps({"job": args.job, "run_id": run_id, "params": params}), flush=True)
    if args.no_wait:
        return 0
    try:
        result = client.wait(run_id, timeout_s=args.timeout)
    except DatabricksError as exc:
        print(f"FAILED {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "run_id": run_id,
                "state": result.life_cycle_state,
                "result": result.result_state,
                "message": result.state_message,
                "url": result.run_page_url,
            }
        )
    )
    return 0 if result.ok else 1


def _read_resume(path: str) -> str:
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        print(f"note: no resume at {path}; continuing without the resume (it stays local)")
        return ""
    return p.read_text(errors="ignore")


def cmd_fit_train(args: argparse.Namespace, settings: Settings) -> int:
    from datetime import date as _date

    from jobradar.fit.features import fetch_postings
    from jobradar.fit.labels import read_labels, time_split
    from jobradar.fit.model import resume_scores, save, train_and_evaluate

    labels = read_labels(args.labels)
    train, test = time_split(
        labels, _date.fromisoformat(args.test_from) if args.test_from else None
    )
    postings = fetch_postings(labels["posting_key"], env=args.env)
    data = labels.drop(columns=["role_family"], errors="ignore").merge(postings, on="posting_key")
    missing = len(labels) - len(data)
    resume = _read_resume(args.resume)
    pipe, report = train_and_evaluate(
        data, train["posting_key"], test["posting_key"], resume_text=resume
    )
    out = save(pipe, report, args.out)
    m, b = report.model, report.baseline
    print(
        f"labels: {len(labels)} ({int(labels['y'].sum())} would apply); "
        f"not found in gold: {missing}"
    )
    print(
        f"train days {report.train_days} n={report.n_train}; "
        f"test days {report.test_days} n={report.n_test}"
    )
    print(f"{'':10}{'precision':>10}{'recall':>8}{'PR-AUC':>8}{'P@10':>7}")
    print(
        f"{'model':10}{m.precision:>10}{m.recall:>8}{str(m.pr_auc):>8}{str(m.precision_at_10):>7}"
    )
    print(f"{'baseline':10}{b.precision:>10}{b.recall:>8}{'-':>8}{'-':>7}")
    if resume:
        rm = resume_scores(pipe, data)
        print(
            f"resume match, average: would apply {rm[data['y'] == 1].mean():.3f}, "
            f"would skip {rm[data['y'] == 0].mean():.3f}"
        )
    print("pushes toward apply:", ", ".join(report.top_apply_terms[:10]))
    print("pushes toward skip: ", ", ".join(report.top_skip_terms[:10]))
    print(f"saved {out}/fit_model.joblib and {out}/fit_report.json (git-ignored)")
    return 0


def cmd_fit_queue(args: argparse.Namespace, settings: Settings) -> int:
    from datetime import date as _date
    from pathlib import Path

    import joblib

    from jobradar.fit.features import fetch_candidates
    from jobradar.fit.labels import read_labels
    from jobradar.fit.model import predict_proba
    from jobradar.fit.queue import SHEET_COLUMNS, build_queue, split_posting_key

    pipe = joblib.load(Path(args.model) / "fit_model.joblib")
    labeled = read_labels(args.labels)["posting_key"]
    cands = split_posting_key(fetch_candidates(env=args.env))
    today = _date.today()
    queue = build_queue(
        cands, predict_proba(pipe, cands), labeled, n=args.n, seed=today.toordinal()
    )
    out = Path(args.out or f"data/labels/queue_{today.isoformat()}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    queue[SHEET_COLUMNS].to_csv(out, index=False, header=False, sep="\t")
    queue[["posting_key", "pick", "score"]].to_csv(out.with_suffix(".picks.csv"), index=False)
    counts = queue["pick"].value_counts().to_dict()
    print(
        f"{len(cands)} open candidates, {len(labeled)} already labeled; "
        f"picked {len(queue)}: {counts}"
    )
    print(f"wrote {out}: tab-separated, columns B to H, ready to paste into Daily Labels")
    return 0


def cmd_fit_score(args: argparse.Namespace, settings: Settings) -> int:
    from pathlib import Path

    import joblib

    from jobradar.fit.features import _connect, fetch_candidates
    from jobradar.fit.labels import read_labels
    from jobradar.fit.model import predict_proba
    from jobradar.fit.scores import SCORES_TABLE, model_version, upload_scores

    model_file = Path(args.model) / "fit_model.joblib"
    pipe = joblib.load(model_file)
    version = model_version(model_file, len(read_labels(args.labels)))
    conn = _connect()
    try:
        cands = fetch_candidates(env="prod", connection=conn)
        scores = predict_proba(pipe, cands)
        n = upload_scores(conn, list(cands["posting_key"]), list(scores), version)
    finally:
        conn.close()
    top = cands.assign(score=scores).nlargest(5, "score")
    print(f"scored {n} open jobs with model {version}; uploaded to {SCORES_TABLE}")
    for _, r in top.iterrows():
        print(f"  {r['score']:.2f}  {r['company']}: {r['title']}")
    return 0


def cmd_rag_index(args: argparse.Namespace, settings: Settings) -> int:
    import time

    from jobradar.rag.index import FastEmbedder, build_index, fetch_open_postings

    started = time.time()
    postings = fetch_open_postings(env=args.env)
    print(
        f"{len(postings)} open US postings at sponsors; embedding (first run downloads the model)"
    )

    def progress(done: int, total: int) -> None:
        rate = done / max(time.time() - started, 1)
        left = (total - done) / max(rate, 1e-9)
        print(f"  embedded {done}/{total} new passages, about {left / 60:.0f} min left", flush=True)

    info = build_index(postings, FastEmbedder(), progress=progress)
    print(
        f"indexed {info['chunks']} passages from {info['postings']} postings "
        f"({info['embedded']} embedded, {info['reused']} reused) with {info['model']} "
        f"in {time.time() - started:.0f}s; saved data/rag/ (git-ignored)"
    )
    return 0


def _searcher():
    from pathlib import Path

    if not Path("data/rag/index.faiss").exists():
        print("note: no search index yet (run jobradar rag-index); answering with SQL only")
        return None
    from jobradar.rag.index import FastEmbedder, SearchIndex

    return SearchIndex(FastEmbedder())


def cmd_ask(args: argparse.Namespace, settings: Settings) -> int:
    import anthropic

    from jobradar.agent.assistant import ask, save_trace
    from jobradar.agent.tools import DatabricksRunner

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY in .env (never paste it in chat or commit it)")
    runner = DatabricksRunner(env=args.env)
    try:
        kwargs = {"model": args.model} if args.model else {}
        result = ask(
            args.question,
            anthropic.Anthropic(),
            runner,
            env=args.env,
            searcher=_searcher(),
            resume_text=_read_resume(args.resume) or None,
            **kwargs,
        )
    finally:
        runner.close()
    print(result.answer)
    print("\n---")
    for i, q in enumerate(result.queries, 1):
        print(f"query {i}: {q['detail']}")
        if args.show_sql:
            print("  " + q["sql"].replace("\n", "\n  "))
    print(
        f"{result.model}: {len(result.queries)} queries, {result.input_tokens} input + "
        f"{result.output_tokens} output tokens, {result.seconds}s"
        + (" (stopped at step limit)" if result.stopped_early else "")
        + (f", stop: {result.stop_reason}" if result.stop_reason not in ("end_turn", "") else "")
    )
    print(f"trace: {save_trace(result)}")
    return 0


def cmd_eval(args: argparse.Namespace, settings: Settings) -> int:
    from jobradar.agent.tools import DatabricksRunner
    from jobradar.evals.runner import load_questions, run_evals, truth

    questions = load_questions(only=args.only)
    if not questions:
        sys.exit(f"no questions match --only {args.only!r}")
    runner = DatabricksRunner(env=args.env)
    try:
        if args.truth_only:
            bad = 0
            for q in questions:
                rows, error = truth(q, runner, args.env)
                if error:
                    bad += 1
                    print(f"{q.id} ERROR {error}")
                elif rows is not None:
                    shown = [r[0] if len(r) == 1 else list(r) for r in rows[:5]]
                    more = f" (+{len(rows) - 5} more)" if len(rows) > 5 else ""
                    print(f"{q.id} {len(rows)} rows: {shown}{more}")
            print(f"\n{len(questions)} questions, {bad} truth errors (no API calls made)")
            return 1 if bad else 0

        import anthropic

        from jobradar.agent.assistant import DEFAULT_MODEL, ask

        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("Set ANTHROPIC_API_KEY in .env (never paste it in chat or commit it)")
        model = args.model or DEFAULT_MODEL
        client, schema = anthropic.Anthropic(), runner.describe()
        searcher, resume = _searcher(), _read_resume(args.resume) or None

        def ask_fn(question: str):
            return ask(
                question, client, runner, env=args.env, model=model, schema_text=schema,
                searcher=searcher, resume_text=resume,
            )  # fmt: skip

        print(f"asking {len(questions)} questions with {model}…")
        outcomes, md = run_evals(questions, ask_fn, runner, args.env, model)
    finally:
        runner.close()
    print("\n" + md.read_text())
    print(f"scores: {md}  (also evals/results/latest.md); full answers: {md.with_suffix('.jsonl')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Export .env into the process so libraries such as boto3 see AWS_PROFILE too.
    load_dotenv()
    parser = argparse.ArgumentParser(prog="jobradar")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("ingest", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--companies", help="path to companies.yaml")
        p.add_argument("--only", nargs="+", metavar="SLUG", help="limit to these company slugs")
        if name == "ingest":
            p.add_argument("--dest", choices=["s3", "local"])
            p.add_argument("--load-date", help="override load date, YYYY-MM-DD (backfills)")
    dol = sub.add_parser("dol-upload", help="land DOL LCA disclosure .xlsx files")
    dol.add_argument("files", nargs="+", help="LCA_Disclosure_Data_FY2026_Q3.xlsx and so on")
    dol.add_argument("--dest", choices=["s3", "local"])
    disc = sub.add_parser("discover", help="find public job boards for a list of employers")
    disc.add_argument("file", help="CSV with an employer_name column, e.g. a DOL query export")
    disc.add_argument("--column", default="employer_name")
    disc.add_argument("--out", default="data/discovered_boards.csv")
    dep = sub.add_parser("databricks-deploy", help="create or update the Databricks job")
    dep.add_argument("spec", nargs="?", default="infra/databricks/daily_job.json")
    run = sub.add_parser("databricks-run", help="start a Databricks job and wait for it")
    run.add_argument("--job", default="job-radar-daily")
    run.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    run.add_argument("--timeout", type=float, default=3600, help="seconds to wait")
    run.add_argument("--no-wait", action="store_true")
    fit = sub.add_parser("fit-train", help="train the fit model on your labels")
    fit.add_argument("--labels", default="data/labels/daily_labels.csv")
    fit.add_argument("--out", default="data/model")
    fit.add_argument("--env", choices=["dev", "prod"], default="prod", help="gold to read")
    fit.add_argument("--test-from", help="first labeling day to hold out (default: the last)")
    fit.add_argument("--resume", default="data/resume/resume.txt", help="plain-text resume")
    fq = sub.add_parser("fit-queue", help="pick the next postings to label")
    fq.add_argument("--labels", default="data/labels/daily_labels.csv")
    fq.add_argument("--model", default="data/model")
    fq.add_argument("--env", choices=["dev", "prod"], default="prod")
    fq.add_argument("-n", type=int, default=40, help="how many postings")
    fq.add_argument("--out", help="default data/labels/queue_<today>.csv")
    fs = sub.add_parser("fit-score", help="score open jobs and upload the scores")
    fs.add_argument("--labels", default="data/labels/daily_labels.csv")
    fs.add_argument("--model", default="data/model")
    ri = sub.add_parser("rag-index", help="build the search index over job descriptions")
    ri.add_argument("--env", choices=["dev", "prod"], default="prod")
    ak = sub.add_parser("ask", help="ask the AI assistant a question")
    ak.add_argument("question")
    ak.add_argument("--env", choices=["dev", "prod"], default="prod")
    ak.add_argument("--model", help="Claude model id (default: JOBRADAR_AGENT_MODEL or Sonnet)")
    ak.add_argument("--show-sql", action="store_true", help="print each query")
    ak.add_argument(
        "--resume",
        default="data/resume/resume.txt",
        help="plain-text resume for the resume_fit tool (read locally, never uploaded)",
    )
    ev = sub.add_parser("eval", help="run the eval questions and score the assistant")
    ev.add_argument("--only", help="categories or IDs, comma-separated (e.g. Safety or C01,X02)")
    ev.add_argument("--truth-only", action="store_true", help="check the Expected SQL only")
    ev.add_argument("--env", choices=["dev", "prod"], default="prod")
    ev.add_argument("--model", help="Claude model id (default: JOBRADAR_AGENT_MODEL or Sonnet)")
    ev.add_argument("--resume", default="data/resume/resume.txt", help="plain-text resume")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not args.verbose:  # these clients log every HTTP call at INFO
        for noisy in ("databricks", "httpx", "httpx2", "anthropic"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    overrides = {"dest": args.dest} if getattr(args, "dest", None) else {}
    settings = get_settings(**overrides)
    commands = {
        "ingest": cmd_ingest,
        "verify": cmd_verify,
        "dol-upload": cmd_dol_upload,
        "discover": cmd_discover,
        "databricks-deploy": cmd_databricks_deploy,
        "databricks-run": cmd_databricks_run,
        "fit-train": cmd_fit_train,
        "fit-queue": cmd_fit_queue,
        "fit-score": cmd_fit_score,
        "ask": cmd_ask,
        "rag-index": cmd_rag_index,
        "eval": cmd_eval,
    }
    return commands[args.cmd](args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
