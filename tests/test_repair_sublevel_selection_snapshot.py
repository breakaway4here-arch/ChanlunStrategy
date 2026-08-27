import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from chanlun.market_history_store import MarketHistoryStore
from chanlun.report_generator import (
    _build_report_v2_html,
    _escape_inline_json,
    _report_asset_version,
)
from scripts import enable_shadow_evaluation_snapshot as atomic
from scripts.repair_sublevel_selection_snapshot import (
    SUPPORTED_REPORT_DATE,
    _protected_digest,
    publish_sublevel_selection_snapshot,
    rebuild_sublevel_selection_report,
)


def _bar(ts, close, final=True):
    return {
        "ts": ts,
        "open": close - 0.05,
        "high": close + 0.1,
        "low": close - 0.1,
        "close": close,
        "volume": 1_000_000,
        "amount": close * 1_000_000,
        "adjustment": "qfq",
        "is_final": final,
        "source_batch": "fixture:sina",
    }


def _candidate():
    closes = np.linspace(14.0, 16.03, 120).tolist()
    opens = [value - 0.05 for value in closes]
    highs = [value + 0.1 for value in closes]
    lows = [value - 0.1 for value in closes]
    volumes = [1_000_000.0] * 119 + [1_800_000.0]
    dates = ["2026-{:02d}-{:02d}".format(3 + index // 28, index % 28 + 1) for index in range(119)] + ["2026-08-26"]
    best = {
        "type": "强势启动候选",
        "tier": "candidate",
        "price": 16.03,
        "reason": "低位放量启动",
        "strength": "中",
        "source_type": "日线强势启动",
        "confirmed_by": "30min确认",
        "confirmations": ["30min EMA5维持"],
        "startup_reason": "低位放量启动",
        "startup_signals": ["close_above_ma5", "close_above_ma10"],
        "startup_index": 119,
        "startup_date": "2026-08-26",
        "startup_age_days": 0,
        "confirm_date": "2026-08-21 15:00:00",
        "confirm_index": 79,
        "confirm_age_days": 0,
        "change_pct": 6.51,
        "volume_ratio": 1.8,
    }
    return {
        "code": "300697",
        "name": "电工合金",
        "sector": "工业金属",
        "source_channel": "low_position",
        "signal_tier": "candidate",
        "tier": "candidate",
        "category": "A",
        "view": "main",
        "change_pct": 6.51,
        "current_price": 16.03,
        "reference_price": 16.03,
        "best_buy_point": best,
        "buy_points": [copy.deepcopy(best)],
        "reference_buy_points": [],
        "blocked_buy_points": [],
        "closes": closes,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
        "dates": dates,
        "data_status": {
            "daily": "verified",
            "latest_date": "2026-08-26",
            "source": "market_history_db",
            "bars": 120,
            "stale": False,
            "is_final": True,
        },
        "decision_engine_v1": {
            "decision": "推荐",
            "decision_code": "recommend",
            "total_score": 70,
        },
    }


def _report():
    candidate = _candidate()
    return {
        "date": SUPPORTED_REPORT_DATE,
        "market": {},
        "picks_pure": [copy.deepcopy(candidate)],
        "picks_fusion": [copy.deepcopy(candidate)],
        "startup_watchlist": [],
        "observation_watchlist": [],
        "next_day_boom": {"mode": "disabled", "candidates": []},
        "luojie_pool": {"mode": "active", "candidates": []},
        "h4_t3_pool": {
            "status": "ok",
            "mode": "production",
            "production_attested": False,
            "candidates": [],
            "diagnostics": {"upstream_pool": "picks_fusion"},
        },
        "data_quality": {
            "report_date": SUPPORTED_REPORT_DATE,
            "generated_at": "2026-08-26T15:05:10+08:00",
            "as_of": "2026-08-26T15:05:10+08:00",
            "bar_state": "closed",
            "is_official": True,
            "is_trading_day": True,
            "sources_trusted": True,
            "market_status": "verified",
            "fallback_used": False,
            "stock_pool_incomplete": False,
            "stale_stock_count": 0,
            "missing_daily_count": 0,
        },
        "selection_input_health": {
            "schema_version": 2,
            "required_date": SUPPORTED_REPORT_DATE,
            "status": "unavailable",
            "formal": {
                "status": "unavailable",
                "formal_actions_allowed": False,
                "all_formal_actions_allowed": False,
                "allowed_strategies": [],
                "blocked_strategies": ["daily_fusion", "h4_t3"],
                "invalid_count": 1,
                "invalid_codes": ["300697"],
                "blocking_reason": "strategy_input_stale_or_unverified",
            },
            "by_strategy": {
                "daily_fusion": {
                    "status": "unavailable",
                    "formal_actions_allowed": False,
                    "invalid_codes": ["300697"],
                    "blocking_reason": "strategy_input_stale_or_unverified",
                },
                "h4_t3": {
                    "status": "unavailable",
                    "formal_actions_allowed": False,
                    "invalid_codes": [],
                    "blocking_reason": "strategy_upstream_contract_mismatch",
                },
                "luojie_pool": {
                    "status": "unavailable",
                    "research_output_trusted": False,
                    "invalid_codes": [],
                    "blocking_reason": "strategy_input_stale_or_unverified",
                },
            },
            "sublevels": {
                "30m": {"status": "unavailable"},
                "15m": {"status": "unavailable"},
            },
            "incident_ids": [
                "sublevel-input-stale-2026-08-24-26-luojie",
                "sublevel-input-stale-2026-08-26-fusion-300697",
                "upstream-contract-2026-08-26-h4-picks-fusion",
            ],
        },
        "recommendation_ledger": [
            {"recommendation_id": "original-entry", "code": "600000"}
        ],
        "strategy_scorecards": {"schema_version": 2},
        "shadow_evaluations": {
            "production_guard": {
                "unchanged": True,
                "before_sha256": "old",
                "after_sha256": "old",
            }
        },
        "diagnostics": {},
    }


class RepairSublevelSelectionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "market.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def seed_verified_30m(self, include_future=False):
        bars = []
        for index in range(80):
            day = "2026-08-25" if index < 72 else "2026-08-26"
            hour = 11 + (index % 8) // 2
            minute = 30 if index % 2 else 0
            if index == 79:
                hour, minute = 15, 0
            bars.append(
                _bar(
                    "{} {:02d}:{:02d}:00".format(day, hour, minute),
                    15.0 + index * 0.01,
                )
            )
        # Make timestamps unique and sorted while retaining an exact close.
        for index, bar in enumerate(bars[:-8]):
            bar["ts"] = "2026-08-{:02d} {:02d}:{:02d}:00".format(
                1 + index // 8,
                10 + (index % 8) // 2,
                30 if index % 2 else 0,
            )
        if include_future:
            bars.append(_bar("2026-08-27 10:00:00", 16.2))
        with MarketHistoryStore(self.db_path) as store:
            instrument_id = store.upsert_instrument(
                "stock", "SZ", "300697", name="电工合金"
            )
            store.upsert_bars("30m", instrument_id, bars, adjustment="qfq")

    def seed_public_docs(self):
        docs = Path(self.tmp.name) / "docs"
        (docs / "data").mkdir(parents=True)
        (docs / SUPPORTED_REPORT_DATE).mkdir(parents=True)
        (docs / "assets").mkdir(parents=True)
        report = _report()
        (docs / "data" / "{}.json".format(SUPPORTED_REPORT_DATE)).write_text(
            json.dumps(report, ensure_ascii=False), encoding="utf-8"
        )
        aggregate = {"reports": {SUPPORTED_REPORT_DATE: report}}
        (docs / "data.json").write_text(
            json.dumps(aggregate, ensure_ascii=False), encoding="utf-8"
        )
        (docs / "data" / "index.json").write_text(
            json.dumps({"dates": [SUPPORTED_REPORT_DATE]}),
            encoding="utf-8",
        )
        (docs / "data" / "comparison-index.json").write_text(
            json.dumps({"sentinel": "unchanged"}), encoding="utf-8"
        )
        envelope = {
            "pageDate": SUPPORTED_REPORT_DATE,
            "inlineReportData": report,
        }
        for path, prefix in (
            (docs / "index.html", ""),
            (docs / SUPPORTED_REPORT_DATE / "index.html", "../"),
        ):
            path.write_text(
                _build_report_v2_html(
                    SUPPORTED_REPORT_DATE,
                    _escape_inline_json(envelope),
                    asset_prefix=prefix,
                    asset_version=_report_asset_version(),
                ),
                encoding="utf-8",
            )
        source_assets = Path(__file__).resolve().parents[1] / "chanlun" / "report_assets"
        for name in ("report-v2.js", "report-v2.css"):
            shutil.copy2(source_assets / name, docs / "assets" / name)
        return docs, report

    def test_rebuild_adds_review_overlay_and_keeps_original_snapshot_exact(self):
        self.seed_verified_30m(include_future=True)
        source = _report()
        protected_before = copy.deepcopy(source)
        digest_before = _protected_digest(source)

        rebuilt = rebuild_sublevel_selection_report(
            source,
            report_date=SUPPORTED_REPORT_DATE,
            market_db_path=self.db_path,
            acquired_at="2026-08-27T12:00:00+08:00",
        )

        overlay = rebuilt["historical_reconstruction"]
        repaired = overlay["candidates"][0]
        evidence = repaired["strategy_input_evidence"]
        self.assertEqual(evidence["latest_date"], SUPPORTED_REPORT_DATE)
        self.assertEqual(evidence["latest_ts"], "2026-08-26 15:00:00")
        self.assertTrue(evidence["is_final"])
        self.assertEqual(
            repaired["review_identity"], "历史重建·仅复盘"
        )
        self.assertFalse(repaired["scorecard_eligible"])
        self.assertEqual(overlay["original_publication"]["main_count"], 0)
        self.assertEqual(
            overlay["original_publication"]["affected_candidate_count"],
            1,
        )
        self.assertFalse(overlay["scorecard_eligible"])
        protected_after = copy.deepcopy(rebuilt)
        protected_after.pop("historical_reconstruction")
        self.assertEqual(protected_after, protected_before)
        self.assertEqual(_protected_digest(rebuilt), digest_before)
        self.assertEqual(
            atomic.formal_report_digest(rebuilt),
            atomic.formal_report_digest(source),
        )
        self.assertEqual(
            rebuilt["shadow_evaluations"],
            source["shadow_evaluations"],
        )

    def test_no_current_confirmation_keeps_original_pools_and_empty_overlay(self):
        self.seed_verified_30m()
        source = _report()
        with patch(
            "chanlun.strong_startup._check_30min_confirmations",
            return_value=[],
        ):
            rebuilt = rebuild_sublevel_selection_report(
                source,
                report_date=SUPPORTED_REPORT_DATE,
                market_db_path=self.db_path,
                acquired_at="2026-08-27T12:00:00+08:00",
            )
        self.assertEqual(rebuilt["picks_fusion"], source["picks_fusion"])
        self.assertEqual(rebuilt.get("workspace"), source.get("workspace"))
        self.assertEqual(
            rebuilt["historical_reconstruction"]["candidates"], []
        )
        self.assertEqual(
            rebuilt["historical_reconstruction"]["outcome"],
            "no_confirmation",
        )

    def test_missing_exact_report_date_bars_fails_closed(self):
        bars = [_bar("2026-08-25 15:00:00", 15.0)] * 80
        with MarketHistoryStore(self.db_path) as store:
            instrument_id = store.upsert_instrument(
                "stock", "SZ", "300697"
            )
            # Distinct dates are not needed: the repository must reject before
            # reconstruction because the requested date is absent.
            for index, bar in enumerate(bars):
                bar = dict(bar)
                bar["ts"] = "2026-08-{:02d} 15:00:00".format(
                    1 + index % 25
                )
                store.upsert_bars("30m", instrument_id, [bar], adjustment="qfq")

        with self.assertRaisesRegex(ValueError, "verified 30m"):
            rebuild_sublevel_selection_report(
                _report(),
                report_date=SUPPORTED_REPORT_DATE,
                market_db_path=self.db_path,
                acquired_at="2026-08-27T12:00:00+08:00",
            )

    def test_wrong_report_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported repair date"):
            rebuild_sublevel_selection_report(
                _report(),
                report_date="2026-08-25",
                market_db_path=self.db_path,
                acquired_at="2026-08-27T12:00:00+08:00",
            )

    def test_acquired_at_must_be_after_report_date(self):
        self.seed_verified_30m()
        with self.assertRaisesRegex(ValueError, "after the report date"):
            rebuild_sublevel_selection_report(
                _report(),
                report_date=SUPPORTED_REPORT_DATE,
                market_db_path=self.db_path,
                acquired_at="2026-08-26T16:00:00+08:00",
            )

    def test_repair_rejects_duplicate_overlay(self):
        self.seed_verified_30m()
        source = _report()
        source["historical_reconstruction"] = {"status": "existing"}
        with self.assertRaisesRegex(ValueError, "already exists"):
            rebuild_sublevel_selection_report(
                source,
                report_date=SUPPORTED_REPORT_DATE,
                market_db_path=self.db_path,
                acquired_at="2026-08-27T12:00:00+08:00",
            )

    def test_atomic_publish_preserves_all_original_planes_and_comparison(self):
        self.seed_verified_30m()
        docs, original = self.seed_public_docs()
        original_manifest = atomic._read_json(docs / "data" / "index.json")
        original_comparison = atomic._read_json(
            docs / "data" / "comparison-index.json"
        )

        result = publish_sublevel_selection_snapshot(
            docs_dir=docs,
            report_date=SUPPORTED_REPORT_DATE,
            market_db_path=self.db_path,
            acquired_at="2026-08-27T12:00:00+08:00",
        )

        self.assertEqual(result["status"], "repaired")
        planes = atomic._load_public_planes(docs, SUPPORTED_REPORT_DATE)
        for payload in planes.values():
            protected = copy.deepcopy(payload)
            overlay = protected.pop("historical_reconstruction")
            self.assertEqual(protected, original)
            self.assertFalse(overlay["scorecard_eligible"])
            self.assertFalse(overlay["comparison_mutated"])
        self.assertEqual(
            atomic._read_json(docs / "data" / "index.json"),
            original_manifest,
        )
        self.assertEqual(
            atomic._read_json(docs / "data" / "comparison-index.json"),
            original_comparison,
        )


if __name__ == "__main__":
    unittest.main()
