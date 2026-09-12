import tempfile
import unittest
from pathlib import Path
import subprocess
import json
from tests.test_stage_recommendation_evidence_pages import (
    StageFixture,
    _bootstrap_from_html,
    _html_for,
)
from scripts.stage_recommendation_evidence_pages import stage_recommendation_evidence_pages


class WorkbenchStaging(unittest.TestCase):
    def test_staged_workbench_is_derived_without_changing_daily_facts(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = StageFixture(td)
            before = (fixture.docs / 'data/2026-08-28.json').read_bytes()
            target = Path(td) / 'preview'
            stage_recommendation_evidence_pages(fixture.root, fixture.docs, '2026-08-28',
                                               stage_root=target, source_assets_dir=fixture.source_assets)
            payload = _bootstrap_from_html((target / 'index.html').read_text())
            self.assertEqual(payload.get('decisionWorkbench', {}).get('schema_version'), 'decision-workbench-v1')
            self.assertEqual(before, (fixture.docs / 'data/2026-08-28.json').read_bytes())

    def test_staged_workbench_uses_nearest_previous_daily_projection(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = StageFixture(td)
            basis = {
                "adjustment": "qfq",
                "factor_vs_raw": 1.0,
                "source": "fixture.price_basis",
            }
            identity = {
                "strategy": "daily_fusion",
                "version": "daily-fusion-close-v1",
                "source_pool": "picks_fusion",
                "entry_mode": "immediate_close",
                "price_basis": basis,
            }
            current = dict(fixture.data)
            current.update({
                "data_quality": {
                    "as_of": "2026-08-28T15:20:00+08:00",
                    "is_official": True,
                    "bar_state": "closed",
                    "market_status": "verified",
                },
                "selection_input_health": {
                    "formal": {
                        "status": "verified",
                        "formal_actions_allowed": True,
                    },
                },
                "strategy_scorecards": {
                    "formal": [{
                        "strategy": "daily_fusion",
                        "version": "daily-fusion-close-v1",
                        "source_pool": "picks_fusion",
                        "comparison_identity": identity,
                        "latest_report_date": "2026-08-28",
                    }],
                },
            })
            previous = dict(current)
            previous["date"] = "2026-08-27"
            previous["data_quality"] = dict(current["data_quality"])
            previous["data_quality"]["as_of"] = "2026-08-27T15:20:00+08:00"
            previous["strategy_scorecards"] = {
                "formal": [{
                    "strategy": "daily_fusion",
                    "version": "daily-fusion-close-v1",
                    "source_pool": "picks_fusion",
                    "comparison_identity": identity,
                    "latest_report_date": "2026-08-27",
                }],
            }

            data_dir = fixture.docs / "data"
            (data_dir / "2026-08-27.json").write_text(
                json.dumps(previous, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (data_dir / "2026-08-28.json").write_text(
                json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (fixture.docs / "index.html").write_text(
                _html_for(current, archive=False), encoding="utf-8"
            )
            (fixture.docs / "2026-08-28" / "index.html").write_text(
                _html_for(current, archive=True), encoding="utf-8"
            )
            subprocess.run(["git", "add", "-A"], cwd=fixture.root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "previous report fixture"],
                cwd=fixture.root,
                check=True,
            )

            result = stage_recommendation_evidence_pages(
                fixture.root,
                fixture.docs,
                "2026-08-28",
                stage_root=Path(td) / "preview",
                source_assets_dir=fixture.source_assets,
            )
            payload = _bootstrap_from_html(
                (Path(result["stage_dir"]) / "index.html").read_text(
                    encoding="utf-8"
                )
            )
            changes = payload["decisionWorkbench"]["changes"]
            self.assertEqual(result["previous_report_date"], "2026-08-27")
            self.assertEqual(changes["previous_report_date"], "2026-08-27")
            self.assertEqual(changes["status"], "available")
            self.assertEqual(changes["added"], [])
            self.assertEqual(changes["removed"], [])
