"""RED contracts for the recommendation evidence responsive surface.

These contracts describe the next layout/accessibility boundary without
claiming screenshot acceptance.  They deliberately inspect the source CSS
and the HTML returned by the Node VM frontend harness so implementation can
turn them green before real 1440/1366/390 viewport review.
"""

import re
import unittest

from tests.test_auxiliary_frontend import CSS, JS, _assert_node_contract


def _media_bodies(css, max_width):
    """Return CSS bodies for every media query containing ``max_width``."""

    pattern = re.compile(
        r"@media[^\{]*max-width:\s*" + re.escape(max_width) + r"[^\{]*\{",
        re.IGNORECASE,
    )
    starts = [match.end() for match in pattern.finditer(css)]
    bodies = []
    for start in starts:
        next_media = css.find("@media", start)
        end = len(css) if next_media < 0 else next_media
        bodies.append(css[start:end])
    return bodies


class TestRecommendationEvidenceResponsiveContract(unittest.TestCase):
    def test_evidence_layout_has_no_page_level_horizontal_overflow_contract(self):
        page_rules = re.search(r"html,\s*body\s*\{(?P<body>[^}]*)\}", CSS, re.DOTALL)
        self.assertIsNotNone(page_rules, "page-level html/body rule is missing")
        self.assertRegex(
            page_rules.group("body"),
            r"overflow-x:\s*(?:hidden|clip)\s*;",
            "the page itself needs an explicit horizontal-overflow guard",
        )

        shell_rules = re.search(r"\.report-shell\s*\{(?P<body>[^}]*)\}", CSS, re.DOTALL)
        self.assertIsNotNone(shell_rules, "report shell rule is missing")
        self.assertRegex(
            shell_rules.group("body"),
            r"min-width:\s*0\s*;",
            "the report shell must be shrinkable inside a narrow viewport",
        )
        self.assertNotRegex(
            shell_rules.group("body"),
            r"overflow-x:\s*(?:auto|scroll)\s*;",
            "page-level scrolling must not own the comparison table overflow",
        )

    def test_1366_keeps_two_columns_and_comparison_owns_its_scroll(self):
        workspace_rules = re.search(
            r"\.today-workspace\s+\.workspace-body\s*\{(?P<body>[^}]*)\}",
            CSS,
            re.DOTALL,
        )
        self.assertIsNotNone(workspace_rules, "today workspace grid rule is missing")
        self.assertRegex(
            workspace_rules.group("body"),
            r"grid-template-columns:\s*minmax\([^;]+\)\s+minmax\(0,\s*1fr\)\s*;",
            "1366px must retain a shrinkable two-column workspace",
        )

        table_rules = re.search(
            r"\.candidate-evidence-table-wrap\s*\{(?P<body>[^}]*)\}",
            CSS,
            re.DOTALL,
        )
        self.assertIsNotNone(table_rules, "comparison table wrapper rule is missing")
        self.assertRegex(
            table_rules.group("body"),
            r"overflow-x:\s*auto\s*;",
            "the wide comparison table must own its horizontal scroll region",
        )
        self.assertRegex(
            CSS,
            re.compile(
                r"\.candidate-evidence-table\s+th:first-child\s*\{[^}]*"
                r"position:\s*sticky\s*;[^}]*left:\s*0\s*;",
                re.DOTALL,
            ),
            "the comparison table needs a pinned first column while scrolling",
        )

    def test_390_stacks_evidence_cards_and_chart_lane(self):
        mobile = "\n".join(_media_bodies(CSS, "390px"))
        self.assertTrue(mobile, "390px media query is missing")
        self.assertRegex(
            mobile,
            re.compile(
                r"\.candidate-evidence-table-wrap\s*\{[^}]*display:\s*none\s*;",
                re.DOTALL,
            ),
            "390px comparison must switch away from the wide table",
        )
        self.assertRegex(
            mobile,
            re.compile(
                r"\.candidate-evidence-ticket-list\s*\{[^}]*display:\s*grid\s*;",
                re.DOTALL,
            ),
            "390px comparison must render one evidence card per ticket",
        )
        for selector in (
            r"\.detail-price-grid",
            r"\.recommendation-evidence-facts",
            r"\.recommendation-score-split",
            r"\.recommendation-condition-grid",
            r"\.chart-signal-list",
        ):
            self.assertRegex(
                mobile,
                re.compile(
                    selector + r"\s*\{[^}]*grid-template-columns:\s*1fr\s*;",
                    re.DOTALL,
                ),
                "390px detail/chart lane is not explicitly single-column: " + selector,
            )

    def test_mobile_drawer_close_stays_in_sticky_header_without_covering_content(self):
        shell_start = JS.index("function buildAppShell")
        shell_end = JS.index("function getReportDataStatus", shell_start)
        shell = JS[shell_start:shell_end]
        panel_start = shell.index('id="mobileDrawerPanel"')
        toolbar_start = shell.index('class="mobile-drawer-toolbar"', panel_start)
        toolbar_end = shell.index("</div>", toolbar_start)
        close_start = shell.index('id="mobileDrawerClose"')
        self.assertLess(toolbar_start, close_start, "drawer close must live inside its sticky header")
        self.assertLess(close_start, toolbar_end, "drawer close must not float over drawer content")

        close_rules = re.search(
            r"\.mobile-drawer-floating-close\s*\{(?P<body>[^}]*)\}",
            CSS,
            re.DOTALL,
        )
        self.assertIsNotNone(close_rules, "drawer close style is missing")
        self.assertRegex(close_rules.group("body"), r"position:\s*static\s*;")
        self.assertNotRegex(close_rules.group("body"), r"position:\s*(?:fixed|absolute)\s*;")

    def test_comparison_and_detail_have_keyboard_and_aria_labels(self):
        _assert_node_contract(
            self,
            "({ render: renderCandidateEvidenceComparison, state: state })",
            r"""
globalThis.__auxTest.state.data = { date: '2026-08-28' };
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-28', recommendationEvidence: {
  schema_version: 1,
  report_date: '2026-08-28',
  views: { main: [{
    code: '600001',
    summary: { status: 'available', source: 'workspace', name: '证据股', sector: '工业', formal_action: '观察' },
    decision_score: { status: 'available', source: 'decision', score: 62, components: {} },
    rank_evidence: { status: 'available', source: 'rank', view_rank: 1, opportunity_score: 88 },
    price_evidence: { status: 'missing', source: 'prices' },
    daily_structure: { status: 'missing', source: 'daily' },
    sublevel_30m: { status: 'missing', source: '30m' },
    volume_and_capital: { status: 'missing', source: 'volume' },
    market_and_sector: { status: 'missing', source: 'sector' },
    risk_and_next: { status: 'missing', source: 'risk' },
    historical_validation: { status: 'missing', source: 'history' }
  }] }
} };
const html = globalThis.__auxTest.render('main');
assert(html.includes('role="region"'), 'comparison scroll region has no landmark role');
assert(html.includes('tabindex="0"'), 'comparison scroll region is not keyboard focusable');
assert(html.includes('aria-label="候选证据比较表"'), 'comparison scroll region has no accessible label');
""",
        )

        module_start = JS.index("function renderRecommendationEvidenceModule")
        module_end = JS.index("function evidencePositiveNumber", module_start)
        module_source = JS[module_start:module_end]
        self.assertIn("aria-labelledby", module_source)
        self.assertIn("evidence-module-", module_source)

        switch_start = JS.index("function renderChartLayerSwitcher")
        switch_end = JS.index("function renderChart(raw", switch_start)
        switch_source = JS[switch_start:switch_end]
        self.assertIn("aria-pressed", switch_source)
        self.assertIn("data-chart-layer", switch_source)

    def test_psy12_shadow_panel_stacks_single_column_on_390(self):
        mobile = "\n".join(_media_bodies(CSS, "390px"))
        self.assertRegex(
            mobile,
            re.compile(
                r"\.psy12-shadow-grid\s*\{[^}]*"
                r"grid-template-columns:\s*1fr\s*;",
                re.DOTALL,
            ),
            "PSY12 shadow subpanel is not explicitly single-column at 390px",
        )
        self.assertRegex(
            mobile,
            re.compile(
                r"\.market-temperature-card\s+\.psy12-shadow-card\s*\{[^}]*"
                r"min-width:\s*0\s*;",
                re.DOTALL,
            ),
            "nested PSY12 panel has no narrow-viewport overflow guard",
        )


if __name__ == "__main__":
    unittest.main()
