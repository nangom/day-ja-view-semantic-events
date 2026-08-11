from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
import uuid
from contextlib import closing
from typing import Any

from ..db import SemanticEventDB, utc_now


SOURCE_CODE = "US_FED_REGISTER"
API_URL = "https://www.federalregister.gov/api/v1/documents.json"
NAMESPACE = uuid.UUID("9d51ed4b-f14c-43bc-91cc-3304774b574a")
SCOPE_RULE_VERSION = "federal-register-policy-scope-v1"

# overnight 정본의 Policy/Regulation MVP 범위만 후보로 만든다. 먼저 일치한
# 구체 규칙을 사용하며, 결과는 accepted Event가 아니라 pending candidate다.
SCOPE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("POLICY.SHORT_SELLING_BAN", "djv:ShortSellingBan", ("short selling ban", "prohibit short selling")),
    ("POLICY.SHORT_SELLING_RESUMPTION", "djv:ShortSellingResumption", ("resume short selling", "short selling resumption")),
    ("POLICY.EXPORT_CONTROL", "djv:ExportControl", ("export control", "export restriction", "export administration regulations")),
    ("POLICY.TARIFF", "djv:Tariff", ("tariff", "customs duty", "antidumping duty", "countervailing duty")),
    ("POLICY.IMPORT_RESTRICTION", "djv:ImportRestriction", ("import restriction", "import ban", "adjusting imports", "import quota")),
    ("POLICY.SUBSIDY", "djv:Subsidy", ("subsidy", "grant program", "financial assistance award")),
    ("POLICY.TAX_BENEFIT", "djv:TaxBenefit", ("tax credit", "tax benefit", "tax incentive")),
    ("POLICY.INVESTMENT_SUPPORT", "djv:InvestmentSupport", ("investment support", "manufacturing incentive", "industrial investment")),
    ("POLICY.MARKET_REGULATION", "djv:MarketRegulation", ("securities exchange act", "market regulation", "trading rule")),
)


def _stable_id(kind: str, value: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}:{value}"))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scope_match(document: dict[str, Any]) -> tuple[str, str] | None:
    text = " ".join(
        part for part in (document.get("title"), document.get("abstract")) if part
    ).casefold()
    for rule_id, event_kind_iri, keywords in SCOPE_RULES:
        if any(keyword in text for keyword in keywords):
            return rule_id, event_kind_iri
    return None


