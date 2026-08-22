"""Tests for publishing an enabled-but-empty shadow evaluation snapshot."""

import hashlib
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chanlun.h4_t3_pool import STRATEGY_VERSION
from chanlun.report_generator import generate_report, update_data_json
from scripts import enable_shadow_evaluation_snapshot as snapshot
from scripts.finalize_recommendation_ledger import _shadow_report_authorization


REPORT_DATE = "2026-08-21"
STARTED_AT = "2026-08-22"


def _formal_digest(payload):
    return snapshot.formal_report_digest(payload)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _bootstrap(path):
    html = Path(path).read_text(encoding="utf-8")
    match = re.search(
        r"window\.CHANLUN_BOOTSTRAP\s*=\s*(\{[\s\S]*?\});",
        html,
    )
    if not match:
        raise AssertionError("missing report bootstrap")
    return json.loads(match.group(1))


def _strip_legacy_shadow_from_html(path):
    path = Path(path)
    html = path.read_text(encoding="utf-8")
    match = re.search(
        r"window\.CHANLUN_BOOTSTRAP\s*=\s*(\{[\s\S]*?\});",
        html,
    )
    if not match:
        raise AssertionError("missing report bootstrap")
    bootstrap = json.loads(match.group(1))
    bootstrap["inlineReportData"].pop("shadow_evaluations", None)
    rewritten = html[:match.start(1)] + json.dumps(
        bootstrap, ensure_ascii=False, separators=(",", ":")
    ) + html[match.end(1):]
    path.write_text(rewritten, encoding="utf-8")


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _report_fixture():
    return {
        "date": REPORT_DATE,
        "market": {"status": "closed", "index": 3580.2},
        "chanlun_structure": {"trend": "up"},
        "picks_pure": [{
            "code": "000001",
            "name": "正式结构候选",
            "dates": ["2026-08-20", REPORT_DATE],
            "opens": [9.8, 10.0],
            "highs": [10.2, 10.3],
            "lows": [9.7, 9.9],
            "closes": [10.0, 10.1],
            "volumes": [1000, 1200],
            "best_buy_point": {
                "type": "三买", "price": 10.0, "index": 0
            },
        }],
        "picks_fusion": [{
            "code": "000001",
            "name": "正式融合主推",
            "dates": ["2026-08-20", REPORT_DATE],
            "opens": [9.8, 10.0],
            "highs": [10.2, 10.3],
            "lows": [9.7, 9.9],
            "closes": [10.0, 10.1],
            "volumes": [1000, 1200],
            "best_buy_point": {
                "type": "三买", "price": 10.0, "index": 0
            },
        }],
        "decision_brief": {
            "summary": "正式辅助决策保持不变",
            "risk_reasons": ["正式风险原因"],
        },
        "diagnostics": {"formal": {"status": "ok"}},
        "data_quality": {
            "report_date": REPORT_DATE,
            "generated_at": "2026-08-21T15:01:02+08:00",
            "bar_state": "closed",
            "is_trading_day": True,
            "is_official": True,
            "sources_trusted": True,
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


class EnableShadowEvaluationSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="shadow_snapshot_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir)
        self.docs = Path(self.tmpdir) / "docs"
        report = _report_fixture()
        generate_report(report, output_dir=self.docs, comparison_db_path="")
        update_data_json(report, output_dir=self.docs)
        daily_path = self.docs / "data" / f"{REPORT_DATE}.json"
        daily = _read_json(daily_path)
        daily.pop("shadow_evaluations", None)
        daily_path.write_text(
            json.dumps(daily, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        aggregate_path = self.docs / "data.json"
        aggregate = _read_json(aggregate_path)
        aggregate["reports"][REPORT_DATE].pop("shadow_evaluations", None)
        aggregate_path.write_text(
            json.dumps(aggregate, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _strip_legacy_shadow_from_html(self.docs / "index.html")
        _strip_legacy_shadow_from_html(
            self.docs / REPORT_DATE / "index.html"
        )

    def _enable(self):
        return snapshot.enable_shadow_evaluation_snapshot(
            docs_dir=self.docs,
            report_date=REPORT_DATE,
            started_at=STARTED_AT,
        )

    def test_builds_only_post_deployment_empty_h4_contract(self):
        daily_path = self.docs / "data" / f"{REPORT_DATE}.json"
        before = _read_json(daily_path)
        before_digest = _formal_digest(before)

        result = self._enable()

        after = _read_json(daily_path)
        shadow = after["shadow_evaluations"]
        experiment = shadow["experiments"][0]
        self.assertEqual(result["formal_digest_before"], before_digest)
        self.assertEqual(result["formal_digest_after"], before_digest)
        self.assertEqual(_formal_digest(after), before_digest)
        self.assertEqual(shadow["schema_version"], 1)
        self.assertEqual(shadow["mode"], "shadow")
        self.assertFalse(shadow["affects_production"])
        self.assertEqual(shadow["status"], "collecting")
        self.assertEqual(shadow["started_at"], STARTED_AT)
        self.assertTrue(shadow["production_guard"]["unchanged"])
        self.assertEqual(
            shadow["production_guard"]["before_sha256"], before_digest
        )
        self.assertEqual(
            shadow["production_guard"]["after_sha256"], before_digest
        )
        self.assertRegex(before_digest, r"^[0-9a-f]{64}$")

        self.assertEqual(experiment["version"], STRATEGY_VERSION)
        self.assertEqual(experiment["upstream_pool"], "picks_pure")
        self.assertEqual(experiment["source_pool"], "h4_t3_pool")
        self.assertEqual(experiment["intended_horizon"], 3)
        self.assertEqual(experiment["entry_mode"], "immediate_close")
        self.assertEqual(experiment["status"], "available")
        self.assertFalse(experiment["affects_production"])
        self.assertFalse(experiment["promotion_eligible"])
        self.assertEqual(experiment["research_tier"], "oot_shadow")
        self.assertEqual(experiment["comparison_status"], "collecting")
        self.assertEqual(experiment["today"]["candidates"], [])
        self.assertEqual(experiment["sample_size"], 0)
        for field in (
            "mean_close_return",
            "median_close_return",
            "up_rate",
            "hit_rate_ge_5",
            "mean_mfe",
            "mean_mae",
            "worst_close_return",
        ):
            self.assertIsNone(experiment[field])
        self.assertEqual(shadow["today_entries"], [])
        self.assertEqual(shadow["scorecards"], [])
        self.assertEqual(shadow["pending"]["status"], "withheld")
        self.assertNotIn("batch", shadow["pending"])
        self.assertNotIn("batch_sha256", shadow["pending"])
        self.assertEqual(
            _shadow_report_authorization(REPORT_DATE, report_path=daily_path)[
                "status"
            ],
            "withheld",
        )

    def test_rebuilds_all_public_planes_and_assets_without_formal_drift(self):
        original_daily = _read_json(
            self.docs / "data" / f"{REPORT_DATE}.json"
        )
        original_aggregate = _read_json(self.docs / "data.json")["reports"][
            REPORT_DATE
        ]
        original_inline = _bootstrap(self.docs / "index.html")[
            "inlineReportData"
        ]
        original_archive = _bootstrap(
            self.docs / REPORT_DATE / "index.html"
        )["inlineReportData"]

        self._enable()

        daily = _read_json(self.docs / "data" / f"{REPORT_DATE}.json")
        aggregate = _read_json(self.docs / "data.json")["reports"][REPORT_DATE]
        inline = _bootstrap(self.docs / "index.html")["inlineReportData"]
        archive = _bootstrap(self.docs / REPORT_DATE / "index.html")[
            "inlineReportData"
        ]
        shadow = daily["shadow_evaluations"]
        for before, after in (
            (original_daily, daily),
            (original_aggregate, aggregate),
            (original_inline, inline),
            (original_archive, archive),
        ):
            self.assertEqual(_formal_digest(after), _formal_digest(before))
            self.assertEqual(after["shadow_evaluations"], shadow)
        js = (self.docs / "assets" / "report-v2.js").read_text(
            encoding="utf-8"
        )
        css = (self.docs / "assets" / "report-v2.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("function renderShadowEvaluations", js)
        self.assertIn(".shadow-card", css)

    def test_rerun_is_idempotent(self):
        self._enable()
        targets = [
            self.docs / "index.html",
            self.docs / "data.json",
            self.docs / "data" / f"{REPORT_DATE}.json",
            self.docs / REPORT_DATE / "index.html",
            self.docs / "assets" / "report-v2.js",
            self.docs / "assets" / "report-v2.css",
        ]
        first = {os.fspath(path): _file_sha(path) for path in targets}

        self._enable()

        second = {os.fspath(path): _file_sha(path) for path in targets}
        self.assertEqual(second, first)

    def test_rejects_wrong_date_and_existing_nonempty_shadow(self):
        with self.assertRaisesRegex(ValueError, "report date mismatch"):
            snapshot.enable_shadow_evaluation_snapshot(
                docs_dir=self.docs,
                report_date="2026-08-20",
                started_at=STARTED_AT,
            )

        daily_path = self.docs / "data" / f"{REPORT_DATE}.json"
        report = _read_json(daily_path)
        report["shadow_evaluations"] = {
            "mode": "shadow",
            "today_entries": [{"code": "000001"}],
        }
        daily_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "existing shadow snapshot"):
            self._enable()

    def test_generation_formal_drift_fails_before_replacing_docs(self):
        daily_path = self.docs / "data" / f"{REPORT_DATE}.json"
        index_path = self.docs / "index.html"
        original_daily_sha = _file_sha(daily_path)
        original_index_sha = _file_sha(index_path)
        real_rebuild = snapshot._rebuild_staged_public_artifacts

        def drifting_rebuild(
            staged_docs,
            original_planes,
            original_aggregate_payload,
            original_bootstraps,
            report_date,
            expected_shadow,
        ):
            result = real_rebuild(
                staged_docs,
                original_planes,
                original_aggregate_payload,
                original_bootstraps,
                report_date,
                expected_shadow,
            )
            generated = Path(staged_docs) / "data" / f"{REPORT_DATE}.json"
            payload = _read_json(generated)
            payload["decision_brief"]["summary"] = "意外漂移"
            generated.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return result

        with mock.patch.object(
            snapshot,
            "_rebuild_staged_public_artifacts",
            side_effect=drifting_rebuild,
        ):
            with self.assertRaisesRegex(RuntimeError, "formal digest drift"):
                self._enable()

        self.assertEqual(_file_sha(daily_path), original_daily_sha)
        self.assertEqual(_file_sha(index_path), original_index_sha)


if __name__ == "__main__":
    unittest.main()
