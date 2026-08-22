import copy
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chanlun.h4_t3_pool import STRATEGY_VERSION
from chanlun.report_generator import generate_report, update_data_json
from scripts.repair_auxiliary_decision_snapshot import (
    publish_auxiliary_decision_snapshot,
    protected_report_digest,
    rebuild_auxiliary_report,
)
from scripts import enable_shadow_evaluation_snapshot as snapshot
from scripts import repair_auxiliary_decision_snapshot as repair
from scripts.enable_shadow_evaluation_snapshot import formal_report_digest


def _strip_shadow_from_html(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    match = re.search(
        r"window\.CHANLUN_BOOTSTRAP\s*=\s*(\{[\s\S]*?\});",
        text,
    )
    envelope = json.loads(match.group(1))
    envelope["inlineReportData"].pop("shadow_evaluations", None)
    path.write_text(
        text[:match.start(1)]
        + json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        + text[match.end(1):],
        encoding="utf-8",
    )


def _publication_fixture():
    return {
        "date": "2026-08-21",
        "market": {"status": "closed"},
        "picks_pure": [{"code": "000001", "name": "结构候选"}],
        "picks_fusion": [{"code": "000001", "name": "融合候选"}],
        "events": [],
        "sector_flow": [],
        "limit_up_snapshot": {
            "generated_at": "2026-08-21T15:06:50+08:00",
        },
        "personal_watchlist": {
            "generated_at": "2026-08-21T15:01:02+08:00",
            "items": [],
        },
        "decision_brief": {
            "generated_at": "2026-08-21T15:01:02+08:00",
            "theses": [{"theme": "过期方向"}],
        },
        "diagnostics": {"formal": {"status": "ok"}},
        "data_quality": {
            "report_date": "2026-08-21",
            "generated_at": "2026-08-21T15:01:02+08:00",
            "bar_state": "closed",
            "is_trading_day": True,
            "is_official": True,
            "sources_trusted": True,
            "market_status": "verified",
            "stock_pool_source": "fixture",
        },
        "h4_t3_pool": {
            "status": "ok",
            "production_attested": True,
            "mode": "production",
            "horizon": "T+3",
            "strategy": "H4",
            "strategy_version": STRATEGY_VERSION,
            "candidates": [],
        },
    }


class RepairAuxiliaryDecisionSnapshotTests(unittest.TestCase):
    def test_frozen_report_rebuilds_mixed_recap_without_changing_formal_fields(self):
        report = json.loads(
            Path("docs/data/2026-08-21.json").read_text(encoding="utf-8")
        )
        before = copy.deepcopy(report)

        rebuilt = rebuild_auxiliary_report(report)

        self.assertEqual(report, before)
        self.assertEqual(
            protected_report_digest(rebuilt),
            protected_report_digest(before),
        )
        by_theme = {
            row["theme"]: row
            for row in rebuilt["decision_brief"]["theses"]
        }
        self.assertEqual(by_theme["光伏"]["direction"], "negative")
        self.assertEqual(by_theme["创新药"]["direction"], "negative")
        self.assertEqual(by_theme["半导体"]["direction"], "positive")
        self.assertNotIn("AI算力", by_theme)
        self.assertNotIn("光模块", by_theme)
        self.assertTrue(by_theme["光伏"]["risk_reasons"])
        self.assertTrue(by_theme["创新药"]["risk_reasons"])
        self.assertEqual(by_theme["半导体"]["risk_reasons"], [])
        self.assertEqual(
            rebuilt["decision_brief"]["generated_at"],
            "2026-08-21T15:06:50+08:00",
        )

        shadow = rebuilt["shadow_evaluations"]
        experiment = shadow["experiments"][0]
        self.assertEqual(
            experiment["experiment_id"],
            "h4-t3-pure-upstream-close-review-v1",
        )
        self.assertEqual(
            experiment["display_name"],
            "H4 T+3 · picks_pure 上游收盘价影子回看",
        )
        expected_guard = formal_report_digest(rebuilt)
        self.assertEqual(
            shadow["production_guard"]["before_sha256"],
            expected_guard,
        )
        self.assertEqual(
            shadow["production_guard"]["after_sha256"],
            expected_guard,
        )

    def test_refuses_to_relabel_shadow_contract_after_samples_exist(self):
        report = json.loads(
            Path("docs/data/2026-08-21.json").read_text(encoding="utf-8")
        )
        report["shadow_evaluations"]["experiments"][0]["sample_size"] = 1

        with self.assertRaisesRegex(ValueError, "non-empty shadow"):
            rebuild_auxiliary_report(report)

    def test_publishes_same_repair_to_all_public_planes_atomically(self):
        tmpdir = tempfile.mkdtemp(prefix="auxiliary_snapshot_repair_")
        self.addCleanup(shutil.rmtree, tmpdir)
        docs = Path(tmpdir) / "docs"
        report = _publication_fixture()
        generate_report(report, output_dir=docs, comparison_db_path="")
        update_data_json(report, output_dir=docs)
        daily_path = docs / "data" / "2026-08-21.json"
        daily = json.loads(daily_path.read_text(encoding="utf-8"))
        daily.pop("shadow_evaluations", None)
        daily_path.write_text(
            json.dumps(daily, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        aggregate_path = docs / "data.json"
        aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
        aggregate["reports"]["2026-08-21"].pop("shadow_evaluations", None)
        aggregate_path.write_text(
            json.dumps(aggregate, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _strip_shadow_from_html(docs / "index.html")
        _strip_shadow_from_html(docs / "2026-08-21" / "index.html")
        snapshot.enable_shadow_evaluation_snapshot(
            docs_dir=docs,
            report_date="2026-08-21",
            started_at="2026-08-22",
        )
        before_planes = snapshot._load_public_planes(docs, "2026-08-21")
        before_digests = {
            name: protected_report_digest(payload)
            for name, payload in before_planes.items()
        }

        result = publish_auxiliary_decision_snapshot(
            docs_dir=docs,
            report_date="2026-08-21",
        )

        after_planes = snapshot._load_public_planes(docs, "2026-08-21")
        briefs = []
        shadows = []
        for name, payload in after_planes.items():
            self.assertEqual(
                protected_report_digest(payload),
                before_digests[name],
            )
            briefs.append(payload["decision_brief"])
            shadows.append(payload["shadow_evaluations"])
            self.assertEqual(
                payload["shadow_evaluations"]["experiments"][0][
                    "experiment_id"
                ],
                "h4-t3-pure-upstream-close-review-v1",
            )
        self.assertTrue(all(brief == briefs[0] for brief in briefs))
        self.assertTrue(all(shadow == shadows[0] for shadow in shadows))
        self.assertEqual(briefs[0]["theses"], [])
        self.assertEqual(result["status"], "repaired")
        self.assertEqual(len(result["updated_files"]), 6)
        self.assertEqual(
            set(result["protected_digests_before"]),
            {"daily", "aggregate", "inline", "archive"},
        )
        self.assertEqual(
            result["protected_digests_before"],
            result["protected_digests_after"],
        )
        self.assertRegex(result["shadow_digest"], r"^[0-9a-f]{64}$")

    def test_empty_shadow_migration_fails_closed_on_non_initial_state(self):
        base = json.loads(
            Path("docs/data/2026-08-21.json").read_text(encoding="utf-8")
        )
        mutations = {
            "representative samples": lambda shadow: shadow["experiments"][0].update({
                "representative_samples": [{"code": "000001"}],
            }),
            "active dates": lambda shadow: shadow["experiments"][0].update({
                "active_dates": 1,
            }),
            "return metric": lambda shadow: shadow["experiments"][0].update({
                "mean_close_return": 3.5,
            }),
            "experiment active": lambda shadow: shadow["experiments"][0].update({
                "affects_production": True,
            }),
            "top mode active": lambda shadow: shadow.update({"mode": "active"}),
            "pending finalized": lambda shadow: shadow["pending"].update({
                "finalized": True,
            }),
            "historical backfill": lambda shadow: shadow["review_diagnostics"].update({
                "historical_backfill": True,
            }),
            "unknown field": lambda shadow: shadow.update({"unexpected": True}),
        }

        for label, mutate in mutations.items():
            report = copy.deepcopy(base)
            mutate(report["shadow_evaluations"])
            with self.subTest(label=label), self.assertRaisesRegex(
                ValueError, "non-empty shadow|invalid empty shadow"
            ):
                rebuild_auxiliary_report(report)

    def test_empty_shadow_migration_rejects_unrelated_experiment(self):
        report = json.loads(
            Path("docs/data/2026-08-21.json").read_text(encoding="utf-8")
        )
        report["shadow_evaluations"]["experiments"][0][
            "experiment_id"
        ] = "unrelated-empty-experiment"

        with self.assertRaisesRegex(ValueError, "source experiment"):
            rebuild_auxiliary_report(report)

    def test_rebuild_rejects_invalid_or_cross_day_timestamps(self):
        base = json.loads(
            Path("docs/data/2026-08-21.json").read_text(encoding="utf-8")
        )
        for value in (
            "not-a-time",
            "2026-08-21T15:06:50",
            "2026-08-22T15:06:50+08:00",
        ):
            report = copy.deepcopy(base)
            report["limit_up_snapshot"]["generated_at"] = value
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "timestamp"
            ):
                rebuild_auxiliary_report(report)

    def test_publication_is_restricted_to_the_reviewed_report_date(self):
        with self.assertRaisesRegex(ValueError, "unsupported repair date"):
            publish_auxiliary_decision_snapshot(
                docs_dir="docs",
                report_date="2026-08-20",
            )

    def test_publication_refuses_unapproved_source_asset_hash(self):
        with mock.patch.dict(
            repair.APPROVED_ASSET_SHA256,
            {"report-v2.js": "0" * 64},
            clear=False,
        ), self.assertRaisesRegex(RuntimeError, "unapproved report asset"):
            repair._validate_approved_source_assets()


if __name__ == "__main__":
    unittest.main()
