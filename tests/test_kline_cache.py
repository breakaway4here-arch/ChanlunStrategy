"""Tests for kline_cache — merge, prune, roundtrip, and incremental fetch."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import chanlun.data_fetcher as data_fetcher

from chanlun.kline_cache import (
    kline_dict_to_records,
    records_to_kline_dict,
    merge_kline_records,
    prune_records_by_trading_days,
    read_cached_records,
    write_cached_records,
    cached_kline_if_sufficient,
    reset_cache_stats,
)


class KlineCacheTest(unittest.TestCase):

    # ---- merge / prune / roundtrip ----

    def test_merge_dedupes_by_date_and_sorts(self):
        old = [
            {"date": "2026-05-25", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
            {"date": "2026-05-26", "open": 2, "high": 3, "low": 2, "close": 3, "volume": 20},
        ]
        new = [
            {"date": "2026-05-26", "open": 20, "high": 30, "low": 20, "close": 30, "volume": 200},
            {"date": "2026-05-27", "open": 3, "high": 4, "low": 3, "close": 4, "volume": 30},
        ]
        merged = merge_kline_records(old, new)
        self.assertEqual([r["date"] for r in merged], ["2026-05-25", "2026-05-26", "2026-05-27"])
        self.assertEqual(merged[1]["close"], 30)

    def test_prune_uses_trading_dates_not_calendar_days(self):
        records = [
            {"date": "2026-05-13", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-14", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-15", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-18", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-19", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-20", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-21", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-22", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-25", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-26", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-27", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        ]
        pruned = prune_records_by_trading_days(records, keep_trading_days=10)
        self.assertEqual(pruned[0]["date"], "2026-05-14")
        self.assertEqual(pruned[-1]["date"], "2026-05-27")
        self.assertEqual(len(pruned), 10)

    def test_roundtrip_preserves_numpy_arrays(self):
        kline = {
            "dates": ["2026-05-25", "2026-05-26"],
            "opens": np.array([1.0, 2.0]),
            "highs": np.array([2.0, 3.0]),
            "lows": np.array([0.8, 1.8]),
            "closes": np.array([1.5, 2.5]),
            "volumes": np.array([100.0, 200.0]),
        }
        records = kline_dict_to_records(kline)
        restored = records_to_kline_dict(records)
        self.assertEqual(restored["dates"], kline["dates"])
        self.assertTrue(np.array_equal(restored["closes"], kline["closes"]))

    # ---- file I/O ----

    def test_write_and_read_cache(self):
        records = [
            {"date": "2026-05-25", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
            {"date": "2026-05-26", "open": 2, "high": 3, "low": 2, "close": 3, "volume": 20},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with patch("chanlun.kline_cache.KLINE_CACHE_DIR", tmp):
                write_cached_records("day", "600519", records, "test", keep_trading_days=120)
                loaded = read_cached_records("day", "600519")
                self.assertEqual(len(loaded), 2)
                self.assertEqual(loaded[0]["date"], "2026-05-25")

    def test_cached_kline_sufficient_and_insufficient(self):
        records = [{"date": f"2026-05-{d:02d}", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}
                   for d in range(1, 29)]
        with tempfile.TemporaryDirectory() as tmp:
            with patch("chanlun.kline_cache.KLINE_CACHE_DIR", tmp):
                write_cached_records("day", "600519", records, "test", keep_trading_days=120)
                kline = cached_kline_if_sufficient("day", "600519", count=10)
                self.assertIsNotNone(kline)
                self.assertEqual(len(kline["dates"]), 10)
                kline_none = cached_kline_if_sufficient("day", "600519", count=50)
                self.assertIsNone(kline_none)

    def test_fetch_daily_uses_incremental_remote_count_when_cache_sufficient(self):
        records = []
        start = date(2026, 1, 1)
        for i in range(100):
            d = start + timedelta(days=i)
            records.append({
                "date": d.isoformat(),
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 10,
            })

        calls = []

        def fake_remote(_code, count=100):
            calls.append(count)
            return _make_kline_dict(count, date(2026, 5, 1))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("chanlun.kline_cache.KLINE_CACHE_DIR", tmp):
                write_cached_records("day", "600519", records, "test", keep_trading_days=120)
                with patch.object(data_fetcher, "KLINE_REPOSITORY_ENABLED", False):
                    with patch.object(data_fetcher, "_fetch_daily_kline_remote", fake_remote):
                        kline = data_fetcher.fetch_daily_kline("600519", count=100)
        self.assertEqual(calls, [5])
        self.assertEqual(len(kline["dates"]), 100)

    def test_fetch_30min_uses_incremental_remote_count_when_cache_sufficient(self):
        records = []
        for i in range(80):
            records.append({
                "date": f"2026-05-26 {9 + (i // 2):02d}:{'30' if i % 2 == 0 else '00'}:00",
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 10,
            })

        calls = []

        def fake_remote(_code, count=80):
            calls.append(count)
            return _make_30min_kline_dict(count)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("chanlun.kline_cache.KLINE_CACHE_DIR", tmp):
                write_cached_records("30min", "600519", records, "test", keep_trading_days=10)
                with patch.object(data_fetcher, "KLINE_REPOSITORY_ENABLED", False):
                    with patch.object(data_fetcher, "_fetch_30min_kline_remote", fake_remote):
                        kline = data_fetcher.fetch_30min_kline("600519", count=80)
        self.assertEqual(calls, [16])
        self.assertEqual(len(kline["dates"]), 80)

    def test_fetch_15min_uses_incremental_remote_count_when_cache_sufficient(self):
        records = []
        for i in range(220):
            records.append({
                "date": f"2026-05-{20 + (i // 32):02d} {9 + ((i % 32) // 4):02d}:{(i % 4) * 15:02d}:00",
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 10,
            })

        calls = []

        def fake_remote(_code, count=220):
            calls.append(count)
            return _make_15min_kline_dict(count)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("chanlun.kline_cache.KLINE_CACHE_DIR", tmp):
                write_cached_records("15min", "600519", records, "test", keep_trading_days=10)
                with patch.object(data_fetcher, "KLINE_REPOSITORY_ENABLED", False):
                    with patch.object(data_fetcher, "_fetch_15min_kline_remote", fake_remote):
                        kline = data_fetcher.fetch_15min_kline("600519", count=220)
        self.assertEqual(calls, [32])
        self.assertEqual(len(kline["dates"]), 220)

    def test_prune_records_by_trading_days_keeps_same_day_30min_bars_together(self):
        records = [
            {"date": "2026-05-13 09:30:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-13 10:00:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-14 09:30:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-26 09:30:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-27 09:30:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        ]
        pruned = prune_records_by_trading_days(records, keep_trading_days=2)
        dates = [r["date"] for r in pruned]
        self.assertIn("2026-05-26 09:30:00", dates)
        self.assertIn("2026-05-27 09:30:00", dates)
        self.assertNotIn("2026-05-13 09:30:00", dates)

    def test_stock_name_cache_uses_project_cache_before_parent_cache(self):
        self.assertEqual(
            Path(data_fetcher.STOCK_CACHE_PATH),
            Path(data_fetcher.BASE_DIR) / "stock_names_cache.json",
        )
        code_to_name = data_fetcher._build_code_to_name()
        self.assertEqual(code_to_name["601878"], "浙商证券")


def _make_kline_dict(count, start):
    dates = [(start + timedelta(days=i)).isoformat() for i in range(count)]
    return {
        "dates": dates,
        "opens": np.ones(count),
        "highs": np.ones(count) * 2,
        "lows": np.ones(count),
        "closes": np.ones(count) * 1.5,
        "volumes": np.ones(count) * 100,
    }


def _make_30min_kline_dict(count):
    dates = [f"2026-05-26 {9 + (i // 2):02d}:{'30' if i % 2 == 0 else '00'}:00"
             for i in range(count)]
    return {
        "dates": dates,
        "opens": np.ones(count),
        "highs": np.ones(count) * 2,
        "lows": np.ones(count),
        "closes": np.ones(count) * 1.5,
        "volumes": np.ones(count) * 100,
    }


def _make_15min_kline_dict(count):
    dates = [f"2026-05-{20 + (i // 32):02d} {9 + ((i % 32) // 4):02d}:{(i % 4) * 15:02d}:00"
             for i in range(count)]
    return {
        "dates": dates,
        "opens": np.ones(count),
        "highs": np.ones(count) * 2,
        "lows": np.ones(count),
        "closes": np.ones(count) * 1.5,
        "volumes": np.ones(count) * 100,
    }


if __name__ == "__main__":
    unittest.main()
