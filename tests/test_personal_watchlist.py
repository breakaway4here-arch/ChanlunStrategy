import json
import tempfile
import unittest
from pathlib import Path

from chanlun.personal_watchlist import (
    build_personal_watchlist_snapshot,
    build_watchlist_fact_index,
    ensure_watchlist_stocks,
    load_personal_watchlist,
    resolve_personal_watchlist,
)


INITIAL_CODES = ["300139", "002281", "300308", "688041", "688525"]
NAME_MAP = {
    "300139": "晓程科技",
    "002281": "光迅科技",
    "300308": "中际旭创",
    "688041": "海光信息",
    "688525": "佰维存储",
}


class PersonalWatchlistConfigTests(unittest.TestCase):
    def _write_config(self, payload):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "watchlist.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _payload(self, items=None):
        return {
            "schema_version": "1",
            "revision": "watchlist-20260820-01",
            "updated_at": "2026-08-20T16:00:00+08:00",
            "updated_by": "user",
            "items": items
            if items is not None
            else [
                {
                    "code": code,
                    "enabled": True,
                    "added_at": "2026-08-20",
                    "role": "strong_watch",
                    "priority": priority,
                    "tags": ["用户重点观察"],
                    "note": "",
                    "thesis": "",
                }
                for priority, code in enumerate(INITIAL_CODES, start=1)
            ],
        }

    def test_loads_initial_codes_derives_names_and_sorts_priority(self):
        payload = self._payload()
        payload["items"] = list(reversed(payload["items"]))

        config = load_personal_watchlist(
            self._write_config(payload), name_map=NAME_MAP
        )

        self.assertEqual(config["schema_version"], "1")
        self.assertEqual(config["revision"], "watchlist-20260820-01")
        self.assertEqual(
            [item["code"] for item in config["items"]], INITIAL_CODES
        )
        self.assertEqual(
            [item["name"] for item in config["items"]],
            [NAME_MAP[code] for code in INITIAL_CODES],
        )

    def test_canonical_config_contains_the_five_user_selected_stocks(self):
        config = load_personal_watchlist()

        self.assertEqual(
            [item["code"] for item in config["items"]], INITIAL_CODES
        )
        self.assertEqual(
            [item["name"] for item in config["items"]],
            [NAME_MAP[code] for code in INITIAL_CODES],
        )

    def test_rejects_duplicate_invalid_code_and_role(self):
        cases = []
        duplicate = self._payload()
        duplicate["items"].append(dict(duplicate["items"][0]))
        cases.append(duplicate)

        invalid_code = self._payload()
        invalid_code["items"][0]["code"] = "ABC"
        cases.append(invalid_code)

        unsupported_role = self._payload()
        unsupported_role["items"][0]["role"] = "holding"
        cases.append(unsupported_role)

        for payload in cases:
            with self.subTest(payload=payload["items"][0]):
                with self.assertRaises(ValueError):
                    load_personal_watchlist(
                        self._write_config(payload), name_map=NAME_MAP
                    )

    def test_worker_valid_code_without_local_name_map_uses_code_not_user_label(self):
        payload = self._payload(items=[{
            "code": "600999",
            "note": "不可信的任意名称",
            "enabled": True,
            "role": "research",
            "priority": 1,
            "thesis": "等待本地证券名称表更新",
        }])

        config = load_personal_watchlist(
            self._write_config(payload), name_map=NAME_MAP
        )

        self.assertEqual(config["items"][0]["name"], "600999")
        self.assertEqual(config["name_resolution_missing_codes"], ["600999"])

    def test_remote_version_wins_and_supports_research_role(self):
        remote = self._payload(items=[
            {
                "code": "688041",
                "enabled": True,
                "role": "research",
                "priority": 1,
                "thesis": "跟踪国产算力验证",
            }
        ])
        remote["revision"] = "watchlist-remote-02"

        config, diagnostics = resolve_personal_watchlist(
            path=self._write_config(self._payload()),
            remote_url="https://example.test/api/decision-watchlist",
            fetcher=lambda _url: remote,
            name_map=NAME_MAP,
        )

        self.assertEqual(config["revision"], "watchlist-remote-02")
        self.assertEqual(config["items"][0]["role"], "research")
        self.assertEqual(diagnostics["status"], "remote_live")
        self.assertEqual(diagnostics["source"], "worker")
        self.assertEqual(diagnostics["revision"], "watchlist-remote-02")

    def test_remote_failure_falls_back_to_local_with_explicit_diagnostics(self):
        def fail(_url):
            raise TimeoutError("timed out")

        config, diagnostics = resolve_personal_watchlist(
            path=self._write_config(self._payload()),
            remote_url="https://example.test/api/decision-watchlist",
            fetcher=fail,
            name_map=NAME_MAP,
        )

        self.assertEqual(config["revision"], "watchlist-20260820-01")
        self.assertEqual(diagnostics["status"], "local_fallback")
        self.assertEqual(diagnostics["source"], "local_file")
        self.assertIn("timed out", diagnostics["remote_error"])

    def test_invalid_remote_payload_does_not_partially_merge(self):
        remote = self._payload(items=[
            {
                "code": "300139",
                "enabled": True,
                "role": "holding",
                "priority": 1,
            }
        ])

        config, diagnostics = resolve_personal_watchlist(
            path=self._write_config(self._payload()),
            remote_url="https://example.test/api/decision-watchlist",
            fetcher=lambda _url: remote,
            name_map=NAME_MAP,
        )

        self.assertEqual(
            [item["code"] for item in config["items"]], INITIAL_CODES
        )
        self.assertEqual(diagnostics["status"], "local_fallback")
        self.assertIn("unsupported watchlist role", diagnostics["remote_error"])


