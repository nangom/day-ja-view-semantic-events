from __future__ import annotations

import hashlib
import json
from contextlib import closing
from typing import Any

from .db import SemanticEventDB, utc_now


REQUIRED_RELATIONS = {
    "djv:Escalation": ("djv:occurredIn",),
    "djv:ExportControlTightening": ("djv:targetsAgent", "djv:affectsIndustry"),
    "djv:ExportControlEasing": ("djv:targetsAgent", "djv:affectsIndustry"),
    "djv:EconomicSanctionTightening": ("djv:targetsAgent",),
    "djv:TariffIncrease": ("djv:targetsAgent", "djv:affectsIndustry"),
    "djv:TariffDecrease": ("djv:targetsAgent", "djv:affectsIndustry"),
    "djv:ImportRestrictionTightening": ("djv:targetsAgent", "djv:affectsIndustry"),
    "djv:ImportRestrictionLifting": ("djv:targetsAgent", "djv:affectsIndustry"),
    "djv:SubsidyAward": ("djv:occurredIn", "djv:affectsIndustry"),
    "djv:TaxBenefitExpansion": ("djv:occurredIn", "djv:affectsIndustry"),
    "djv:RegulationTightening": ("djv:occurredIn",),
    "djv:RegulationEasing": ("djv:occurredIn",),
    "djv:ShortSellingBan": ("djv:occurredIn",),
    "djv:ShortSellingResumption": ("djv:occurredIn",),
    "djv:InvestmentSupport": ("djv:occurredIn", "djv:affectsIndustry"),
}
AUTO_ACCEPT_KINDS = frozenset(REQUIRED_RELATIONS)


def validate_candidates(database: SemanticEventDB) -> dict[str, Any]:
    """Validate deterministic candidates and automatically accept valid rows.

    The latest team decision removes the human approval gate. Invalid rows remain
    pending and are represented in review_queue with explicit validation errors.
    """
    accepted = 0
    pending = 0
    failures: list[dict[str, Any]] = []
    with closing(database.connect()) as connection:
        with connection:
            candidates = connection.execute(
                """
                SELECT c.*, d.canonical_url, d.official_url, e.text_hash
                FROM event_candidates c
                JOIN source_documents d ON d.source_document_id=c.source_document_id
                JOIN evidence_spans e ON e.evidence_span_id=c.primary_evidence_span_id
                WHERE c.review_status IN ('pending', 'accepted')
                ORDER BY c.candidate_id
                """
            ).fetchall()
            for candidate in candidates:
                errors: list[str] = []
                if candidate["event_kind_iri"] not in AUTO_ACCEPT_KINDS:
                    errors.append("no_auto_accept_rule")
                if not candidate["event_kind_iri"]:
                    errors.append("missing_event_kind")
                if not (candidate["occurrence_on"] or candidate["occurrence_at"]):
                    errors.append("missing_occurrence")
                if not (
                    candidate["publicly_available_on"]
                    or candidate["publicly_available_at"]
                ):
                    errors.append("missing_public_availability")
                if not (candidate["canonical_url"] or candidate["official_url"]):
                    errors.append("missing_evidence_url")
                if not candidate["text_hash"]:
                    errors.append("missing_evidence_hash")
                if (
                    candidate["occurrence_on"]
                    and candidate["publicly_available_on"]
                    and candidate["publicly_available_on"] < candidate["occurrence_on"]
                ):
                    errors.append("availability_before_occurrence")

                relation_rows = connection.execute(
                    """SELECT predicate_iri, object_key FROM event_candidate_relations
                       WHERE candidate_id=?""",
                    (candidate["candidate_id"],),
                ).fetchall()
                predicates = {row["predicate_iri"] for row in relation_rows}
                for predicate in REQUIRED_RELATIONS.get(
                    candidate["event_kind_iri"], ()
                ):
                    if predicate not in predicates:
                        errors.append(f"missing_relation:{predicate}")

                duplicates = connection.execute(
                    """SELECT COUNT(*) FROM event_candidates
                       WHERE duplicate_group_key=? AND candidate_id<>?
                         AND review_status='accepted'""",
                    (candidate["duplicate_group_key"], candidate["candidate_id"]),
                ).fetchone()[0]
                if duplicates:
                    errors.append("duplicate_accepted_episode")

                status = "pending" if errors else "accepted"
                connection.execute(
                    "UPDATE event_candidates SET review_status=? WHERE candidate_id=?",
                    (status, candidate["candidate_id"]),
                )
                connection.execute(
                    "UPDATE event_candidate_relations SET review_status=? WHERE candidate_id=?",
                    (status, candidate["candidate_id"]),
                )
                if errors:
                    pending += 1
                    failures.append(
                        {"candidate_id": candidate["candidate_id"], "errors": errors}
                    )
                    payload = json.dumps(failures[-1], sort_keys=True)
                    connection.execute(
                        """
                        INSERT INTO review_queue (
                          review_item_id, item_type, candidate_id, payload_json,
                          payload_hash, priority, status, created_at
                        ) VALUES ('validation:' || ?, 'event_candidate', ?, ?,
                          ?, 1, 'pending', ?)
                        ON CONFLICT(review_item_id) DO UPDATE SET
                          payload_json=excluded.payload_json, status='pending'
                        """,
                        (candidate["candidate_id"], candidate["candidate_id"], payload,
                         hashlib.sha256(payload.encode("utf-8")).hexdigest(), utc_now()),
                    )
                else:
                    accepted += 1
                    connection.execute(
                        "DELETE FROM review_queue WHERE candidate_id=?",
                        (candidate["candidate_id"],),
                    )
    return {
        "checked": accepted + pending,
        "accepted": accepted,
        "pending": pending,
        "critical": pending,
        "failures": failures,
    }
