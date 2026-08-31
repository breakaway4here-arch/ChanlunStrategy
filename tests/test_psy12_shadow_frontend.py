"""RED contracts for the PSY12 shadow panel in the market-temperature card.

These tests intentionally describe the next display contract without changing
the renderer.  The panel is research-only: its twelve-day window, independent
twenty-day audit, and non-promotion boundary must remain explicit and safely
escaped at every viewport.
"""

import re
import unittest

from tests.test_auxiliary_frontend import CSS, _assert_node_contract


def _valid_market_fixture(audit=None):
    """Return a compact JS fixture shared by the renderer contracts."""

    audit_expr = "undefined" if audit is None else audit
    return r"""
const audit = AUDIT_EXPR;
const base = {
  date: '2026-08-28',
  market_sentiment: {
    date: '2026-08-28',
    score: 61,
    label: '偏强',
    version: 'v2',
    coverage: 1,
    insufficient: false,
    components: {
      breadth: 41,
      index: 52,
      limit_ecology: 63,
      turnover: 74,
      trend: 85
    },
    evidence: {
      breadth: { available: true },
      index: { available: true },
      limit_ecology: { available: true },
      turnover: { available: true },
      trend: { available: true }
    }
  },
  psy12: {
    status: 'available',
    score: 50,
    up_days: 6,
    valid_days: 12,
    window: 12,
    start_date: '2026-08-11',
    end_date: '2026-08-26',
    daily_directions: []
  },
  psy12_shadow: {
    schema_version: 1,
    mode: 'shadow',
    affects_production: false,
    promotion_eligible: false,
    promotion_requires_new_authorization: true,
    status: 'available',
    formal_score: 61,
    shadow_score_with_psy12: 61,
    delta_vs_formal: 0,
    formal_label: '偏强',
    shadow_label: '偏强',
    weights: { psy12: 0.1 }
  },
  psy12_shadow_audit: audit
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: {},
    market_sentiment: {
      formal_contract: {
        status: 'available',
        source: 'daily.market_sentiment',
        as_of: '2026-08-28',
        score: 61,
        label: '偏强',
        version: 'v2',
        coverage: 1,
        components: {
          breadth: 41,
          index: 52,
          limit_ecology: 63,
          turnover: 74,
          trend: 85
        },
        evidence: {
          breadth: { available: true },
          index: { available: true },
          limit_ecology: { available: true },
          turnover: { available: true },
          trend: { available: true }
        }
      },
      psy12_shadow_audit: audit
    }
  }
};
""".replace("AUDIT_EXPR", audit_expr)


def _audit_literal(**overrides):
    values = {
        "schema_version": 1,
        "mode": "psy12_shadow_audit",
        "status": "insufficient_observation_days",
        "reason": None,
        "as_of_date": "2026-08-28",
        "required_days": 20,
        "valid_days": 7,
        "stored_complete_days": 7,
        "recomputable_days": 12,
        "complete_days": 7,
        "missing_days": 5,
        "mismatch_days": 0,
        "affects_production": False,
        "promotion_eligible": False,
        "promotion_requires_new_authorization": True,
    }
    values.update(overrides)
    # JSON is valid JavaScript and keeps the fixture free of hand-built HTML.
    import json

    return json.dumps(values, ensure_ascii=False)


