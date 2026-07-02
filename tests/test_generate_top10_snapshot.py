"""Unit tests for scripts/generate_top10_snapshot.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_top10_snapshot import build_snapshot_payload


class GenerateTop10SnapshotTests(unittest.TestCase):
    def make_fixture(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="top10-snapshot-fixture-"))

    def write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))

    def test_uses_latest_trading_date(self) -> None:
        data_dir = self.make_fixture() / "docs" / "data"
        self.write_json(
            data_dir / "index.json",
            {
                "dates": ["2026-07-01", "2026-07-02"],
                "trading_dates": ["2026-07-01", "2026-07-02"],
                "latest": "2026-07-01",
                "latest_trading_date": "2026-07-02",
            },
        )
        self.write_json(
            data_dir / "2026-07-01.json",
            {"workspace": {"views": {"highlights": [{"code": "A1", "name": "Old", "score": 1}]}}},
        )
        self.write_json(
            data_dir / "2026-07-02.json",
            {
                "workspace": {
                    "views": {"highlights": [{"code": "A2", "name": "New", "score": 2}]},
                }
            },
        )

        payload = build_snapshot_payload("job-latest", data_dir)
        self.assertEqual(payload["snapshot_date"], "2026-07-02")
        self.assertEqual(payload["items"][0]["code"], "A2")

    def test_top10_cap_and_rank(self) -> None:
        data_dir = self.make_fixture() / "docs" / "data"
        self.write_json(
            data_dir / "index.json",
            {
                "dates": ["2026-07-01"],
                "trading_dates": ["2026-07-01"],
                "latest": "2026-07-01",
                "latest_trading_date": "2026-07-01",
            },
        )
        self.write_json(
            data_dir / "2026-07-01.json",
            {
                "workspace": {
                    "views": {
                        "highlights": [
                            {"code": f"S{i}", "name": f"Stock{i}", "score": 20 - i, "rank": i}
                            for i in range(15)
                        ],
                    },
                },
            },
        )

        payload = build_snapshot_payload("job-top10", data_dir)
        self.assertEqual(payload["status"], "done")
        self.assertEqual(len(payload["items"]), 10)
        self.assertEqual([item["rank"] for item in payload["items"]], list(range(1, 11)))

        scores = [item["score"] for item in payload["items"]]
        self.assertTrue(all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)))

    def test_payload_schema(self) -> None:
        data_dir = self.make_fixture() / "docs" / "data"
        self.write_json(
            data_dir / "index.json",
            {
                "dates": ["2026-07-01"],
                "trading_dates": ["2026-07-01"],
                "latest": "2026-07-01",
                "latest_trading_date": "",
            },
        )
        self.write_json(
            data_dir / "2026-07-01.json",
            {
                "workspace": {
                    "views": {
                        "highlights": [
                            {
                                "code": "300001",
                                "name": "示例股票",
                                "score": 88.8,
                                "action": "可上车",
                                "action_reason": "测试原因",
                                "change_pct": 3.14,
                                "current_price": 12.34,
                            },
                        ],
                    },
                },
            },
        )

        payload = build_snapshot_payload("job-schema", data_dir)
        self.assertEqual(payload["source"], "github_actions")
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["job_id"], "job-schema")
        self.assertIn("items", payload)
        self.assertIsInstance(payload["items"], list)
        self.assertEqual(len(payload["items"]), 1)

        item = payload["items"][0]
        for field in ("rank", "code", "name", "score", "action", "reason", "source", "change_pct", "current_price"):
            self.assertIn(field, item)

        self.assertEqual(item["code"], "300001")
        self.assertEqual(item["source"], "highlights")

    def test_fallback_uses_raw_sources(self) -> None:
        data_dir = self.make_fixture() / "docs" / "data"
        self.write_json(
            data_dir / "index.json",
            {
                "dates": ["2026-07-01"],
                "trading_dates": ["2026-07-01"],
                "latest": "2026-07-01",
                "latest_trading_date": "2026-07-01",
            },
        )
        self.write_json(
            data_dir / "2026-07-01.json",
            {
                "picks_fusion": [{"code": "600001", "name": "A", "score": 11.0}],
                "picks_pure": [{"code": "600002", "name": "B", "score": 33.0}],
                "startup_watchlist": [{"code": "600003", "name": "C", "watch_score": 22.0}],
            },
        )

        payload = build_snapshot_payload("job-fallback", data_dir)
        self.assertEqual(payload["diagnostics"]["fallback_used"], True)
        self.assertEqual(payload["items"][0]["source"], "picks_pure")
        self.assertEqual(payload["items"][0]["code"], "600002")

    def test_fallback_to_data_json(self) -> None:
        docs_dir = self.make_fixture() / "docs"
        data_dir = docs_dir / "data"
        self.write_json(
            data_dir / "index.json",
            {
                "dates": ["2026-07-01"],
                "trading_dates": ["2026-07-01"],
                "latest": "2026-07-01",
                "latest_trading_date": "2026-07-01",
            },
        )
        self.write_json(
            docs_dir / "data.json",
            {
                "picks_pure": [{"code": "600888", "name": "FallbackPool", "score": 99}],
            },
        )

        payload = build_snapshot_payload("job-fallback-data-json", data_dir)
        self.assertEqual(payload["snapshot_date"], "2026-07-01")
        self.assertEqual(payload["items"][0]["code"], "600888")
        self.assertEqual(payload["items"][0]["source"], "picks_pure")


if __name__ == "__main__":
    unittest.main()
