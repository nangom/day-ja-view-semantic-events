from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
import uuid
from contextlib import closing
from typing import Any

from ..checkpoints import clear_scope, load_page, save_page, scope_key
from ..db import SemanticEventDB, utc_now
from ..validation import validate_candidates


SOURCE_CODE = "US_FED_REGISTER"
API_URL = "https://www.federalregister.gov/api/v1/documents.json"
NAMESPACE = uuid.UUID("9d51ed4b-f14c-43bc-91cc-3304774b574a")
SCOPE_RULE_VERSION = "federal-register-policy-scope-v2"
CHINA_TERMS = ("china", "chinese", "people's republic of china", "prc")
SEMICONDUCTOR_TERMS = (
    "semiconductor", "advanced computing", "integrated circuit", "computing chip"
)
TIGHTENING_TERMS = (
    "additional export controls", "new export controls", "tightening export",
    "expanding export controls", "adding entities", "addition of entities",
    "restricting exports",
)
EASING_TERMS = (
    "easing export controls", "removing export controls", "removal of controls",
    "rescinding export controls", "license exception", "removing entities",
)
SANCTION_TERMS = ("economic sanction", "sanctions regulations", "blocking sanctions")
SANCTION_TIGHTENING_TERMS = (
    "imposing sanctions", "additional sanctions", "blocking property",
    "adding persons", "designation of",
)
TARIFF_TERMS = ("tariff", "customs duty", "import duty")
TARIFF_INCREASE_TERMS = (
    "increase tariffs", "increasing tariffs", "additional tariff",
    "raise tariffs", "raising tariffs", "higher tariffs",
)
TARIFF_DECREASE_TERMS = (
    "decrease tariffs", "decreasing tariffs", "reduce tariffs",
    "reducing tariffs", "tariff reduction", "removing tariffs",
)
IMPORT_RESTRICTION_TERMS = (
    "import restriction", "import prohibition", "prohibiting imports",
    "restricting imports", "import quota",
)
IMPORT_RELIEF_TERMS = (
    "removing import restrictions", "lifting import restrictions",
    "rescinding import restrictions", "removing import prohibition",
)
SUBSIDY_TERMS = ("subsidy", "grant program", "financial assistance")
SUBSIDY_AWARD_TERMS = (
    "providing subsidies", "awarding grants", "grant awards",
    "financial assistance for", "incentives for semiconductor",
)
TAX_BENEFIT_TERMS = ("tax credit", "tax deduction", "tax exemption")
TAX_BENEFIT_EXPANSION_TERMS = (
    "establishing a tax credit", "expanding the tax credit",
    "increase the tax credit", "investment tax credit",
)
FINANCIAL_MARKET_TERMS = (
    "securities market", "financial market", "broker-dealer", "short selling",
)
REGULATION_TIGHTENING_TERMS = (
    "new requirements", "additional requirements", "prohibiting short selling",
    "short selling ban", "strengthening investor protections",
)
REGULATION_EASING_TERMS = (
    "removing requirements", "rescinding requirements", "regulatory relief",
    "resuming short selling", "lifting the short selling ban",
)
INVESTMENT_SUPPORT_TERMS = (
    "investment support", "investment incentive", "funding for semiconductor",
    "semiconductor manufacturing incentives", "facility investment grant",
)

