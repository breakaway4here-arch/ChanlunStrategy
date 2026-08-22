import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import copy

from chanlun.h4_t3_pool import (
    FEATURE_DIMENSION,
    H4T3PoolError,
    build_h4_t3_pool,
    build_tail_feature_vector,
    is_continuation_microstate,
    load_model,
)


def _candidate(code="000001", score=80.0):
    return {
        "code": code,
        "name": "测试股" + code,
        "score": score,
        "source_channel": "trend_continuation",
        "change_pct": 4.2,
        "volume_ratio": 1.8,
        "market_regime": "strong",
        "ma_bullish": True,
        "position_absolute_percentile": 60.0,
        "position_distance_pct": 1.0,
        "best_buy_point": {
            "strength": "强",
            "change_pct": 4.2,
            "volume_ratio": 1.8,
            "confirmations": [],
            "startup_signals": [],
        },
        "gf_dma_health": {
            "alignment": "bullish",
            "extension_level": "overheated",
            "fomo_risk": "medium",
            "pullback_health": "healthy",
            "trend_stage": "uptrend",
            "data_quality": "sufficient",
            "score": 85.0,
            "distance_pct": {"vs_ma20": 8.0, "vs_ma50": 12.0, "vs_ma100": 20.0},
            "risk_flags": [],
            "positive_flags": ["趋势向上"],
        },
        "decision_engine_v1": {
            "decision_code": "recommend",
            "total_score": 70,
            "sentiment": {"score": 20},
            "structure": {"score": 30},
            "position": {"score": 20},
            "risk_reasons": [],
        },
        "fusion_admission": {"passed": True},
        "buy_points": [],
        "buy_points_30min": [],
        "blocked_buy_points": [],
        "reference_buy_points": [],
        "pivots": {},
        "trailing_targets": [],
    }


