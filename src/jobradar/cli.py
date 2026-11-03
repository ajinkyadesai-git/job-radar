"""Command line entry point.

jobradar ingest                   # pull every enabled board, land raw JSON
jobradar ingest --only crusoe     # one or more company slugs
jobradar ingest --dest local      # write to ./data instead of S3
jobradar verify                   # check each board token responds (no writes)
jobradar dol-upload FILE.xlsx ...  # land DOL LCA disclosure files downloaded in a browser
"""

from __future__ import annotations

import argparse
import json
import logging
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
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    overrides = {"dest": args.dest} if getattr(args, "dest", None) else {}
    settings = get_settings(**overrides)
    commands = {"ingest": cmd_ingest, "verify": cmd_verify, "dol-upload": cmd_dol_upload}
    return commands[args.cmd](args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
