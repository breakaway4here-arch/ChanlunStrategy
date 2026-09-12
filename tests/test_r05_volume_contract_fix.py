import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from chanlun import data_fetcher
from chanlun.daily_structure_pool import build_daily_structure_pool
from chanlun.kline_repository import KLineRepository, KLineResult
from chanlun.market_sentiment import build_daily_inputs_from_windows
from chanlun.preclose_data import _merge_daily_klines
from chanlun.preclose_pipeline import _derive_turnover
from chanlun.preclose_runtime import _append_intraday_quote_with_reason
from chanlun.preclose_runtime import _sector_context
from chanlun.report_view_model import _build_pool_quality_features
from chanlun.screener_fusion import screen_daily_fusion
from chanlun.screener_pure import screen_daily_pure
from chanlun import volume_contract
from run import _attach_liquidity


def _mixed_rows(count=2):
    rows = []
    for index in range(count):
        rows.append({
            "ts": "2026-08-{:02d}".format(10 + index),
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 100.0 + index,
            "amount": 1000.0 if index == 0 else 0.0,
            "amount_available": index == 0,
            "volume_unit": "hands" if index == 0 else "unknown",
            "volume_raw_unit": "hands" if index == 0 else "shares",
            "volume_source": "eastmoney" if index == 0 else "sina",
            "amount_unit": "CNY" if index == 0 else "unknown",
            "amount_source": "eastmoney" if index == 0 else "",
            "is_final": 1,
            "adjustment": "qfq",
        })
    return rows


def _daily_payload(dates, *, amount_available, amount_units, volume_units):
    size = len(dates)
    return {
        "dates": list(dates),
        "opens": [1.0] * size,
        "highs": [2.0] * size,
        "lows": [0.5] * size,
        "closes": [1.5] * size,
        "volumes": [10.0] * size,
        "amounts": [1234.0] * size,
        "amount_available": list(amount_available),
        "amount_units": list(amount_units),
        "amount_sources": ["eastmoney" if unit == "CNY" else "" for unit in amount_units],
        "volume_units": list(volume_units),
        "volume_raw_units": list(volume_units),
        "volume_sources": ["eastmoney" if unit == "hands" else "tencent" for unit in volume_units],
        "finals": [True] * size,
        "adjustment": "qfq",
    }


