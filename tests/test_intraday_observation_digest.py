"""Finite offline digest contracts using the producers' existing row fields."""
import copy
import json
import socket
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from chanlun import intraday_observation_delivery as delivery
from tests.test_intraday_observation_delivery import report_fixture


def classic(code, **changes):
    row = {"code": code, "name": "候选" + code,
           "best_buy_point": {"type": "三买", "tier": "formal", "is_recent": True,
                              "signal_age_days": 0, "signal_date": "2026-10-13"},
           "data_status": {"daily": "verified", "stale": False, "latest_date": "2026-10-13"}}
    row.update(changes)
    return row


def right(code, **changes):
    row = classic(code, source_channel="right_side_startup", tier="candidate",
                  confirmations=["30min新鲜二买"], strategy_input_evidence={
                      "interval": "30m", "status": "intraday_available", "stale": False,
                      "latest_date": "2026-10-13", "bar_state": "intraday", "is_final": False,
                      "as_of": "2026-10-13T14:45:00+08:00"})
    row.update(changes)
    return row


def report_with(**pools):
    report = report_fixture()
    paths = {key: path for key, _, path in delivery.POOL_SPECS}
    for key, rows in pools.items():
        target = report
        for part in paths[key][:-1]:
            target = target[part]
        target[paths[key][-1]] = copy.deepcopy(rows)
        report["intraday_observation"]["pool_status"][key] = {"status": "available" if rows else "empty"}
    return report


