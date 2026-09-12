import base64
import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from chanlun import report_generator
from chanlun.report_generator import (
    CHART_LIBRARY_ASSET,
    CHART_LIBRARY_VERSION,
    _chart_library_integrity,
    _report_asset_version,
    _build_report_v2_html,
    copy_report_assets,
    refresh_report_chart_library_references,
)


ROOT = Path(__file__).resolve().parents[1]


class TestUiLoadingContract(unittest.TestCase):
    def test_chart_asset_is_fixed_local_version_and_published_copy_matches(self):
        source = ROOT / "chanlun" / "report_assets" / CHART_LIBRARY_ASSET
        published = ROOT / "docs" / "assets" / CHART_LIBRARY_ASSET
        self.assertEqual(source.read_bytes(), published.read_bytes())
        self.assertEqual(CHART_LIBRARY_VERSION, "5.4.3")
        digest = base64.b64encode(hashlib.sha256(source.read_bytes()).digest()).decode("ascii")
        self.assertEqual(_chart_library_integrity(), "sha256-" + digest)

    def test_generated_shell_does_not_block_dom_on_chart_library(self):
        bootstrap = '{"inlineReportData":{"date":"2026-09-11"}}'
        html = _build_report_v2_html("2026-09-11", bootstrap, asset_prefix="../", asset_version="a" * 12)
        self.assertNotIn("cdn.bootcdn.net/ajax/libs/echarts", html)
        self.assertIn("window.CHANLUN_CHART_LIBRARY", html)
        self.assertIn("../assets/echarts-5.4.3.min.js?v=" + "a" * 12, html)
        self.assertIn("assets/report-v2.js?v=" + "a" * 12, html)
        self.assertRegex(html, r'<script src="\.\./assets/report-v2\.js\?v=[0-9a-f]{12}" defer></script>')

    def test_required_chart_asset_missing_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            (source / "report-v2.css").write_text("css", encoding="utf-8")
            (source / "report-v2.js").write_text("js", encoding="utf-8")
            with mock.patch.object(
                report_generator, "_report_asset_source_dir", return_value=str(source)
            ):
                with self.assertRaises(FileNotFoundError):
                    _report_asset_version()
                with self.assertRaises(FileNotFoundError):
                    _chart_library_integrity()
                with self.assertRaises(FileNotFoundError):
                    copy_report_assets(str(Path(temp) / "output"))

    def test_existing_v2_shell_upgrade_preserves_bootstrap_bytes(self):
        bootstrap = '<script>window.CHANLUN_BOOTSTRAP={"sentinel":"保持不变"};</script>'
        html = (
            '<script defer src="https://cdn.bootcdn.net/ajax/libs/echarts/5.4.3/echarts.min.js"></script>\n'
            + bootstrap
            + '<script src="../assets/report-v2.js?v=old" defer></script>'
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            page = root / "2026-09-11" / "index.html"
            page.parent.mkdir(parents=True)
            page.write_text(html, encoding="utf-8")
            changed = refresh_report_chart_library_references(str(root), _report_asset_version())
            self.assertEqual([Path(item).resolve() for item in changed], [page.resolve()])
            upgraded = page.read_text(encoding="utf-8")
            second_changed = refresh_report_chart_library_references(str(root), _report_asset_version())
            rerun = page.read_text(encoding="utf-8")
        self.assertNotIn("cdn.bootcdn.net/ajax/libs/echarts", upgraded)
        self.assertIn(bootstrap, upgraded)
        self.assertIn("../assets/echarts-5.4.3.min.js", upgraded)
        self.assertIn("window.CHANLUN_CHART_LIBRARY", upgraded)
        self.assertIn('src="../assets/report-v2.js?v=old"', upgraded)
        self.assertEqual(second_changed, [])
        self.assertEqual(upgraded, rerun)


if __name__ == "__main__":
    unittest.main()