class PersonalWatchlistSnapshotTests(unittest.TestCase):
    def _config(self, *, added_at="2026-08-20"):
        return {
            "schema_version": "1",
            "revision": "watchlist-20260820-01",
            "items": [
                {
                    "code": code,
                    "name": NAME_MAP[code],
                    "enabled": True,
                    "added_at": added_at,
                    "role": "strong_watch",
                    "priority": priority,
                    "tags": ["用户重点观察"],
                    "note": "",
                    "thesis": "跟踪催化与结构共振",
                }
                for priority, code in enumerate(INITIAL_CODES, start=1)
            ],
        }

    @staticmethod
    def _fact(code, evidence_date="2026-08-20"):
        return {
            "code": code,
            "evidence_date": evidence_date,
            "data_status": "verified",
            "current_price": 100.5,
            "change_pct": 2.35,
            "sector": "通信设备",
            "trend_type": "上涨趋势",
            "divergence": None,
            "price_levels": {"support": 96.0, "resistance": 105.0},
            "candidate_intersections": [
                {"pool": "fusion", "evidence_ref": "candidate:2026-08-20:fusion:" + code}
            ],
        }

    def test_five_items_are_always_present_and_fresh_facts_are_exposed(self):
        facts = {code: self._fact(code) for code in INITIAL_CODES[:2]}

        snapshot = build_personal_watchlist_snapshot(
            self._config(),
            facts,
            "2026-08-20",
            as_of="2026-08-20T15:10:00+08:00",
            generated_at="2026-08-20T15:11:00+08:00",
        )

        self.assertEqual(len(snapshot["items"]), 5)
        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(snapshot["fresh_count"], 2)
        self.assertEqual(snapshot["missing_count"], 3)
        first = snapshot["items"][0]
        self.assertEqual(first["fact_status"], "fresh")
        self.assertEqual(first["current"]["current_price"], 100.5)
        self.assertEqual(first["change_status"], "new")
        self.assertTrue(first["evidence_refs"])

    def test_stale_or_missing_facts_never_emit_price_levels_or_actions(self):
        facts = {INITIAL_CODES[0]: self._fact(INITIAL_CODES[0], "2026-08-19")}

        snapshot = build_personal_watchlist_snapshot(
            self._config(added_at="2026-08-01"),
            facts,
            "2026-08-20",
            as_of="2026-08-20T15:10:00+08:00",
        )

        stale = snapshot["items"][0]
        missing = snapshot["items"][1]
        self.assertEqual(stale["fact_status"], "stale")
        self.assertNotIn("current_price", stale["current"])
        self.assertEqual(stale["price_levels"], {})
        self.assertEqual(stale["action_status"], "data_insufficient")
        self.assertEqual(missing["fact_status"], "missing")
        self.assertEqual(missing["current"], {})
        self.assertEqual(missing["price_levels"], {})
        self.assertEqual(missing["action_status"], "data_insufficient")

    def test_previous_snapshot_marks_only_new_additions(self):
        previous = {
            "items": [
                {
                    "code": code,
                    "current": {"current_price": 90.0},
                    "fact_status": "fresh",
                }
                for code in INITIAL_CODES[:-1]
            ]
        }
        facts = {code: self._fact(code) for code in INITIAL_CODES}

        snapshot = build_personal_watchlist_snapshot(
            self._config(added_at="2026-08-01"),
            facts,
            "2026-08-20",
            previous_snapshot=previous,
        )

        self.assertEqual(snapshot["items"][0]["change_status"], "tracked")
        self.assertEqual(snapshot["items"][-1]["change_status"], "new")
        self.assertEqual(
            snapshot["items"][0]["previous"]["current_price"], 90.0
        )


