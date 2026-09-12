import json
import os
import unittest
from pathlib import Path

from chanlun.preclose_pipeline import PreclosePipelineConfig, run_preclose_pipeline


REPLAY_ROOT = Path(
    "/Users/yangfan/yf_source/ChanlunStrategy/research/"
    "project-audit-fixes-20260911/replay-r05-inprogress-v1"
)


@unittest.skipUnless(
    os.environ.get("CHANLUN_R05_FROZEN_REPLAY") == "1",
    "bounded R05 frozen replay is opt-in",
)
class R05FixedInputReplayTests(unittest.TestCase):
    def test_old_raw_inputs_report_quantity_gap_instead_of_healthy_empty(self):
        summaries = []
        for replay_path in sorted(REPLAY_ROOT.glob("2026-*.json")):
            prior = json.loads(replay_path.read_text(encoding="utf-8"))
            market_inputs = json.loads(
                Path(prior["input_path"]).read_text(encoding="utf-8")
            )
            old_snapshot = prior["snapshot"]
            result = run_preclose_pipeline(
                market_inputs,
                config=PreclosePipelineConfig(
                    trade_date=prior["date"],
                    as_of=old_snapshot["as_of"],
                    generated_at=old_snapshot["generated_at"],
                    source_sha="r05-final-integration-replay",
                    run_id="r05-final-{}".format(prior["date"]),
                ),
            )
            daily = result["diagnostics"]["input_health"]["daily"]
            quantity = daily["quantity"]
            summaries.append({
                "date": prior["date"],
                "old_status": old_snapshot["status"],
                "new_status": result["status"],
                "daily_status": daily["status"],
                "quantity_required": quantity["required_count"],
                "quantity_available": quantity["available_count"],
                "quantity_coverage": quantity["coverage"],
                "quantity_pending": len(quantity["pending_codes"]),
            })
            self.assertGreater(quantity["required_count"], 0)
            self.assertGreater(len(quantity["pending_codes"]), 0)
            self.assertNotEqual(daily["status"], "verified")
            self.assertFalse(
                result["status"] == "empty" and daily["status"] == "verified"
            )
        self.assertEqual(len(summaries), 11)
        print("R05_FIXED_INPUT_REPLAY=" + json.dumps(
            summaries, ensure_ascii=False, sort_keys=True
        ))


if __name__ == "__main__":
    unittest.main()
