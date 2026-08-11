from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections import deque
from contextlib import closing
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

from ..db import SemanticEventDB, utc_now
from ..validation import validate_candidates


SOURCE_CODE = "UCDP"
NAMESPACE = uuid.UUID("cb7a4d7a-8489-4e75-aeeb-9ed1460df47f")
RULE_VERSION = "ucdp-middle-east-escalation-v2"
FATALITY_THRESHOLD = 25
ESCALATION_MULTIPLIER = 1.5
EPISODE_GAP_DAYS = 3
BASELINE_DAYS = 30
API_BASE_URL = "https://ucdpapi.pcr.uu.se/api/gedevents"
DEFAULT_VERSION = "26.1"
DEFAULT_CSV_ZIP_URL = "https://ucdp.uu.se/downloads/ged/ged261-csv.zip"
# Broad Middle East bounding box; the exact UCDP `region` field is checked again locally.
MIDDLE_EAST_GEOGRAPHY = "12 25,42 63"
MIDDLE_EAST_COUNTRIES = {
    "bahrain", "egypt", "iran", "iraq", "israel", "jordan", "kuwait",
    "lebanon", "oman", "palestine", "qatar", "saudi arabia", "syria",
    "turkey", "united arab emirates", "yemen",
}


def _stable_id(kind: str, value: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}:{value}"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _insert_relation(
    connection: Any, *, candidate_id: str, predicate: str, object_key: str,
    object_label: str, evidence_id: str, now: str
) -> None:
    relation_id = _stable_id(
        "relation", f"{candidate_id}:{predicate}:{object_key}:{evidence_id}"
    )
    connection.execute(
        """INSERT INTO event_candidate_relations (
          relation_candidate_id, candidate_id, predicate_iri, object_key,
          object_label, evidence_span_id, confidence_code, review_status, recorded_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'high', 'pending', ?)
        ON CONFLICT(candidate_id, predicate_iri, object_key, evidence_span_id)
        DO NOTHING""",
        (relation_id, candidate_id, predicate, object_key, object_label,
         evidence_id, now),
    )


