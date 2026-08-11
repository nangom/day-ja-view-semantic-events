from __future__ import annotations

import hashlib
import json
from contextlib import closing
from typing import Any

from .db import SemanticEventDB, utc_now


def scope_key(parameters: dict[str, Any]) -> str:
    value = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_page(
    database: SemanticEventDB, source_code: str, key: str, page: int
) -> dict[str, Any] | None:
    database.initialize()
    with closing(database.connect()) as connection:
        row = connection.execute(
            """SELECT payload_json FROM ingestion_page_checkpoints
               WHERE source_code=? AND scope_key=? AND page_number=?""",
            (source_code, key, page),
        ).fetchone()
    return json.loads(row[0]) if row else None


def save_page(
    database: SemanticEventDB, source_code: str, key: str, page: int,
    payload: dict[str, Any],
) -> None:
    database.initialize()
    payload_json = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    content_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    with closing(database.connect()) as connection:
        with connection:
            connection.execute(
                """INSERT INTO ingestion_page_checkpoints (
                     source_code, scope_key, page_number, payload_json,
                     content_hash, saved_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_code, scope_key, page_number) DO UPDATE SET
                     payload_json=excluded.payload_json,
                     content_hash=excluded.content_hash,
                     saved_at=excluded.saved_at""",
                (source_code, key, page, payload_json, content_hash, utc_now()),
            )


def clear_scope(database: SemanticEventDB, source_code: str, key: str) -> int:
    with closing(database.connect()) as connection:
        with connection:
            result = connection.execute(
                """DELETE FROM ingestion_page_checkpoints
                   WHERE source_code=? AND scope_key=?""",
                (source_code, key),
            )
    return max(result.rowcount, 0)
