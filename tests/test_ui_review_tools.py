"""Behavior regressions for the U11/U13/U15 review tools.

The tests execute the report asset in Node with local fixtures.  They exercise
the rendered behavior and selection state instead of asserting source snippets.
"""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


class UIReviewToolsBehavior(unittest.TestCase):
    def test_u11_changes_panel_drills_real_changes_and_keeps_comparison_identity(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
function el(){return {innerHTML:'',textContent:'',attrs:{},setAttribute(k,v){this.attrs[k]=String(v);},
  getAttribute(k){return this.attrs[k]||null;},querySelector(){return null;},querySelectorAll(){return [];},
  addEventListener(){},classList:{add(){},remove(){},toggle(){},contains(){return false;}}};}
const day='2026-09-12';
const changes={status:'partial',previous_report_date:'2026-09-11',previous_phase:'formal',
  previous_snapshot_id:'snapshot-20260911',previous_version:'formal-v1',
  added:['600001'],removed:['600002'],changed:['600003'],
  value_unavailable_codes:['600003','600004'],value_unavailable_reasons:{'600003':'price_basis_changed','600004':'price_basis_missing'}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',snapshot_id:'snapshot-20260912',version:'formal-v2',items:[],changes:changes}};
const t=globalThis.__auxTest;t.state.data={date:day};t.nodes.decisionChanges=el();
const html=t.render();
if(html.indexOf('上一有效交易快照')<0 || html.indexOf('2026-09-11')<0 || html.indexOf('snapshot-20260911')<0)
  throw Error('comparison identity was not shown');
if(html.indexOf('600001')<0 || html.indexOf('600002')<0 || html.indexOf('600003')<0)
  throw Error('existing added/removed/changed lists were not rendered');
if(html.indexOf('600004')<0 || html.indexOf('价基缺失')<0)
  throw Error('single-stock incomparable reason was not drilled');
if(html.indexOf('data-change-kind="changed"')<0 || html.indexOf('data-change-code="600003"')<0)
  throw Error('change entry did not expose a drill-down target');
if(html.indexOf('移出本期集合（不等于破位）')<0 || html.indexOf('价基')<0)
  throw Error('membership and price comparability boundaries were missing');
''')

    def test_u11_unavailable_history_does_not_claim_no_change(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
function el(){return {innerHTML:'',textContent:'',attrs:{},setAttribute(k,v){this.attrs[k]=String(v);},
  getAttribute(k){return this.attrs[k]||null;},querySelector(){return null;},querySelectorAll(){return [];},
  addEventListener(){},classList:{add(){},remove(){},toggle(){},contains(){return false;}}};}
const day='2026-09-12';
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',items:[],changes:{status:'comparison_unavailable',
  reason:'comparison_identity_changed',previous_report_date:'2026-09-11'}}};
const t=globalThis.__auxTest;t.state.data={date:day};t.nodes.decisionChanges=el();
const html=t.render();
if(html.indexOf('不能确认跨期是否变化')<0 && html.indexOf('历史缺口')<0)
  throw Error('incomplete comparison was presented as a conclusion');
if(html.indexOf('确认无变化')>=0 || html.indexOf('没有变化')>=0)
  throw Error('unavailable history claimed no change');
''')

    def test_u11_selected_stock_history_keeps_current_and_previous_source_contracts(self):
        _assert_node_contract(self, "{ history:renderDecisionChangeHistory }", r'''
const t=globalThis.__auxTest;
const current=[{source:'统一决策清单',record:{code:'600001',page_status:'formal_incomplete',
  strategy_results:[{strategy_id:'main',role:'formal',formal_action:'等回踩',score:71,
    contract:{intended_horizon:'T+3',reference_price:10,invalidation_price:9,price_basis:'qfq'},
    evidence:{summary:{status:'available',as_of:'2026-09-12'},daily_structure:{status:'available',summary:'当前结构'}}}]}}];
const previous=[{source:'正式主推',record:{code:'600001',action:'可上车',action_semantics:'formal',
  reference_price:9.5,invalidation_price:8.8,primary_reason:'上一期结构依据',
  data_status:{latest_date:'2026-09-11'},risk_flags:['上一期风险']}}];
const html=t.history('600001',current,previous,{current:{date:'2026-09-12',phase:'formal',version:'v2'},previous:{date:'2026-09-11',phase:'formal',version:'v1'}});
if(html.indexOf('当前有效快照')<0 || html.indexOf('上一有效交易快照')<0)throw Error('both snapshot panes missing');
if(html.indexOf('等回踩')<0 || html.indexOf('可上车')<0 || html.indexOf('T+3')<0)throw Error('source actions or horizon were merged');
if(html.indexOf('参考价 10')<0 || html.indexOf('参考价 9.5')<0 || html.indexOf('qfq')<0)throw Error('snapshot price contract was dropped');
if(html.indexOf('最早')>=0 || html.indexOf('首次出现')>=0)throw Error('history renderer invented first appearance');
''')

    def test_u11_history_button_reads_previous_snapshot_only_when_opened(self):
        _assert_node_contract(self, "{ load:loadDecisionChangeHistory,state:state }", r'''
const day='2026-09-12';let requested='';
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',version:'v2',items:[{code:'600001',name:'Alpha',page_status:'formal_ready',
  strategy_results:[{strategy_id:'main',role:'formal',formal_action:'可上车',contract:{intended_horizon:'T+3'},evidence:{summary:{status:'available'}}}]}],
  changes:{status:'available',previous_report_date:'2026-09-11',previous_phase:'formal',previous_version:'v1'}}};
const t=globalThis.__auxTest;t.state.data={date:day,workspace:{views:{}}};
const history={innerHTML:'',querySelector(){return history;}};
const target={querySelector(){return history;}};
window.fetch=function(url){
  requested=url;
  return Promise.resolve({ok:true,json(){
    return Promise.resolve({date:'2026-09-11',workspace:{views:{main:[
      {code:'600001',name:'Alpha',action:'上一期动作',reference_price:9.5}
    ]}}});
  }});
};
t.load('600001',target);
setTimeout(function(){
  if(requested!=='data/2026-09-11.json')throw Error('previous snapshot was not read on demand');
  if(history.innerHTML.indexOf('上一期动作')<0)throw Error('loaded previous snapshot was not rendered');
},10);
''')

    def test_u11_nested_previous_identity_drives_on_demand_request(self):
        _assert_node_contract(self, "{ load:loadDecisionChangeHistory,state:state }", r'''
const day='2026-09-12';let requested='';
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',items:[{code:'600001',name:'Alpha'}],
  changes:{status:'available',previous_snapshot:{report_date:'2026-09-11',phase:'formal',snapshot_id:'nested-prev'}}}};
const t=globalThis.__auxTest;t.state.data={date:day,workspace:{views:{}}};
const history={innerHTML:'',querySelector(){return history;}};const target={querySelector(){return history;}};
window.fetch=function(url){requested=url;return Promise.resolve({ok:true,json(){return Promise.resolve({date:'2026-09-11',workspace:{views:{main:[]}}});}});};
t.load('600001',target);
setTimeout(function(){if(requested!=='data/2026-09-11.json')throw Error('nested previous identity was ignored');},10);
''')

    def test_u11_history_identity_validation_rejects_wrong_date_and_phase_and_marks_missing_contract(self):
        _assert_node_contract(self, "{ validate:validateDecisionHistoryPayload }", r'''
const t=globalThis.__auxTest;
let wrongDate=t.validate({date:'2026-09-10',phase:'formal'},
  {date:'2026-09-11',phase:'formal',version:'v1',snapshot:'s1'});
if(wrongDate.ok || wrongDate.dateStatus!=='conflict')throw Error('wrong date was accepted as previous snapshot');
let wrongPhase=t.validate({date:'2026-09-11',phase:'research'},
  {date:'2026-09-11',phase:'formal'});
if(wrongPhase.ok || wrongPhase.phaseStatus!=='conflict')throw Error('phase conflict was accepted');
let missing=t.validate({date:'2026-09-11',data_quality:{is_official:true,bar_state:'closed'}},
  {date:'2026-09-11',phase:'formal',version:'v1',snapshot:'s1',priceBasis:'qfq'});
if(!missing.ok || missing.phaseStatus!=='verified' || missing.versionStatus!=='unverified'
  || missing.snapshotStatus!=='unverified' || missing.priceBasisStatus!=='unverified'
  || missing.priceComparable)throw Error('missing identity contract was not marked unverified');
let basis=t.validate({date:'2026-09-11',phase:'formal',version:'v1',snapshot_id:'s1',price_basis:'hfq'},
  {date:'2026-09-11',phase:'formal',version:'v1',snapshot:'s1',priceBasis:'qfq'});
if(!basis.ok || basis.priceBasisStatus!=='conflict' || basis.priceComparable)
  throw Error('price-basis conflict was treated as comparable');
let undeclared=t.validate({date:'2026-09-11',phase:'formal'},
  {date:'2026-09-11',phase:'formal'});
if(undeclared.identityComparable || undeclared.priceComparable
  || undeclared.versionStatus!=='not_declared' || undeclared.priceBasisStatus!=='not_declared')
  throw Error('undeclared identity was treated as comparable');
''')

    def test_u11_duplicate_source_code_selects_matching_identity(self):
        _assert_node_contract(self, "{ entries:decisionHistoryEntries }", r'''
const t=globalThis.__auxTest;
const payload={workspace:{views:{main:[
  {code:'600001',name:'旧版本',version:'v1',action:'旧动作'},
  {code:'600001',name:'目标版本',version:'v2',action:'目标动作'}
]}}};
const rows=t.entries(payload,'600001',null,{version:'v2'});
if(rows.length!==1 || rows[0].record.action!=='目标动作')throw Error('duplicate source/code did not select matching identity');
''')

    def test_u11_single_row_identity_conflict_and_missing_declaration_are_visible(self):
        _assert_node_contract(self, "{ row:validateDecisionHistoryRow }", r'''
const t=globalThis.__auxTest;const expected={date:'2026-09-11',phase:'formal',version:'v2',snapshot:'s2',priceBasis:'qfq'};
const conflict=t.row({code:'600001',report_date:'2026-09-11',phase:'formal',version:'v1',snapshot_id:'s2',price_basis:'qfq'},expected);
if(conflict.identityComparable || conflict.versionStatus!=='conflict')throw Error('single row version conflict was accepted');
const consistent=t.row({code:'600001',report_date:'2026-09-11',phase:'formal',version:'v2',snapshot_id:'s2',price_basis:'qfq'},expected);
if(!consistent.identityComparable || !consistent.priceComparable)throw Error('single matching row was rejected');
const missing=t.row({code:'600001',report_date:'2026-09-11',phase:'formal'},expected);
if(missing.identityComparable || missing.priceComparable || missing.versionStatus!=='unverified')
  throw Error('missing row identity was treated as verified');
''')

    def test_u11_change_counts_focus_existing_group(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
function button(kind){return {handlers:{},getAttribute(k){return k==='data-change-group-toggle'?kind:'';},addEventListener(k,fn){this.handlers[k]=fn;}};}
const toggle=button('changed');let focused=false,scrolled=false;
const section={classList:{add(){focused=true;}},scrollIntoView(){scrolled=true;}};
const target={innerHTML:'',querySelectorAll(selector){return selector==='[data-change-group-toggle]'?[toggle]:[];},querySelector(){return section;}};
const day='2026-09-12';window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',report_date:day,phase:'formal',items:[],changes:{status:'available',changed:['600001']}}};
const t=globalThis.__auxTest;t.state.data={date:day};t.nodes.decisionChanges=target;t.render();
if(target.innerHTML.indexOf('data-change-group-toggle="changed"')<0)throw Error('change count was not actionable');
toggle.handlers.click({currentTarget:toggle});
if(!focused || !scrolled)throw Error('change count did not focus its existing group');
''')

    def test_u13_quick_comparison_caps_three_preserves_sources_and_keeps_filtered_selection(self):
        _assert_node_contract(self, "{ render:renderQuickComparison,toggle:toggleQuickComparisonSelection,state:state,nodes:nodes }", r'''
function el(){return {innerHTML:'',textContent:'',attrs:{},setAttribute(k,v){this.attrs[k]=String(v);},
  getAttribute(k){return this.attrs[k]||null;},querySelector(){return null;},querySelectorAll(){return [];},
  addEventListener(){},classList:{add(){},remove(){},toggle(){},contains(){return false;}}};}
function evidence(status){return {summary:{status:status||'available',formal_action:'保留来源动作'},
  daily_structure:{status:status||'available',summary:'日线结构'},risk_and_next:{status:status||'available',risk_labels:['风险项']}};}
function strategyFixture(id,role,action,horizon,score){return {strategy_id:id,role:role,formal_action:action,
  action_semantics:role==='research'?'watch_only':'formal',score:score,contract:{intended_horizon:horizon,
  reference_price:10,invalidation_price:9},evidence:evidence('available')};}
function item(code,name){return {code:code,name:name,sector:'测试',primary_reason:'结构依据 '+name,
  invalidation_price:9,risk_flags:['风险项'],data_status:{latest_date:'2026-09-12',daily:'verified'},
  strategy_results:[strategyFixture('main','formal','可上车','T+3',81),strategyFixture('h4_t3','formal','等回踩','T+3',72),
    strategyFixture('confirming','research','仅观察','T+1',null)]};}
const items=[item('600001','Alpha'),item('600002','Beta'),item('600003','Gamma'),item('600004','Delta')];
const day='2026-09-12';
const t=globalThis.__auxTest;t.state.data={date:day,selection_input_health:{schema_version:2,status:'verified',formal:{status:'verified',formal_actions_allowed:true}}};
t.state.workspace={views:{main:items},view_meta:{main:{role:'formal',action_semantics:'formal',availability:{state:'available'}}}};
t.state.currentView='main';t.state.candidateQuery='';t.state.sectorFilter='';t.state.sectorFilterCode='';t.state.sectorFilterRefs=[];
t.state.quickComparison={selectedKeys:[],message:''};t.nodes.candidateQuickComparison=el();
if(!t.toggle('600001') || !t.toggle('600002') || !t.toggle('600003')) throw Error('three selections were not accepted');
if(t.toggle('600004')!==false) throw Error('fourth selection was accepted');
let html=t.render();
if(html.indexOf('Alpha')<0 || html.indexOf('Gamma')<0
  || html.indexOf('class="quick-comparison-column" data-quick-code="600004"')>=0)
  throw Error('selection set was wrong');
if(html.indexOf('最多比较 3 只')<0) throw Error('fourth selection did not explain the cap');
if(html.indexOf('正式主推：可上车')<0 || html.indexOf('H4 T+3：等回踩')<0 || html.indexOf('等确认：仅观察')<0)
  throw Error('source actions or contracts were merged');
if(html.indexOf('综合分')>=0 || html.indexOf('胜率')>=0) throw Error('cross-strategy aggregate was invented');
t.state.candidateQuery='Alpha';
html=t.render();
if(html.indexOf('Beta')<0 || html.indexOf('不在当前集合')<0) throw Error('filtered selected item was silently replaced');
if(html.indexOf('data-quick-remove="600002"')<0) throw Error('filtered selection had no remove control');
''')

    def test_u13_legacy_candidate_preserves_explicit_action_score_and_contract(self):
        _assert_node_contract(self, "{ render:renderQuickComparison,toggle:toggleQuickComparisonSelection,state:state,nodes:nodes }", r'''
function el(){return {innerHTML:'',querySelectorAll(){return [];},addEventListener(){}};}
const legacy={code:'600010',name:'Legacy',sector:'测试',formal_action:'可上车',page_action:'等回踩',score:88,
  formal_decision_contract:{reference_price:10.5,invalidation_price:9.2,intended_horizon:'T+3',price_basis:{adjustment:'qfq'}}};
const t=globalThis.__auxTest;t.state.data={date:'2026-09-12',selection_input_health:{schema_version:2,status:'verified',formal:{status:'verified',formal_actions_allowed:true}}};
t.state.workspace={views:{main:[legacy]},view_meta:{main:{role:'formal',action_semantics:'formal',availability:{state:'available'}}}};
t.state.currentView='main';t.state.candidateQuery='';t.state.sectorFilter='';t.state.sectorFilterCode='';t.state.sectorFilterRefs=[];
t.state.quickComparison={selectedKeys:[],selectedItems:{},message:'',max:3};t.nodes.candidateQuickComparison=el();
if(!t.toggle('600010'))throw Error('legacy candidate was not selectable');
const html=t.render();
if(html.indexOf('<fieldset class="quick-comparison-selection">')<0)
  throw Error('quick comparison selection is not an accessible group');
if(html.indexOf('可上车')<0 || html.indexOf('T+3')<0 || html.indexOf('参考价 10.5')<0
  || html.indexOf('失效位 9.2')<0 || html.indexOf('qfq')<0 || html.indexOf('分数 88')<0)
  throw Error('legacy candidate contract fields were dropped');
''')

    def test_u15_history_link_names_existing_validation_performance_and_simulation_boundaries(self):
        _assert_node_contract(self, "{ link:renderHistoricalValidationLink,validation:renderHistoricalValidation }", r'''
const t=globalThis.__auxTest;
const link=t.link({code:'600001',name:'Alpha'},{historical_validation:{status:'partial'}});
if(link.indexOf('历史验证')<0 || link.indexOf('榜单表现')<0 || link.indexOf('模拟验证')<0)
  throw Error('detail did not link the existing history evidence surfaces');
const progress=t.validation({summary:'已有记录',comparison_identity:{strategy:'main',version:'v1',source_pool:'picks_fusion',intended_horizon:3},
  progress_by_horizon:{t1:{status:'waiting',mature_samples:2,required_mature_samples:100,waiting_samples:1,unavailable_samples:2},t3:{status:'contract_missing'},t5:{status:'contract_missing'}},
  metrics_by_horizon:{t1:{mean:12,win_rate:66}},simulation_tracking:{status:'missing'}});
if(progress.indexOf('样本进度')<0 || progress.indexOf('2 / 100 成熟样本')<0 || progress.indexOf('暂无同合同历史跟踪记录')<0)
  throw Error('historical progress or simulation boundary missing');
if(progress.indexOf('均值 12')>=0 || progress.indexOf('上涨率 66')>=0)
  throw Error('metrics were shown before the mature comparison gate');
''')

    def test_u15_history_links_use_real_targets_and_compare_route(self):
        _assert_node_contract(self, "{ link:renderHistoricalValidationLink,bind:bindHistoricalEvidenceLinks }", r'''
const t=globalThis.__auxTest;
const html=t.link({code:'600001'},{historical_validation:{status:'ready_for_manual_comparison',simulation_tracking:{status:'available'}}});
if(html.indexOf('data-evidence-target="historical-validation"')<0
  || html.indexOf('data-evidence-target="simulation-tracking"')<0
  || html.indexOf('href="compare/"')<0)
  throw Error('history links do not point to existing evidence/compare routes');
if(html.indexOf('historical_validation')>=0 || html.indexOf('simulation_tracking')>=0)
  throw Error('internal evidence field names leaked into the main link labels');
let handler=null,opened=false,scrolled=false;const bound={};
const button={getAttribute(k){return k==='data-evidence-target'?'historical-validation':(bound[k]||'');},setAttribute(k,v){bound[k]=v;},addEventListener(k,fn){handler=fn;}};
const details={tagName:'DETAILS',open:false,parentNode:null};
const evidence={parentNode:details,scrollIntoView(){scrolled=true;},focus(){}};
const root={querySelectorAll(){return [button];},querySelector(){return evidence;}};
t.bind(root);handler({currentTarget:button});opened=details.open;
if(!opened || !scrolled)throw Error('evidence target event did not open and locate module');
const missing=t.link({code:'600001'},{historical_validation:{status:'missing',simulation_tracking:{status:'missing'}}});
if(missing.indexOf('暂无同合同历史跟踪记录')<0 || missing.indexOf('data-evidence-target="simulation-tracking"')>=0)
  throw Error('missing simulation evidence was not shown as a gap');
''')

    def test_u15_non_history_evidence_targets_do_not_open_module08(self):
        _assert_node_contract(self, "{ bind:bindHistoricalEvidenceLinks }", r'''
const handlers={};
function button(target){const attrs={'data-evidence-target':target};return {getAttribute(k){return attrs[k]||'';},setAttribute(k,v){attrs[k]=v;},addEventListener(k,fn){handlers[target]=fn;}};}
const price=button('price-evidence'),daily=button('daily-chart'),history=button('historical-validation');
const root={querySelectorAll(){return [price,daily,history];},querySelector(){return {parentNode:null,scrollIntoView(){},focus(){}};}};
globalThis.__auxTest.bind(root);
if(handlers['price-evidence'] || handlers['daily-chart'] || !handlers['historical-validation'])
  throw Error('non-history evidence target was bound to history module');
''')


if __name__ == '__main__':
    unittest.main()