class TestPsy12ShadowFrontend(unittest.TestCase):
    def test_psy12_is_nested_in_market_temperature_and_not_a_research_sibling(self):
        fixture = _valid_market_fixture(audit=_audit_literal())
        _assert_node_contract(
            self,
            "({ market: renderMarketTemperatureCard, stacks: buildAuxiliaryStacks })",
            fixture
            + r"""
const market = globalThis.__auxTest.market(base);
const marketStart = market.indexOf('<section class="decision-card market-temperature-card"');
const marketEnd = market.lastIndexOf('</section>');
assert(marketStart >= 0 && marketEnd > marketStart, 'market-temperature card missing');
assert(market.indexOf('psy12-shadow-card', marketStart) > marketStart, 'PSY12 shadow panel missing');
assert(market.indexOf('psy12-shadow-card', marketStart) < marketEnd, 'PSY12 shadow panel is not nested');

const research = globalThis.__auxTest.stacks(base).research;
const shadowMatches = research.match(/psy12-shadow-card/g) || [];
assert(shadowMatches.length === 1, 'PSY12 shadow card remained as a duplicate sibling');
const researchStart = research.indexOf('<section class="decision-card market-temperature-card"');
const nestedStart = research.indexOf('psy12-shadow-card', researchStart);
let depth = 0;
let researchEnd = -1;
for (let cursor = researchStart; cursor >= 0 && cursor < research.length;) {
  const open = research.indexOf('<section', cursor);
  const close = research.indexOf('</section>', cursor);
  if (close < 0) break;
  if (open >= 0 && open < close) {
    depth += 1;
    cursor = open + 8;
  } else {
    depth -= 1;
    cursor = close + 10;
    if (depth === 0) {
      researchEnd = close;
      break;
    }
  }
}
assert(nestedStart > researchStart && nestedStart < researchEnd, 'PSY12 shadow card is a research sibling');
""",
        )

    def test_psy12_window_and_stored_complete_audit_progress_are_distinct(self):
        collecting = _audit_literal(
            status="insufficient_observation_days",
            valid_days=7,
            stored_complete_days=7,
            recomputable_days=12,
        )
        complete = _audit_literal(
            status="ready_for_manual_review",
            valid_days=20,
            stored_complete_days=20,
            recomputable_days=20,
            complete_days=20,
            missing_days=0,
        )
        fixture = _valid_market_fixture(audit="AUDIT")
        _assert_node_contract(
            self,
            "({ market: renderMarketTemperatureCard })",
            fixture.replace("AUDIT", collecting)
            + r"""
const collectingHtml = globalThis.__auxTest.market(base);
assert(collectingHtml.includes('6 / 12'), 'PSY12 twelve-day window is missing');
assert(collectingHtml.includes('影子评测进度'), 'independent audit progress label is missing');
assert(collectingHtml.includes('7 / 20'), 'stored-complete audit progress is missing');
assert(!collectingHtml.includes('6 / 20'), 'PSY12 window was reused as audit progress');

const completeBase = Object.assign({}, base, { psy12_shadow_audit: COMPLETE_AUDIT });
window.CHANLUN_BOOTSTRAP.recommendationEvidence.market_sentiment.psy12_shadow_audit = COMPLETE_AUDIT;
const completeHtml = globalThis.__auxTest.market(completeBase);
assert(completeHtml.includes('6 / 12'), 'complete audit hid the PSY12 window');
assert(completeHtml.includes('20 / 20'), 'complete audit progress is missing');
assert(completeHtml.includes('仍需新授权'), 'twenty complete days implied automatic promotion');
""".replace("COMPLETE_AUDIT", complete),
        )

    def test_psy12_shadow_panel_discloses_ten_percent_weighted_result(self):
        fixture = _valid_market_fixture(audit=_audit_literal())
        _assert_node_contract(
            self,
            "({ market: renderMarketTemperatureCard })",
            fixture
            + r"""
const html = globalThis.__auxTest.market(base);
assert(html.includes('10%'), 'PSY12 影子权重没有明确展示');
assert(html.includes('加入 10% 后') || html.includes('加入10%后'),
  'PSY12 加权后的影子结果没有按合同命名');
assert(html.includes('影子分') && html.includes('差值'),
  '10%影子结果缺少加权分或与正式分的差值');
""",
        )

    def test_missing_or_invalid_psy12_weight_hides_weighted_result(self):
        fixture = _valid_market_fixture(audit=_audit_literal())
        _assert_node_contract(
            self,
            "({ market: renderMarketTemperatureCard })",
            fixture
            + r"""
[
  {},
  { weights: {} },
  { weights: { psy12: 0.2 } },
  { weights: { psy12: '0.1' } }
].forEach(function (override) {
  const invalidShadow = Object.assign({}, base.psy12_shadow, override);
  if (!Object.prototype.hasOwnProperty.call(override, 'weights')) {
    delete invalidShadow.weights;
  }
  const html = globalThis.__auxTest.market(Object.assign({}, base, {
    psy12_shadow: invalidShadow
  }));
  assert(html.includes('影子权重不可验证'), '缺失或异常影子权重没有 fail-closed');
  assert(!html.includes('加入 10% 后') && !html.includes('加入10%后'),
    '异常权重仍展示了10%加权结果');
  assert(!html.includes('影子分</span><strong>61'),
    '异常权重仍泄漏加权影子分');
});
""",
        )

    def test_missing_audit_progress_is_explicit_and_never_inferred_from_psy12(self):
        fixture = _valid_market_fixture()
        body = (
            fixture
            + r"""
const html = globalThis.__auxTest.market(base);
assert(html.includes('6 / 12'), 'PSY12 window evidence disappeared');
assert(html.includes('影子评测进度未随本期报告提供'), 'missing audit state is not explicit');
assert(!html.includes('0 / 20'), 'missing audit was fabricated as zero progress');
assert(!html.includes('6 / 20'), 'PSY12 twelve-day window was used as audit progress');

const missingAudit = MISSING_AUDIT;
window.CHANLUN_BOOTSTRAP.recommendationEvidence.market_sentiment.psy12_shadow_audit = missingAudit;
const missingHtml = globalThis.__auxTest.market(Object.assign({}, base, { psy12_shadow_audit: missingAudit }));
assert(missingHtml.includes('影子评测进度未随本期报告提供'), 'status=missing audit fabricated progress');
assert(!missingHtml.includes('0 / 20'), 'status=missing audit rendered a fake zero-day progress');
"""
        ).replace(
            "MISSING_AUDIT",
            _audit_literal(
                status="missing",
                reason="historical_reports_not_mapping",
                valid_days=0,
                stored_complete_days=0,
                recomputable_days=0,
                complete_days=0,
                missing_days=0,
            ),
        )
        _assert_node_contract(
            self,
            "({ market: renderMarketTemperatureCard })",
            body,
        )

    def test_shadow_and_audit_boundaries_cannot_override_formal_temperature(self):
        extreme = _audit_literal(
            status="ready_for_manual_review",
            valid_days=20,
            stored_complete_days=20,
            recomputable_days=20,
            complete_days=20,
            missing_days=0,
            affects_production=True,
            promotion_eligible=True,
            promotion_requires_new_authorization=False,
        )
        fixture = _valid_market_fixture(audit="AUDIT")
        _assert_node_contract(
            self,
            "({ market: renderMarketTemperatureCard, temperature: buildMarketTemperature })",
            fixture.replace("AUDIT", extreme)
            + r"""
base.psy12_shadow.shadow_score_with_psy12 = 999;
base.psy12_shadow.shadow_label = '极强';
const temperature = globalThis.__auxTest.temperature(base);
assert(temperature.score === 61, 'shadow score replaced formal market temperature');
assert(temperature.label === '偏强', 'shadow label replaced formal market label');
assert(temperature.components.breadth_score === 41, 'shadow altered formal breadth component');
assert(temperature.components.index_score === 52, 'shadow altered formal index component');
assert(temperature.components.limit_score === 63, 'shadow altered formal limit component');
assert(temperature.components.volume_score === 74, 'shadow altered formal volume component');
assert(temperature.components.trend_score === 85, 'shadow altered formal trend component');

const html = globalThis.__auxTest.market(base);
assert(html.includes('61 &#47; 100'), 'formal score is not rendered with escaped metric text');
assert(html.includes('偏强'), 'formal label is not rendered');
assert(html.includes('affects_production=false'), 'production isolation boundary is not explicit');
assert(html.includes('promotion_eligible=false'), 'promotion boundary is not explicit');
assert(html.includes('仍需新授权'), 'new authorization boundary is not explicit');
assert(!html.includes('affects_production=true'), 'unsafe production flag leaked into the UI');
assert(!html.includes('promotion_eligible=true'), 'unsafe promotion flag leaked into the UI');
""",
        )

    def test_incomplete_raw_sentiment_cannot_bypass_formal_projection_contract(self):
        _assert_node_contract(
            self,
            "({ temperature: buildMarketTemperature })",
            r"""
const report = {
  date: '2026-08-28',
  market_sentiment: { score: 62, label: '偏强' }
};
window.CHANLUN_BOOTSTRAP = {
  pageDate: '2026-08-28',
  recommendationEvidence: {
    schema_version: 1,
    report_date: '2026-08-28',
    views: {},
    market_sentiment: {
      formal_contract: {
        status: 'available',
        source: 'daily.market_sentiment',
        as_of: '2026-08-28',
        score: 62,
        label: '偏强',
        coverage: null,
        components: {},
        evidence: {}
      }
    }
  }
};
const temperature = globalThis.__auxTest.temperature(report);
assert(temperature.score === null, 'incomplete raw sentiment bypassed the formal projection');
assert(temperature.insufficient === true, 'incomplete formal sentiment looked available');
assert(temperature.label === '数据不足', 'incomplete formal sentiment kept a formal label');
""",
        )

    def test_complete_legacy_raw_sentiment_remains_available_without_projection(self):
        _assert_node_contract(
            self,
            "({ temperature: buildMarketTemperature })",
            r"""
const report = {
  date: '2026-08-27',
  market_sentiment: {
    date: '2026-08-27',
    score: 63,
    label: '偏强',
    version: 'v2',
    coverage: 1,
    insufficient: false,
    components: {
      breadth: 41,
      index: 52,
      limit_ecology: 63,
      turnover: 74,
      trend: 85
    },
    evidence: {
      breadth: { available: true },
      index: { available: true },
      limit_ecology: { available: true },
      turnover: { available: true },
      trend: { available: true }
    }
  }
};
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-27' };
const temperature = globalThis.__auxTest.temperature(report);
assert(temperature.score === 63, 'complete legacy formal sentiment was discarded');
assert(temperature.label === '偏强', 'complete legacy formal label was discarded');
assert(temperature.insufficient === false, 'complete legacy formal sentiment was degraded');
""",
        )

    def test_unavailable_component_requires_null_value_in_legacy_contract(self):
        _assert_node_contract(
            self,
            "({ temperature: buildMarketTemperature })",
            r"""
const report = {
  date: '2026-08-27',
  market_sentiment: {
    date: '2026-08-27',
    score: 63,
    label: '偏强',
    version: 'v2',
    coverage: 0.8,
    insufficient: false,
    components: {
      breadth: null,
      index: 52,
      limit_ecology: 63,
      turnover: 74,
      trend: 85
    },
    evidence: {
      breadth: { available: false },
      index: { available: true },
      limit_ecology: { available: true },
      turnover: { available: true },
      trend: { available: true }
    }
  }
};
window.CHANLUN_BOOTSTRAP = { pageDate: '2026-08-27' };
let temperature = globalThis.__auxTest.temperature(report);
assert(temperature.score === 63, 'null/unavailable component broke a valid partial contract');
assert(temperature.components.breadth_score === null, 'unavailable component gained a value');
report.market_sentiment.evidence.breadth.available = true;
temperature = globalThis.__auxTest.temperature(report);
assert(temperature.score === null, 'null/available component conflict was accepted');
assert(temperature.insufficient === true, 'component conflict did not fail closed');
""",
        )

    def test_formal_contract_rejects_non_string_text_and_insufficient_conflicts(self):
        fixture = _valid_market_fixture(audit=_audit_literal())
        _assert_node_contract(
            self,
            "({ temperature: buildMarketTemperature })",
            fixture
            + r"""
const formal = window.CHANLUN_BOOTSTRAP
  .recommendationEvidence.market_sentiment.formal_contract;
formal.label = true;
let temperature = globalThis.__auxTest.temperature(base);
assert(temperature.score === null, 'boolean label was accepted as formal text');
        formal.label = '偏强';
        formal.version = 2;
        temperature = globalThis.__auxTest.temperature(base);
        assert(temperature.score === null, 'numeric version was accepted as formal text');
        formal.version = 'v2';
        formal.insufficient = true;
        temperature = globalThis.__auxTest.temperature(base);
        assert(temperature.score === null, 'insufficient projection was accepted as formal');
""",
        )

    def test_unsafe_shadow_promotion_contract_hides_shadow_scores(self):
        fixture = _valid_market_fixture(audit=_audit_literal())
        _assert_node_contract(
            self,
            "({ market: renderMarketTemperatureCard })",
            fixture
            + r"""
[
  { promotion_eligible: true },
  { promotion_requires_new_authorization: false }
].forEach(function (unsafe) {
  const unsafeShadow = Object.assign({}, base.psy12_shadow, unsafe);
  const html = globalThis.__auxTest.market(Object.assign({}, base, {
    psy12_shadow: unsafeShadow
  }));
  assert(html.includes('合同不可用'), 'unsafe promotion contract was rendered as available');
  assert(!html.includes('正式分</span><strong>61'), 'unsafe formal score leaked from shadow panel');
  assert(!html.includes('影子分</span><strong>61'), 'unsafe shadow score leaked');
});
""",
        )

    def test_all_psy12_audit_text_is_escaped(self):
        malicious = _audit_literal(
            status="<script>alert(1)</script>",
            reason="<img src=x onerror=alert(2)>",
            as_of_date="<svg onload=alert(3)>",
        )
        fixture = _valid_market_fixture(audit="AUDIT")
        _assert_node_contract(
            self,
            "({ market: renderMarketTemperatureCard })",
            fixture.replace("AUDIT", malicious)
            + r"""
const html = globalThis.__auxTest.market(base);
['<script', '<img', '<svg'].forEach(function (unsafe) {
  assert(!html.includes(unsafe), 'unsafe PSY12 audit text leaked: ' + unsafe);
});
assert(html.includes('&lt;script&gt;'), 'escaped audit status is missing');
assert(html.includes('&lt;img'), 'escaped audit reason is missing');
assert(html.includes('&lt;svg'), 'escaped audit date is missing');
""",
        )

    def test_psy12_shadow_subpanel_is_single_column_at_390px(self):
        start = CSS.rfind("@media (max-width: 390px)")
        self.assertGreaterEqual(start, 0, "390px media query missing")
        mobile = CSS[start:]
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
                r"\.market-temperature-card\s+\.psy12-shadow-card[^}]*"
                r"min-width:\s*0\s*;",
                re.DOTALL,
            ),
            "nested PSY12 panel has no narrow-viewport overflow guard",
        )


if __name__ == "__main__":
    unittest.main()
