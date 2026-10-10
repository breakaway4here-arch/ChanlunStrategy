"""The browser's filtered cohort statistics match the published builder."""

import json
import math
import subprocess
import unittest
from pathlib import Path

from chanlun.selection_performance import aggregate_selection_performance


ROOT = Path(__file__).resolve().parents[1]


class SelectionPerformanceFrontendParityTests(unittest.TestCase):
    def test_six_horizons_and_filters_match_backend_aggregate(self):
        horizons = (1, 3, 5, 10, 20, 30)
        values = (10.0, -5.0, 0.0, None)
        observations = []
        for index, value in enumerate(values):
            strategies = ([{"strategy_key": "s1", "role": "formal",
                            "recommendation_scope": "formal_recommendation"}]
                          if index == 0 else
                          [{"strategy_key": "s1", "role": "formal",
                            "recommendation_scope": "published_observation"}]
                          if index == 1 else
                          [{"strategy_key": "s2", "role": "research",
                            "recommendation_scope": "published_observation"}])
            observations.append({
                "observation_id": "sample-{}".format(index),
                "instrument_id": "SH60000{}".format(index),
                "code": "60000{}".format(index), "name": "样本{}".format(index),
                "report_date": "2026-09-01" if index < 3 else "2026-09-02",
                "publication_ref": {"snapshot_id": "published"},
                "theme_refs": ([{"theme_id": "ai", "name": "AI"}] if index != 1 else []),
                "strategy_refs": strategies,
                "outcomes": {"t{}".format(h): {
                    "status": "ready" if value is not None else "price_basis_unverified",
                    "return_pct": value, "start_close": 100,
                    "end_close": 100 + value if value is not None else None,
                    "target_date": "2026-09-30",
                } for h in horizons},
            })
        dataset = {
            "schema_version": "selection-performance-v1", "dataset_id": "parity-test",
            "report_as_of": "2026-09-30", "evaluation_as_of": "2026-09-30T15:20:00+08:00",
            "horizons": list(horizons), "trading_dates": ["2026-09-01", "2026-09-02"],
            "observations": observations,
        }
        cases = [
            {}, {"theme_id": "ai"}, {"theme_id": "unrecorded"},
            {"strategy_key": "s1"},
            {"strategy_key": "s1", "role": "formal",
             "recommendation_scope": "formal_recommendation"},
            {"report_start": "2026-09-02"},
        ]
        script = """const fs=require('fs');
const ui=require('./chanlun/report_assets/selection-performance.js');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(input.cases.flatMap(f=>input.dataset.horizons.map(h=>{
 const v=ui.computeView(input.dataset,{horizon:h,reportStart:f.report_start||null,
  themeId:f.theme_id,strategyKey:f.strategy_key,
  role:f.role, recommendationScope:f.recommendation_scope});
 return v.summary;
}))));"""
        result = subprocess.run(
            ["node", "-e", script], input=json.dumps({"dataset": dataset, "cases": cases}),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(ROOT), check=True,
        )
        browser = json.loads(result.stdout)
        for case_index, filters in enumerate(cases):
            for horizon_index, horizon in enumerate(horizons):
                with self.subTest(filters=filters, horizon=horizon):
                    expected = aggregate_selection_performance(dataset, horizon=horizon, **filters)
                    actual = browser[case_index * len(horizons) + horizon_index]
                    for key in ("total_observations", "counts", "expected_results",
                                "unique_stocks", "report_dates"):
                        self.assertEqual(actual[key], expected[key])
                    for key in ("mean_return_pct", "median_return_pct", "positive_ratio_pct"):
                        if expected[key] is None:
                            self.assertIsNone(actual[key])
                        else:
                            self.assertTrue(math.isclose(actual[key], expected[key], abs_tol=1e-10))
                    for key in ("best_observations", "worst_observations"):
                        self.assertEqual([row["observation_id"] for row in actual[key]],
                                         [row["observation_id"] for row in expected[key]])


if __name__ == "__main__":
    unittest.main()
