from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PACKAGE_DIR / "data" / "semantic_events.sqlite3"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SemanticEventDB:
    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        schema = (PACKAGE_DIR / "schema.sql").read_text(encoding="utf-8")
        taxonomy = json.loads(
            (PACKAGE_DIR / "taxonomy_seed.json").read_text(encoding="utf-8")
        )
        with closing(self.connect()) as connection:
            with connection:
                connection.executescript(schema)
                connection.executemany(
                    """
                INSERT INTO event_kind_catalog (
                  event_kind_iri, parent_iri, domain, label_ko, label_en,
                  definition, active
                ) VALUES (
                  :event_kind_iri, :parent_iri, :domain, :label_ko, :label_en,
                  :definition, 1
                )
                ON CONFLICT(event_kind_iri) DO UPDATE SET
                  parent_iri=excluded.parent_iri,
                  domain=excluded.domain,
                  label_ko=excluded.label_ko,
                  label_en=excluded.label_en,
                  definition=excluded.definition
                """,
                    taxonomy,
                )
                self._seed_sources(connection)

    @staticmethod
    def _seed_sources(connection: sqlite3.Connection) -> None:
        created_at = utc_now()
        sources = json.loads(
            (PACKAGE_DIR / "source_plan.json").read_text(encoding="utf-8")
        )
        connection.executemany(
            """
            INSERT INTO source_registry (
              source_code, source_name, source_kind, base_url, jurisdiction,
              authority_level, contract_status, intended_role,
              access_requirement, license_review_status,
              production_enabled, created_at
            ) VALUES (
              :source_code, :source_name, :source_kind, :base_url, :jurisdiction,
              :authority_level, :contract_status, :intended_role,
              :access_requirement, :license_review_status, 0, :created_at
            )
            ON CONFLICT(source_code) DO UPDATE SET
              source_name=excluded.source_name,
              source_kind=excluded.source_kind,
              base_url=excluded.base_url,
              jurisdiction=excluded.jurisdiction,
              authority_level=excluded.authority_level,
              contract_status=excluded.contract_status,
              intended_role=excluded.intended_role,
              access_requirement=excluded.access_requirement,
              license_review_status=excluded.license_review_status,
              production_enabled=0
            """,
            [{**source, "created_at": created_at} for source in sources],
        )

    def stats(self) -> dict[str, int]:
        tables = (
            "source_registry",
            "event_kind_catalog",
            "dataset_snapshots",
            "raw_source_items",
            "source_documents",
            "evidence_spans",
            "event_candidates",
            "event_candidate_relations",
            "review_queue",
        )
        with closing(self.connect()) as connection:
            return {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table}"  # table names are fixed above
                ).fetchone()[0]
                for table in tables
            }