class DigestTests(unittest.TestCase):
    def setUp(self):
        guard = mock.patch.object(socket.socket, "connect", side_effect=AssertionError("offline test"))
        guard.start()
        self.addCleanup(guard.stop)

    def digest(self, report):
        return delivery.build_observation_digest(delivery.build_observation_snapshot(report))

    def test_same_parent_family_is_one_vote_and_independent_source_wins(self):
        a, b = classic("600001"), classic("600002")
        report = report_with(picks_pure=[a, b], picks_fusion=[a], startup_watchlist=[a],
                             observation_watchlist=[a], next_day_boom=[a], h4_t3_pool=[a],
                             right_side_startup=[right("600002")])
        before = copy.deepcopy(report)
        digest = self.digest(report)
        self.assertEqual([row["code"] for row in digest["selected"]], ["600002", "600001"])
        self.assertEqual([row["valid_source_count"] for row in digest["selected"]], [2, 1])
        self.assertEqual(digest["candidate_count"], 2)
        self.assertEqual(report, before)
        snapshot = delivery.build_observation_snapshot(report)
        for key, _, path in delivery.POOL_SPECS:
            original = report
            for part in path:
                original = original[part]
            self.assertEqual([row["code"] for row in snapshot["pools"][key]["rows"]],
                             [row["code"] for row in original])

    def test_mixed_view_uses_row_source_instead_of_container(self):
        digest = self.digest(report_with(picks_pure=[right("600001")],
                                         picks_fusion=[right("600001")],
                                         right_side_startup=[right("600001")]))
        self.assertEqual(digest["selected"][0]["sources"], ["right_side"])
        self.assertEqual(digest["selected"][0]["valid_source_count"], 1)

    def test_watch_pending_unknown_and_luojie_observation_do_not_supply_votes(self):
        report = report_with(picks_pure=[classic("600001")],
            right_side_startup_watch=[right("600001", tier="watch", failure_gate="30min_structure"),
                                     right("600002", tier="watch", reason_code="waiting_30m_confirm")],
            luojie_pool=[classic("600001", tier="生命线观察"), classic("600003", tier="风控观察")],
            observation_watchlist=[classic("600004", tier="watch", minute30_confirmation_status="pending")])
        digest = self.digest(report)
        self.assertEqual([row["code"] for row in digest["selected"]], ["600001"])
        self.assertEqual(digest["selected"][0]["valid_source_count"], 1)
        self.assertEqual(digest["candidate_count"], 4)

    def test_hard_invalidity_cannot_be_overridden_by_more_pools(self):
        for changes in ({"expired": True}, {"invalidated": True},
                        {"data_status": {"daily": "verified", "stale": True}},
                        {"price_basis": {"status": "conflict"}},
                        {"best_buy_point": {"tier": "formal", "is_recent": False, "signal_age_days": 11}}):
            with self.subTest(changes=changes):
                report = report_with(picks_pure=[classic("600001", **changes)],
                    picks_fusion=[classic("600001")], right_side_startup=[right("600001")])
                self.assertEqual(self.digest(report)["selected"], [])

    def test_same_source_retains_old_order_without_cross_source_score_addition(self):
        report = report_with(picks_pure=[classic("600009", score=1), classic("600001", score=999999)])
        self.assertEqual([row["code"] for row in self.digest(report)["selected"]], ["600009", "600001"])
        changed = copy.deepcopy(report)
        changed["picks_pure"][0]["score"] = -999999
        self.assertEqual(self.digest(report), self.digest(changed))

    def test_cross_source_ties_use_stable_identity_while_preserving_source_order(self):
        def confirmed(code):
            return classic(code, confirmations=['30min二买'],
                strategy_input_evidence=right(code)['strategy_input_evidence'])
        digest = self.digest(report_with(picks_pure=[confirmed('600009'), confirmed('600001')],
                                         right_side_startup=[right('600002')]))
        self.assertEqual([row['code'] for row in digest['selected']], ['600002', '600009', '600001'])

    def test_confirmed_source_precedes_daily_candidate_with_same_vote_count(self):
        digest = self.digest(report_with(picks_pure=[classic("600001"), classic("600002",
            best_buy_point={"type": "二买候选", "tier": "candidate", "is_recent": True,
                            "confirmations": ["30min二买"], "signal_age_days": 0},
            strategy_input_evidence=right("600002")["strategy_input_evidence"])]))
        self.assertEqual([row["code"] for row in digest["selected"]], ["600002", "600001"])

    def test_classic_confirmation_needs_current_minute_evidence(self):
        for status in ("missing", "unavailable", None):
            row = classic("600001", best_buy_point={"tier": "candidate", "is_recent": True,
                "confirmations": ["30min二买"]}, minute30_input_status=status)
            with self.subTest(status=status):
                self.assertEqual(self.digest(report_with(picks_pure=[row]))["selected"], [])
        # Daily formal evidence remains usable under its own daily-only label.
        row = classic("600001", minute30_input_status="missing",
            best_buy_point={"tier": "formal", "is_recent": True, "confirmations": ["stale text"]})
        selected = self.digest(report_with(picks_pure=[row]))["selected"]
        self.assertEqual(selected[0]["source_states"], {"classic": "daily_candidate"})

    def test_row_provenance_precedes_mixed_container_and_unknown_channel_does_not_vote(self):
        row = classic("600001", source_channel="low_position")
        digest = self.digest(report_with(luojie_pool=[row]))
        self.assertEqual(digest["selected"][0]["sources"], ["classic"])
        self.assertEqual(self.digest(report_with(picks_pure=[classic("600001", source_channel="unverified")]))["selected"], [])

    def test_existing_decision_reject_does_not_vote_or_veto_other_independent_source(self):
        rejected = classic("600001", decision_engine_v1={"decision_code": "reject",
            "decision": "不推荐（高位风险）", "risk_reasons": []})
        self.assertEqual(self.digest(report_with(picks_pure=[rejected]))["selected"], [])
        digest = self.digest(report_with(picks_pure=[rejected], right_side_startup=[right("600001")]))
        self.assertEqual(digest["selected"][0]["sources"], ["right_side"])
        self.assertTrue(digest["selected"][0]["has_pending"])

    def test_actual_basis_status_conflict_and_missing_minute_cannot_be_good_hits(self):
        self.assertEqual(self.digest(report_with(picks_pure=[classic("600001",
            price_basis={"basis_status": "conflict"})]))["selected"], [])
        row = right("600001", minute30_input_status="missing")
        self.assertEqual(self.digest(report_with(right_side_startup=[row]))["selected"], [])

    def test_nonfinite_event_age_stays_local_invalid_and_snapshot_is_serializable(self):
        for age in (float('nan'), float('inf'), -1, True):
            row = classic('600001', best_buy_point={'tier':'formal', 'is_recent':True, 'signal_age_days':age})
            with self.subTest(age=age):
                snapshot = delivery.build_observation_snapshot(report_with(picks_pure=[row, classic('600002')]))
                delivery.canonical_bytes(snapshot)
                self.assertEqual([item['code'] for item in delivery.build_observation_digest(snapshot)['selected']], ['600002'])

    def test_malformed_optional_data_state_does_not_abort_healthy_pool(self):
        report = report_with(picks_pure=[classic('600001', data_status={'daily': []}), classic('600002')])
        snapshot = delivery.build_observation_snapshot(report)
        self.assertEqual(len(snapshot['pools']['picks_pure']['rows']), 2)
        self.assertEqual([item['code'] for item in delivery.build_observation_digest(snapshot)['selected']], ['600002'])

    def test_old_identity_only_snapshot_is_unknown_never_empty_or_filled(self):
        report = report_with(picks_pure=[{"code": "600001", "name": "旧候选"}])
        snapshot = delivery.build_observation_snapshot(report)
        digest = delivery.build_observation_digest(snapshot)
        self.assertEqual(digest["selected"], [])
        self.assertEqual(digest["candidate_count"], 1)
        text = delivery.format_observation_messages(snapshot)[0]
        self.assertIn("候选1只", text)
        self.assertIn("依据不足", text)
        self.assertNotIn("未选出候选", text)

    def test_one_message_max_five_deduped_and_bounded_utf8_full_archive_survives(self):
        rows = [classic(str(600000+i), name="中文🚀"*10) for i in range(100)]
        snapshot = delivery.build_observation_snapshot(report_with(picks_pure=rows, picks_fusion=rows))
        messages = delivery.format_observation_messages(snapshot)
        self.assertEqual(messages, delivery.format_observation_messages(snapshot, max_bytes=2048))
        self.assertEqual(len(messages), 1)
        self.assertLessEqual(len(messages[0].encode("utf-8")), 2048)
        self.assertIn("精选5只", messages[0])
        self.assertIn("候选100只", messages[0])
        for index in range(100):
            self.assertEqual(messages[0].count(str(600000+index)), 1 if index < 5 else 0)
        self.assertEqual(len(snapshot["pools"]["picks_pure"]["rows"]), 100)
        self.assertNotIn("http", messages[0])

    def test_real_luojie_producer_tier_reaches_snapshot_digest_and_both_outboxes(self):
        # Producer is a pure numpy computation; no run/main or data acquisition.
        from chanlun.luojie_pool import build_luojie_pool
        from tests.test_luojie_pool import _result
        result = _result(buy_points=[{"type": "三买", "tier": "formal"}])
        result.strategy_input_evidence = {"interval": "15m", "status": "intraday_available",
            "latest_date": "2026-10-13", "as_of": "2026-10-13T14:45:00+08:00", "stale": False}
        pool = build_luojie_pool([{"code": "600001", "name": "测试通信", "sector": "通信设备",
            "data_status": {"daily": "verified", "latest_date": "2026-10-13", "stale": False}}], [result])
        self.assertEqual(pool["candidates"][0]["tier"], "主升候选")
        snapshot = delivery.build_observation_snapshot(report_with(luojie_pool=pool["candidates"]))
        self.assertEqual(delivery.build_observation_digest(snapshot)["selected"][0]["sources"], ["luojie"])
        calls = []
        now = datetime.fromisoformat("2026-10-13T14:58:00+08:00")
        with tempfile.TemporaryDirectory() as directory:
            args = {"sender": lambda message, **kwargs: calls.append(message) or {"success": True},
                    "deadline": now + timedelta(seconds=30), "clock": lambda: now}
            self.assertTrue(delivery.deliver_observation(snapshot, outbox_path=Path(directory)/"wx.json",
                app_token="stub", uid="stub", **args)["success"])
            self.assertTrue(delivery.deliver_wecom_observation(snapshot, outbox_path=Path(directory)/"wecom.json",
                webhook="https://example.invalid/stub", **args)["success"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertIn("罗姐", calls[0])

    def test_real_right_side_producers_reach_digest_from_frozen_price_fixture(self):
        from chanlun.trend_continuation import (
            build_trend_continuation_pool, upgrade_trend_continuation_with_30min, normalize_trend_candidate)
        from tests.test_trend_continuation import _fixture_result
        seeds, watches, _ = build_trend_continuation_pool([_fixture_result(code)
            for code in ('300709', '002636', '002952')])
        minute = _fixture_result('300709', interval='min30')
        candidates, pending, _ = upgrade_trend_continuation_with_30min(seeds, [minute])
        self.assertEqual([row['code'] for row in candidates], ['300709'])
        self.assertEqual(pending, [])
        report = report_with(picks_pure=[normalize_trend_candidate(candidates[0])],
                             right_side_startup=candidates, right_side_startup_watch=watches)
        report['date'] = '2026-08-31'
        report['intraday_observation']['cutoff'] = '2026-08-31T14:45:00+08:00'
        # The historical preclose fixture was captured at 14:47:05, after this
        # observation cutoff. Its unmodified evidence must remain rejected.
        self.assertEqual(self.digest(report)['selected'], [])
        # A synthetic cutoff boundary reuses the same prices and real producer;
        # this is field reachability, not a claim of actual 14:45 availability.
        minute.strategy_input_evidence = dict(minute.strategy_input_evidence,
            as_of='2026-08-31T14:45:00+08:00')
        candidates, _, _ = upgrade_trend_continuation_with_30min(seeds, [minute])
        report['picks_pure'] = [normalize_trend_candidate(candidates[0])]
        report['right_side_startup']['candidates'] = candidates
        digest = self.digest(report)
        self.assertEqual([row['code'] for row in digest['selected']], ['300709'])
        self.assertEqual(digest['selected'][0]['valid_source_count'], 1)
        self.assertEqual(digest['selected'][0]['source_states'], {'right_side': 'confirmed'})

    def test_prior_formats_sent_partial_dispatching_unknown_are_never_reformatted_and_sent(self):
        snapshot = delivery.build_observation_snapshot(report_with(picks_pure=[classic("600001")]))
        now = datetime.fromisoformat("2026-10-13T14:58:00+08:00")
        for channel in ("wxpusher", "wecom"):
            for states in (("sent", "sent"), ("sent",), ("sent", "dispatching"), ("unknown",), ("uncertain",)):
                with self.subTest(channel=channel, states=states), tempfile.TemporaryDirectory() as directory:
                    path = Path(directory)/"outbox.json"
                    receipt = {key: snapshot.get(key) for key in ("run_id", "input_hash", "content_hash")}
                    receipt.update(channel=channel, parts={str(i): {"state": state} for i, state in enumerate(states)})
                    if channel == "wecom":
                        import hashlib
                        receipt.update(format_version="wecom-text-utf8-v1", message_hashes=["old"]*3,
                            webhook_hash=hashlib.sha256(b"stub").hexdigest())
                    path.write_text(json.dumps(receipt))
                    before = path.read_bytes()
                    calls = []
                    args = dict(outbox_path=path, sender=lambda *a, **k: calls.append(1) or {"success": True},
                                deadline=now+timedelta(seconds=30), clock=lambda: now)
                    if channel == "wecom":
                        delivery.deliver_wecom_observation(snapshot, webhook="stub", **args)
                    else:
                        delivery.deliver_observation(snapshot, app_token="stub", uid="stub", **args)
                    self.assertEqual(calls, [])
                    self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
