import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import requests

from chanlun import data_fetcher


TRADE_DATE = "2026-08-26"


def _sina_rows(trade_date=TRADE_DATE, count=40):
    end = datetime.fromisoformat("{} 14:30:00".format(trade_date))
    rows = []
    for index in range(count):
        timestamp = end - timedelta(minutes=30 * (count - index - 1))
        rows.append(
            {
                "day": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open": "10.0",
                "high": "10.2",
                "low": "9.8",
                "close": "10.1",
                "volume": "1000",
            }
        )
    return rows


def _eastmoney_payload(trade_date=TRADE_DATE, count=40):
    rows = _sina_rows(trade_date, count)
    return {
        "data": {
            "klines": [
                "{},{},{},{},{},{}".format(
                    row["day"],
                    row["open"],
                    row["close"],
                    row["high"],
                    row["low"],
                    row["volume"],
                )
                for row in rows
            ]
        }
    }


class _Response:
    def __init__(
        self,
        payload=None,
        *,
        text="",
        status_code=200,
        content_type="application/json"
    ):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("provider returned HTTP {}".format(self.status_code))

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class MinuteFailureEvidenceTests(unittest.TestCase):
    def _fetch_exhausted(self, response_or_error):
        def get(*_args, **_kwargs):
            if isinstance(response_or_error, BaseException):
                raise response_or_error
            return response_or_error

        with patch.object(data_fetcher.SESSION, "get", side_effect=get):
            with self.assertRaises(data_fetcher.MinuteDataFetchError) as caught:
                data_fetcher._fetch_minute_for_repository(
                    "600000",
                    30,
                    40,
                    required_date=TRADE_DATE,
                    as_of="{}T15:05:00+08:00".format(TRADE_DATE),
                    sleep_fn=lambda _delay: None,
                )
        return caught.exception.diagnostics

    def test_non_json_http_response_is_summarized_without_secret_or_url(self):
        diagnostics = self._fetch_exhausted(
            _Response(
                ValueError("response was not JSON"),
                text=(
                    "<html>https://provider.example/path?token=secret "
                    "authorization=Bearer secret</html>"
                ),
                content_type="text/html; charset=utf-8",
            )
        )

        attempts = diagnostics["attempt_evidence"]
        self.assertEqual(len(attempts), 4)
        self.assertEqual(attempts[0]["provider"], "eastmoney")
        self.assertEqual(attempts[1]["provider"], "sina")
        self.assertEqual(attempts[0]["result"], "failed")
        self.assertEqual(attempts[0]["reason"], "decode_error")
        self.assertEqual(attempts[0]["http_status"], 200)
        self.assertEqual(attempts[0]["content_type"], "text/html; charset=utf-8")
        self.assertNotIn("https://", json.dumps(diagnostics))
        self.assertNotIn("secret", json.dumps(diagnostics))

    def test_connection_error_records_category_and_exception_type_only(self):
        diagnostics = self._fetch_exhausted(
            requests.ConnectionError("https://provider.example/?token=secret")
        )

        attempt = diagnostics["attempt_evidence"][0]
        self.assertEqual(attempt["exception_category"], "connection")
        self.assertEqual(attempt["exception_type"], "ConnectionError")
        self.assertNotIn("token", json.dumps(diagnostics))
        self.assertNotIn("provider.example", json.dumps(diagnostics))

    def test_timeout_records_category_and_exception_type_only(self):
        diagnostics = self._fetch_exhausted(
            requests.Timeout("timeout url=https://provider.example/?token=secret")
        )

        attempt = diagnostics["attempt_evidence"][0]
        self.assertEqual(attempt["exception_category"], "timeout")
        self.assertEqual(attempt["exception_type"], "Timeout")
        self.assertNotIn("timeout url", json.dumps(diagnostics))

    def test_valid_json_payload_rejected_by_business_validation_is_recorded(self):
        response = _Response(_eastmoney_payload("2026-08-25"), content_type="application/json")

        def get(url, **_kwargs):
            if "sina" in url:
                return _Response(_sina_rows("2026-08-25"), content_type="application/json")
            return response

        with patch.object(data_fetcher.SESSION, "get", side_effect=get):
            with self.assertRaises(data_fetcher.MinuteDataFetchError) as caught:
                data_fetcher._fetch_minute_for_repository(
                    "600000",
                    30,
                    40,
                    required_date=TRADE_DATE,
                    as_of="{}T15:05:00+08:00".format(TRADE_DATE),
                    sleep_fn=lambda _delay: None,
                )

        attempt = caught.exception.diagnostics["attempt_evidence"][0]
        self.assertEqual(attempt["result"], "rejected")
        self.assertEqual(attempt["reason"], "latest_date_mismatch")
        self.assertEqual(attempt["exception_category"], "validation")
        self.assertEqual(attempt["http_status"], 200)
        self.assertEqual(attempt["content_type"], "application/json")
        self.assertIn("json_", attempt["response_summary"])

    def test_previous_provider_failure_then_next_provider_success_keeps_rejection_evidence(self):
        calls = []

        def eastmoney(code, scale, count):
            calls.append("eastmoney")
            return None

        def sina(code, scale, count):
            calls.append("sina")
            rows = _sina_rows(TRADE_DATE, count)
            rows[-1]["day"] = "{} 15:00:00".format(TRADE_DATE)
            return data_fetcher._with_source(
                {
                    "dates": [row["day"] for row in rows],
                    "opens": [10.0] * count,
                    "highs": [10.2] * count,
                    "lows": [9.8] * count,
                    "closes": [10.1] * count,
                    "volumes": [1000] * count,
                },
                "sina",
            )

        with patch.object(
            data_fetcher, "_fetch_eastmoney_minute_kline_remote", side_effect=eastmoney
        ), patch.object(
            data_fetcher, "_fetch_sina_minute_kline_remote", side_effect=sina
        ):
            payload = data_fetcher._fetch_minute_for_repository(
                "600000",
                30,
                40,
                required_date=TRADE_DATE,
                as_of="{}T15:05:00+08:00".format(TRADE_DATE),
                sleep_fn=lambda _delay: None,
            )

        self.assertEqual(calls, ["eastmoney", "sina"])
        self.assertEqual(payload["source"], "sina")
        self.assertEqual(payload["_fetch_diagnostics"]["attempts"], 2)
        self.assertEqual(
            payload["_fetch_diagnostics"]["attempt_evidence"][0]["provider"],
            "eastmoney",
        )
        self.assertEqual(
            payload["_fetch_diagnostics"]["attempt_evidence"][0]["reason"],
            "empty_response",
        )
        self.assertEqual(
            payload["_fetch_diagnostics"]["attempt_evidence"][1]["result"],
            "success",
        )


if __name__ == "__main__":
    unittest.main()
