from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any

from .db import SemanticEventDB


def export_accepted_jsonl(database: SemanticEventDB, output: Path) -> int:
    """Export accepted episodes without assuming a team backend schema."""
    database.initialize()
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with closing(database.connect()) as connection, output.open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        candidates = connection.execute(
            """SELECT c.*, d.source_code, d.canonical_url, d.official_url,
                      e.evidence_span_id, e.text_hash
               FROM event_candidates c
               JOIN source_documents d ON d.source_document_id=c.source_document_id
               JOIN evidence_spans e ON e.evidence_span_id=c.primary_evidence_span_id
               WHERE c.review_status='accepted'
               ORDER BY COALESCE(c.occurrence_at, c.occurrence_on), c.candidate_id"""
        ).fetchall()
        for candidate in candidates:
            relations = [
                dict(row) for row in connection.execute(
                    """SELECT predicate_iri, object_key, object_label,
                              evidence_span_id, confidence_code
                       FROM event_candidate_relations
                       WHERE candidate_id=? AND review_status='accepted'
                       ORDER BY predicate_iri, object_key""",
                    (candidate["candidate_id"],),
                )
            ]
            metrics = {
                row["metric_key"]: {
                    "value": row["metric_value"],
                    "unit": row["unit"],
                    "method_version": row["method_version"],
                }
                for row in connection.execute(
                    """SELECT metric_key, metric_value, unit, method_version
                       FROM event_candidate_metrics WHERE candidate_id=?
                       ORDER BY metric_key""",
                    (candidate["candidate_id"],),
                )
            }
            payload: dict[str, Any] = dict(candidate)
            payload["relations"] = relations
            payload["metrics"] = metrics
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count
