import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from chanlun.preclose_compare import (
    build_reconciliation,
    diff_pool,
    normalize_formal_workspace_views,
    normalize_preclose_pools,
    reconciliation_content_hash,
)
from chanlun.report_view_model import build_workspace
from scripts.preclose_reconcile import (
    load_formal_workspace,
    run_reconciliation_once,
)


TRADE_DATE = "2026-08-27"


def _candidate(code, name, decision_code="recommend", price=10.0):
    return {
        "code": code,
        "name": name,
        "score": 80,
        "reference_price": price,
        "best_buy_point": {
            "type": "二买",
            "price": price,
            "reason": "测试信号",
        },
        "decision_engine_v1": {
            "decision_code": decision_code,
            "decision": "推荐" if decision_code == "recommend" else "观察",
        },
    }


def _formal_report():
    return {
        "date": TRADE_DATE,
        "data_quality": {
            "is_official": True,
            "is_final": True,
            "bar_state": "closed",
        },
        "picks_fusion": [
            _candidate("600001", "A股", decision_code="observe"),
            _candidate("600002", "B股", decision_code="recommend"),
        ],
        "picks_pure": [],
        "h4_t3_pool": {
            "mode": "production",
            "status": "ok",
            "production_attested": True,
            "candidates": [_candidate("600003", "H股")],
        },
        "next_day_boom": {
            "mode": "enabled",
            "status": "ok",
            "candidates": [_candidate("600004", "加速股")],
        },
        "startup_watchlist": [],
        "luojie_pool": {"mode": "enabled", "status": "ok", "candidates": []},
        "selection_input_health": {
            "schema_version": 2,
            "status": "verified",
            "formal": {
                "status": "verified",
                "formal_actions_allowed": True,
                "all_formal_actions_allowed": True,
            },
            "by_strategy": {
                "daily_fusion": {
                    "status": "verified",
                    "formal_actions_allowed": True,
                },
                "h4_t3": {
                    "status": "verified",
                    "formal_actions_allowed": True,
                },
            },
        },
    }


def _preclose_snapshot():
    return {
        "trade_date": TRADE_DATE,
        "snapshot_id": "preclose:2026-08-27:abc",
        "content_hash": "a" * 64,
        "pools": {
            "main": [
                {"code": "600002", "name": "B股", "reference_price": 9.8},
                {"code": "600009", "name": "盘中股", "reference_price": 12.0},
            ],
            "h4_t3": [{"code": "600003", "name": "H股", "reference_price": 10.0}],
            "acceleration": [],
        },
    }


