import json
import tempfile
import unittest
from pathlib import Path

from research.semantic_events.collectors.ucdp import store_events
from research.semantic_events.db import SemanticEventDB
from research.semantic_events.export import export_accepted_jsonl
from research.semantic_events.tests.test_ucdp import MIDDLE_EAST_ESCALATION


class AcceptedExportTest(unittest.TestCase):
    def test_export_includes_evidence_relations_and_metrics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            store_events(database, [MIDDLE_EAST_ESCALATION])
            output = Path(temp_dir) / "accepted.jsonl"
            count = export_accepted_jsonl(database, output)
            payload = json.loads(output.read_text(encoding="utf-8").strip())

        self.assertEqual(count, 1)
        self.assertEqual(payload["review_status"], "accepted")
        self.assertEqual(len(payload["text_hash"]), 64)
        self.assertTrue(payload["canonical_url"].startswith("https://"))
        self.assertIn("episode_duration_days", payload["metrics"])
        self.assertIn("djv:occurredIn", {
            relation["predicate_iri"] for relation in payload["relations"]
        })


if __name__ == "__main__":
    unittest.main()
