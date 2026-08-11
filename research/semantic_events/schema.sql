PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_registry (
  source_code TEXT PRIMARY KEY,
  source_name TEXT NOT NULL,
  source_kind TEXT NOT NULL CHECK (source_kind IN ('official', 'event_dataset', 'other')),
  base_url TEXT NOT NULL,
  jurisdiction TEXT,
  authority_level INTEGER NOT NULL CHECK (authority_level BETWEEN 1 AND 3),
  contract_status TEXT NOT NULL CHECK (contract_status IN ('candidate', 'approved', 'blocked')),
  intended_role TEXT NOT NULL,
  access_requirement TEXT NOT NULL,
  license_review_status TEXT NOT NULL CHECK (license_review_status IN ('pending', 'approved', 'required_before_use', 'rejected')),
  production_enabled INTEGER NOT NULL DEFAULT 0 CHECK (production_enabled IN (0, 1)),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
  run_id TEXT PRIMARY KEY,
  source_code TEXT NOT NULL REFERENCES source_registry(source_code),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
  cursor_in TEXT,
  cursor_out TEXT,
  fetched_count INTEGER NOT NULL DEFAULT 0,
  inserted_count INTEGER NOT NULL DEFAULT 0,
  candidate_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS dataset_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  source_code TEXT NOT NULL REFERENCES source_registry(source_code),
  dataset_version TEXT NOT NULL,
  dataset_released_on TEXT,
  source_uri TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  fetched_count INTEGER NOT NULL,
  accepted_count INTEGER NOT NULL,
  coverage_start TEXT,
  coverage_end TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (source_code, dataset_version, input_hash)
);

