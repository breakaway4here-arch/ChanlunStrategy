import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReportSentimentLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.asset_js = (ROOT / "chanlun/report_assets/report-v2.js").read_text(encoding="utf-8")
        cls.asset_css = (ROOT / "chanlun/report_assets/report-v2.css").read_text(encoding="utf-8")

    def test_sentiment_card_uses_split_snapshot_and_trend_layout(self):
        self.assertIn('class="market-temp-layout"', self.asset_js)
        self.assertIn('class="market-temp-snapshot"', self.asset_js)
        self.assertIn('class="market-temp-trend"', self.asset_js)
        self.assertIn(".research-validation-stack", self.asset_css)
        self.assertIn(".supporting-decisions-stack", self.asset_css)
        self.assertNotIn(".aux-grid.decision-grid {\n  display: grid;\n  grid-template-columns: repeat(4", self.asset_css)
        self.assertIn(
            "grid-template-columns: minmax(210px, 30%) minmax(0, 70%);",
            self.asset_css,
        )
        self.assertIn(
            ".market-temp-snapshot .metric-pair-grid {\n  grid-template-columns: 1fr;",
            self.asset_css,
        )
        self.assertIn(
            ".market-temp-snapshot .metric-pair {\n  display: flex;",
            self.asset_css,
        )
        self.assertIn(
            ".research-validation-stack > .decision-card,\n.supporting-decisions-stack > .decision-card {\n  grid-column: 1 / -1;",
            self.asset_css,
        )

    def test_sentiment_card_expands_on_tablet_and_stacks_on_mobile(self):
        tablet_css = self.asset_css.split("@media (max-width: 1180px)", 1)[1]
        tablet_css = tablet_css.split("@media (max-width: 760px)", 1)[0]
        self.assertIn(".today-workspace", tablet_css)
        self.assertNotIn("grid-template-columns: repeat(3, minmax(0, 1fr));", tablet_css)

        mobile_css = self.asset_css.rsplit("@media (max-width: 760px)", 1)[1]
        self.assertIn(".market-temp-layout {\n    grid-template-columns: 1fr;", mobile_css)
        self.assertIn(".market-sentiment-chart {\n    height: 240px;", mobile_css)
        self.assertIn(
            ".market-temp-snapshot .metric-pair-grid {\n    grid-template-columns: repeat(2, minmax(0, 1fr));",
            mobile_css,
        )
        self.assertIn(".primary-mode-tabs", mobile_css)
        self.assertIn(".today-workspace", mobile_css)

    def test_mobile_first_screen_avoids_direction_scroller_and_three_row_header(self):
        mobile_css = self.asset_css.rsplit("@media (max-width: 760px)", 1)[1]
        self.assertIn(
            ".compact-header-facts {\n    grid-template-columns: repeat(3, minmax(0, 1fr));",
            mobile_css,
        )
        self.assertIn(
            ".direction-quick-list {\n    grid-column: 1 / -1;\n    grid-row: 2;\n    display: grid;",
            mobile_css,
        )
        self.assertIn("overflow: visible;", mobile_css)

    def test_psy12_shadow_evidence_has_a_distinct_research_layout(self):
        self.assertIn('class="psy12-shadow-notice"', self.asset_js)
        self.assertIn('class="psy12-shadow-grid"', self.asset_js)
        self.assertIn(".psy12-shadow-card", self.asset_css)
        self.assertIn(".psy12-shadow-grid", self.asset_css)
        self.assertIn(".psy12-shadow-notice", self.asset_css)

        mobile_css = self.asset_css.rsplit("@media (max-width: 760px)", 1)[1]
        self.assertIn(
            ".psy12-shadow-grid {\n    grid-template-columns: 1fr;",
            mobile_css,
        )


if __name__ == "__main__":
    unittest.main()
