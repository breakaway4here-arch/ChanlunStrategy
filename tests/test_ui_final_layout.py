"""Contracts for the second M3 presentation batch.

The tests intentionally use the existing Node contract harness so the fixed
report renderer can be checked without a server, report regeneration, or
browser state.
"""

import pathlib
import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


ROOT = pathlib.Path(__file__).resolve().parents[1]


class UIFinalLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (ROOT / "chanlun/report_assets/report-v2.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "chanlun/report_assets/report-v2.css").read_text(encoding="utf-8")

    def test_u07_shell_has_ordered_reading_anchors_and_data_cutoff(self):
        self.assertIn('id="decisionOverview"', self.js)
        self.assertIn('id="marketDecisionBar"', self.js)
        self.assertIn('id="candidateWorkspace"', self.js)
        self.assertIn('id="personalWatchlistSection"', self.js)
        self.assertIn('id="reportChanges"', self.js)
        self.assertIn('数据截止', self.js)
        self.assertNotIn('<small>更新时间</small>', self.js)

    def test_u07_empty_formal_pool_offers_research_observation_entry(self):
        self.assertIn('data-open-research-observation', self.js)
        self.assertIn('进入全部研究观察', self.js)
        self.assertIn('本期没有正式推荐', self.js)

    def test_u07_legacy_without_workspace_capability_does_not_turn_unknown_into_zero(self):
        _assert_node_contract(self, "{ counts:decisionOverviewCounts,empty:buildCandidateEmptyState,state:state }", r'''
window.CHANLUN_BOOTSTRAP={pageDate:'2026-09-12'};
const t=globalThis.__auxTest;
t.state.data={date:'2026-09-12'};
t.state.workspace={views:{},view_meta:{}};
const counts=t.counts();
if(counts.formal!==null || counts.research!==null || counts.capability!=='unavailable') throw Error('legacy capability absence became zero counts');
const html=t.empty('main',{state:'verified_empty'},{filtered:false});
if(html.indexOf('研究观察数量未提供')<0 || html.indexOf('data-open-research-observation')>=0) throw Error('legacy no-capability empty state invented an observation route');
''')

    def test_u07_legacy_views_deduplicate_same_stock_across_main_and_h4(self):
        _assert_node_contract(self, "{ counts:decisionOverviewCounts,state:state }", r'''
const t=globalThis.__auxTest;
window.CHANLUN_BOOTSTRAP={pageDate:'2026-09-12'};
t.state.data={date:'2026-09-12'};
t.state.workspace={views:{
  main:[{code:'600001',action_semantics:'formal'}],
  h4_t3:[{code:'600001',action_semantics:'formal'},{code:'600002',action_semantics:'formal'}],
  highlights:[{code:'600010'}],confirming:[{code:'600010'},{code:'600011'}]
},view_meta:{}};
const counts=t.counts();
if(counts.formal!==2 || counts.research!==2 || counts.capability!=='available') throw Error('legacy view counts did not deduplicate stable stock identity');
''')

    def test_u08_candidate_row_has_three_reading_lines_and_preserves_reason(self):
        _assert_node_contract(self, "{ render:renderCandidateList,state:state,nodes:nodes }", r'''
function el(){return {innerHTML:'',textContent:'',hidden:false,children:[],attrs:{},handlers:{},
  setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]||null;},
  appendChild(v){this.children.push(v);return v;},querySelector(){return null;},querySelectorAll(){return [];},
  addEventListener(k,fn){this.handlers[k]=fn;},focus(){},classList:{add(){},remove(){},toggle(){},contains(){return false;}}};}
document.createElement=el;document.body=el();
const item={code:'600001',name:'长名称示例',sector:'半导体设备',sector_code:'S-01',page_action_reason:'主要阻碍：30分钟证据未提供；下一确认：等待回踩；失效：跌破正式失效位',risk_flags:['风险一','风险二'],data_status:{daily:'verified',is_final:true,stale:false,latest_date:'2026-09-12'},current_price:12.34,change_pct:1.2,price_basis:'qfq'};
const t=globalThis.__auxTest;
t.state.data={date:'2026-09-12',selection_input_health:{schema_version:2,status:'verified',formal:{status:'verified',formal_actions_allowed:true}}};
t.state.workspace={views:{main:[item]},view_meta:{main:{role:'formal',action_semantics:'formal',availability:{state:'available'}}}};
t.state.currentView='main';t.state.activeItem=item;t.state.activeCandidateKey='';t.state.candidateQuery='';t.state.candidateLimit=20;t.state.sectorFilter='';t.state.sectorFilterCode='';t.state.sectorFilterRefs=[];
t.nodes.candidateList=el();t.nodes.detailPanel=el();t.nodes.workspaceBody=el();t.nodes.candidateTools=null;t.nodes.candidateCount=el();t.nodes.candidateMore=el();
t.render();
const html=t.nodes.candidateList.innerHTML || t.nodes.candidateList.children.map(function (row) { return row.innerHTML || ''; }).join('');
if(html.indexOf('candidate-row-identity')<0 || html.indexOf('candidate-row-market')<0 || html.indexOf('candidate-row-reason')<0) throw Error('candidate row does not expose the three fixed reading lines');
if(html.indexOf('candidate-row-statuses')>=0) throw Error('candidate row still appends a fourth status block');
if(html.indexOf('title="数据日期')<0 || html.indexOf('非实时')<0) throw Error('candidate market metadata lost its date or non-realtime disclosure');
if(html.indexOf('主要阻碍')<0 || html.indexOf('30分钟')<0 || html.indexOf('风险一')<0 || html.indexOf('风险二')<0) throw Error('candidate blocker/risk reason was clipped or dropped');
if(!t.nodes.candidateList.children.some(function(node){return node.className==='candidate-list-market-context' && node.textContent.indexOf('非实时')>=0;})) throw Error('common market date/basis context is not visible above the candidate rows');
if(html.indexOf('研究观察')<0 && html.indexOf('正式')<0) throw Error('candidate identity is missing');
''')

    def test_u06_short_judgment_precedes_chart_and_15m_is_not_called_30m_confirmation(self):
        _assert_node_contract(self, "{ render:buildMergedCandidateDetail,state:state }", r'''
const day='2026-09-12';
window.CHANLUN_BOOTSTRAP={pageDate:day,recommendationEvidence:{schema_version:1,report_date:day,views:{main:[{
  code:'600001',summary:{status:'available',name:'Alpha',sector:'半导体',formal_action:'观察',signal_date:day,data_latest_date:day},
  daily_structure:{status:'available',summary:'日线启动线索',signal_date:day},
  sublevel_30m:{status:'available',interval:'15m',summary:'15分钟数据已提供',reason:'等待确认'},
  price_evidence:{status:'partial',current_price:10,reference_price:9},
  market_and_sector:{status:'available',summary:'市场支持，板块分歧',market_state:'支持',sector_layer_state:'分歧',stock_state:'未知'},
  risk_and_next:{status:'available',next_confirmation:{items:['等待回踩']},invalidation_conditions:{items:['跌破参考位']},risk_labels:['板块分歧']}
}]}}};
globalThis.__auxTest.state.data={date:day};
const item={code:'600001',name:'Alpha',sector:'半导体'};
const html=globalThis.__auxTest.render(item,{});
if(html.indexOf('decision-workbench-brief')<0)throw Error('short judgment missing');
if(html.indexOf('decision-workbench-brief')>html.indexOf('chart-panel'))throw Error('short judgment was placed after chart');
if(html.indexOf('data-evidence-target')<0)throw Error('reason has no evidence jump target');
if(html.indexOf('15分钟')<0 || html.indexOf('30分钟确认')>=0)throw Error('15m evidence was mislabeled as 30m confirmation');
''')

    def test_u06_u09_mobile_detail_keeps_one_core_judgment_before_chart(self):
        _assert_node_contract(self, "{ render:buildMergedCandidateDetail,state:state }", r'''
const day='2026-09-12';
window.CHANLUN_BOOTSTRAP={pageDate:day,recommendationEvidence:{schema_version:1,report_date:day,views:{main:[{
  code:'600001',summary:{status:'available',name:'Alpha',formal_action:'观察',signal_date:day,data_latest_date:day},
  daily_structure:{status:'available',summary:'日线仍有关注线索',signal_date:day},
  sublevel_30m:{status:'available',interval:'15m',summary:'15分钟证据',reason:'等待30分钟确认'},
  price_evidence:{status:'partial',current_price:10,reference_price:9},
  risk_and_next:{status:'available',next_confirmation:{items:['等待回踩确认']},invalidation_conditions:{items:['跌破参考位']}}
}]}}};
globalThis.__auxTest.state.data={date:day};
const html=globalThis.__auxTest.render({code:'600001',name:'Alpha',sector:'半导体'},{});
const core=html.indexOf('decision-brief-core');
const chart=html.indexOf('class="chart-panel"');
const after=html.indexOf('decision-brief-after-chart');
if(core<0 || chart<0 || after<0 || !(core<chart && chart<after)) throw Error('mobile detail order is not core judgment -> chart -> remaining judgment');
const beforeChart=html.slice(core,chart);
['主要阻碍','下一确认','失效'].forEach(function(label){
  if(beforeChart.indexOf(label)>=0) throw Error('mobile placed '+label+' before chart');
});
const afterChart=html.slice(chart);
['主要阻碍','下一确认','失效'].forEach(function(label){
  if(afterChart.indexOf(label)<0) throw Error('mobile dropped '+label+' after chart');
});
if(html.indexOf('decision-brief-alert')<0) throw Error('important data anomaly is not persistent in detail');
''')

    def test_u06_evidence_locator_uses_current_chart_dates_and_keeps_historical_entries_mapped(self):
        _assert_node_contract(self, "{ locate:locateDetailEvidence,state:state }", r'''
window.setTimeout=function(){};
const calls=[];
const mount={};
const root={
  contains:function(node){return node===mount;},
  querySelector:function(selector){return null;}
};
const t=globalThis.__auxTest;
t.state.detailTarget=root;
t.state.chartMount=mount;
t.state.data={dates:['WRONG-DATE']};
t.state.chartInstance={
  getOption:function(){return {xAxis:[{data:['2026-09-10','2026-09-11']}]}},
  dispatchAction:function(action){calls.push(action);}
};
t.locate('daily-chart',root,'2026-09-11');
if(calls.length!==1 || calls[0].type!=='showTip' || calls[0].dataIndex!==1) throw Error('locator did not use the mounted chart x-axis date');
t.locate('daily-chart',root,'WRONG-DATE');
if(calls.length!==1) throw Error('locator reused stale state.data.dates to dispatch a false tip');
const staleRoot={contains:function(){return false;},querySelector:function(){return null;}};
t.locate('daily-chart',staleRoot,'2026-09-10');
if(calls.length!==1) throw Error('stale detail root dispatched a chart tip');
function destination(tagName){
  return {tagName:tagName,parentNode:{tagName:'DETAILS',open:false,parentNode:null},classList:{add:function(){}},scrollIntoView:function(){}};
}
const historical=destination('SECTION');
const simulation=destination('ASIDE');
const mappingRoot={contains:function(node){return node===mount;},querySelector:function(selector){
  if(selector==='.recommendation-simulation-tracking') return simulation;
  if(selector==='[data-evidence-module="08"]') return historical;
  return null;
}};
t.state.detailTarget=mappingRoot;
t.locate('historical-validation',mappingRoot);
if(!historical.parentNode.open) throw Error('historical validation entry did not open its evidence ancestor');
t.locate('simulation-tracking',mappingRoot);
if(!simulation.parentNode.open) throw Error('simulation tracking entry did not open its evidence ancestor');
''')

    def test_u16_candidate_fact_rows_keep_dl_semantics_and_one_step_evidence_jump(self):
        _assert_node_contract(self, "{ facts:renderCandidateFactPanel,state:state }", r'''
const t=globalThis.__auxTest;
t.state.data={date:'2026-09-12'};
const html=t.facts({
  code:'600001', current_price:10, change_pct:1.2, reference_price:9,
  price_basis:'qfq', sector:'半导体', formal_action:'观察',
  data_status:{daily:'verified',latest_date:'2026-09-12',is_final:true,stale:false},
  pool_quality:{market_cap:100}
});
if(/<dl>\s*<div[^>]*role="button"/.test(html)) throw Error('fact row still makes a dl child an interactive div');
if(html.indexOf('<div class="candidate-fact-row"><dt>')<0) throw Error('fact rows lost valid dl item structure');
if(html.indexOf('<button type="button" class="candidate-fact-jump" data-evidence-target="price">')<0) throw Error('fact row lost one-step evidence jump');
''')

    def test_u16_status_summary_uses_a_named_group_role(self):
        _assert_node_contract(self, "{ status:renderCandidateStatusSummary }", r'''
const html=globalThis.__auxTest.status({code:'600001',risk_flags:['涨幅过热']},'main');
if(html.indexOf('role="group"')<0) throw Error('status summary uses aria-label without a valid group role');
''')

    def test_u09_mobile_brief_css_keeps_core_compact_and_after_chart_flow(self):
        self.assertIn('.decision-brief-core {', self.css)
        self.assertIn('.decision-brief-after-chart { grid-template-columns: 1fr; gap: 8px; }', self.css)
        self.assertIn('.decision-brief-alert {', self.css)
        self.assertIn('.header-version-details', self.css)
        self.assertIn('.candidate-list-market-context {', self.css)
        self.assertIn('.candidate-row-market { grid-template-columns: minmax(0, 1fr) auto auto; }', self.css)

    def test_u16_missing_evidence_and_ecology_labels_meet_readability_floor(self):
        self.assertIn('.evidence-step.is-missing span,', self.css)
        self.assertIn('color: #475569;', self.css)
        self.assertIn('.ecology-leader small,', self.css)
        self.assertIn('font-size: 12px;', self.css)

    def test_u07_header_has_one_directly_expandable_version_details_entry(self):
        self.assertNotIn('class="header-version-detail"', self.js)
        self.assertEqual(self.js.count('<summary>版本详情</summary>'), 1)

    def test_u10_watchlist_uses_collapsed_personal_details_and_keeps_missing_analysis_explicit(self):
        _assert_node_contract(self, "{ render:renderPersonalWatchlist,state:state }", r'''
const data={personal_watchlist:{items:[{code:'600001',name:'Alpha',enabled:true,thesis:'我的逻辑',fact_status:'fresh',current:{current_price:10,change_pct:1.2},candidate_intersections:[],evidence_date:'2026-09-12'}],fresh_count:1},decision_brief:{theses:[]}};
const html=globalThis.__auxTest.render(data);
if(html.indexOf('data-watch-select')<0 || html.indexOf('personal-watch-detail')<0)throw Error('watchlist detail is not selection-gated');
if(html.indexOf('未提供本期策略分析')<0)throw Error('watch item without candidate evidence borrowed or invented analysis');
''')

    def test_u12_sector_feedback_exposes_original_pool_and_match_count(self):
        _assert_node_contract(self, "{ render:renderFundingMainline }", r'''
const html=globalThis.__auxTest.render({title:'热门板块',status:{label:'收盘核验'},items:[{name:'半导体',sectorCode:'S-01',direction:'heat-up',fact:{change_pct:1,up_count:2,total_count:3,limit_up_count:1}}]},'半导体','S-01',[],{originalCount:25,matchedCount:3});
if(html.indexOf('原池')<0 || html.indexOf('匹配')<0 || html.indexOf('清除筛选')<0)throw Error('sector filter feedback is incomplete');
''')

    def test_u09_mobile_chart_controls_are_split_and_page_does_not_overflow(self):
        mobile_css = self.css.rsplit('@media (max-width: 760px)', 1)[1]
        self.assertIn('.chart-toolbar', mobile_css)
        self.assertIn('flex-direction: column', mobile_css)
        self.assertIn('.chart-layer-switcher', mobile_css)
        self.assertIn('overflow-x: clip', self.css)


if __name__ == '__main__':
    unittest.main()