def _duplicate_group_key(title: str, published_on: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    return _sha256(f"{normalized}|{published_on or 'unknown'}")


def fetch_documents(
    *, start_date: str, end_date: str, limit: int = 20, timeout: int = 30
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    params = urllib.parse.urlencode(
        {
            "per_page": min(limit, 1000),
            "order": "newest",
            "conditions[publication_date][gte]": start_date,
            "conditions[publication_date][lte]": end_date,
            "conditions[type][]": ["RULE", "PRORULE", "PRESDOCU"],
        },
        doseq=True,
    )
    request = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={"User-Agent": "DAY-JA-VIEW-semantic-events/0.2"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return payload.get("results", [])[:limit]


def _previous_document_id(
    connection: Any, source_item_id: str, content_hash: str
) -> str | None:
    row = connection.execute(
        """
        SELECT source_document_id
        FROM source_documents
        WHERE source_code=? AND source_item_id=? AND content_hash<>?
        ORDER BY recorded_at DESC
        LIMIT 1
        """,
        (SOURCE_CODE, source_item_id, content_hash),
    ).fetchone()
    return row[0] if row else None


def _insert_evidence(
    connection: Any,
    *,
    source_document_id: str,
    locator: str,
    value: str,
    now: str,
) -> str:
    evidence_span_id = _stable_id("evidence", f"{source_document_id}:{locator}")
    connection.execute(
        """
        INSERT INTO evidence_spans (
          evidence_span_id, source_document_id, locator_type, locator,
          text_hash, language, created_at
        ) VALUES (?, ?, 'json_pointer', ?, ?, 'en', ?)
        ON CONFLICT(source_document_id, locator_type, locator) DO NOTHING
        """,
        (evidence_span_id, source_document_id, locator, _sha256(value), now),
    )
    return evidence_span_id


def _superseded_candidate_id(
    connection: Any, supersedes_document_id: str | None
) -> str | None:
    if not supersedes_document_id:
        return None
    row = connection.execute(
        """
        SELECT candidate_id
        FROM event_candidates
        WHERE source_document_id=?
        ORDER BY recorded_at DESC
        LIMIT 1
        """,
        (supersedes_document_id,),
    ).fetchone()
    return row[0] if row else None


def store_documents(
    database: SemanticEventDB, documents: list[dict[str, Any]]
) -> dict[str, int | str]:
    database.initialize()
    now = utc_now()
    run_id = str(uuid.uuid4())
    inserted_raw = 0
    inserted_documents = 0
    inserted_candidates = 0
    excluded_from_scope = 0

    with closing(database.connect()) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO ingestion_runs
                  (run_id, source_code, started_at, status)
                VALUES (?, ?, ?, 'running')
                """,
                (run_id, SOURCE_CODE, now),
            )
            for document in documents:
                document_number = document["document_number"]
                raw_json = _canonical_json(document)
                content_hash = _sha256(raw_json)
                raw_id = _stable_id("raw", f"{document_number}:{content_hash}")
                published_on = document.get("publication_date")
                published_precision = "day" if published_on else "unknown"

                raw_result = connection.execute(
                    """
                    INSERT INTO raw_source_items (
                      raw_id, source_code, source_item_id, canonical_url,
                      published_on, published_at, published_precision,
                      retrieved_at, first_seen_at, content_hash, payload_json, run_id
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_code, source_item_id, content_hash) DO NOTHING
                    """,
                    (
                        raw_id,
                        SOURCE_CODE,
                        document_number,
                        document.get("html_url"),
                        published_on,
                        published_precision,
                        now,
                        now,
                        content_hash,
                        raw_json,
                        run_id,
                    ),
                )
                raw_inserted = max(raw_result.rowcount, 0)
                inserted_raw += raw_inserted

                source_document_id = _stable_id(
                    "document", f"{document_number}:{content_hash}"
                )
                supersedes_document_id = _previous_document_id(
                    connection, document_number, content_hash
                )
                document_result = connection.execute(
                    """
                    INSERT INTO source_documents (
                      source_document_id, source_code, raw_id, source_item_id,
                      revision_key, kind, title, canonical_url, official_url,
                      published_on, published_at, published_precision,
                      publicly_available_on, publicly_available_at,
                      availability_precision, content_hash,
                      supersedes_document_id, recorded_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, 'official_release', ?, ?, ?, ?, NULL, ?,
                      ?, NULL, ?, ?, ?, ?
                    )
                    ON CONFLICT(source_code, source_item_id, revision_key) DO NOTHING
                    """,
                    (
                        source_document_id,
                        SOURCE_CODE,
                        raw_id,
                        document_number,
                        content_hash,
                        document["title"],
                        document.get("html_url"),
                        document.get("pdf_url"),
                        published_on,
                        published_precision,
                        published_on,
                        published_precision,
                        content_hash,
                        supersedes_document_id,
                        now,
                    ),
                )
                inserted_documents += max(document_result.rowcount, 0)

                title_evidence_id = _insert_evidence(
                    connection,
                    source_document_id=source_document_id,
                    locator="/title",
                    value=document["title"],
                    now=now,
                )
                scope_match = _scope_match(document)
                if scope_match is None:
                    excluded_from_scope += 1
                    continue
                if not raw_inserted:
                    continue

                scope_rule_id, event_kind_iri = scope_match
                candidate_id = _stable_id(
                    "candidate", f"{source_document_id}:{SCOPE_RULE_VERSION}"
                )
                candidate_iri = f"urn:dayjaview:event-candidate:{candidate_id}"
                supersedes_candidate_id = _superseded_candidate_id(
                    connection, supersedes_document_id
                )
                candidate_result = connection.execute(
                    """
                    INSERT INTO event_candidates (
                      candidate_id, candidate_iri, event_kind_iri, title, summary,
                      occurrence_on, occurrence_at, occurrence_precision,
                      occurrence_to_on, occurrence_to_at, publicly_available_on,
                      publicly_available_at, availability_precision, jurisdiction,
                      source_document_id, primary_evidence_span_id,
                      extraction_kind, extraction_rule_version, confidence_code,
                      review_status, scope_rule_id, duplicate_group_key,
                      parent_event_candidate_id, supersedes_candidate_id, recorded_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, NULL, NULL, 'unknown', NULL, NULL, ?, NULL,
                      ?, 'US', ?, ?, 'rule', ?, 'medium', 'pending', ?, ?,
                      NULL, ?, ?
                    )
                    """,
                    (
                        candidate_id,
                        candidate_iri,
                        event_kind_iri,
                        document["title"],
                        document.get("abstract"),
                        published_on,
                        published_precision,
                        source_document_id,
                        title_evidence_id,
                        SCOPE_RULE_VERSION,
                        scope_rule_id,
                        _duplicate_group_key(document["title"], published_on),
                        supersedes_candidate_id,
                        now,
                    ),
                )
                inserted_candidates += max(candidate_result.rowcount, 0)

                review_payload = {
                    "candidate_id": candidate_id,
                    "event_kind_iri": event_kind_iri,
                    "scope_rule_id": scope_rule_id,
                    "source_document_id": source_document_id,
                    "reason": "deterministic scope keyword match; occurrence and relations require review",
                }
                payload_json = _canonical_json(review_payload)
                connection.execute(
                    """
                    INSERT INTO review_queue (
                      review_item_id, item_type, candidate_id, payload_json,
                      payload_hash, priority, status, created_at
                    ) VALUES (?, 'event_candidate', ?, ?, ?, 3, 'pending', ?)
                    """,
                    (
                        _stable_id("review", candidate_id),
                        candidate_id,
                        payload_json,
                        _sha256(payload_json),
                        now,
                    ),
                )

            connection.execute(
                """
                UPDATE ingestion_runs
                SET finished_at=?, status='success', fetched_count=?,
                    inserted_count=?, candidate_count=?
                WHERE run_id=?
                """,
                (utc_now(), len(documents), inserted_raw, inserted_candidates, run_id),
            )

    return {
        "run_id": run_id,
        "fetched": len(documents),
        "inserted_raw": inserted_raw,
        "inserted_documents": inserted_documents,
        "inserted_candidates": inserted_candidates,
        "excluded_from_scope": excluded_from_scope,
    }


def collect(
    database: SemanticEventDB, *, start_date: str, end_date: str, limit: int = 20
) -> dict[str, int | str]:
    return store_documents(
        database,
        fetch_documents(start_date=start_date, end_date=end_date, limit=limit),
    )
