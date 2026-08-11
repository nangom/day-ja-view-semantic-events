import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from research.semantic_events.collectors.federal_register import store_documents
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


class FederalRegisterCollectorTest(unittest.TestCase):
    def test_store_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            first = store_documents(database, [IN_SCOPE_DOCUMENT, OUT_OF_SCOPE_DOCUMENT])
            second = store_documents(database, [IN_SCOPE_DOCUMENT, OUT_OF_SCOPE_DOCUMENT])
            self.assertEqual(first["inserted_raw"], 2)
            self.assertEqual(first["inserted_candidates"], 1)
            self.assertEqual(first["excluded_from_scope"], 1)
            self.assertEqual(second["inserted_raw"], 0)
            self.assertEqual(second["inserted_candidates"], 0)
            stats = database.stats()
            self.assertEqual(stats["raw_source_items"], 2)
            self.assertEqual(stats["source_documents"], 2)
            self.assertEqual(stats["event_candidates"], 1)
            self.assertEqual(stats["review_queue"], 1)

    def test_date_precision_is_preserved_without_invented_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            store_documents(database, [IN_SCOPE_DOCUMENT])
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


if __name__ == "__main__":
    unittest.main()
