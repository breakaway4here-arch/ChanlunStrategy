import unittest
from tests.test_auxiliary_frontend import _assert_node_contract


class UnifiedWorkbenchFrontend(unittest.TestCase):
    def test_closing_drawer_releases_its_chart_and_markup(self):
        _assert_node_contract(self, "{ close:closeMobileDetailDrawer,state:state,nodes:nodes,setup:function(){setDrawerBackgroundInert=function(){};} }", r'''
const t=globalThis.__auxTest;t.setup();let disposed=0;
document.body={style:{}};
t.nodes.drawer={classList:{remove(){}},setAttribute(){}};
t.nodes.drawerContent={innerHTML:'duplicate detail',contains(){return true;}};
t.state.chartMount={};t.state.chartInstance={dispose(){disposed++;}};
t.close();
if(t.nodes.drawerContent.innerHTML || disposed!==1 || t.state.chartInstance!==null)throw Error('hidden drawer retained chart and duplicate markup');
''')

    def test_each_strategy_evidence_has_unique_accessible_heading_ids(self):
        _assert_node_contract(self, "{ evidence:renderStrategyEvidence }", r'''
window.CHANLUN_BOOTSTRAP={pageDate:'2026-09-08'};
const s={strategy_id:'confirming',role:'research',action_semantics:'watch_only',evidence:{}};
const html=globalThis.__auxTest.evidence(s,0)+globalThis.__auxTest.evidence(s,1);
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(x=>x[1]);
if(ids.length!==new Set(ids).size)throw Error('strategy heading IDs collide');
for(const label of [...html.matchAll(/aria-labelledby="([^"]+)"/g)].map(x=>x[1]))if(!ids.includes(label))throw Error('heading reference missing');
''')

    def test_empty_focus_has_action_without_repeating_screen_summary(self):
        _assert_node_contract(self, "{ empty:buildCandidateEmptyState }", r'''
window.CHANLUN_BOOTSTRAP={pageDate:'2026-09-08',decisionWorkbench:{schema_version:'decision-workbench-v1',report_date:'2026-09-08',phase:'formal',items:[{code:'600001'}],summary:{reason:'已在顶部说明筛选过程'}}};
const html=globalThis.__auxTest.empty('decision_focus',{},{});
if(html.includes('已在顶部说明筛选过程'))throw Error('empty state repeats overview');
if(!html.includes('data-workbench-open-all') || !html.includes('查看全部 1 只'))throw Error('no route to remaining candidates');
const filtered=globalThis.__auxTest.empty('decision_focus',{}, {filtered:true,filterLabel:'测试'});
if(!filtered.includes('已保留筛选条件'))throw Error('filter empty state was lost');
''')

    def test_legacy_report_explains_projection_capability(self):
        _assert_node_contract(self, "{ render:renderDecisionOverview }", r'''
const mount={hidden:true,innerHTML:''};
document.getElementById=function(){return mount;};
window.CHANLUN_BOOTSTRAP={pageDate:'2026-09-04'};
globalThis.__auxTest.render();
if(mount.hidden || !mount.innerHTML.includes('旧版报告'))throw Error('legacy capability not explained');
''')

    def test_mobile_to_desktop_remounts_selected_chart(self):
        _assert_node_contract(self, "{ run:function() { var count=0; var detect=isMobileViewport, render=renderCandidateDetail, close=closeMobileDetailDrawer; state.isMobile=true; state.activeItem={code:600001}; nodes.detailPanel={}; isMobileViewport=function(){return false;}; renderCandidateDetail=function(){count++;}; closeMobileDetailDrawer=function(){}; syncViewport(); isMobileViewport=detect;renderCandidateDetail=render;closeMobileDetailDrawer=close;return count; } }", r'''
if(globalThis.__auxTest.run()!==1)throw Error('desktop chart was not remounted after mobile drawer');
''')

    def test_primary_navigation_consumes_same_projection_and_source_evidence(self):
        _assert_node_contract(self, "{ setup: function(d) { state.data=d; normalizeWorkspace(d); return getCandidateViews(); }, groups:getWorkspaceNavigationGroups, row:buildCandidateRowSummary, detail:buildMergedCandidateDetail }", r'''
const data={date:'2026-09-07',workspace:{views:{main:[],confirming:[]},view_meta:{}}};
const ev={code:'600001',summary:{status:'available'},daily_structure:{status:'available',signal:'日线回踩验收样本'}};
const item={id:'one',code:'600001',name:'样本',page_status:'watch_only',status_label:'研究观察',formal_action:null,score:null,primary_reason:'等待回踩',next_confirmation:[],invalidation:[],blocked_reasons:[],sources:['confirming'],evidence_view:'confirming',candidate:{code:'600001',name:'样本',ref:{pool:'startup_watchlist',code:'600001'}},strategy_results:[{strategy_id:'confirming',role:'research',formal_action:null,contract:{},evidence:ev}]};
window.CHANLUN_BOOTSTRAP={pageDate:data.date,decisionWorkbench:{schema_version:'decision-workbench-v1',report_date:data.date,phase:'formal',summary:{title:'暂无正式推荐',reason:'确认条件不足'},items:[item],featured_ids:[]}};
const views=globalThis.__auxTest.setup(data);
if(views.views.decision_all.length!==1 || views.views.decision_focus.length!==0)throw Error('projection not consumed');
if(globalThis.__auxTest.groups().primary.some(x=>x.key==='confirming'||x.key==='observation_top5'))throw Error('duplicate pool navigation');
const row=views.views.decision_all[0];
const summary=globalThis.__auxTest.row(row,'decision_all');
if(summary.action.indexOf('观察')<0 || summary.scoreText.indexOf('决策分')>=0)throw Error('research formal label leaked');
const html=globalThis.__auxTest.detail(row,null);
if(html.indexOf('K线图表')<0 || html.indexOf('下一确认')<0 || html.indexOf('失效')<0)throw Error('chart/brief missing');
if(html.indexOf('本期未声明正式动作')>=0)throw Error('not applicable misreported missing');
if(!html.includes('日线回踩验收样本') || !html.includes('30分钟确认'))throw Error('full strategy evidence was dropped');
''')

    def test_projection_of_other_day_is_never_reused(self):
        _assert_node_contract(self, "{ get:getDecisionWorkbench }", r'''
window.CHANLUN_BOOTSTRAP={pageDate:'2026-09-08',decisionWorkbench:{schema_version:'decision-workbench-v1',report_date:'2026-09-07',phase:'formal',items:[]}};
if(globalThis.__auxTest.get({date:'2026-09-08'})!==null)throw Error('cross-date projection reused');
''')