CREATE TABLE IF NOT EXISTS raw_source_items (
  raw_id TEXT PRIMARY KEY,
  source_code TEXT NOT NULL REFERENCES source_registry(source_code),
  source_item_id TEXT NOT NULL,
  canonical_url TEXT,
  published_on TEXT,
  published_at TEXT,
  published_precision TEXT NOT NULL CHECK (published_precision IN ('day', 'second', 'unknown')),
  retrieved_at TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  run_id TEXT REFERENCES ingestion_runs(run_id),
  UNIQUE (source_code, source_item_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_raw_source_time
  ON raw_source_items(source_code, published_on, published_at);

CREATE TABLE IF NOT EXISTS source_documents (
  source_document_id TEXT PRIMARY KEY,
  source_code TEXT NOT NULL REFERENCES source_registry(source_code),
  raw_id TEXT NOT NULL REFERENCES raw_source_items(raw_id),
  source_item_id TEXT NOT NULL,
  revision_key TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('news', 'disclosure', 'official_release', 'official_dataset', 'other')),
  title TEXT NOT NULL,
  canonical_url TEXT,
  official_url TEXT,
  published_on TEXT,
  published_at TEXT,
  published_precision TEXT NOT NULL CHECK (published_precision IN ('day', 'second', 'unknown')),
  publicly_available_on TEXT,
  publicly_available_at TEXT,
  availability_precision TEXT NOT NULL CHECK (availability_precision IN ('day', 'second', 'unknown')),
  content_hash TEXT NOT NULL,
  supersedes_document_id TEXT REFERENCES source_documents(source_document_id),
  recorded_at TEXT NOT NULL,
  UNIQUE (source_code, source_item_id, revision_key)
);

CREATE TABLE IF NOT EXISTS evidence_spans (
  evidence_span_id TEXT PRIMARY KEY,
  source_document_id TEXT NOT NULL REFERENCES source_documents(source_document_id),
  locator_type TEXT NOT NULL CHECK (locator_type IN ('char_range', 'page', 'section', 'xpath', 'json_pointer')),
  locator TEXT NOT NULL,
  text_hash TEXT NOT NULL,
  language TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (source_document_id, locator_type, locator)
);

CREATE TABLE IF NOT EXISTS event_kind_catalog (
  event_kind_iri TEXT PRIMARY KEY,
  parent_iri TEXT REFERENCES event_kind_catalog(event_kind_iri),
  domain TEXT NOT NULL CHECK (domain IN ('root', 'geopolitical', 'policy_regulation')),
  label_ko TEXT NOT NULL,
  label_en TEXT NOT NULL,
  definition TEXT,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS event_candidates (
  candidate_id TEXT PRIMARY KEY,
  candidate_iri TEXT NOT NULL UNIQUE,
  event_kind_iri TEXT NOT NULL REFERENCES event_kind_catalog(event_kind_iri),
  title TEXT NOT NULL,
  summary TEXT,
  occurrence_on TEXT,
  occurrence_at TEXT,
  occurrence_precision TEXT NOT NULL CHECK (occurrence_precision IN ('day', 'second', 'unknown')),
  occurrence_to_on TEXT,
  occurrence_to_at TEXT,
  effective_on TEXT,
  effective_at TEXT,
  publicly_available_on TEXT,
  publicly_available_at TEXT,
  availability_precision TEXT NOT NULL CHECK (availability_precision IN ('day', 'second', 'unknown')),
  jurisdiction TEXT,
  source_document_id TEXT NOT NULL REFERENCES source_documents(source_document_id),
  primary_evidence_span_id TEXT NOT NULL REFERENCES evidence_spans(evidence_span_id),
  extraction_kind TEXT NOT NULL CHECK (extraction_kind IN ('official_metadata', 'rule', 'model', 'human', 'hybrid')),
  extraction_rule_version TEXT,
  confidence_code TEXT NOT NULL CHECK (confidence_code IN ('low', 'medium', 'high')),
  review_status TEXT NOT NULL CHECK (review_status IN ('pending', 'in_review', 'accepted', 'rejected', 'superseded')),
  scope_rule_id TEXT NOT NULL,
  duplicate_group_key TEXT NOT NULL,
  parent_event_candidate_id TEXT REFERENCES event_candidates(candidate_id),
  supersedes_candidate_id TEXT REFERENCES event_candidates(candidate_id),
  recorded_at TEXT NOT NULL,
  CHECK (NOT (occurrence_on IS NOT NULL AND occurrence_at IS NOT NULL)),
  CHECK (NOT (effective_on IS NOT NULL AND effective_at IS NOT NULL)),
  CHECK (NOT (publicly_available_on IS NOT NULL AND publicly_available_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_event_candidates_review
  ON event_candidates(review_status, event_kind_iri);
CREATE INDEX IF NOT EXISTS idx_event_candidates_time
  ON event_candidates(occurrence_on, occurrence_at, publicly_available_on, publicly_available_at);

CREATE TABLE IF NOT EXISTS event_candidate_relations (
  relation_candidate_id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES event_candidates(candidate_id),
  predicate_iri TEXT NOT NULL CHECK (predicate_iri IN ('djv:hasParticipant', 'djv:targetsAgent', 'djv:occurredIn', 'djv:affectsCommodity', 'djv:affectsIndustry', 'djv:affectsAsset', 'djv:partOfEvent')),
  object_key TEXT NOT NULL,
  object_label TEXT NOT NULL,
  evidence_span_id TEXT NOT NULL REFERENCES evidence_spans(evidence_span_id),
  confidence_code TEXT NOT NULL CHECK (confidence_code IN ('low', 'medium', 'high')),
  review_status TEXT NOT NULL CHECK (review_status IN ('pending', 'in_review', 'accepted', 'rejected', 'superseded')),
  recorded_at TEXT NOT NULL,
  UNIQUE (candidate_id, predicate_iri, object_key, evidence_span_id)
);

CREATE TABLE IF NOT EXISTS review_queue (
  review_item_id TEXT PRIMARY KEY,
  item_type TEXT NOT NULL CHECK (item_type IN ('event_candidate', 'relation_candidate', 'duplicate_candidate', 'assertion_conflict', 'high_impact')),
  candidate_id TEXT REFERENCES event_candidates(candidate_id),
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
  status TEXT NOT NULL CHECK (status IN ('pending', 'in_review', 'accepted', 'rejected', 'superseded')),
  decision_note TEXT,
  decided_at TEXT,
  created_at TEXT NOT NULL
);

-- accepted KG snapshot과 projection은 이 연구용 SQLite DB에서 만들지 않는다.
-- production publisher가 review 결과와 ontology release를 고정한 뒤 PostgreSQL/RDF에 생성한다.