class R05VolumeContractFixTests(unittest.TestCase):
    def test_legacy_main_screeners_surface_actual_five_bar_quantity_gap(self):
        closes = np.linspace(8.0, 10.0, 120)
        result = SimpleNamespace(
            code="300998",
            name="旧入口数量缺口",
            closes=closes,
            opens=closes - 0.1,
            highs=closes + 0.2,
            lows=closes - 0.2,
            dates=["2026-09-11"] * 120,
            volumes=np.ones(120) * 2_000_000,
            buy_points=[{
                "type": "一买",
                "tier": "formal",
                "category": "A",
                "index": 119,
                "price": 10.0,
                "trend_strength": 2,
                "volatility": 0.05,
            }],
            trend_type="上涨趋势",
            divergence=None,
            fractals=[],
            strokes=[],
            segments=[],
            macd_hist=np.zeros(120),
            pivots=[],
        )
        pure_diagnostics = {}
        fusion_diagnostics = {}

        self.assertEqual(
            screen_daily_pure(
                [result], {}, [], quantity_diagnostics=pure_diagnostics
            ),
            [],
        )
        self.assertEqual(
            screen_daily_fusion(
                [result], closes, {}, quantity_diagnostics=fusion_diagnostics
            ),
            [],
        )
        for consumer, diagnostics in (
            ("legacy_pure_liquidity", pure_diagnostics),
            ("legacy_fusion_liquidity", fusion_diagnostics),
        ):
            self.assertEqual(diagnostics["quantity_evidence"], [{
                "code": "300998",
                "consumer": consumer,
                "window": 5,
                "status": "unavailable",
                "reason": "quantity_evidence_unavailable",
            }])

    def test_windowed_volume_evidence_ignores_only_bars_outside_requested_slice(self):
        self.assertTrue(
            hasattr(volume_contract, "canonical_volume_window"),
            "window-aware canonical helper is required",
        )
        values = [999999999.0] * 14 + [100.0] * 6
        source = {
            "volumes": values,
            "volume_units": ["unknown"] * 14 + ["hands"] * 6,
            "volume_raw_units": ["unknown"] * 14 + ["hands"] * 6,
            "volume_sources": ["tencent"] * 14 + ["eastmoney"] * 6,
        }

        recent = volume_contract.canonical_volume_window(source, slice(-6, None))
        self.assertEqual(recent.tolist(), [100.0] * 6)

        source["volume_units"][-6] = "unknown"
        source["volume_raw_units"][-6] = "unknown"
        source["volume_sources"][-6] = "tencent"
        self.assertIsNone(
            volume_contract.canonical_volume_window(source, slice(-6, None))
        )

    def test_multi_bar_amount_availability_must_be_row_aligned(self):
        source = {
            "amounts": [1000.0, 2000.0],
            "amount_available": True,
            "amount_units": ["CNY", "CNY"],
            "amount_sources": ["eastmoney", "eastmoney"],
        }
        self.assertIsNone(
            volume_contract.canonical_amount_window(source, slice(-2, None))
        )

    def test_repository_and_batch_keep_row_level_volume_and_amount_metadata(self):
        rows = _mixed_rows(60)
        kline = KLineRepository._rows_to_kline(rows, "verified", False)
        self.assertEqual(kline["volume_units"][0], "hands")
        self.assertEqual(kline["volume_units"][-1], "unknown")
        self.assertEqual(kline["amount_available"].tolist()[0], True)
        self.assertEqual(kline["amount_units"][0], "CNY")

        kline["_data_status"] = {
            "daily": "verified",
            "latest_date": rows[-1]["ts"],
            "source": "market_history_db",
            "bars": len(rows),
            "stale": False,
            "is_final": True,
            "adjustment": "qfq",
        }
        repository = MagicMock()
        repository.get_many.return_value = {
            "600000": KLineResult(
                kline=kline,
                status="verified",
                source="market_history_db",
                stale=False,
            )
        }
        previous = data_fetcher._KLINE_REPOSITORY
        try:
            data_fetcher._KLINE_REPOSITORY = repository
            output = data_fetcher.batch_fetch_daily_klines(
                [{"code": "600000", "name": "测试"}],
                required_date=rows[-1]["ts"],
            )
        finally:
            data_fetcher._KLINE_REPOSITORY = previous

        self.assertEqual(output[0]["volume_units"][0], "hands")
        self.assertEqual(output[0]["amount_units"][0], "CNY")
        self.assertEqual(output[0]["klines"]["volume_sources"][-1], "sina")

    def test_repository_does_not_infer_amount_availability_from_positive_value(self):
        rows = _mixed_rows(1)
        rows[0].pop("amount_available")
        kline = KLineRepository._rows_to_kline(rows, "verified", False)
        self.assertEqual(kline["amount_available"].tolist(), [False])
        self.assertTrue(np.isnan(kline["amounts"][0]))

    def test_preclose_merge_preserves_row_level_metadata_and_unavailable_amount(self):
        history = _daily_payload(
            ["2026-08-27"],
            amount_available=[False],
            amount_units=["unknown"],
            volume_units=["unknown"],
        )
        live = _daily_payload(
            ["2026-08-28"],
            amount_available=[False],
            amount_units=["unknown"],
            volume_units=["hands"],
        )
        live["finals"] = [False]
        merged = _merge_daily_klines(history, live, "2026-08-28")
        self.assertEqual(merged["amount_available"], [False, False])
        self.assertEqual(merged["amount_units"], ["unknown", "unknown"])
        self.assertEqual(merged["volume_units"], ["unknown", "hands"])

    def test_preclose_turnover_does_not_infer_availability_from_positive_amount(self):
        payload = _daily_payload(
            ["2026-08-28"],
            amount_available=[False],
            amount_units=["unknown"],
            volume_units=["hands"],
        )
        self.assertIsNone(
            _derive_turnover({"daily": [{"status": "available", "klines": payload}]})
        )

    def test_market_sentiment_rejects_unknown_amount_unit(self):
        result = build_daily_inputs_from_windows({
            "dates": ["2026-08-28"],
            "rows": [{
                "asset_type": "stock",
                "exchange": "SH",
                "code": "600000",
                "ts": "2026-08-28",
                "close": 10.0,
                "amount": 1234.0,
                "amount_available": True,
                "amount_unit": "unknown",
            }],
        })
        self.assertIsNone(result[0]["turnover"])
        self.assertEqual(result[0]["turnover_quality"], "missing_amount_evidence")

    def test_amount_consumers_reject_missing_source_even_when_marker_and_cny_are_present(self):
        result = build_daily_inputs_from_windows({
            "dates": ["2026-08-28"],
            "rows": [{
                "asset_type": "stock",
                "exchange": "SH",
                "code": "600000",
                "ts": "2026-08-28",
                "close": 10.0,
                "amount": 1234.0,
                "amount_available": True,
                "amount_unit": "CNY",
                "amount_source": "",
            }],
        })
        self.assertIsNone(result[0]["turnover"])
        self.assertIsNone(_derive_turnover({"daily": [{
            "status": "available",
            "klines": {
                "amounts": [1234.0],
                "amount_available": [True],
                "amount_units": ["CNY"],
                "amount_sources": [""],
            },
        }]}))
        sectors = _sector_context([{
            "industry": "测试行业",
            "change_pct": 1.0,
            "amount": 1234.0,
            "amount_available": True,
            "amount_unit": "CNY",
            "amount_source": "",
        }])
        self.assertEqual(sectors[0]["amount"], 0.0)

    def test_preclose_quote_without_explicit_units_keeps_price_but_not_volume_or_amount_evidence(self):
        history = {
            "code": "600000",
            "name": "测试",
            "klines": {
                "dates": ["2026-08-27"],
                "opens": [10.0],
                "highs": [11.0],
                "lows": [9.0],
                "closes": [10.0],
                "volumes": [100.0],
                "amounts": [None],
                "amount_available": [False],
                "volume_units": ["hands"],
                "volume_raw_units": ["hands"],
                "volume_sources": ["eastmoney"],
                "amount_units": ["unknown"],
                "amount_sources": [""],
                "adjustment": "qfq",
            },
        }
        quote = {
            "code": "600000",
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "current_price": 10.5,
            "prev_close": 10.0,
            "volume": 100.0,
            "amount": 10000.0,
        }
        row, reason = _append_intraday_quote_with_reason(
            history, quote, "2026-08-28", "2026-08-28T14:45:00+08:00"
        )
        self.assertEqual(reason, "")
        self.assertIsNotNone(row)
        self.assertEqual(row["volume_unit"], "unknown")
        self.assertFalse(row["amount_available"])
        self.assertEqual(row["amount_unit"], "unknown")
        self.assertEqual(row["klines"]["volume_units"][-1], "unknown")
        self.assertFalse(row["klines"]["amount_available"][-1])

    def test_preclose_quote_units_without_sources_are_not_quantity_evidence(self):
        history = {
            "code": "600000",
            "name": "测试",
            "klines": _daily_payload(
                ["2026-08-27"],
                amount_available=[True],
                amount_units=["CNY"],
                volume_units=["hands"],
            ),
        }
        history["klines"]["closes"] = [10.0]
        history["klines"]["opens"] = [10.0]
        history["klines"]["highs"] = [10.5]
        history["klines"]["lows"] = [9.5]
        quote = {
            "code": "600000",
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "current_price": 10.5,
            "prev_close": 10.0,
            "volume": 100.0,
            "volume_unit": "hands",
            "volume_raw_unit": "hands",
            "amount": 10000.0,
            "amount_available": True,
            "amount_unit": "CNY",
        }
        row, reason = _append_intraday_quote_with_reason(
            history, quote, "2026-08-28", "2026-08-28T14:45:00+08:00"
        )
        self.assertEqual(reason, "")
        self.assertEqual(row["volume_source"], "")
        self.assertFalse(row["amount_available"])
        self.assertEqual(row["amount_source"], "")

    def test_preclose_history_scalar_summaries_are_not_broadcast_as_row_evidence(self):
        history = {
            "code": "600000",
            "name": "测试",
            "klines": {
                "dates": ["2026-08-26", "2026-08-27"],
                "opens": [10.0, 10.0],
                "highs": [11.0, 11.0],
                "lows": [9.0, 9.0],
                "closes": [10.0, 10.0],
                "volumes": [100.0, 100.0],
                "amounts": [100000.0, 100000.0],
                "volume_unit": "hands",
                "volume_raw_unit": "hands",
                "volume_source": "last-row-only",
                "amount_available": True,
                "amount_unit": "CNY",
                "amount_source": "last-row-only",
                "adjustment": "qfq",
            },
        }
        quote = {
            "code": "600000",
            "prev_close": 10.0,
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "current_price": 10.2,
            "volume": 200.0,
            "amount": 204000.0,
            "volume_unit": "hands",
            "volume_raw_unit": "hands",
            "volume_source": "eastmoney",
            "amount_available": True,
            "amount_unit": "CNY",
            "amount_source": "eastmoney",
        }
        row, reason = _append_intraday_quote_with_reason(
            history, quote, "2026-08-28", "2026-08-28T14:45:00+08:00"
        )
        self.assertEqual(reason, "")
        self.assertEqual(row["klines"]["volume_units"], ["unknown", "unknown", "hands"])
        self.assertEqual(row["klines"]["volume_sources"], ["", "", "eastmoney"])
        self.assertEqual(row["klines"]["amount_available"], [False, False, True])
        self.assertEqual(row["klines"]["amount_units"], ["unknown", "unknown", "CNY"])

    def test_liquidity_rejects_unavailable_amount_and_missing_volume_unit(self):
        row = {
            "amounts": [1000.0, 2000.0],
            "amount_available": [False, False],
            "amount_units": ["CNY", "CNY"],
            "volume_units": ["unknown", "unknown"],
        }
        _attach_liquidity(row)
        self.assertIsNone(row["money20"])
        self.assertEqual(row["liquidity_source"], "missing")
        self.assertEqual(row["liquidity_window_bars"], 0)

        proxy_row = {"closes": [10.0, 10.0], "volumes": [100.0, 100.0]}
        _attach_liquidity(proxy_row)
        self.assertIsNone(proxy_row["money20"])
        self.assertEqual(proxy_row["liquidity_source"], "missing")
        self.assertEqual(proxy_row["liquidity_window_bars"], 0)

        missing_provenance = {
            "closes": [10.0, 10.0],
            "volumes": [100.0, 100.0],
            "volume_units": ["hands", "hands"],
            "volume_raw_units": ["hands", "hands"],
            "volume_sources": ["", ""],
        }
        _attach_liquidity(missing_provenance)
        self.assertIsNone(missing_provenance["money20"])
        self.assertEqual(missing_provenance["liquidity_source"], "missing")
        self.assertEqual(missing_provenance["liquidity_window_bars"], 0)

    def test_liquidity_uses_only_its_twenty_bar_evidence_window(self):
        amount_row = {
            "amounts": [999999999.0] + [1000.0] * 20,
            "amount_available": [False] + [True] * 20,
            "amount_units": ["unknown"] + ["CNY"] * 20,
            "amount_sources": ["tencent"] + ["eastmoney"] * 20,
        }
        _attach_liquidity(amount_row)
        self.assertEqual(amount_row["money20"], 1000.0)
        self.assertEqual(amount_row["liquidity_source"], "amounts")
        self.assertEqual(amount_row["liquidity_window_bars"], 20)

        proxy_row = {
            "closes": [10.0] * 21,
            "volumes": [999999999.0] + [100.0] * 20,
            "volume_units": ["unknown"] + ["hands"] * 20,
            "volume_raw_units": ["unknown"] + ["hands"] * 20,
            "volume_sources": ["tencent"] + ["eastmoney"] * 20,
        }
        _attach_liquidity(proxy_row)
        self.assertEqual(proxy_row["money20"], 100000.0)
        self.assertEqual(proxy_row["liquidity_source"], "volume_price_proxy")
        self.assertEqual(proxy_row["liquidity_window_bars"], 20)

    def test_liquidity_proxy_does_not_attest_a_partial_close_window(self):
        closes = [10.0] * 20
        closes[7] = None
        row = {
            "closes": closes,
            "volumes": [100.0] * 20,
            "volume_units": ["hands"] * 20,
            "volume_raw_units": ["hands"] * 20,
            "volume_sources": ["eastmoney"] * 20,
        }

        _attach_liquidity(row)

        self.assertIsNone(row["money20"])
        self.assertEqual(row["liquidity_source"], "missing")
        self.assertEqual(row["liquidity_window_bars"], 0)

    def test_report_volume_window_is_pending_when_old_bars_are_unknown(self):
        row = {
            "code": "600000",
            "volumes": [1_000_000_000.0] * 8 + [100.0] * 13,
            "volume_units": ["unknown"] * 8 + ["hands"] * 13,
            "volume_raw_units": ["unknown"] * 8 + ["hands"] * 13,
            "volume_sources": ["tencent"] * 8 + ["eastmoney"] * 13,
        }
        quality = _build_pool_quality_features(row)
        self.assertIsNone(quality["volume20"])
        self.assertIsNone(quality["volume_ratio20"])
        self.assertEqual(quality["volume_evidence_status"], "unknown")

    def test_report_volume_window_rejects_missing_value_without_realigning_rows(self):
        volumes = [100.0] * 21
        volumes[-10] = None
        row = {
            "code": "600000",
            "volumes": volumes,
            "volume_units": ["hands"] * 21,
            "volume_raw_units": ["hands"] * 21,
            "volume_sources": ["eastmoney"] * 21,
        }
        quality = _build_pool_quality_features(row)
        self.assertIsNone(quality["volume20"])
        self.assertIsNone(quality["volume_ratio20"])
        self.assertEqual(quality["volume_evidence_status"], "invalid")


if __name__ == "__main__":
    unittest.main()
