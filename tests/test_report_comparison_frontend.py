"""Static contract tests for the report comparison frontend assets."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "chanlun" / "report_assets"


class ReportComparisonFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (ASSETS / "report-v2.js").read_text(encoding="utf-8")
        cls.css = (ASSETS / "report-v2.css").read_text(encoding="utf-8")
        cls.html = (ASSETS / "comparison.html").read_text(encoding="utf-8")

    def test_comparison_page_has_static_index_and_refresh_controls(self):
        self.assertIn("comparison-index.json", self.html)
        self.assertIn("刷新对比价", self.js)
        self.assertIn("comparisonApp", self.html)

    def test_comparison_page_uses_final_docs_compare_asset_paths(self):
        self.assertIn('href="../assets/report-v2.css"', self.html)
        self.assertIn('src="../assets/report-v2.js"', self.html)
        self.assertIn("pageMode: 'comparison'", self.html)
        self.assertIn("'../data/comparison-index.json'", self.js)

    def test_quote_request_is_click_only_post_contract(self):
        self.assertIn("/api/quotes/current", self.js)
        self.assertIn("method: 'POST'", self.js)
        self.assertIn("JSON.stringify({ codes: codes })", self.js)
        self.assertIn("addEventListener('click', requestCurrentQuotes)", self.js)
        self.assertNotIn("initComparisonPage();\n    requestCurrentQuotes();", self.js)

    def test_current_is_explicit_target_and_quote_state_is_invalidated(self):
        self.assertIn('<option value="current">当前</option>', self.js)
        self.assertIn("dates.length > 1 ? dates[dates.length - 2]", self.js)
        self.assertIn("targetDate === 'current'", self.js)
        self.assertIn("clearComparisonQuotes", self.js)
        self.assertIn("开始比对", self.js)
        self.assertIn("尚未刷新当前行情", self.js)

    def test_comparison_renders_actual_return_primary_and_missing_bucket(self):
        self.assertIn("实际涨跌", self.js)
        self.assertIn("沪深300", self.js)
        self.assertIn("超额收益", self.js)
        self.assertIn("缺失数据", self.js)
        self.assertIn("sourceDate > targetDate", self.js)

    def test_all_views_summary_and_complete_statistics_are_present(self):
        self.assertIn("全部榜单（去重）", self.js)
        self.assertIn("dedupeComparisonRows", self.js)
        for label in ("实际平均涨跌", "中位数", "上涨率", "最大涨幅", "最大跌幅", "有效", "缺失"):
            self.assertIn(label, self.js)
        self.assertIn("指数数据缺失", self.js)

    def test_chart_uses_shared_scale_and_one_benchmark_line(self):
        self.assertIn("comparison-chart", self.css)
        self.assertIn("comparison-chart-benchmark", self.css)
        self.assertIn("comparisonScale", self.js)
        self.assertIn("comparisonBenchmarkPosition", self.js)
        self.assertEqual(self.js.count('class="comparison-chart-benchmark'), 1)

    def test_report_home_mounts_click_to_refresh_yesterday_summary(self):
        self.assertIn("function initComparisonSummary", self.js)
        self.assertIn("section.id = 'comparisonSummary'", self.js)
        self.assertIn("initComparisonSummary();", self.js)

    def test_archived_report_resolves_root_comparison_paths(self):
        self.assertIn("function isArchiveReportPath(pathname)", self.js)
        self.assertIn("(?:\\/index\\.html)?$", self.js)
        self.assertIn("isArchiveReportPath(window.location && window.location.pathname)", self.js)
        self.assertIn("isArchiveReportPath(window.location.pathname)", self.js)
        self.assertIn("昨日榜单表现", self.js)
        self.assertIn("进入完整比对", self.js)
        self.assertIn("comparisonSummaryRefresh", self.js)
        self.assertIn("全部榜单（去重）", self.js)
        self.assertIn("尚未刷新当前行情", self.js)
        self.assertIn(".report-comparison-summary", self.css)

    def test_comparison_layout_is_desktop_master_detail_and_mobile_single_column(self):
        self.assertIn(".comparison-workspace", self.css)
        self.assertIn("grid-template-columns: minmax(260px, 30%) minmax(0, 70%)", self.css)
        self.assertIn("@media (max-width: 760px)", self.css)
        self.assertIn("grid-template-columns: 1fr", self.css)


if __name__ == "__main__":
    unittest.main()
