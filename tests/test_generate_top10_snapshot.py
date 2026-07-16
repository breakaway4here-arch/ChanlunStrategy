"""Unit tests for scripts/generate_top10_snapshot.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from chanlun.report_view_model import build_workspace
from scripts.generate_top10_snapshot import build_snapshot_payload


class GenerateTop10SnapshotTests(unittest.TestCase):
    def make_fixture(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="top10-snapshot-fixture-"))

    def write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))

    def official_report(self, report_date: str, highlights: list[dict]) -> dict:
        normalized_highlights = []
        for source_row in highlights:
            row = dict(source_row)
            row.setdefault("change_pct", 0.0)
            row.setdefault("current_price", 1.0)
            row.setdefault("data_status", {"daily": "verified"})
            normalized_highlights.append(row)
        return {
            "date": report_date,
            "picks_fusion": [],
            "picks_pure": [],
            "next_day_boom": {"candidates": []},
            "luojie_pool": {"candidates": []},
            "startup_watchlist": [],
            "data_quality": {
                "report_date": report_date,
                "generated_at": f"{report_date}T15:05:00+08:00",
                "as_of": f"{report_date}T15:05:00+08:00",
                "is_official": True,
                "bar_state": "closed",
                "sources_trusted": True,
                "is_trading_day": True,
                "stock_pool_incomplete": False,
                "market_status": "verified",
                "fallback_used": False,
                "stale_stock_count": 0,
                "missing_daily_count": 0,
            },
            "workspace": {
                "views": {
                    "highlights": normalized_highlights,
                    "main": [],
                    "baseline": [],
                }
            },
        }

    def official_manifest(
        self,
        dates: list[str],
        *,
        latest: str | None = None,
        latest_trading_date: str | None = None,
    ) -> dict:
        return {
            "dates": dates,
            "trading_dates": dates,
            "latest": latest or dates[-1],
            "latest_trading_date": latest_trading_date or dates[-1],
            "date_meta": {
                value: {"is_trading_day": True, "is_official": True}
                for value in dates
            },
        }

    def test_uses_latest_trading_date(self) -> None:
        data_dir = self.make_fixture() / "docs" / "data"
        self.write_json(
            data_dir / "index.json",
            self.official_manifest(
                ["2026-07-01", "2026-07-02"],
                latest="2026-07-01",
                latest_trading_date="2026-07-02",
            ),
        )
        self.write_json(
            data_dir / "2026-07-01.json",
            self.official_report(
                "2026-07-01",
                [{"code": "A1", "name": "Old", "score": 1, "view_rank": 1}],
            ),
        )
        self.write_json(
            data_dir / "2026-07-02.json",
            self.official_report(
                "2026-07-02",
                [{"code": "A2", "name": "New", "score": 2, "view_rank": 1}],
            ),
        )

        payload = build_snapshot_payload("job-latest", data_dir)
        self.assertEqual(payload["snapshot_date"], "2026-07-02")
        self.assertEqual(payload["items"][0]["code"], "A2")

    def test_top10_cap_and_rank(self) -> None:
        data_dir = self.make_fixture() / "docs" / "data"
        self.write_json(
            data_dir / "index.json",
            self.official_manifest(["2026-07-01"]),
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
            self.official_manifest(["2026-07-01"]),
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
                        "view_rank": 1,
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
        self.assertEqual(item["rank"], 1)
        self.assertEqual(item["view_rank"], 1)
        self.assertEqual(item["action_reason"], "测试动作原因")
        self.assertEqual(item["reason"], "测试入选原因")

    def test_top10_reason_uses_primary_reason_from_real_workspace(self) -> None:
        workspace = build_workspace({
            "picks_fusion": [{
                "code": "600001",
                "name": "真实工作区票",
                "score": 82,
                "best_buy_point": {
                    "type": "底背驰候选",
                    "reason": "真实工作区入选理由",
                    "price": 10.0,
                    "current_price": 10.1,
                    "distance_from_reference_pct": 1.0,
                    "change_pct": 1.0,
                },
            }],
        })
        highlights = workspace["views"]["highlights"]
        self.assertEqual(highlights[0]["primary_reason"], "真实工作区入选理由")

        data_dir = self.make_fixture() / "docs" / "data"
        self.write_json(
            data_dir / "index.json",
            self.official_manifest(["2026-07-01"]),
        )
        self.write_json(
            data_dir / "2026-07-01.json",
            self.official_report("2026-07-01", highlights),
        )

        payload = build_snapshot_payload("job-real-workspace-reason", data_dir)

        self.assertEqual(payload["items"][0]["reason"], "真实工作区入选理由")
        self.assertEqual(
            payload["items"][0]["action_reason"], highlights[0]["action_reason"]
        )

    def test_top10_fails_closed_on_missing_or_conflicting_view_rank(self) -> None:
        invalid_ranks = (None, 0, "1", True, 2)
        for invalid_rank in invalid_ranks:
            with self.subTest(view_rank=invalid_rank):
                data_dir = self.make_fixture() / "docs" / "data"
                self.write_json(
                    data_dir / "index.json",
                    self.official_manifest(["2026-07-01"]),
                )
                row = {"code": "600001"}
                if invalid_rank is not None:
                    row["view_rank"] = invalid_rank
                self.write_json(
                    data_dir / "2026-07-01.json",
                    self.official_report("2026-07-01", [row]),
                )

                with self.assertRaisesRegex(ValueError, "view_rank"):
                    build_snapshot_payload("job-invalid-view-rank", data_dir)

    def test_top10_does_not_infer_action_from_chinese_decision_text(self) -> None:
        data_dir = self.make_fixture() / "docs" / "data"
        self.write_json(
            data_dir / "index.json",
            self.official_manifest(["2026-07-01"]),
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
            self.official_manifest(["2026-07-01"]),
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
            self.official_manifest(["2026-07-01"]),
        )
        self.write_json(
            data_dir / "2026-07-01.json",
            {
                **self.official_report("2026-07-01", []),
                "startup_watchlist": [{
                    "code": "600888",
                    "name": "FallbackPool",
                    "score": 99,
                    "data_status": {"daily": "verified"},
                }],
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

                with self.assertRaisesRegex(ValueError, "report contract invalid"):
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
        with self.assertRaisesRegex(ValueError, "manifest contract invalid"):
            build_snapshot_payload("job-meta-not-official", data_dir)

    def test_top10_reuses_full_report_publish_contract(self) -> None:
        mutations = (
            lambda report: report["data_quality"].pop("generated_at"),
            lambda report: report["data_quality"].pop("as_of"),
            lambda report: report["data_quality"].update({
                "generated_at": "2026-07-01T14:35:00+08:00",
                "as_of": "2026-07-01T14:35:00+08:00",
            }),
            lambda report: report["data_quality"].update({"market_status": "unverified"}),
            lambda report: report["data_quality"].update({"fallback_used": True}),
            lambda report: report["data_quality"].update({"stale_stock_count": 1}),
            lambda report: report["data_quality"].update({"missing_daily_count": 1}),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                data_dir = self.make_fixture() / "docs" / "data"
                self.write_json(
                    data_dir / "index.json",
                    self.official_manifest(["2026-07-01"]),
                )
                report = self.official_report("2026-07-01", [])
                mutate(report)
                self.write_json(data_dir / "2026-07-01.json", report)

                with self.assertRaisesRegex(ValueError, "report contract invalid"):
                    build_snapshot_payload("job-invalid-report-contract", data_dir)

    def test_top10_rejects_stale_or_missing_workspace_and_raw_rows(self) -> None:
        for location in ("workspace", "raw"):
            for daily_status in ("stale_cache", "missing"):
                with self.subTest(location=location, daily_status=daily_status):
                    data_dir = self.make_fixture() / "docs" / "data"
                    self.write_json(
                        data_dir / "index.json",
                        self.official_manifest(["2026-07-01"]),
                    )
                    if location == "workspace":
                        report = self.official_report(
                            "2026-07-01",
                            [{"code": "600001", "view_rank": 1}],
                        )
                        report["workspace"]["views"]["highlights"][0]["data_status"] = {
                            "daily": daily_status
                        }
                    else:
                        report = self.official_report("2026-07-01", [])
                        report["next_day_boom"] = {"candidates": [{
                            "code": "600002",
                            "change_pct": 1.0,
                            "current_price": 10.0,
                            "data_status": {"daily": daily_status},
                        }]}
                    self.write_json(data_dir / "2026-07-01.json", report)

                    with self.assertRaisesRegex(ValueError, "report contract invalid"):
                        build_snapshot_payload("job-invalid-row-status", data_dir)

    def test_top10_reuses_manifest_contract_before_selecting_date(self) -> None:
        def missing_date_meta(manifest):
            manifest.pop("date_meta")

        def selected_not_in_dates(manifest):
            manifest["dates"] = []

        def selected_not_in_trading_dates(manifest):
            manifest["trading_dates"] = []
            manifest["latest_trading_date"] = ""

        def latest_trading_not_max(manifest):
            manifest["dates"] = ["2026-06-30", "2026-07-01"]
            manifest["trading_dates"] = ["2026-06-30", "2026-07-01"]
            manifest["latest_trading_date"] = "2026-06-30"
            manifest["date_meta"]["2026-06-30"] = {
                "is_trading_day": True,
                "is_official": True,
            }

        def selected_meta_not_official(manifest):
            manifest["date_meta"]["2026-07-01"]["is_official"] = False

        def selected_meta_not_trading(manifest):
            manifest["date_meta"]["2026-07-01"]["is_trading_day"] = False

        for mutate in (
            missing_date_meta,
            selected_not_in_dates,
            selected_not_in_trading_dates,
            latest_trading_not_max,
            selected_meta_not_official,
            selected_meta_not_trading,
        ):
            with self.subTest(case=mutate.__name__):
                data_dir = self.make_fixture() / "docs" / "data"
                manifest = self.official_manifest(["2026-07-01"])
                mutate(manifest)
                self.write_json(data_dir / "index.json", manifest)
                self.write_json(
                    data_dir / "2026-07-01.json",
                    self.official_report("2026-07-01", []),
                )
                if "2026-06-30" in manifest.get("date_meta", {}):
                    self.write_json(
                        data_dir / "2026-06-30.json",
                        self.official_report("2026-06-30", []),
                    )

                with self.assertRaisesRegex(ValueError, "manifest contract invalid"):
                    build_snapshot_payload("job-invalid-manifest", data_dir)


if __name__ == "__main__":
    unittest.main()