class H4T3PoolTests(unittest.TestCase):

    @staticmethod
    def _unlink(path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _model_path(self, return_pct=6.0):
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        json.dump(
            {
                "artifact_type": "h4_t3_production_model",
                "schema_version": 1,
                "strategy_version": "h4_t3_k30_tail_safe_v1",
                "feature_dimension": FEATURE_DIMENSION,
                "neighbor_count": 30,
                "training_rows": [
                    {
                        "trade_date": "2026-07-01",
                        "exit_date": "2026-07-06",
                        "code": "600000",
                        "record_index": 1,
                        "return_pct": return_pct,
                        "vector": [0.0] * FEATURE_DIMENSION,
                    }
                ],
            },
            handle,
        )
        handle.close()
        self.addCleanup(self._unlink, Path(handle.name))
        return Path(handle.name)

    def test_exact_continuation_microstate_and_vector_dimension(self):
        row = _candidate()
        self.assertTrue(is_continuation_microstate(row))
        self.assertEqual(FEATURE_DIMENSION, len(build_tail_feature_vector(row)))

        row["gf_dma_health"]["fomo_risk"] = "high"
        self.assertFalse(is_continuation_microstate(row))

    def test_keeps_every_candidate_that_passes_without_daily_cap(self):
        model_path = self._model_path(return_pct=6.0)
        candidates = [
            _candidate("{:06d}".format(index), 100.0 - index)
            for index in range(1, 26)
        ]
        pool = build_h4_t3_pool(
            candidates,
            "2026-08-20",
            model_path=model_path,
        )

        self.assertEqual("ok", pool["status"])
        self.assertEqual(25, pool["diagnostics"]["eligible_count"])
        self.assertEqual(
            [row["code"] for row in candidates],
            [row["code"] for row in pool["candidates"]],
        )
        self.assertEqual(
            [row["score"] for row in candidates],
            [row["score"] for row in pool["candidates"]],
        )
        self.assertTrue(pool["no_backfill"])
        self.assertIsNone(pool["daily_cap"])

    def test_successful_empty_pool_is_not_a_technical_failure(self):
        model_path = self._model_path(return_pct=-1.0)
        pool = build_h4_t3_pool([_candidate()], "2026-08-20", model_path=model_path)

        self.assertEqual("ok", pool["status"])
        self.assertEqual([], pool["candidates"])
        self.assertEqual(1, pool["diagnostics"]["base_return_rejected_count"])

    def test_diagnostics_record_explicit_upstream_and_keep_legacy_count(self):
        model_path = self._model_path(return_pct=6.0)
        candidates = [_candidate()]

        pool = build_h4_t3_pool(
            candidates,
            "2026-08-20",
            model_path=model_path,
            upstream_pool="picks_pure",
        )

        self.assertEqual("picks_pure", pool["diagnostics"]["upstream_pool"])
        self.assertEqual(1, pool["diagnostics"]["upstream_count"])
        self.assertEqual(1, pool["diagnostics"]["fusion_count"])

    def test_missing_or_invalid_model_fails_instead_of_becoming_empty(self):
        missing = Path(tempfile.gettempdir()) / "missing-h4-t3-model.json"
        self._unlink(missing)
        with self.assertRaises(H4T3PoolError):
            build_h4_t3_pool([_candidate()], "2026-08-20", model_path=missing)

    def test_committed_model_is_compact_and_uses_frozen_contract(self):
        model = load_model()
        self.assertEqual("h4_t3_k30_tail_safe_v1", model["strategy_version"])
        self.assertEqual(FEATURE_DIMENSION, model["feature_dimension"])
        self.assertEqual(30, model["neighbor_count"])
        self.assertGreater(len(model["training_rows"]), 100)
        self.assertLess(
            Path("chanlun/data/h4_t3_model_v1.json").stat().st_size,
            5 * 1024 * 1024,
        )

    def test_exporter_keeps_only_collapsed_t3_microstate_training_rows(self):
        from scripts.export_h4_t3_production_model import build_model_payload

        candidate = _candidate("000001")
        features = {
            "records": [
                {
                    "trade_date": "2026-07-01",
                    "code": "000001",
                    "record_index": 1,
                    "pool": "picks_fusion",
                    "features": candidate,
                },
                {
                    "trade_date": "2026-07-01",
                    "code": "000001",
                    "record_index": 2,
                    "pool": "picks_fusion",
                    "features": candidate,
                },
            ]
        }
        labels = {
            "records": [
                {
                    "trade_date": "2026-07-01",
                    "code": "000001",
                    "record_index": index,
                    "labels": {
                        "t3": {
                            "horizon": 3,
                            "exit_date": "2026-07-06",
                            "primary_return_pct": 4.0,
                        }
                    },
                }
                for index in (1, 2)
            ]
        }

        model = build_model_payload(features, labels)

        self.assertEqual(1, len(model["training_rows"]))
        self.assertEqual(1, model["training_rows"][0]["record_index"])
        self.assertEqual(FEATURE_DIMENSION, len(model["training_rows"][0]["vector"]))

    def test_daily_runner_hook_uses_real_fusion_candidates(self):
        from run import _build_daily_h4_t3_pool

        candidates = [_candidate("000001")]
        expected = {"status": "ok", "candidates": candidates}
        with mock.patch("run.build_h4_t3_pool", return_value=expected) as builder:
            actual = _build_daily_h4_t3_pool(candidates, "2026-08-20")

        self.assertIs(expected, actual)
        builder.assert_called_once_with(
            candidates,
            "2026-08-20",
            upstream_pool="picks_fusion",
        )

    def test_incremental_backfill_preserves_existing_daily_pools(self):
        from scripts.backfill_h4_t3_pool import backfill_h4_t3_pool

        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir)
            data_dir = output_dir / "data"
            archive_dir = output_dir / "2026-08-20"
            data_dir.mkdir()
            archive_dir.mkdir()
            payload = {
                "date": "2026-08-20",
                "picks_fusion": [],
                "picks_pure": [{"code": "600001"}],
                "next_day_boom": {"mode": "enabled", "candidates": [{"code": "600002"}]},
                "luojie_pool": {"candidates": [{"code": "600003"}]},
                "workspace": {"old": True},
            }
            original = copy.deepcopy(payload)
            (data_dir / "2026-08-20.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            bootstrap = {"pageDate": "2026-08-20", "inlineReportData": payload}
            html = (
                '<script src="assets/report-v2.js?v=old"></script>'
                "<script>window.CHANLUN_BOOTSTRAP = " + json.dumps(bootstrap) + ";</script>"
            )
            archive_html = html.replace('src="assets/', 'src="../assets/')
            (output_dir / "index.html").write_text(html, encoding="utf-8")
            (archive_dir / "index.html").write_text(archive_html, encoding="utf-8")

            result = backfill_h4_t3_pool(output_dir, "2026-08-20")

            updated = json.loads((data_dir / "2026-08-20.json").read_text(encoding="utf-8"))
            self.assertEqual("ok", updated["h4_t3_pool"]["status"])
            for key in ("picks_fusion", "picks_pure", "next_day_boom", "luojie_pool"):
                self.assertEqual(original[key], updated[key])
            self.assertIn("h4_t3", updated["workspace"]["view_order"])
            self.assertEqual(0, result["candidate_count"])
            self.assertIn('"h4_t3_pool"', (output_dir / "index.html").read_text(encoding="utf-8"))
            self.assertIn('"h4_t3_pool"', (archive_dir / "index.html").read_text(encoding="utf-8"))
            self.assertNotIn("report-v2.js?v=old", (output_dir / "index.html").read_text(encoding="utf-8"))
            self.assertNotIn("report-v2.js?v=old", (archive_dir / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