class PrecloseCompareTests(unittest.TestCase):
    def test_diff_pool_has_stable_membership_semantics(self):
        self.assertEqual(diff_pool(["A", "B"], ["B", "C"]), {
            "retained": ["B"],
            "added_after_close": ["C"],
            "removed_after_close": ["A"],
            "unchanged": False,
        })
        self.assertEqual(diff_pool([], []), {
            "retained": [],
            "added_after_close": [],
            "removed_after_close": [],
            "unchanged": True,
        })
        self.assertEqual(
            diff_pool(["B", "A", "A"], ["C", "B", "B"]),
            {
                "retained": ["B"],
                "added_after_close": ["C"],
                "removed_after_close": ["A"],
                "unchanged": False,
            },
        )

    def test_normalizers_require_all_three_pool_contracts(self):
        with self.assertRaises(ValueError):
            normalize_preclose_pools({"pools": {"main": [], "h4_t3": []}})
        with self.assertRaises(ValueError):
            normalize_formal_workspace_views({"views": {"main": [], "h4_t3": []}})

    def test_formal_main_uses_workspace_recommend_filter_not_raw_fusion(self):
        report = _formal_report()
        workspace = build_workspace(report)
        views = normalize_formal_workspace_views(workspace)

        self.assertEqual([row["code"] for row in views["main"]], ["600002"])
        self.assertNotIn("600001", json.dumps(views, ensure_ascii=False))

        report["selection_input_health"]["by_strategy"]["daily_fusion"] = {
            "status": "unavailable",
            "formal_actions_allowed": False,
        }
        gated = normalize_formal_workspace_views(build_workspace(report))
        self.assertEqual(gated["main"], [])

    def test_reconciliation_tracks_membership_and_non_membership_details(self):
        formal = normalize_formal_workspace_views(build_workspace(_formal_report()))
        result = build_reconciliation(
            _preclose_snapshot(),
            formal,
            generated_at="2026-08-27T16:10:00+08:00",
        )

        self.assertEqual(result["status"], "changed")
        self.assertEqual(
            [row["code"] for row in result["pools"]["main"]["retained"]],
            ["600002"],
        )
        self.assertEqual(
            [row["code"] for row in result["pools"]["main"]["removed_after_close"]],
            ["600009"],
        )
        self.assertEqual(
            [row["code"] for row in result["pools"]["acceleration"]["added_after_close"]],
            ["600004"],
        )
        changes = result["pools"]["main"]["details"]["field_changes"]
        self.assertEqual(changes[0]["code"], "600002")
        self.assertIn("reference_price", changes[0]["changes"])
        self.assertEqual(result["content_hash"], reconciliation_content_hash(result))

        repeated = build_reconciliation(
            _preclose_snapshot(),
            formal,
            generated_at="2026-08-27T16:20:00+08:00",
        )
        self.assertEqual(repeated["formal_content_hash"], result["formal_content_hash"])
        self.assertEqual(repeated["content_hash"], result["content_hash"])

    def test_cross_pool_move_is_removed_from_old_and_added_to_new(self):
        snapshot = _preclose_snapshot()
        snapshot["pools"] = {
            "main": [{"code": "600008", "name": "移动股", "reference_price": 10}],
            "h4_t3": [],
            "acceleration": [],
        }
        formal = {
            "main": [],
            "h4_t3": [{"code": "600008", "name": "移动股", "reference_price": 10}],
            "acceleration": [],
        }
        result = build_reconciliation(snapshot, formal)
        self.assertEqual(result["pools"]["main"]["removed_after_close"][0]["code"], "600008")
        self.assertEqual(result["pools"]["h4_t3"]["added_after_close"][0]["code"], "600008")

    def test_formal_loader_fails_pending_without_writing_for_every_gate(self):
        cases = ("missing", "date", "preview", "validator", "pool")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp_dir:
                docs = Path(temp_dir) / "docs"
                data_dir = docs / "data"
                data_dir.mkdir(parents=True)
                if case != "missing":
                    report = _formal_report()
                    if case == "date":
                        report["date"] = "2026-08-26"
                    if case == "preview":
                        report["data_quality"]["bar_state"] = "preview"
                    if case == "pool":
                        report.pop("next_day_boom")
                    path = data_dir / (TRADE_DATE + ".json")
                    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
                before = {
                    str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in docs.rglob("*") if path.is_file()
                }
                result = load_formal_workspace(
                    TRADE_DATE,
                    docs_dir=docs,
                    validator=(lambda *_args: case != "validator"),
                )
                after = {
                    str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in docs.rglob("*") if path.is_file()
                }
                self.assertEqual(result["status"], "formal_pending")
                self.assertEqual(before, after)

    def test_formal_loader_returns_only_build_workspace_visible_views(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            docs = Path(temp_dir) / "docs"
            (docs / "data").mkdir(parents=True)
            (docs / "data" / (TRADE_DATE + ".json")).write_text(
                json.dumps(_formal_report(), ensure_ascii=False), encoding="utf-8"
            )
            result = load_formal_workspace(
                TRADE_DATE,
                docs_dir=docs,
                validator=lambda *_args: True,
            )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(set(result["views"]), {"main", "h4_t3", "acceleration"})
        self.assertEqual([row["code"] for row in result["views"]["main"]], ["600002"])

    def test_reconcile_run_writes_only_isolated_cache_and_never_formal_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            docs = base / "docs"
            (docs / "data").mkdir(parents=True)
            report_path = docs / "data" / (TRADE_DATE + ".json")
            report_path.write_text(
                json.dumps(_formal_report(), ensure_ascii=False),
                encoding="utf-8",
            )
            cache = base / "preclose"
            day_root = cache / TRADE_DATE
            day_root.mkdir(parents=True)
            (day_root / "snapshot.json").write_text(
                json.dumps(_preclose_snapshot(), ensure_ascii=False),
                encoding="utf-8",
            )
            env_file = base / "preclose.env"
            env_file.write_text(
                "PRECLOSE_API_BASE=https://preclose.example\n"
                "PRECLOSE_WRITE_TOKEN=write-token\n"
                "WXPUSHER_APP_TOKEN=app-token\n"
                "WXPUSHER_UID=uid-1\n",
                encoding="utf-8",
            )
            env_file.chmod(0o600)
            before = hashlib.sha256(report_path.read_bytes()).hexdigest()
            published = []

            def publisher(reconciliation, **_kwargs):
                published.append(reconciliation)
                return {"publish": {"success": True}, "notifications": {}}

            result = run_reconciliation_once(
                TRADE_DATE,
                root=cache,
                docs_dir=docs,
                env_file=env_file,
                validator=lambda *_args: True,
                publisher=publisher,
            )

            self.assertEqual(result["status"], "changed")
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(len(published), 1)
            self.assertEqual(
                hashlib.sha256(report_path.read_bytes()).hexdigest(),
                before,
            )
            self.assertFalse((day_root / "reconcile.lock").exists())
            self.assertTrue((day_root / "reconciliation.json").is_file())
            self.assertTrue((day_root / "reconciliation-delivery.json").is_file())


if __name__ == "__main__":
    unittest.main()
