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

    def official_report(self, report_date: str, highlights: list[dict]) -> dict:
        return {
            "date": report_date,
            "data_quality": {
                "report_date": report_date,
                "is_official": True,
                "bar_state": "closed",
                "sources_trusted": True,
                "stock_pool_incomplete": False,
            },
            "workspace": {"views": {"highlights": highlights}},
        }

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
            self.official_report(
                "2026-07-01", [{"code": "A1", "name": "Old", "score": 1}]
            ),
        )
        self.write_json(
            data_dir / "2026-07-02.json",
            self.official_report(
                "2026-07-02", [{"code": "A2", "name": "New", "score": 2}]
            ),
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
            self.official_report(
                "2026-07-01",
                [
                    {
                        "code": f"S{i}",
                        "name": f"Stock{i}",
                        "score": i,
                        "view_rank": i + 1,
                    }
                    for i in range(15)
                ],
            ),
        )

        payload = build_snapshot_payload("job-top10", data_dir)
        self.assertEqual(payload["status"], "done")
        self.assertEqual(len(payload["items"]), 10)
        self.assertEqual([item["rank"] for item in payload["items"]], list(range(1, 11)))

        self.assertEqual([item["code"] for item in payload["items"]], [f"S{i}" for i in range(10)])
        self.assertEqual([item["view_rank"] for item in payload["items"]], list(range(1, 11)))

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
            self.official_report(
                "2026-07-01",
                [
                    {
                        "code": "300001",
                        "name": "示例股票",
                        "score": 88.8,
                        "view_rank": 7,
                        "action": "可上车",
                        "action_reason": "测试动作原因",
                        "reason": "测试入选原因",
                        "change_pct": 3.14,
                        "current_price": 12.34,
                    },
                ],
            ),
        )

        payload = build_snapshot_payload("job-schema", data_dir)
        self.assertEqual(payload["source"], "github_actions")
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["job_id"], "job-schema")
        self.assertIn("items", payload)
        self.assertIsInstance(payload["items"], list)
        self.assertEqual(len(payload["items"]), 1)

        item = payload["items"][0]
        for field in (
            "rank", "view_rank", "code", "name", "score", "action",
            "action_reason", "reason", "source", "change_pct", "current_price",
        ):
            self.assertIn(field, item)

        self.assertEqual(item["code"], "300001")
        self.assertEqual(item["source"], "highlights")
        self.assertEqual(item["view_rank"], 7)
        self.assertEqual(item["action_reason"], "测试动作原因")
        self.assertEqual(item["reason"], "测试入选原因")

    def test_top10_does_not_infer_action_from_chinese_decision_text(self) -> None:
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
            self.official_report(
                "2026-07-01",
                [{
                    "code": "300002",
                    "view_rank": 1,
                    "decision_engine_v1": {"decision": "不推荐（高位风险）"},
                }],
            ),
        )

        payload = build_snapshot_payload("job-no-decision-guess", data_dir)

        self.assertEqual(payload["items"][0]["action"], "")

    def test_missing_workspace_highlights_does_not_fallback_to_raw_sources(self) -> None:
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
        report = self.official_report("2026-07-01", [])
        report.pop("workspace")
        report.update({
            "picks_fusion": [{"code": "600001", "name": "A", "score": 11.0}],
            "picks_pure": [{"code": "600002", "name": "B", "score": 33.0}],
            "startup_watchlist": [{"code": "600003", "name": "C", "watch_score": 22.0}],
        })
        self.write_json(data_dir / "2026-07-01.json", report)

        with self.assertRaisesRegex(ValueError, "workspace.views.highlights"):
            build_snapshot_payload("job-fallback", data_dir)

    def test_empty_highlights_is_a_valid_empty_top10_without_raw_fallback(self) -> None:
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
            data_dir / "2026-07-01.json",
            {
                **self.official_report("2026-07-01", []),
                "picks_pure": [{"code": "600888", "name": "FallbackPool", "score": 99}],
            },
        )

        payload = build_snapshot_payload("job-empty-highlights", data_dir)
        self.assertEqual(payload["snapshot_date"], "2026-07-01")
        self.assertEqual(payload["items"], [])
        self.assertFalse(payload["diagnostics"]["fallback_used"])

    def test_rejects_nonofficial_or_open_snapshot_and_manifest_meta(self) -> None:
        cases = (
            ("is_official", False),
            ("bar_state", "intraday"),
            ("sources_trusted", False),
            ("stock_pool_incomplete", True),
        )
        for field, value in cases:
            with self.subTest(field=field):
                data_dir = self.make_fixture() / "docs" / "data"
                manifest = {
                    "dates": ["2026-07-01"],
                    "trading_dates": ["2026-07-01"],
                    "latest": "2026-07-01",
                    "latest_trading_date": "2026-07-01",
                    "date_meta": {"2026-07-01": {"is_trading_day": True, "is_official": True}},
                }
                self.write_json(data_dir / "index.json", manifest)
                report = self.official_report("2026-07-01", [])
                report["data_quality"][field] = value
                self.write_json(data_dir / "2026-07-01.json", report)

                with self.assertRaisesRegex(ValueError, "official closed snapshot"):
                    build_snapshot_payload("job-nonofficial", data_dir)

        data_dir = self.make_fixture() / "docs" / "data"
        self.write_json(
            data_dir / "index.json",
            {
                "dates": ["2026-07-01"],
                "trading_dates": ["2026-07-01"],
                "latest": "2026-07-01",
                "latest_trading_date": "2026-07-01",
                "date_meta": {"2026-07-01": {"is_trading_day": True, "is_official": False}},
            },
        )
        self.write_json(
            data_dir / "2026-07-01.json", self.official_report("2026-07-01", [])
        )
        with self.assertRaisesRegex(ValueError, "manifest date_meta"):
            build_snapshot_payload("job-meta-not-official", data_dir)


if __name__ == "__main__":
    unittest.main()
