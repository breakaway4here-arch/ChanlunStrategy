import unittest

from chanlun.chan_engine import analyze_dual
from chanlun.engine_candidate import analyze_with_all_candidate_components
from tests.test_chan_engine_candidate_macd import _make_kline
from tests.test_chan_engine_snapshot import SCENARIOS


class ChanEngineCandidateAllTests(unittest.TestCase):
    def test_all_candidate_components_match_legacy_dual_output(self):
        for name, closes in SCENARIOS.items():
            with self.subTest(name=name):
                kline = _make_kline(closes)
                payload = analyze_dual(
                    code=name,
                    name=name,
                    dates=kline["dates"],
                    opens=kline["opens"],
                    highs=kline["highs"],
                    lows=kline["lows"],
                    closes=kline["closes"],
                    volumes=kline["volumes"],
                    candidate_analyzer=analyze_with_all_candidate_components,
                )

                self.assertTrue(payload["comparison"]["equal"], payload["comparison"])


if __name__ == "__main__":
    unittest.main()
