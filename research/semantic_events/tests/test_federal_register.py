import io
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from research.semantic_events.collectors.federal_register import fetch_documents, store_documents
from research.semantic_events.db import SemanticEventDB


IN_SCOPE_DOCUMENT = {
    "title": "Export Control Rule for Advanced Semiconductors",
    "type": "Rule",
    "abstract": "A deterministic export control fixture, not a real event.",
    "document_number": "TEST-2026-0001",
    "html_url": "https://example.invalid/document",
    "pdf_url": "https://example.invalid/official.pdf",
    "publication_date": "2026-08-11",
    "agencies": [{"name": "Test Agency"}],
}

OUT_OF_SCOPE_DOCUMENT = {
    **IN_SCOPE_DOCUMENT,
    "title": "Administrative Procedure Update",
    "abstract": "A general administrative fixture.",
    "document_number": "TEST-2026-0002",
}

CHINA_SEMICONDUCTOR_DOCUMENT = {
    **IN_SCOPE_DOCUMENT,
    "title": "Export Controls on Advanced Computing Semiconductors to China",
    "abstract": "A rule tightening export restrictions on advanced computing chips to the PRC.",
    "document_number": "TEST-2026-0003",
}


class FederalRegisterCollectorTest(unittest.TestCase):
    def test_fetch_follows_pages_and_honors_limit(self):
        first = io.BytesIO(json.dumps({
            "total_pages": 2, "results": [{"document_number": "A"}]
        }).encode())
        second = io.BytesIO(json.dumps({
            "total_pages": 2,
            "results": [{"document_number": "B"}, {"document_number": "C"}],
        }).encode())
        with patch(
            "research.semantic_events.collectors.federal_register.urllib.request.urlopen",
            side_effect=[first, second],
        ) as urlopen:
            rows = fetch_documents(
                start_date="2024-01-01", end_date="2024-12-31", limit=2
            )
        self.assertEqual([row["document_number"] for row in rows], ["A", "B"])
        self.assertEqual(urlopen.call_count, 2)

    def test_store_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            first = store_documents(database, [CHINA_SEMICONDUCTOR_DOCUMENT, OUT_OF_SCOPE_DOCUMENT])
            second = store_documents(database, [CHINA_SEMICONDUCTOR_DOCUMENT, OUT_OF_SCOPE_DOCUMENT])
            self.assertEqual(first["inserted_raw"], 2)
            self.assertEqual(first["inserted_candidates"], 1)
            self.assertEqual(first["excluded_from_scope"], 1)
            self.assertEqual(second["inserted_raw"], 0)
            self.assertEqual(second["inserted_candidates"], 0)
            stats = database.stats()
            self.assertEqual(stats["raw_source_items"], 2)
            self.assertEqual(stats["source_documents"], 2)
            self.assertEqual(stats["event_candidates"], 1)
            self.assertEqual(stats["review_queue"], 0)
            with closing(database.connect()) as connection:
                status = connection.execute(
                    "SELECT review_status FROM event_candidates"
                ).fetchone()[0]
            self.assertEqual(status, "accepted")

    def test_date_precision_is_preserved_without_invented_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            store_documents(database, [CHINA_SEMICONDUCTOR_DOCUMENT])
            with closing(database.connect()) as connection:
                row = connection.execute(
                    """
                    SELECT published_on, published_at, published_precision
                    FROM source_documents
                    """
                ).fetchone()
            self.assertEqual(row["published_on"], "2026-08-11")
            self.assertIsNone(row["published_at"])
            self.assertEqual(row["published_precision"], "day")

    def test_china_semiconductor_export_control_is_accepted_with_relations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            result = store_documents(database, [CHINA_SEMICONDUCTOR_DOCUMENT])
            self.assertEqual(result["validation"]["critical"], 0)
            with closing(database.connect()) as connection:
                candidate = connection.execute(
                    "SELECT event_kind_iri, review_status FROM event_candidates"
                ).fetchone()
                relations = {
                    (row["predicate_iri"], row["object_key"])
                    for row in connection.execute(
                        "SELECT predicate_iri, object_key FROM event_candidate_relations"
                    )
                }
            self.assertEqual(candidate["event_kind_iri"], "djv:ExportControlTightening")
            self.assertEqual(candidate["review_status"], "accepted")
            self.assertIn(("djv:targetsAgent", "country:CN"), relations)
            self.assertIn(("djv:affectsIndustry", "industry:SEMICONDUCTOR"), relations)


if __name__ == "__main__":
    unittest.main()
