import json
import tempfile
import unittest
from pathlib import Path

from chanlun.position_book import (
    build_public_holding_risks,
    build_public_position_diagnostics,
    build_holding_risks,
    load_position_book,
    normalize_position_book,
    position_book_error_snapshot,
    summarize_position_book,
)


NOW = "2026-08-20T15:10:00+08:00"


def _payload(*, items=None, stale_after="2026-08-21T09:00:00+08:00"):
    return {
        "schema_version": "1",
        "source": "manual-confirmation",
        "as_of": "2026-08-20T15:00:00+08:00",
        "confirmed_at": "2026-08-20T15:05:00+08:00",
        "stale_after": stale_after,
        "items": items if items is not None else [],
    }


def _position(code="300308", *, confirmed=True):
    return {
        "code": code,
        "name": "中际旭创" if code == "300308" else "测试股",
        "quantity": 100,
        "cost_price": 188.5,
        "confirmed": confirmed,
    }


def _sell_signal(code="300308"):
    return {
        "code": code,
        "name": "中际旭创" if code == "300308" else "未持有股票",
        "sell_points": [
            {"type": "一卖", "reason": "日线一卖风险"},
            {"type": "顶背驰", "reason": "MACD 顶背驰"},
        ],
        "trend_type": "上涨趋势转弱",
        "sector": "通信设备",
    }