def _first(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _fatalities(row: dict[str, Any]) -> int:
    value = _first(row, "_episode_best", "best", "best_est", "deaths_a", "fatalities") or 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def is_middle_east_escalation(row: dict[str, Any]) -> bool:
    country = str(_first(row, "country", "country_name") or "").casefold()
    region = str(_first(row, "region", "region_name") or "").casefold()
    return (
        (country in MIDDLE_EAST_COUNTRIES or "middle east" in region)
        and _fatalities(row) >= FATALITY_THRESHOLD
    )


def _event_date(row: dict[str, Any], *names: str) -> date:
    return date.fromisoformat(str(_first(row, *names))[:10])


def build_escalation_episodes(
    rows: Iterable[dict[str, Any]],
) -> tuple[int, int, list[dict[str, Any]], str]:
    """Group nearby GED rows and retain only reproducible intensity increases."""
    fetched = 0
    input_hasher = hashlib.sha256()
    middle_east: list[dict[str, Any]] = []
    for row in rows:
        fetched += 1
        input_hasher.update(_hash(_canonical_json(row)).encode("ascii"))
        country = str(_first(row, "country", "country_name") or "").casefold()
        region = str(_first(row, "region", "region_name") or "").casefold()
        if country in MIDDLE_EAST_COUNTRIES or "middle east" in region:
            middle_east.append(dict(row))

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in middle_east:
        conflict_key = str(
            _first(row, "conflict_new_id", "conflict_dset_id", "dyad_new_id", "dyad_dset_id")
            or f"country:{_first(row, 'country', 'country_name')}"
        )
        grouped.setdefault(conflict_key, []).append(row)

    accepted: list[dict[str, Any]] = []
    accepted_member_count = 0
    for conflict_key, conflict_rows in grouped.items():
        conflict_rows.sort(key=lambda row: _event_date(row, "date_start", "date", "event_date"))
        clusters: list[tuple[date, date, list[dict[str, Any]]]] = []
        current_cluster: list[dict[str, Any]] = []
        current_start: date | None = None
        current_end: date | None = None
        for row in conflict_rows:
            row_start = _event_date(row, "date_start", "date", "event_date")
            row_end = _event_date(row, "date_end", "date", "event_date")
            if not current_cluster:
                current_cluster = [row]
                current_start = row_start
                current_end = row_end
                continue
            assert current_start is not None and current_end is not None
            if (row_start - current_end).days <= EPISODE_GAP_DAYS:
                current_cluster.append(row)
                current_end = max(current_end, row_end)
            else:
                clusters.append((current_start, current_end, current_cluster))
                current_cluster = [row]
                current_start = row_start
                current_end = row_end
        if current_cluster:
            assert current_start is not None and current_end is not None
            clusters.append((current_start, current_end, current_cluster))

        recent: deque[tuple[date, int]] = deque()
        recent_deaths = 0
        for start, end, cluster in clusters:
            while recent and (start - recent[0][0]).days > BASELINE_DAYS:
                _, expired_deaths = recent.popleft()
                recent_deaths -= expired_deaths
            deaths = sum(_fatalities(row) for row in cluster)
            prior_deaths = recent_deaths
            recent.append((end, deaths))
            recent_deaths += deaths
            if deaths < FATALITY_THRESHOLD:
                continue
            if prior_deaths and deaths < prior_deaths * ESCALATION_MULTIPLIER:
                continue
            representative = dict(cluster[0])
            member_ids = [str(_first(row, "id", "id_event", "event_id")) for row in cluster]
            representative.update({
                "_episode_id": f"{conflict_key}:{start.isoformat()}:{end.isoformat()}",
                "_member_event_ids": member_ids,
                "_episode_best": deaths,
                "_prior_30d_best": prior_deaths,
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
            })
            accepted.append(representative)
            accepted_member_count += len(cluster)
    return fetched, fetched - accepted_member_count, accepted, input_hasher.hexdigest()


def fetch_events(
    *,
    start_date: str,
    end_date: str,
    version: str = DEFAULT_VERSION,
    token: str | None = None,
    page_size: int = 1000,
    max_pages: int | None = None,
    timeout: int = 60,
) -> list[dict[str, Any]]:
    """Fetch versioned UCDP GED pages using the official token API."""
    access_token = token or os.environ.get("UCDP_API_TOKEN")
    if not access_token:
        raise RuntimeError("UCDP_API_TOKEN is required for UCDP API collection")
    if page_size < 1 or page_size > 1000:
        raise ValueError("page_size must be between 1 and 1000")

    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        params = urllib.parse.urlencode(
            {
                "pagesize": page_size,
                "page": page,
                "StartDate": start_date,
                "EndDate": end_date,
                "Geography": MIDDLE_EAST_GEOGRAPHY,
            }
        )
        request = urllib.request.Request(
            f"{API_BASE_URL}/{version}?{params}",
            headers={
                "x-ucdp-access-token": access_token,
                "User-Agent": "DAY-JA-VIEW-semantic-events/0.2",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        rows.extend(payload.get("Result", []))
        total_pages = int(payload.get("TotalPages", page))
        if page >= total_pages or (max_pages is not None and page >= max_pages):
            break
        page += 1
    return rows


def collect(
    database: SemanticEventDB,
    *,
    start_date: str,
    end_date: str,
    version: str = DEFAULT_VERSION,
    page_size: int = 1000,
    max_pages: int | None = None,
) -> dict[str, Any]:
    return store_events(
        database,
        fetch_events(
            start_date=start_date,
            end_date=end_date,
            version=version,
            page_size=page_size,
            max_pages=max_pages,
        ),
        dataset_version=version,
        source_uri=f"{API_BASE_URL}/{version}",
    )


def collect_official_download(
    database: SemanticEventDB,
    *,
    download_url: str = DEFAULT_CSV_ZIP_URL,
    timeout: int = 120,
) -> dict[str, Any]:
    """Download the official versioned GED CSV ZIP without an API token."""
    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": "DAY-JA-VIEW-semantic-events/0.2"},
    )
    with tempfile.TemporaryFile() as archive_file:
        archive_hasher = hashlib.sha256()
        released_on: str | None = None
        with urllib.request.urlopen(request, timeout=timeout) as response:
            last_modified = response.headers.get("Last-Modified")
            if last_modified:
                released_on = parsedate_to_datetime(last_modified).date().isoformat()
            while chunk := response.read(1024 * 1024):
                archive_hasher.update(chunk)
                archive_file.write(chunk)
        archive_file.seek(0)
        with zipfile.ZipFile(archive_file) as archive:
            csv_names = [name for name in archive.namelist() if name.casefold().endswith(".csv")]
            if len(csv_names) != 1:
                raise RuntimeError(f"expected one CSV in UCDP archive, found {len(csv_names)}")
            with archive.open(csv_names[0]) as raw_stream:
                text_stream = io.TextIOWrapper(raw_stream, encoding="utf-8-sig", newline="")
                return store_events(
                    database,
                    csv.DictReader(text_stream),
                    dataset_version=DEFAULT_VERSION,
                    source_uri=download_url,
                    input_hash=archive_hasher.hexdigest(),
                    dataset_released_on=released_on,
                )


def store_events(
    database: SemanticEventDB,
    rows: Iterable[dict[str, Any]],
    *,
    dataset_version: str = DEFAULT_VERSION,
    source_uri: str = "local-file",
    input_hash: str | None = None,
    dataset_released_on: str | None = None,
) -> dict[str, Any]:
    fetched, excluded, episodes, calculated_input_hash = build_escalation_episodes(rows)
    database.initialize()
    now = utc_now()
    run_id = str(uuid.uuid4())
    inserted = 0
    coverage_start: str | None = None
    coverage_end: str | None = None
    with closing(database.connect()) as connection:
        with connection:
            connection.execute(
                "INSERT INTO ingestion_runs (run_id, source_code, started_at, status) "
                "VALUES (?, ?, ?, 'running')",
                (run_id, SOURCE_CODE, now),
            )
            for row in episodes:
                row_json = _canonical_json(row)
                source_id = str(_first(row, "_episode_id", "id", "id_event", "event_id"))
                member_ids = row.get("_member_event_ids") or [source_id]
                occurrence_on = str(_first(row, "date_start", "date", "event_date"))[:10]
                occurrence_to_on = str(_first(row, "date_end", "date", "event_date"))[:10]
                country = str(_first(row, "country", "country_name"))
                raw_json = row_json
                content_hash = _hash(raw_json)
                raw_id = _stable_id("raw", f"{source_id}:{content_hash}")
                document_id = _stable_id("document", f"{source_id}:{content_hash}")
                evidence_id = _stable_id("evidence", f"{document_id}:/")
                candidate_id = _stable_id("candidate", f"{document_id}:{RULE_VERSION}")
                # `source_original` is often a publisher name, not a URL. Use the
                # stable UCDP record page as Evidence URL and preserve the source
                # label only inside the immutable raw payload.
                source_url = f"https://ucdp.uu.se/exploratory/{member_ids[0]}"
                raw_result = connection.execute(
                    """
                    INSERT INTO raw_source_items (
                      raw_id, source_code, source_item_id, canonical_url,
                      published_on, published_at, published_precision, retrieved_at,
                      first_seen_at, content_hash, payload_json, run_id
                    ) VALUES (?, ?, ?, ?, NULL, NULL, 'unknown', ?, ?, ?, ?, ?)
                    ON CONFLICT(source_code, source_item_id, content_hash) DO NOTHING
                    """,
                    (raw_id, SOURCE_CODE, source_id, source_url, now, now,
                     content_hash, raw_json, run_id),
                )
                if not max(raw_result.rowcount, 0):
                    continue
                connection.execute(
                    """
                    INSERT INTO source_documents (
                      source_document_id, source_code, raw_id, source_item_id,
                      revision_key, kind, title, canonical_url, official_url,
                      published_on, published_at, published_precision,
                      publicly_available_on, publicly_available_at,
                      availability_precision, content_hash, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, 'official_dataset', ?, ?, ?, NULL, NULL,
                      'unknown', NULL, ?, 'second', ?, ?)
                    """,
                    (document_id, SOURCE_CODE, raw_id, source_id, content_hash,
                     f"UCDP escalation event {source_id} in {country}", source_url,
                     source_url, now, content_hash, now),
                )
                connection.execute(
                    """INSERT INTO evidence_spans (
                      evidence_span_id, source_document_id, locator_type, locator,
                      text_hash, language, created_at
                    ) VALUES (?, ?, 'json_pointer', '/', ?, 'en', ?)""",
                    (evidence_id, document_id, content_hash, now),
                )
                connection.execute(
                    """
                    INSERT INTO event_candidates (
                      candidate_id, candidate_iri, event_kind_iri, title, summary,
                      occurrence_on, occurrence_precision, occurrence_to_on,
                      publicly_available_at, availability_precision, jurisdiction,
                      source_document_id, primary_evidence_span_id, extraction_kind,
                      extraction_rule_version, confidence_code, review_status,
                      scope_rule_id, duplicate_group_key, recorded_at
                    ) VALUES (?, ?, 'djv:Escalation', ?, ?, ?, 'day', ?, ?, 'second',
                      ?, ?, ?, 'rule', ?, 'high', 'pending', ?, ?, ?)
                    """,
                    (candidate_id, f"urn:dayjaview:event-candidate:{candidate_id}",
                     f"Armed conflict escalation in {country}",
                     f"UCDP GED event with {_fatalities(row)} best-estimate fatalities",
                     occurrence_on, occurrence_to_on, now, country,
                     document_id, evidence_id, RULE_VERSION,
                     "GEO.ARMED_CONFLICT.ESCALATION.MIDDLE_EAST",
                     _hash(f"{source_id}|{occurrence_on}"), now),
                )
                _insert_relation(
                    connection, candidate_id=candidate_id,
                    predicate="djv:occurredIn", object_key="region:MIDDLE_EAST",
                    object_label="Middle East", evidence_id=evidence_id, now=now,
                )
                for side, id_fields in (
                    ("side_a", ("side_a_new_id", "side_a_dset_id")),
                    ("side_b", ("side_b_new_id", "side_b_dset_id")),
                ):
                    actor_label = _first(row, side)
                    actor_id = _first(row, *id_fields)
                    if actor_label and actor_id:
                        _insert_relation(
                            connection, candidate_id=candidate_id,
                            predicate="djv:hasParticipant",
                            object_key=f"actor:{actor_id}",
                            object_label=str(actor_label), evidence_id=evidence_id,
                            now=now,
                        )
                conflict_id = _first(row, "conflict_new_id", "conflict_dset_id")
                conflict_label = _first(row, "conflict_name")
                if conflict_id and conflict_label:
                    _insert_relation(
                        connection, candidate_id=candidate_id,
                        predicate="djv:partOfEvent",
                        object_key=f"conflict:{conflict_id}",
                        object_label=str(conflict_label), evidence_id=evidence_id,
                        now=now,
                    )
                inserted += 1
                coverage_start = min(coverage_start, occurrence_on) if coverage_start else occurrence_on
                coverage_end = max(coverage_end, occurrence_to_on) if coverage_end else occurrence_to_on
            connection.execute(
                """UPDATE ingestion_runs SET finished_at=?, status='success',
                   fetched_count=?, inserted_count=?, candidate_count=? WHERE run_id=?""",
                (utc_now(), fetched, inserted, inserted, run_id),
            )
            final_input_hash = input_hash or calculated_input_hash
            snapshot_id = _stable_id(
                "snapshot", f"{SOURCE_CODE}:{dataset_version}:{final_input_hash}"
            )
            connection.execute(
                """INSERT INTO dataset_snapshots (
                  snapshot_id, source_code, dataset_version, dataset_released_on,
                  source_uri, input_hash,
                  fetched_count, accepted_count, coverage_start, coverage_end, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_code, dataset_version, input_hash) DO NOTHING""",
                (snapshot_id, SOURCE_CODE, dataset_version, dataset_released_on,
                 source_uri, final_input_hash,
                 fetched, 0, coverage_start, coverage_end, utc_now()),
            )
    validation = validate_candidates(database)
    with closing(database.connect()) as connection:
        with connection:
            accepted_count = connection.execute(
                """SELECT COUNT(*) FROM event_candidates c
                   JOIN source_documents d ON d.source_document_id=c.source_document_id
                   WHERE d.source_code=? AND c.event_kind_iri='djv:Escalation'
                     AND c.review_status='accepted'""",
                (SOURCE_CODE,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE dataset_snapshots SET accepted_count=? WHERE snapshot_id=?",
                (accepted_count, snapshot_id),
            )
    return {
        "run_id": run_id,
        "fetched": fetched,
        "inserted_candidates": inserted,
        "excluded_from_scope": excluded,
        "snapshot_id": snapshot_id,
        "dataset_version": dataset_version,
        "dataset_released_on": dataset_released_on,
        "input_hash": final_input_hash,
        "accepted_count": accepted_count,
        "validation": validation,
    }
