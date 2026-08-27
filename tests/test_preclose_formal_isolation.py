import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from chanlun.preclose_contract import (
    build_preclose_snapshot,
    normalized_formal_summary,
)
from chanlun.preclose_pipeline import (
    PreclosePipelineComponents,
    PreclosePipelineConfig,
    run_preclose_pipeline,
)


def _sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value):
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _formal_fixture():
    def candidate(code, action, version):
        return {
            "code": code,
            "name": code,
            "action": action,
            "strategy": "daily_fusion",
            "version": version,
            "decision_engine_v1": {"decision_code": "recommend"},
        }

    return {
        "picks_pure": [candidate("600001", "仅观察", "pure-v1")],
        "picks_fusion": [candidate("300998", "可上车", "fusion-v1")],
        "h4_t3_pool": {
            "model_version": "h4-v1",
            "candidates": [candidate("600002", "仅观察", "h4-v1")],
        },
        "next_day_boom": {
            "version": "acc-v1",
            "candidates": [candidate("002328", "仅观察", "acc-v1")],
        },
    }


class PrecloseFormalIsolationTests(unittest.TestCase):
    def test_real_pipeline_operates_on_copies_without_mutating_formal_summary(self):
        from tests.test_preclose_pipeline import _components, _config, _market_inputs

        formal = _formal_fixture()
        before = normalized_formal_summary(formal)
        before_hash = _sha256_json(before)

        snapshot = run_preclose_pipeline(
            _market_inputs(),
            config=_config(run_id="formal-isolation"),
            components=_components([]),
        )

        self.assertEqual(snapshot["status"], "available")
        self.assertEqual(normalized_formal_summary(formal), before)
        self.assertEqual(_sha256_json(normalized_formal_summary(formal)), before_hash)

    def test_success_failure_timeout_and_not_run_leave_formal_outputs_unchanged(self):
        for state in ("success", "failure", "timeout", "not_run"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                sentinels = [
                    root / "market_history.sqlite",
                    root / "recommendation_ledger.jsonl",
                    root / "docs" / "data" / "2026-08-27.json",
                    root / "docs" / "index.html",
                    root / "docs" / "data" / "comparison-index.json",
                ]
                for index, path in enumerate(sentinels):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("formal-sentinel-{}".format(index), encoding="utf-8")
                before_files = {
                    str(path): (_sha256_file(path), path.stat().st_mtime_ns)
                    for path in sentinels
                }
                formal = _formal_fixture()
                baseline = normalized_formal_summary(formal)
                baseline_hash = _sha256_json(baseline)

                if state != "not_run":
                    cache = root / ".cache" / "chanlun" / "preclose" / "2026-08-27"
                    cache.mkdir(parents=True)
                    status = {
                        "success": "available",
                        "failure": "failed",
                        "timeout": "deadline_exceeded",
                    }[state]
                    pools = {
                        "main": ([{
                            "code": "300998",
                            "name": "宁波方正",
                            "reference_price": 26.86,
                        }] if state == "success" else []),
                        "h4_t3": [],
                        "acceleration": [],
                    }
                    snapshot = build_preclose_snapshot(
                        trade_date="2026-08-27",
                        as_of="2026-08-27T14:47:00+08:00",
                        generated_at="2026-08-27T14:48:30+08:00",
                        pools=pools,
                        source_sha="6412624",
                        status=status,
                        diagnostics={"state": state},
                    )
                    (cache / "snapshot.json").write_text(
                        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
                    )
                    (cache / "diagnostics.json").write_text(
                        json.dumps({"state": state}), encoding="utf-8"
                    )

                after = normalized_formal_summary(formal)
                self.assertEqual(after, baseline)
                self.assertEqual(_sha256_json(after), baseline_hash)
                self.assertEqual(
                    {
                        str(path): (_sha256_file(path), path.stat().st_mtime_ns)
                        for path in sentinels
                    },
                    before_files,
                )
                generated = {
                    str(path.relative_to(root))
                    for path in root.rglob("*")
                    if path.is_file() and path not in sentinels
                }
                expected = set()
                if state != "not_run":
                    expected = {
                        ".cache/chanlun/preclose/2026-08-27/snapshot.json",
                        ".cache/chanlun/preclose/2026-08-27/diagnostics.json",
                    }
                self.assertEqual(generated, expected)

    def test_normalized_formal_summary_preserves_pool_order_actions_and_versions(self):
        summary = normalized_formal_summary(_formal_fixture())

        self.assertEqual(list(summary), [
            "picks_pure", "picks_fusion", "h4_t3", "acceleration"
        ])
        self.assertEqual(summary["picks_fusion"][0]["code"], "300998")
        self.assertEqual(summary["picks_fusion"][0]["action"], "可上车")
        self.assertEqual(summary["h4_t3"][0]["version"], "h4-v1")
        self.assertEqual(summary["acceleration"][0]["code"], "002328")


if __name__ == "__main__":
    unittest.main()
