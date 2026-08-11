from __future__ import annotations

import argparse
import json
from pathlib import Path

from .collectors.federal_register import collect as collect_federal_register
from .db import DEFAULT_DB_PATH, SemanticEventDB


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DAY-JA-VIEW semantic event DB")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path"
    )
    parser.add_argument(
        "command", choices=("init", "stats", "collect-federal-register")
    )
    parser.add_argument("--start-date", help="inclusive date in YYYY-MM-DD")
    parser.add_argument("--end-date", help="inclusive date in YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=20)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    database = SemanticEventDB(args.db)
    if args.command == "init":
        database.initialize()
        print(f"initialized: {database.path}")
    elif args.command == "stats":
        print(json.dumps(database.stats(), ensure_ascii=False, indent=2))
    else:
        if not args.start_date or not args.end_date:
            raise SystemExit("--start-date and --end-date are required")
        result = collect_federal_register(
            database,
            start_date=args.start_date,
            end_date=args.end_date,
            limit=args.limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
