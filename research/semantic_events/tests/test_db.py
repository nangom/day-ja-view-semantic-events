import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from research.semantic_events.db import SemanticEventDB


class SemanticEventDBTest(unittest.TestCase):
    def test_initialize_is_idempotent_and_seeds_reference_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            database.initialize()
            database.initialize()
            stats = database.stats()
            self.assertGreaterEqual(stats["source_registry"], 8)
            self.assertGreaterEqual(stats["event_kind_catalog"], 20)
            self.assertEqual(stats["event_candidates"], 0)
            self.assertEqual(stats["review_queue"], 0)
            with closing(database.connect()) as connection:
                acled = connection.execute(
                    """
                    SELECT contract_status, production_enabled,
                           license_review_status
                    FROM source_registry WHERE source_code='ACLED'
                    """
                ).fetchone()
            self.assertEqual(acled["contract_status"], "blocked")
            self.assertEqual(acled["production_enabled"], 0)
            self.assertEqual(acled["license_review_status"], "required_before_use")

    def test_foreign_keys_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            database.initialize()
            with closing(database.connect()) as connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO evidence_spans (
                          evidence_span_id, source_document_id, locator_type,
                          locator, text_hash, language, created_at
                        ) VALUES (
                          'evidence', 'missing-document', 'json_pointer',
                          '/title', 'hash', 'en', '2026-08-11T00:00:00Z'
                        )
                        """
                    )


if __name__ == "__main__":
    unittest.main()