class PositionBookContractTests(unittest.TestCase):
    def test_default_private_position_file_is_gitignored(self):
        root = Path(__file__).resolve().parents[1]
        ignored = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("config/position_book.json", ignored.splitlines())

    def test_missing_file_is_unconfigured_and_never_emits_actions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            book = load_position_book(
                Path(tmpdir) / "missing.json",
                now=NOW,
                name_map={"300308": "中际旭创"},
            )

        self.assertEqual(book["status"], "unconfigured")
        self.assertEqual(book["items"], [])
        self.assertEqual(build_holding_risks(book, [_sell_signal()]), [])

    def test_metadata_is_required_and_must_be_timezone_aware(self):
        for field in ("source", "as_of", "confirmed_at", "stale_after"):
            payload = _payload(items=[_position()])
            payload[field] = ""
            with self.subTest(field=field), self.assertRaises(ValueError):
                normalize_position_book(payload, now=NOW)

        payload = _payload(items=[_position()])
        payload["confirmed_at"] = "2026-08-20T15:05:00"
        with self.assertRaises(ValueError):
            normalize_position_book(payload, now=NOW)

    def test_empty_fresh_book_has_no_positions_or_risks(self):
        book = normalize_position_book(_payload(), now=NOW)

        self.assertEqual(book["status"], "empty")
        self.assertEqual(build_holding_risks(book, [_sell_signal()]), [])

    def test_stale_book_fails_closed(self):
        book = normalize_position_book(
            _payload(
                items=[_position()],
                stale_after="2026-08-20T15:09:59+08:00",
            ),
            now=NOW,
        )

        self.assertEqual(book["status"], "stale")
        self.assertEqual(build_holding_risks(book, [_sell_signal()]), [])

    def test_snapshot_expires_at_the_exact_stale_after_instant(self):
        book = normalize_position_book(
            _payload(
                items=[_position()],
                stale_after="2026-08-20T15:10:00+08:00",
            ),
            now=NOW,
        )

        self.assertEqual(book["status"], "stale")
        self.assertEqual(build_holding_risks(book, [_sell_signal()]), [])

    def test_runtime_rechecks_at_output_time_unless_replay_is_explicit(self):
        root = Path(__file__).resolve().parents[1]
        runtime = (root / "run.py").read_text(encoding="utf-8")
        main_start = runtime.index("def main(")
        default_time = runtime.index(
            "generated_at = generated_at or datetime.now().astimezone()",
            main_start,
        )
        explicit_flag = runtime.index(
            "is_explicit_replay = generated_at is not None",
            main_start,
        )
        start = runtime.index("position_name_map = {")
        end = runtime.index("holding_risks = build_holding_risks", start)
        position_block = runtime[start:end]

        self.assertLess(explicit_flag, default_time)
        self.assertIn("if is_explicit_replay", position_block)
        self.assertIn("else None", position_block)
        self.assertIn("now=position_evaluation_time", position_block)
        self.assertIn('time_metadata.get("as_of")', position_block)

    def test_unconfirmed_position_fails_closed(self):
        book = normalize_position_book(
            _payload(items=[_position(confirmed=False)]),
            now=NOW,
        )

        self.assertEqual(book["status"], "unconfirmed")
        self.assertEqual(build_holding_risks(book, [_sell_signal()]), [])

    def test_only_fresh_confirmed_held_signal_becomes_holding_risk(self):
        book = normalize_position_book(
            _payload(items=[_position()]),
            now=NOW,
            name_map={"300308": "中际旭创"},
        )

        risks = build_holding_risks(
            book,
            [_sell_signal("600000"), _sell_signal("300308")],
        )

        self.assertEqual(book["status"], "fresh")
        self.assertEqual(len(risks), 1)
        self.assertEqual(risks[0]["code"], "300308")
        self.assertEqual(risks[0]["name"], "中际旭创")
        self.assertEqual(risks[0]["position_source"], "manual-confirmation")
        self.assertEqual(risks[0]["position_as_of"], book["as_of"])
        self.assertIn("一卖", risks[0]["reason"])
        self.assertIn("顶背驰", risks[0]["reason"])
        self.assertEqual(risks[0]["action"], "复核减仓或退出条件")

    def test_summary_keeps_configuration_state_out_of_user_actions(self):
        book = normalize_position_book(
            _payload(items=[_position()]),
            now=NOW,
        )
        risks = build_holding_risks(book, [_sell_signal()])
        summary = summarize_position_book(book, risks)

        self.assertEqual(summary["status"], "fresh")
        self.assertEqual(summary["position_count"], 1)
        self.assertEqual(summary["confirmed_count"], 1)
        self.assertEqual(summary["holding_risk_count"], 1)

    def test_loader_rejects_duplicate_codes_and_non_positive_quantity(self):
        cases = [
            _payload(items=[_position(), _position()]),
            _payload(items=[dict(_position(), quantity=0)]),
        ]
        for payload in cases:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "position-book.json"
                path.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    load_position_book(path, now=NOW)

    def test_public_projection_is_opt_in_and_never_exposes_size_or_cost(self):
        book = normalize_position_book(
            _payload(items=[_position()]),
            now=NOW,
        )
        risks = build_holding_risks(book, [_sell_signal()])

        self.assertEqual(build_public_holding_risks(risks), [])
        published = build_public_holding_risks(
            risks, allow_identifiers=True
        )
        self.assertEqual(published[0]["code"], "300308")
        self.assertNotIn("quantity", published[0])
        self.assertNotIn("cost_price", published[0])
        self.assertEqual(
            published[0]["privacy_scope"], "explicit_identifier_opt_in"
        )

    def test_public_diagnostics_disclose_state_without_private_metadata(self):
        book = normalize_position_book(
            _payload(items=[_position()]),
            now=NOW,
        )
        risks = build_holding_risks(book, [_sell_signal()])

        private = build_public_position_diagnostics(
            book, risks, details_published=False
        )
        self.assertEqual(private["status"], "private")
        self.assertEqual(private["publication_status"], "withheld")
        for field in (
            "source",
            "as_of",
            "confirmed_at",
            "stale_after",
            "position_count",
            "confirmed_count",
            "holding_risk_count",
        ):
            self.assertNotIn(field, private)

        stale = normalize_position_book(
            _payload(
                items=[_position()],
                stale_after="2026-08-20T15:09:59+08:00",
            ),
            now=NOW,
        )
        stale_public = build_public_position_diagnostics(stale, [])
        self.assertEqual(stale_public["status"], "stale")
        self.assertIn("已禁止输出动作", stale_public["message"])

    def test_error_snapshot_uses_stable_code_without_path_or_raw_error(self):
        error = ValueError(
            "cannot load /Users/example/private/position_book.json"
        )
        snapshot = position_book_error_snapshot(error)

        self.assertEqual(snapshot["status"], "error")
        self.assertEqual(snapshot["error_code"], "invalid_config")
        self.assertNotIn("/Users/", snapshot["reason"])


if __name__ == "__main__":
    unittest.main()
