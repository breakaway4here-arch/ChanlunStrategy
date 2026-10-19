"""Synthetic, offline cutoff acquisition counterexamples."""
import copy
import importlib
import unittest
from datetime import datetime, timedelta, timezone

CN = timezone(timedelta(hours=8))
CUTOFF = "2026-10-13T14:45:00+08:00"
IDENTITY = {"asset_type": "stock", "exchange": "SH", "code": "600000"}


def calendar(day):
    return datetime.fromisoformat(day).weekday() < 5


def fixture():
    dates = []
    current = datetime(2026, 10, 12)
    while len(dates) < 70:
        if calendar(current.date().isoformat()):
            dates.append(current.date().isoformat())
        current -= timedelta(days=1)
    dates.reverse()
    rows = [dict(ts=d, open=10., high=10.2, low=9.9, close=10.1,
                 volume=160000., amount=161600000., amount_available=True,
                 volume_unit="hands", volume_raw_unit="hands", volume_source="fixture",
                 amount_unit="CNY", amount_source="fixture", adjustment="qfq",
                 is_final=True, source_batch="synthetic") for d in dates]
    minutes = []
    for day in dates[-40:] + ["2026-10-13"]:
        for start in (570, 780):
            for minute in range(start + 15, start + 121, 15):
                stamp = "{} {:02}:{:02}".format(day, minute // 60, minute % 60)
                minutes.append(stamp + ",10,10.1,10.2,9.9,10000,10100000,0,0,0,0")
    response = {"data": {"code": "600000", "market": 1, "klines": minutes}}
    return rows, response


class CutoffDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.module = importlib.import_module("chanlun.intraday_observation_data")
        except ImportError:
            cls.module = None

    def api(self):
        self.assertIsNotNone(self.module, "strict cutoff acquisition module missing")
        return self.module

    def pair(self, response=None):
        api = self.api()
        response = response or fixture()[1]
        return {adjustment: api.parse_eastmoney_minutes(
            response, IDENTITY, adjustment=adjustment, cutoff=CUTOFF,
            fetched_at="2026-10-13T14:46:00+08:00") for adjustment in ("raw", "qfq")}

    def build(self, rows=None, pair=None):
        return self.api().build_cutoff_stock(
            dict(IDENTITY, name="合成样本"), rows or fixture()[0], pair or self.pair(),
            cutoff=CUTOFF, previous_trade_date="2026-10-12", calendar_check=calendar)

    def test_closed_cutoff_aggregates_exactly_fifteen_buckets(self):
        row = self.build()
        daily = row["klines"]
        self.assertEqual(daily["dates"][-1], "2026-10-13")
        self.assertEqual(daily["volumes"][-1], 150000.)
        self.assertEqual(daily["amounts"][-1], 151500000.)
        self.assertFalse(daily["finals"][-1])
        self.assertEqual(row["cutoff_minutes"]["15m"]["dates"][-1], "2026-10-13 14:45:00")
        self.assertEqual(row["cutoff_minutes"]["30m"]["dates"][-1], "2026-10-13 14:30:00")

    def test_later_bar_cannot_change_frozen_input(self):
        rows, response = fixture()
        expected = self.build()
        response["data"]["klines"][-1] = "2026-10-13 15:00,100,200,300,99,1000000,20000000000"
        changed = self.build(rows, self.pair(response))
        self.assertEqual(changed["klines"], expected["klines"])

    def test_missing_middle_daily_record_is_rejected(self):
        rows, _ = fixture()
        del rows[-7]
        with self.assertRaisesRegex(ValueError, "daily_gap"):
            self.build(rows)

    def test_missing_cutoff_bucket_is_rejected(self):
        _, response = fixture()
        response["data"]["klines"] = [r for r in response["data"]["klines"] if not r.startswith("2026-10-13 14:45")]
        with self.assertRaisesRegex(ValueError, "incomplete_cutoff_day"):
            self.build(pair=self.pair(response))

    def test_missing_older_minute_bucket_is_rejected(self):
        _, response = fixture()
        del response["data"]["klines"][-40]
        with self.assertRaisesRegex(ValueError, "incomplete_minute_day"):
            self.build(pair=self.pair(response))

    def test_missing_amount_not_filled_from_daily_or_price(self):
        _, response = fixture()
        response["data"]["klines"][-2] = "2026-10-13 14:45,10,10.1,10.2,9.9,10000,-"
        with self.assertRaisesRegex(ValueError, "amount"):
            self.pair(response)

    def test_wrong_identity_and_nonfinite_are_rejected(self):
        _, response = fixture()
        response["data"]["code"] = "600001"
        with self.assertRaisesRegex(ValueError, "identity"):
            self.pair(response)
        _, response = fixture()
        response["data"]["klines"][-2] = "2026-10-13 14:45,10,10.1,NaN,9.9,10000,10100000"
        with self.assertRaises(ValueError):
            self.pair(response)

    def test_historical_qfq_scale_conflict_rejected_without_today_reference(self):
        rows, _ = fixture()
        rows[-1]["close"] = 10.15
        with self.assertRaisesRegex(ValueError, "historical_basis_conflict"):
            self.build(rows)

    def test_raw_qfq_quantities_must_agree(self):
        pair = self.pair()
        pair["qfq"]["volumes"][-1] += 1
        with self.assertRaisesRegex(ValueError, "pair_quantity_conflict"):
            self.build(pair=pair)

    def test_exact_boundary_not_yet_observed_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cutoff_not_observed"):
            self.api().parse_eastmoney_minutes(fixture()[1], IDENTITY, adjustment="raw",
                                               cutoff=CUTOFF, fetched_at=CUTOFF)

    def test_nonfinal_history_is_rejected_and_never_relabelled(self):
        rows, _ = fixture()
        rows[-4]["is_final"] = False
        with self.assertRaisesRegex(ValueError, "daily_nonfinal"):
            self.build(rows)

    def test_today_final_daily_is_not_read_as_cutoff_input(self):
        rows, _ = fixture()
        rows.append(dict(rows[-1], ts="2026-10-13", high=300, close=200))
        with self.assertRaisesRegex(ValueError, "history_not_previous"):
            self.build(rows)

    def test_payload_is_json_serializable(self):
        import json
        json.dumps(self.build(), allow_nan=False)

    def test_fetch_checks_http_identity_and_request_limits(self):
        api = self.api()
        self.assertTrue(hasattr(api, "fetch_eastmoney_cutoff_pair"), "isolated provider adapter missing")
        calls = []
        response = fixture()[1]

        class Response:
            status_code = 200
            def __init__(self, daily=False):
                self.daily = daily
            def json(self):
                if self.daily:
                    return {"data": {"code": "600000", "market": 1, "klines": [
                        "{ts},{open},{close},{high},{low},{volume},{amount}".format(**r)
                        for r in fixture()[0]]}}
                return response
            def close(self):
                pass

        class Session:
            def get(self, url, **kwargs):
                calls.append(kwargs)
                return Response(kwargs["params"]["klt"] == "101")

        pair = api.fetch_eastmoney_cutoff_pair(IDENTITY, cutoff=CUTOFF, session=Session(),
            previous_trade_date="2026-10-12",
            clock=lambda: datetime(2026, 10, 13, 14, 46, tzinfo=CN),
            deadline=datetime(2026, 10, 13, 14, 58, tzinfo=CN))
        self.assertEqual(pair["raw"]["dates"][-1], "2026-10-13 14:45:00")
        self.assertEqual([c["params"]["fqt"] for c in calls], ["0", "1", "0", "1"])
        self.assertEqual([c["params"]["end"] for c in calls[-2:]], ["20261012", "20261012"])
        self.assertEqual(pair["daily"][-1]["ts"], "2026-10-12")
        self.assertTrue(all(c["allow_redirects"] is False for c in calls))
        self.assertTrue(all(c["timeout"] <= 5 for c in calls))

    def test_expired_deadline_never_makes_a_request(self):
        api = self.api()
        self.assertTrue(hasattr(api, "fetch_eastmoney_cutoff_pair"), "isolated provider adapter missing")
        class Session:
            def get(self, *a, **k):
                self.fail("must not request")
        with self.assertRaisesRegex(TimeoutError, "deadline"):
            api.fetch_eastmoney_cutoff_pair(IDENTITY, cutoff=CUTOFF, session=Session(),
                previous_trade_date="2026-10-12",
                clock=lambda: datetime(2026, 10, 13, 14, 59, tzinfo=CN),
                deadline=datetime(2026, 10, 13, 14, 58, tzinfo=CN))

    def test_dated_daily_parser_excludes_today_final_data(self):
        api = self.api()
        self.assertTrue(hasattr(api, "parse_eastmoney_daily"), "isolated bounded daily parser missing")
        response = {"data": {"code": "600000", "market": 1, "klines": [
            "2026-10-12,10,10.1,10.2,9.9,160000,161600000",
            "2026-10-13,10,300,300,9,160000,161600000"]}}
        with self.assertRaisesRegex(ValueError, "daily_after_reference"):
            api.parse_eastmoney_daily(response, IDENTITY, adjustment="qfq", previous_trade_date="2026-10-12")

    def test_source_history_repair_stays_on_independently_certified_scale(self):
        pair = self.pair()
        rows = fixture()[0]
        pair["raw_daily"] = copy.deepcopy(rows)
        # A historical cash dividend is additive. It must not be approximated
        # by a last-close factor and must not use today's eventual close.
        for row in rows[:-2]:
            for key in ("open", "high", "low", "close"):
                row[key] -= .2
        result = self.build(rows, pair)
        self.assertAlmostEqual(result["cutoff_minutes"]["15m"]["closes"][0], 9.9)
        self.assertEqual(result["klines"]["closes"][-1], 10.1)

    def test_same_day_corporate_action_without_anchor_is_isolated(self):
        pair = self.pair()
        rows = fixture()[0]
        pair["raw_daily"] = copy.deepcopy(rows)
        for row in rows:
            for key in ("open", "high", "low", "close"):
                row[key] -= .2
        with self.assertRaisesRegex(ValueError, "current_day_basis_unverified"):
            self.build(rows, pair)

    def test_collector_retries_neither_failures_nor_existing_captures(self):
        import tempfile
        import json
        from pathlib import Path
        from chanlun.market_history_store import MarketHistoryStore
        api = self.api()
        self.assertTrue(hasattr(api, "acquire_observation_payload"), "readonly collector missing")
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "market.sqlite"
            with MarketHistoryStore(db) as store:
                stock = store.upsert_instrument("stock", "SH", "600000")
                store.upsert_stock_meta(stock, "2026-10-12", dict(name="合成样本", listed_days=500,
                    is_st=False, delisting_risk=False, risk_status="verified", risk_source="eastmoney",
                    risk_as_of="2026-10-12", code="600000", exchange="SH", asset_type="stock"))
                for row in fixture()[0]:
                    for exchange in ("SH", "SZ"):
                        store.upsert_trade_calendar(exchange, row["ts"], True)
                store.upsert_trade_calendar("SH", "2026-10-13", True)
                store.upsert_trade_calendar("SZ", "2026-10-13", True)
            before = db.read_bytes()
            calls = []
            def fetch(identity, **kwargs):
                calls.append(identity.code)
                pair = self.pair()
                if identity.asset_type == "index":
                    for key in ("raw", "qfq"):
                        pair[key].update(identity_key=identity.key, code=identity.code,
                            asset_type="index", exchange=identity.exchange, volume_unit="unknown")
                pair.update(raw_daily=copy.deepcopy(fixture()[0]), daily=copy.deepcopy(fixture()[0]))
                return pair
            kwargs = dict(deadline=datetime(2026, 10, 13, 14, 58, tzinfo=CN),
                clock=lambda: datetime(2026, 10, 13, 14, 46, tzinfo=CN), pair_fetcher=fetch,
                snapshot_dir=Path(temp) / "snapshots", max_workers=2)
            payload = api.acquire_observation_payload(db, "2026-10-13", **kwargs)
            self.assertEqual(payload["collection_health"]["status"], "available")
            self.assertEqual(payload["collection_health"]["expected"], 1)
            self.assertEqual(payload["collection_health"]["coverage"], 1)
            self.assertEqual([s["code"] for s in payload["daily_data"]["stocks"]], ["600000"])
            self.assertEqual(len(payload["minute_data"]["15m"]["600000"]["klines"]["dates"]), 220)
            count = len(calls)
            again = api.acquire_observation_payload(db, "2026-10-13", **kwargs)
            self.assertEqual(len(calls), count)
            self.assertEqual(again, payload)
            self.assertEqual(db.read_bytes(), before)
            json.dumps(payload, allow_nan=False)

    def test_systemic_failure_is_not_a_normal_empty_selection(self):
        import tempfile
        from pathlib import Path
        from chanlun.market_history_store import MarketHistoryStore
        api = self.api()
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "market.sqlite"
            with MarketHistoryStore(db) as store:
                iid = store.upsert_instrument("stock", "SH", "600000")
                store.upsert_stock_meta(iid, "2026-10-12", dict(name="合成样本", listed_days=500,
                    is_st=False, delisting_risk=False))
            calls = []
            def unavailable(identity, **kwargs):
                calls.append(identity.key)
                raise ValueError("provider_missing_minute_amount")
            kwargs = dict(deadline=datetime(2026, 10, 13, 14, 58, tzinfo=CN),
                clock=lambda: datetime(2026, 10, 13, 14, 46, tzinfo=CN), pair_fetcher=unavailable,
                snapshot_dir=Path(temp) / "captures", max_workers=1)
            payload = api.acquire_observation_payload(db, "2026-10-13", **kwargs)
            self.assertEqual(payload["collection_health"]["status"], "failed")
            self.assertEqual(payload["collection_health"]["acquired"], 0)
            self.assertEqual(payload["collection_health"]["rejected"], 1)
            self.assertEqual(payload["collection_health"]["coverage"], 0)
            before = len(calls)
            api.acquire_observation_payload(db, "2026-10-13", **kwargs)
            self.assertEqual(len(calls), before)

    def test_after_day_live_acquisition_is_rejected_even_for_historical_cutoff(self):
        with self.assertRaisesRegex(ValueError, "live_capture_date_mismatch"):
            self.api().acquire_observation_payload("does-not-open.sqlite", "2026-10-13",
                deadline=datetime(2026, 10, 14, 14, 58, tzinfo=CN),
                clock=lambda: datetime(2026, 10, 14, 14, 46, tzinfo=CN))

    def test_deadline_failure_keeps_unprocessed_in_denominator(self):
        import tempfile
        from pathlib import Path
        from chanlun.market_history_store import MarketHistoryStore
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "market.sqlite"
            with MarketHistoryStore(db) as store:
                for code in ("600000", "600001"):
                    iid = store.upsert_instrument("stock", "SH", code)
                    store.upsert_stock_meta(iid, "2026-10-12", dict(name="合成样本", listed_days=500,
                        is_st=False, delisting_risk=False))
            def should_not_fetch(*args, **kwargs):
                self.fail("deadline must stop new requests")
            payload = self.api().acquire_observation_payload(db, "2026-10-13",
                deadline=datetime(2026, 10, 13, 14, 58, tzinfo=CN),
                clock=lambda: datetime(2026, 10, 13, 14, 59, tzinfo=CN), pair_fetcher=should_not_fetch)
            health = payload["collection_health"]
            self.assertEqual((health["expected"], health["timed_out"], health["status"]), (2, 2, "failed"))

    def test_rate_limit_stops_further_provider_calls(self):
        from threading import Event
        api = self.api()
        stop = Event()
        calls = []
        class Response:
            status_code = 429
            def close(self):
                pass
        class Session:
            def get(self, *a, **kw):
                calls.append(kw)
                return Response()
        with self.assertRaises(api.SourceRateLimited):
            api.fetch_eastmoney_cutoff_pair(IDENTITY, cutoff=CUTOFF, previous_trade_date="2026-10-12",
                deadline=datetime(2026, 10, 13, 14, 58, tzinfo=CN), session=Session(), stop_event=stop,
                clock=lambda: datetime(2026, 10, 13, 14, 46, tzinfo=CN))
        self.assertTrue(stop.is_set())
        self.assertEqual(len(calls), 1)

    def test_unknown_calendar_or_suspension_is_never_guessed(self):
        rows = fixture()[0]
        with self.assertRaisesRegex(ValueError, "calendar_unavailable"):
            self.api().validate_daily_history(rows, previous_trade_date="2026-10-12",
                calendar_check=lambda date: None)

    def _ten_stock_cohort_health(self, exclusion, excluded_count=1):
        import tempfile
        from pathlib import Path
        from chanlun.market_history_store import MarketHistoryStore
        pair_template = self.pair()
        pair_template.update(raw_daily=copy.deepcopy(fixture()[0]), daily=copy.deepcopy(fixture()[0]))
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "market.sqlite"
            with MarketHistoryStore(db) as store:
                for i in range(10):
                    excluded = i >= 10 - excluded_count
                    code = "600{:03}".format(i)
                    if excluded and exclusion == "invalid_identity":
                        store.connection.execute("INSERT INTO instruments(asset_type,exchange,code,updated_at) VALUES ('stock','SH',?,'2026-10-12')", ("bad" + str(i),))
                        store.connection.commit()
                        continue
                    iid = store.upsert_instrument("stock", "SH", code)
                    if excluded and exclusion == "missing_metadata":
                        continue
                    store.upsert_stock_meta(iid, "2026-10-12", dict(name="合成样本", listed_days=500,
                        is_st=bool(excluded and exclusion == "st_or_delisting"), delisting_risk=False))
                for row in fixture()[0]:
                    for exchange in ("SH", "SZ"):
                        store.upsert_trade_calendar(exchange, row["ts"], True)
                for exchange in ("SH", "SZ"):
                    store.upsert_trade_calendar(exchange, "2026-10-13", True)
            def fetch(identity, **kwargs):
                pair = copy.deepcopy(pair_template)
                for key in ("raw", "qfq"):
                    pair[key].update(identity_key=identity.key, code=identity.code,
                        asset_type=identity.asset_type, exchange=identity.exchange)
                return pair
            payload = self.api().acquire_observation_payload(db, "2026-10-13",
                deadline=datetime(2026, 10, 13, 14, 58, tzinfo=CN),
                clock=lambda: datetime(2026, 10, 13, 14, 46, tzinfo=CN), pair_fetcher=fetch, max_workers=2)
            return payload["collection_health"]

    def test_one_missing_metadata_in_ten_is_partial_even_when_nine_requests_succeed(self):
        health = self._ten_stock_cohort_health("missing_metadata")
        self.assertEqual(health["status"], "partial")
        self.assertEqual((health["expected"], health["acquired"], health["coverage"]), (9, 9, 1.0))
        self.assertEqual(health["instrument_count"], 10)
        self.assertEqual(health["qualified_cohort"], 9)
        self.assertEqual(health["business_excluded"], 0)
        self.assertEqual(health["foundation_missing"], 1)
        self.assertEqual(health["foundation_missing_reasons"], {"missing_metadata": 1})
        self.assertEqual(health["foundation_coverage"], .9)

    def test_one_legitimate_st_exclusion_does_not_become_acquisition_failure(self):
        health = self._ten_stock_cohort_health("st_or_delisting")
        self.assertEqual(health["status"], "available")
        self.assertEqual((health["expected"], health["acquired"]), (9, 9))
        self.assertEqual(health["instrument_count"], 10)
        self.assertEqual(health["business_excluded"], 1)
        self.assertEqual(health["business_excluded_reasons"], {"st_or_delisting": 1})
        self.assertEqual(health["foundation_missing"], 0)
        self.assertEqual(health["foundation_coverage"], 1.0)

    def test_invalid_identity_is_a_foundation_gap_not_silent_business_exclusion(self):
        health = self._ten_stock_cohort_health("invalid_identity")
        self.assertEqual(health["status"], "partial")
        self.assertEqual(health["foundation_missing"], 1)
        self.assertEqual(health["foundation_missing_reasons"], {"invalid_identity": 1})
        self.assertEqual(health["business_excluded"], 0)
        self.assertEqual(health["foundation_coverage"], .9)

    def test_foundation_coverage_below_ninety_percent_still_blocks_batch(self):
        health = self._ten_stock_cohort_health("missing_metadata", excluded_count=2)
        self.assertEqual(health["status"], "failed")
        self.assertEqual(health["foundation_missing"], 2)
        self.assertEqual(health["foundation_coverage"], .8)

    def test_daily_parser_rejects_both_impossible_zero_quantity_combinations(self):
        for volume, amount in ((0, 161600000), (160000, 0)):
            for adjustment in ("raw", "qfq"):
                with self.subTest(volume=volume, amount=amount, adjustment=adjustment):
                    response = {"data": {"code": "600000", "market": 1, "klines": [
                        "2026-10-12,10,10.1,10.2,9.9,{},{}".format(volume, amount)]}}
                    with self.assertRaisesRegex(ValueError, "amount_volume_conflict"):
                        self.api().parse_eastmoney_daily(response, IDENTITY,
                            adjustment=adjustment, previous_trade_date="2026-10-12")

    def test_daily_history_never_uses_zero_volume_positive_amount_in_ratios(self):
        rows = fixture()[0]
        rows[-3]["volume"] = 0
        with self.assertRaisesRegex(ValueError, "amount_volume_conflict"):
            self.build(rows)

    def test_daily_history_rejects_positive_volume_zero_amount(self):
        rows = fixture()[0]
        rows[-3]["amount"] = 0
        with self.assertRaisesRegex(ValueError, "amount_volume_conflict"):
            self.build(rows)

    def test_minute_parser_rejects_both_impossible_zero_quantity_combinations(self):
        for volume, amount in ((0, 10100000), (10000, 0)):
            for adjustment in ("raw", "qfq"):
                with self.subTest(volume=volume, amount=amount, adjustment=adjustment):
                    _, response = fixture()
                    response["data"]["klines"][-2] = "2026-10-13 14:45,10,10.1,10.2,9.9,{},{}".format(volume, amount)
                    with self.assertRaisesRegex(ValueError, "amount_volume_conflict"):
                        self.api().parse_eastmoney_minutes(response, IDENTITY,
                            adjustment=adjustment, cutoff=CUTOFF,
                            fetched_at="2026-10-13T14:46:00+08:00")

    def test_real_zero_quantities_remain_zero_at_parser_boundary(self):
        daily_response = {"data": {"code": "600000", "market": 1, "klines": [
            "2026-10-12,10,10,10,10,0,0"]}}
        row = self.api().parse_eastmoney_daily(daily_response, IDENTITY,
            adjustment="qfq", previous_trade_date="2026-10-12")[0]
        self.assertEqual((row["volume"], row["amount"]), (0, 0))
        _, response = fixture()
        response["data"]["klines"][-2] = "2026-10-13 14:45,10,10,10,10,0,0"
        payload = self.pair(response)["qfq"]
        self.assertEqual((payload["volumes"][-1], payload["amounts"][-1]), (0, 0))


if __name__ == "__main__":
    unittest.main()