def _stable_id(kind: str, value: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}:{value}"))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scope_match(
    document: dict[str, Any],
) -> tuple[str, str, tuple[tuple[str, str, str], ...]] | None:
    text = " ".join(
        part for part in (document.get("title"), document.get("abstract")) if part
    ).casefold()
    has_china = any(term in text for term in CHINA_TERMS)
    has_semiconductor = any(term in text for term in SEMICONDUCTOR_TERMS)

    # Direction-specific rules are intentionally conjunctive. A topic word by
    # itself is never enough to produce an automatically accepted episode.
    if "short selling" in text and any(
        term in text for term in ("resuming short selling", "lifting the short selling ban")
    ):
        return (
            "POLICY.SHORT_SELLING.RESUMPTION.US",
            "djv:ShortSellingResumption",
            (("djv:occurredIn", "country:US", "United States"),),
        )
    if "short selling" in text and any(
        term in text for term in ("short selling ban", "prohibiting short selling")
    ):
        return (
            "POLICY.SHORT_SELLING.BAN.US",
            "djv:ShortSellingBan",
            (("djv:occurredIn", "country:US", "United States"),),
        )
    if (
        any(term in text for term in FINANCIAL_MARKET_TERMS)
        and any(term in text for term in REGULATION_EASING_TERMS)
    ):
        return (
            "POLICY.MARKET_REGULATION.EASING.US",
            "djv:RegulationEasing",
            (("djv:occurredIn", "country:US", "United States"),),
        )
    if (
        any(term in text for term in FINANCIAL_MARKET_TERMS)
        and any(term in text for term in REGULATION_TIGHTENING_TERMS)
    ):
        return (
            "POLICY.MARKET_REGULATION.TIGHTENING.US",
            "djv:RegulationTightening",
            (("djv:occurredIn", "country:US", "United States"),),
        )
    if (
        has_china and has_semiconductor
        and any(term in text for term in EASING_TERMS)
    ):
        return (
            "POLICY.EXPORT_CONTROL.EASING.CHINA.SEMICONDUCTOR",
            "djv:ExportControlEasing",
            (
                ("djv:targetsAgent", "country:CN", "China"),
                ("djv:affectsIndustry", "industry:SEMICONDUCTOR", "Semiconductor"),
            ),
        )
    if (
        has_china and has_semiconductor
        and any(term in text for term in TARIFF_TERMS)
        and any(term in text for term in TARIFF_DECREASE_TERMS)
    ):
        return (
            "POLICY.TARIFF.DECREASE.CHINA.SEMICONDUCTOR",
            "djv:TariffDecrease",
            (
                ("djv:targetsAgent", "country:CN", "China"),
                ("djv:affectsIndustry", "industry:SEMICONDUCTOR", "Semiconductor"),
            ),
        )
    if (
        has_china and has_semiconductor
        and any(term in text for term in TARIFF_TERMS)
        and any(term in text for term in TARIFF_INCREASE_TERMS)
    ):
        return (
            "POLICY.TARIFF.INCREASE.CHINA.SEMICONDUCTOR",
            "djv:TariffIncrease",
            (
                ("djv:targetsAgent", "country:CN", "China"),
                ("djv:affectsIndustry", "industry:SEMICONDUCTOR", "Semiconductor"),
            ),
        )
    if has_china and has_semiconductor and any(
        term in text for term in IMPORT_RELIEF_TERMS
    ):
        return (
            "POLICY.IMPORT_RESTRICTION.LIFTING.CHINA.SEMICONDUCTOR",
            "djv:ImportRestrictionLifting",
            (
                ("djv:targetsAgent", "country:CN", "China"),
                ("djv:affectsIndustry", "industry:SEMICONDUCTOR", "Semiconductor"),
            ),
        )
    if has_china and has_semiconductor and any(
        term in text for term in IMPORT_RESTRICTION_TERMS
    ):
        return (
            "POLICY.IMPORT_RESTRICTION.TIGHTENING.CHINA.SEMICONDUCTOR",
            "djv:ImportRestrictionTightening",
            (
                ("djv:targetsAgent", "country:CN", "China"),
                ("djv:affectsIndustry", "industry:SEMICONDUCTOR", "Semiconductor"),
            ),
        )
    if has_semiconductor and any(term in text for term in SUBSIDY_TERMS) and any(
        term in text for term in SUBSIDY_AWARD_TERMS
    ):
        return (
            "POLICY.SUBSIDY.AWARD.US.SEMICONDUCTOR",
            "djv:SubsidyAward",
            (
                ("djv:occurredIn", "country:US", "United States"),
                ("djv:affectsIndustry", "industry:SEMICONDUCTOR", "Semiconductor"),
            ),
        )
    if has_semiconductor and any(term in text for term in TAX_BENEFIT_TERMS) and any(
        term in text for term in TAX_BENEFIT_EXPANSION_TERMS
    ):
        return (
            "POLICY.TAX_BENEFIT.EXPANSION.US.SEMICONDUCTOR",
            "djv:TaxBenefitExpansion",
            (
                ("djv:occurredIn", "country:US", "United States"),
                ("djv:affectsIndustry", "industry:SEMICONDUCTOR", "Semiconductor"),
            ),
        )
    if has_semiconductor and any(term in text for term in INVESTMENT_SUPPORT_TERMS):
        return (
            "POLICY.INVESTMENT_SUPPORT.US.SEMICONDUCTOR",
            "djv:InvestmentSupport",
            (
                ("djv:occurredIn", "country:US", "United States"),
                ("djv:affectsIndustry", "industry:SEMICONDUCTOR", "Semiconductor"),
            ),
        )
    if (
        has_china and has_semiconductor
        and any(term in text for term in TIGHTENING_TERMS)
    ):
        return (
            "POLICY.EXPORT_CONTROL.TIGHTENING.CHINA.SEMICONDUCTOR",
            "djv:ExportControlTightening",
            (
                ("djv:targetsAgent", "country:CN", "China"),
                ("djv:affectsIndustry", "industry:SEMICONDUCTOR", "Semiconductor"),
            ),
        )
    if (
        has_china
        and any(term in text for term in SANCTION_TERMS)
        and any(term in text for term in SANCTION_TIGHTENING_TERMS)
    ):
        return (
            "POLICY.ECONOMIC_SANCTION.TIGHTENING.CHINA",
            "djv:EconomicSanctionTightening",
            (("djv:targetsAgent", "country:CN", "China"),),
        )
    return None


