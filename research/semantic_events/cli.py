from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .collectors.federal_register import collect as collect_federal_register
from .collectors.ucdp import collect as collect_ucdp
from .collectors.ucdp import collect_official_download
from .collectors.ucdp import store_events as store_ucdp_events
from .db import DEFAULT_DB_PATH, SemanticEventDB
from .validation import validate_candidates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DAY-JA-VIEW semantic event DB")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path"
    )
    parser.add_argument(
        "command",
        choices=("init", "stats", "collect-federal-register", "collect-ucdp-api", "collect-ucdp-download", "collect-ucdp-file", "validate"),
    )
    parser.add_argument("--start-date", help="inclusive date in YYYY-MM-DD")
    parser.add_argument("--end-date", help="inclusive date in YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--query", help="Federal Register full-text search term")
    parser.add_argument("--input", type=Path, help="UCDP GED JSON file")
    parser.add_argument("--version", default="26.1", help="versioned UCDP GED release")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--download-url", help="versioned official UCDP GED CSV ZIP URL")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    database = SemanticEventDB(args.db)
    if args.command == "init":
        database.initialize()
        print(f"initialized: {database.path}")
    elif args.command == "stats":
        print(json.dumps(database.stats(), ensure_ascii=False, indent=2))
    elif args.command == "validate":
        print(json.dumps(validate_candidates(database), ensure_ascii=False, indent=2))
    elif args.command == "collect-ucdp-file":
        if not args.input:
            raise SystemExit("--input is required")
        if args.input.suffix.casefold() == ".csv":
            with args.input.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
        else:
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            rows = payload.get("Result", payload.get("results", payload)) if isinstance(payload, dict) else payload
        print(json.dumps(store_ucdp_events(database, rows), ensure_ascii=False, indent=2))
    elif args.command == "collect-ucdp-api":
        if not args.start_date or not args.end_date:
            raise SystemExit("--start-date and --end-date are required")
        result = collect_ucdp(
            database,
            start_date=args.start_date,
            end_date=args.end_date,
            version=args.version,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "collect-ucdp-download":
        kwargs = {"download_url": args.download_url} if args.download_url else {}
        print(json.dumps(
            collect_official_download(database, **kwargs), ensure_ascii=False, indent=2
        ))
    else:
        if not args.start_date or not args.end_date:
            raise SystemExit("--start-date and --end-date are required")
        result = collect_federal_register(
            database,
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
            query=args.query,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
