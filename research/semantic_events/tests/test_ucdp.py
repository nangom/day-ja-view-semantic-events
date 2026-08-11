import io
import json
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from research.semantic_events.collectors.ucdp import (
    build_escalation_episodes,
    fetch_events,
    store_events,
)
from research.semantic_events.db import SemanticEventDB


MIDDLE_EAST_ESCALATION = {
    "id": 1001,
    "date_start": "2024-04-13",
    "date_end": "2024-04-13",
    "country": "Iran",
    "region": "Middle East",
    "best": 30,
    "source_original": "Ministry of Interior",
    "side_a": "Government of Iran",
    "side_a_new_id": 114,
    "side_b": "Test Armed Group",
    "side_b_new_id": 9001,
    "conflict_name": "Iran: Test conflict",
    "conflict_new_id": 7001,
}


class UcdpCollectorTest(unittest.TestCase):
    def test_nearby_rows_are_grouped_into_one_episode(self):
        first = {**MIDDLE_EAST_ESCALATION, "id": 2001, "best": 15}
        second = {
            **MIDDLE_EAST_ESCALATION,
            "id": 2002,
            "best": 15,
            "date_start": "2024-04-15",
            "date_end": "2024-04-15",
        }
        fetched, excluded, episodes, _ = build_escalation_episodes([first, second])
        self.assertEqual(fetched, 2)
        self.assertEqual(excluded, 0)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["_episode_best"], 30)
        self.assertEqual(episodes[0]["_member_event_ids"], ["2001", "2002"])

    def test_episode_must_exceed_recent_conflict_baseline(self):
        baseline = {**MIDDLE_EAST_ESCALATION, "id": 3001, "best": 20}
        candidate = {
            **MIDDLE_EAST_ESCALATION,
            "id": 3002,
            "best": 25,
            "date_start": "2024-04-25",
            "date_end": "2024-04-25",
        }
        _, _, episodes, _ = build_escalation_episodes([baseline, candidate])
        self.assertEqual(episodes, [])

    def test_api_fetch_uses_token_and_follows_pages(self):
        page_one = io.BytesIO(json.dumps({
            "TotalPages": 2, "Result": [{"id": 1}]
        }).encode())
        page_two = io.BytesIO(json.dumps({
            "TotalPages": 2, "Result": [{"id": 2}]
        }).encode())
        with patch(
            "research.semantic_events.collectors.ucdp.urllib.request.urlopen",
            side_effect=[page_one, page_two],
        ) as urlopen:
            rows = fetch_events(
                start_date="2024-01-01", end_date="2024-12-31", token="secret"
            )
        self.assertEqual([row["id"] for row in rows], [1, 2])
        self.assertEqual(urlopen.call_count, 2)
        request = urlopen.call_args_list[0].args[0]
        headers = {key.casefold(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-ucdp-access-token"], "secret")
        self.assertNotIn("secret", request.full_url)

    def test_api_fetch_requires_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "UCDP_API_TOKEN"):
                fetch_events(start_date="2024-01-01", end_date="2024-12-31")

    def test_api_fetch_resumes_from_saved_page(self):
        page_one = io.BytesIO(json.dumps({
            "TotalPages": 2, "Result": [{"id": 1}]
        }).encode())
        page_two = io.BytesIO(json.dumps({
            "TotalPages": 2, "Result": [{"id": 2}]
        }).encode())
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            with patch(
                "research.semantic_events.collectors.ucdp.urllib.request.urlopen",
                side_effect=[page_one, URLError("interrupted")],
            ):
                with self.assertRaises(URLError):
                    fetch_events(
                        start_date="2024-01-01", end_date="2024-12-31",
                        token="secret", checkpoint_database=database,
                    )
            with patch(
                "research.semantic_events.collectors.ucdp.urllib.request.urlopen",
                return_value=page_two,
            ) as urlopen:
                rows = fetch_events(
                    start_date="2024-01-01", end_date="2024-12-31",
                    token="secret", checkpoint_database=database,
                )
        self.assertEqual([row["id"] for row in rows], [1, 2])
        self.assertEqual(urlopen.call_count, 1)

    def test_middle_east_high_intensity_event_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            result = store_events(
                database, [MIDDLE_EAST_ESCALATION],
                dataset_released_on="2026-06-15",
            )
            self.assertEqual(result["inserted_candidates"], 1)
            self.assertEqual(result["validation"]["critical"], 0)
            with closing(database.connect()) as connection:
                candidate = connection.execute(
                    """SELECT event_kind_iri, review_status, publicly_available_on,
                              publicly_available_at FROM event_candidates"""
                ).fetchone()
                relations = {
                    row[0] for row in connection.execute(
                        "SELECT object_key FROM event_candidate_relations"
                    )
                }
                document_url = connection.execute(
                    "SELECT canonical_url FROM source_documents"
                ).fetchone()[0]
                snapshot = connection.execute(
                    """SELECT dataset_version, dataset_released_on,
                              fetched_count, accepted_count,
                              input_hash FROM dataset_snapshots"""
                ).fetchone()
                metrics = {
                    row["metric_key"]: row["metric_value"]
                    for row in connection.execute(
                        "SELECT metric_key, metric_value FROM event_candidate_metrics"
                    )
                }
            self.assertEqual(candidate["event_kind_iri"], "djv:Escalation")
            self.assertEqual(candidate["review_status"], "accepted")
            self.assertIsNone(candidate["publicly_available_on"])
            self.assertIsNotNone(candidate["publicly_available_at"])
            self.assertIn("region:MIDDLE_EAST", relations)
            self.assertIn("actor:114", relations)
            self.assertIn("actor:9001", relations)
            self.assertIn("conflict:7001", relations)
            self.assertEqual(document_url, "https://ucdp.uu.se/exploratory/1001")
            self.assertEqual(snapshot["dataset_version"], "26.1")
            self.assertEqual(snapshot["dataset_released_on"], "2026-06-15")
            self.assertEqual(snapshot["fetched_count"], 1)
            self.assertEqual(snapshot["accepted_count"], 1)
            self.assertEqual(len(snapshot["input_hash"]), 64)
            self.assertEqual(metrics["episode_duration_days"], 1)
            self.assertEqual(metrics["best_estimate_fatalities"], 30)
            self.assertEqual(metrics["prior_30d_best_estimate_fatalities"], 0)

    def test_low_intensity_event_is_excluded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = SemanticEventDB(Path(temp_dir) / "events.sqlite3")
            row = {**MIDDLE_EAST_ESCALATION, "id": 1002, "best": 3}
            result = store_events(database, [row])
            self.assertEqual(result["inserted_candidates"], 0)
            self.assertEqual(result["excluded_from_scope"], 1)
