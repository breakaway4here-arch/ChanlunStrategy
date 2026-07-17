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
        self.assertIn(".market-temperature-card {\n  grid-column: span 2;", self.asset_css)
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

    def test_sentiment_card_expands_on_tablet_and_stacks_on_mobile(self):
        tablet_css = self.asset_css.split("@media (max-width: 1180px)", 1)[1]
        tablet_css = tablet_css.split("@media (max-width: 760px)", 1)[0]
        self.assertIn(".market-temperature-card {\n    grid-column: span 3;", tablet_css)

        mobile_css = self.asset_css.rsplit("@media (max-width: 760px)", 1)[1]
        self.assertIn(".market-temp-layout {\n    grid-template-columns: 1fr;", mobile_css)
        self.assertIn(".market-sentiment-chart {\n    height: 240px;", mobile_css)
        self.assertIn(
            ".market-temp-snapshot .metric-pair-grid {\n    grid-template-columns: repeat(2, minmax(0, 1fr));",
            mobile_css,
        )


if __name__ == "__main__":
    unittest.main()