def _duplicate_group_key(title: str, published_on: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    return _sha256(f"{normalized}|{published_on or 'unknown'}")


def _insert_relation(
    connection: Any, *, candidate_id: str, predicate_iri: str,
    object_key: str, object_label: str, evidence_span_id: str, now: str
) -> None:
    relation_id = _stable_id(
        "relation", f"{candidate_id}:{predicate_iri}:{object_key}:{evidence_span_id}"
    )
    connection.execute(
        """
        INSERT INTO event_candidate_relations (
          relation_candidate_id, candidate_id, predicate_iri, object_key,
          object_label, evidence_span_id, confidence_code, review_status, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'high', 'pending', ?)
        ON CONFLICT(candidate_id, predicate_iri, object_key, evidence_span_id)
        DO NOTHING
        """,
        (relation_id, candidate_id, predicate_iri, object_key, object_label,
         evidence_span_id, now),
    )


def fetch_documents(
    *, start_date: str, end_date: str, limit: int = 20, timeout: int = 30,
    query: str | None = None, checkpoint_database: SemanticEventDB | None = None,
) -> list[dict[str, Any]]:
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    page_size = min(limit, 1000)
    query_params: dict[str, Any] = {
            "per_page": page_size,
            "order": "newest",
            "conditions[publication_date][gte]": start_date,
            "conditions[publication_date][lte]": end_date,
            "conditions[type][]": ["RULE", "PRORULE", "PRESDOCU"],
        }
    if query:
        query_params["conditions[term]"] = query
    documents: list[dict[str, Any]] = []
    checkpoint_key = scope_key({
        "start_date": start_date, "end_date": end_date, "limit": limit,
        "query": query, "types": query_params["conditions[type][]"],
    })
    page = 1
    while len(documents) < limit:
        query_params["page"] = page
        params = urllib.parse.urlencode(query_params, doseq=True)
        payload = (
            load_page(checkpoint_database, SOURCE_CODE, checkpoint_key, page)
            if checkpoint_database else None
        )
        if payload is None:
            request = urllib.request.Request(
                f"{API_URL}?{params}",
                headers={"User-Agent": "DAY-JA-VIEW-semantic-events/0.2"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            if checkpoint_database:
                save_page(checkpoint_database, SOURCE_CODE, checkpoint_key, page, payload)
        results = payload.get("results", [])
        documents.extend(results)
        total_pages = int(payload.get("total_pages", page))
        if not results or page >= total_pages:
            break
        page += 1
    return documents[:limit]


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
) -> dict[str, Any]:
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

                scope_rule_id, event_kind_iri, relations = scope_match
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
                      occurrence_to_on, occurrence_to_at, effective_on, effective_at,
                      publicly_available_on,
                      publicly_available_at, availability_precision, jurisdiction,
                      source_document_id, primary_evidence_span_id,
                      extraction_kind, extraction_rule_version, confidence_code,
                      review_status, scope_rule_id, duplicate_group_key,
                      parent_event_candidate_id, supersedes_candidate_id, recorded_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, ?, NULL, ?, NULL,
                      ?, 'US', ?, ?, 'rule', ?, 'high', 'pending', ?, ?,
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
                        document.get("effective_on"),
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
                for predicate, object_key, object_label in relations:
                    _insert_relation(
                        connection,
                        candidate_id=candidate_id,
                        predicate_iri=predicate,
                        object_key=object_key,
                        object_label=object_label,
                        evidence_span_id=title_evidence_id,
                        now=now,
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

    result: dict[str, int | str | dict[str, Any]] = {
        "run_id": run_id,
        "fetched": len(documents),
        "inserted_raw": inserted_raw,
        "inserted_documents": inserted_documents,
        "inserted_candidates": inserted_candidates,
        "excluded_from_scope": excluded_from_scope,
    }
    result["validation"] = validate_candidates(database)
    return result


def collect(
    database: SemanticEventDB, *, start_date: str, end_date: str, limit: int = 20,
    query: str | None = None, resume: bool = False,
) -> dict[str, Any]:
    checkpoint_key = scope_key({
        "start_date": start_date, "end_date": end_date, "limit": limit,
        "query": query, "types": ["RULE", "PRORULE", "PRESDOCU"],
    })
    result = store_documents(
        database,
        fetch_documents(
            start_date=start_date, end_date=end_date, limit=limit, query=query,
            checkpoint_database=database if resume else None,
        ),
    )
    if resume:
        result["cleared_checkpoint_pages"] = clear_scope(
            database, SOURCE_CODE, checkpoint_key
        )
    return result