class PersonalWatchlistRuntimeTests(unittest.TestCase):
    def _config(self):
        return {
            "schema_version": "1",
            "revision": "watchlist-20260820-01",
            "items": [
                {
                    "code": code,
                    "name": NAME_MAP[code],
                    "enabled": True,
                    "role": "strong_watch",
                    "priority": priority,
                }
                for priority, code in enumerate(INITIAL_CODES, start=1)
            ],
        }

    @staticmethod
    def _kline(latest="2026-08-20", close=100.0):
        return {
            "dates": ["2026-08-19", latest],
            "opens": [95.0, 98.0],
            "highs": [101.0, 105.0],
            "lows": [94.0, 97.0],
            "closes": [96.0, close],
            "volumes": [10.0, 20.0],
        }

    def test_missing_watch_codes_are_fetched_and_fresh_rows_join_scan(self):
        calls = []

        def fetcher(code, required_date=None, as_of=None):
            calls.append((code, required_date, as_of))
            if code == "688525":
                return self._kline(latest="2026-08-19")
            return self._kline()

        existing = [{
            "code": "300139",
            "name": "晓程科技",
            "klines": self._kline(),
        }]

        stocks, acquisition = ensure_watchlist_stocks(
            existing,
            self._config(),
            fetcher,
            "2026-08-20",
            as_of="2026-08-20T15:10:00+08:00",
        )

        self.assertEqual(len(calls), 4)
        self.assertEqual({row["code"] for row in stocks}, set(INITIAL_CODES[:-1]))
        self.assertEqual(acquisition["by_code"]["688525"]["data_status"], "stale")
        self.assertNotIn("688525", acquisition["added_codes"])

    def test_fact_index_uses_kline_chan_and_candidate_evidence(self):
        class Result:
            code = "300308"
            trend_type = "上涨趋势"
            divergence = None
            buy_points = [{"type": "三买"}]
            sell_points = []

        stocks = [{
            "code": "300308",
            "name": "中际旭创",
            "sector": "通信设备",
            "klines": self._kline(close=102.0),
        }]
        facts = build_watchlist_fact_index(
            self._config(),
            stocks,
            [Result()],
            "2026-08-20",
            candidate_pools={
                "fusion": [{"code": "300308"}],
                "observation": [{"code": "300139"}],
            },
            acquisition={
                "by_code": {
                    "688525": {
                        "code": "688525",
                        "evidence_date": "2026-08-19",
                        "data_status": "stale",
                    }
                }
            },
        )

        fact = facts["300308"]
        self.assertEqual(fact["data_status"], "verified")
        self.assertEqual(fact["current_price"], 102.0)
        self.assertEqual(fact["change_pct"], 6.25)
        self.assertEqual(fact["trend_type"], "上涨趋势")
        self.assertEqual(fact["buy_signal_count"], 1)
        self.assertEqual(
            fact["candidate_intersections"],
            [{
                "pool": "fusion",
                "evidence_ref": "candidate:2026-08-20:fusion:300308",
            }],
        )
        self.assertEqual(facts["688525"]["data_status"], "stale")


if __name__ == "__main__":
    unittest.main()
