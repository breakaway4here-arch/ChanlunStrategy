import unittest
from tests.test_auxiliary_frontend import JS, _assert_node_contract


class MarketEvidenceVisibility(unittest.TestCase):
    def test_default_today_contains_full_evidence_before_stock_conclusion(self):
        shell = JS[JS.index('function buildAppShell'):JS.index('function getReportDataStatus')]
        today = shell.index('id="todayDecisionView"')
        summary = shell.index('id="decisionOverview"')
        market = shell.index('id="marketEvidence"')
        candidate = shell.index('id="candidateWorkspace"')
        research = shell.index('id="researchValidationView"')
        self.assertTrue(today < summary < market < candidate < research)
        self.assertEqual(shell.count('id="marketEvidence"'), 1)
        market_flow = shell[shell.index('id="marketDecisionBar"'):candidate]
        self.assertIn('marketSentimentChart', JS)
        self.assertIn('id="marketDecisionSummary"', market_flow)
        self.assertNotIn('<details', market_flow)

    def test_formal_evidence_is_visible_and_does_not_borrow_research_counts(self):
        _assert_node_contract(self, '{render:buildExpandedMarketEvidence}', r'''
const data=JSON.parse(fs.readFileSync('docs/data/2026-09-08.json','utf8'));
window.CHANLUN_BOOTSTRAP={pageDate:data.date};
data.limit_up_pool=[{name:'研究样本'}];
const html=globalThis.__auxTest.render(data);
for(const fact of ['3253','1858','62.53%','72','0','1.03','0.95','59.84%','上证指数','创业板指','marketSentimentChart'])
  assert(html.includes(fact),'visible evidence missing '+fact);
assert(!html.includes('<details'),'formal market facts are collapsible');
assert(!html.includes('PSY12'),'shadow evidence mixed into formal facts');
assert(html.includes('综合情绪') && html.includes('主要指数'),'different market scopes not explained');
const invalid=JSON.parse(JSON.stringify(data));invalid.market_sentiment.date='2026-09-07';
const unavailable=globalThis.__auxTest.render(invalid);
assert(!unavailable.includes('3253') && unavailable.includes('数据不足'),'stale sentiment evidence leaked');
data.market_sentiment.evidence.breadth.advance_count=null;
assert(globalThis.__auxTest.render(data).includes('上涨 --'),'missing count turned into zero');
''')

    def test_empty_formal_result_explains_candidate_and_h4_separately(self):
        _assert_node_contract(self, '{render:buildFormalOutcomeExplanation}', r'''
const summary={main:{state:'verified_empty',count:0},h4_t3:{state:'verified_empty',count:0}};
const data={diagnostics:{fusion_admission:{kept_formal:0,kept_candidate:3}}};
const html=globalThis.__auxTest.render(summary,data);
assert(html.includes('3 只') && html.includes('候选') && html.includes('尚未形成正式买点'),'no explanation for remaining candidates');
assert(html.includes('H4 T+3') && html.includes('全部门槛'),'H4 absent from result');
summary.main={state:'unavailable',count:0,reason:'数据核验未通过'};
const blocked=globalThis.__auxTest.render(summary,data);
assert(blocked.includes('数据核验未通过') && !blocked.includes('尚未形成正式买点'),'unavailable treated as normal empty');
''')
