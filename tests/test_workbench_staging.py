import tempfile
import unittest
from pathlib import Path
from tests.test_stage_recommendation_evidence_pages import StageFixture, _bootstrap_from_html
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
