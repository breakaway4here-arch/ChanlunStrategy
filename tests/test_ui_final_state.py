"""Behavior regressions for the first UI final-state batch (U01/U02/U03).

These tests exercise the JavaScript behavior through Node rather than checking
source strings.  The fixture intentionally keeps all strategy inputs local and
does not load a report or start a browser server.
"""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


class UIFinalStateBehavior(unittest.TestCase):
    def test_u01_search_empty_releases_chart_and_clear_remounts_valid_selection(self):
        _assert_node_contract(self, "{ render:renderCandidateList,state:state,nodes:nodes }", r'''
function el() {
  return {
    innerHTML:'', textContent:'', hidden:false, children:[], attrs:{},
    setAttribute(k,v){this.attrs[k]=String(v);},
    getAttribute(k){return this.attrs[k] || null;},
    appendChild(v){this.children.push(v);return v;},
    querySelector(){return null;}, querySelectorAll(){return [];},
    addEventListener(){}, focus(){},
    classList:{add(){},remove(){},toggle(){},contains(){return false;}}
  };
}
document.createElement=el;
document.body=el();
const item={code:'600001',name:'Alpha',sector:'芯片'};
const data={date:'2026-09-12',selection_input_health:{schema_version:2,status:'verified',formal:{status:'verified',formal_actions_allowed:true}}};
t=globalThis.__auxTest;
t.state.data=data;
t.state.workspace={views:{main:[item]},view_meta:{main:{role:'formal',action_semantics:'formal',availability:{state:'available'}}}};
t.state.currentView='main';t.state.activeItem=item;t.state.candidateLimit=20;
t.state.sectorFilter='';t.state.sectorFilterCode='';t.state.sectorFilterRefs=[];
t.nodes.candidateList=el();t.nodes.detailPanel=el();t.nodes.workspaceBody=el();
t.nodes.candidateTools=null;t.nodes.candidateCount=el();t.nodes.candidateMore=el();

// A valid active item whose detail was unloaded must be mounted by list sync.
t.state.candidateQuery='alpha';
t.nodes.detailPanel.innerHTML='';
t.render();
if(!t.nodes.detailPanel.innerHTML)throw Error('valid selection detail was not remounted');

let disposed=0;
t.state.chartMount={};t.state.chartInstance={dispose(){disposed++;}};
t.state.candidateQuery='does-not-exist';
t.render();
if(disposed!==1 || t.state.chartInstance!==null)throw Error('empty result retained chart lifecycle');
if(t.nodes.detailPanel.innerHTML.indexOf('0只')<0)throw Error('empty result state missing');

// Clearing the query restores the still-valid active candidate without a click.
t.state.candidateQuery='';
t.render();
if(!t.nodes.detailPanel.innerHTML || t.nodes.detailPanel.innerHTML.indexOf('K线图表')<0)
  throw Error('clearing search did not restore selected detail');
''')

    def test_u01_old_selection_token_cannot_win_after_new_snapshot(self):
        _assert_node_contract(self, "{ begin:beginCandidateSelection,current:isCurrentCandidateSelection,state:state }", r'''
const t=globalThis.__auxTest;
const first={code:'600001'};const second={code:'600002'};
const token=t.begin(first,'snapshot-a');
t.begin(second,'snapshot-b');
if(t.current(token,first,'snapshot-a'))throw Error('stale candidate callback remained current');
''')

    def test_u01_paging_reports_full_selection_and_only_limits_visible_rows(self):
        _assert_node_contract(self, "{ render:renderCandidateList,state:state,nodes:nodes }", r'''
function el(){return {innerHTML:'',textContent:'',hidden:false,children:[],attrs:{},
  setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]||null;},
  appendChild(v){this.children.push(v);return v;},querySelector(){return null;},querySelectorAll(){return [];},
  addEventListener(){},focus(){},classList:{add(){},remove(){},toggle(){},contains(){return false;}}};}
document.createElement=el;document.body=el();
const items=Array.from({length:25},(_,i)=>({code:'60'+String(i+1).padStart(4,'0'),name:'股票'+(i+1),sector:'测试'}));
const t=globalThis.__auxTest;
t.state.data={date:'2026-09-12',selection_input_health:{schema_version:2,status:'verified',formal:{status:'verified',formal_actions_allowed:true}}};
t.state.workspace={views:{main:items},view_meta:{main:{role:'formal',action_semantics:'formal',availability:{state:'available'}}}};
t.state.currentView='main';t.state.activeItem=items[0];t.state.activeCandidateKey='';t.state.candidateQuery='';
t.state.sectorFilter='';t.state.sectorFilterCode='';t.state.sectorFilterRefs=[];t.state.candidateLimit=20;
t.nodes.candidateList=el();t.nodes.detailPanel=el();t.nodes.workspaceBody=el();t.nodes.candidateTools=null;
t.nodes.candidateCount=el();t.nodes.candidateMore=el();
t.render();
if(t.nodes.candidateCount.textContent!=='显示 20 / 25' || t.nodes.candidateMore.hidden)
  throw Error('visible page and full selection counts diverged');
t.state.candidateLimit=40;t.render();
if(t.nodes.candidateCount.textContent!=='显示 25 / 25' || !t.nodes.candidateMore.hidden)
  throw Error('load-more did not expand the same logical selection');
''')

    def test_u02_decision_all_comparison_uses_all_entities_and_each_source_contract(self):
        _assert_node_contract(self, "{ render:renderCandidateEvidenceComparison,state:state,setup:normalizeWorkspace }", r'''
const day='2026-09-12';
function evidence(name,status){return {summary:{status:status||'available',name:name,sector:'测试'},daily_structure:{status:status||'available'},risk_and_next:{status:status||'available'}};}
function strategy(id,role,action,horizon,status){return {strategy_id:id,role:role,action_semantics:role==='formal'?'formal':'watch_only',formal_action:action,contract:{intended_horizon:horizon,reference_price:10,invalidation_price:9},score:role==='formal'?61:null,evidence:evidence(id,status)};}
const items=[];
for(let i=1;i<=25;i++){
  const code='60'+String(i).padStart(4,'0');
  items.push({id:'id-'+code,code:code,name:'股票'+i,page_status:'watch_only',status_label:'研究观察',formal_action:null,score:null,evidence_view:'confirming',strategy_results:[strategy('confirming','research',null,'T+1',i===25?'missing':'available')],candidate:{code:code,name:'股票'+i}});
}
items[0].strategy_results=[
  strategy('main','formal','可上车','T+3','available'),
  strategy('h4_t3','formal','不推荐','T+3','available'),
  strategy('confirming','research',null,'T+1','available')
];
items[0].evidence_view='main';
const data={date:day,workspace:{views:{main:[],h4_t3:[],confirming:[]},view_meta:{}}};
t=globalThis.__auxTest;t.state.data=data;t.setup(data);
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',report_date:day,phase:'formal',items:items,featured_ids:[]}};
const html=t.render('decision_all',data);
if(html.indexOf('600025')<0)throw Error('comparison only used first DOM page');
if(html.indexOf('本期未选出推荐票')>=0)throw Error('non-empty unified list was rendered as empty');
if(html.indexOf('main：可上车')<0 || html.indexOf('h4_t3：不推荐')<0 || html.indexOf('confirming：仅观察')<0)
  throw Error('source strategy actions were merged or dropped');
if(html.indexOf('<dt>唯一正式动作</dt>')>=0)
  throw Error('mobile ticket promoted selected evidence to a unique action');
if(html.indexOf('未提供证据')<0)throw Error('candidate with missing evidence was treated as absent');
''')

    def test_u02_legacy_evidence_fallback_is_filtered_and_does_not_bypass_empty_workspace_view(self):
        _assert_node_contract(self, "{ render:renderCandidateEvidenceComparison,state:state,setup:normalizeWorkspace }", r'''
const day='2026-09-12';
const rows=[
  {code:'600001',summary:{status:'available',name:'Alpha',sector:'芯片'}},
  {code:'600002',summary:{status:'available',name:'Beta',sector:'银行'}}
];
window.CHANLUN_BOOTSTRAP={pageDate:day,recommendationEvidence:{schema_version:1,report_date:day,views:{main:rows}}};
const t=globalThis.__auxTest;
t.state.data={date:day};t.state.currentView='main';t.state.candidateQuery='alpha';t.state.sectorFilter='';t.state.sectorFilterCode='';t.state.sectorFilterRefs=[];
t.state.workspace={views:{},view_meta:{}};t.setup(t.state.data);
let html=t.render('main',t.state.data);
if(html.indexOf('600001')<0 || html.indexOf('600002')>=0)throw Error('legacy fallback ignored the shared search filter');
t.state.candidateQuery='';t.state.sectorFilter='银行';
html=t.render('main',t.state.data);
if(html.indexOf('600002')<0 || html.indexOf('600001')>=0)throw Error('legacy fallback ignored the shared sector filter');
t.state.workspace={views:{main:[]},view_meta:{}};t.state.candidateQuery='';
html=t.render('main',t.state.data);
if(html.indexOf('600001')>=0 || html.indexOf('600002')>=0 || html.indexOf('当前集合没有匹配对象')<0)
  throw Error('explicit empty workspace view was bypassed by legacy evidence');
''')

    def test_u02_filter_events_refresh_comparison_for_search_empty_clear_and_sector_toggle(self):
        _assert_node_contract(self, "{ bind:bindCandidateFilterEvents,refresh:refreshCandidateWorkspace,funding:renderFundingMainlineStrip,state:state,nodes:nodes }", r'''
function el(){return {innerHTML:'',textContent:'',hidden:false,children:[],attrs:{},handlers:{},
  setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return this.attrs[k]||null;},
  appendChild(v){this.children.push(v);return v;},querySelector(){return null;},querySelectorAll(){return [];},
  addEventListener(k,fn){this.handlers[k]=fn;},focus(){},classList:{add(){},remove(){},toggle(){},contains(){return false;}}};}
document.createElement=el;document.body=el();
const alpha={code:'600001',name:'Alpha',sector:'芯片'};
const beta={code:'600002',name:'Beta',sector:'银行'};
const day='2026-09-12';
const data={date:day,sector_flow:[{name:'芯片'}],sector_outflow:[],selection_input_health:{schema_version:2,status:'verified',formal:{status:'verified',formal_actions_allowed:true}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,recommendationEvidence:{schema_version:1,report_date:day,views:{main:[
  {code:'600001',summary:{status:'available',name:'Alpha',sector:'芯片'}},
  {code:'600002',summary:{status:'available',name:'Beta',sector:'银行'}}
]}}};
const t=globalThis.__auxTest;
t.state.data=data;t.state.workspace={views:{main:[alpha,beta]},view_meta:{main:{role:'formal',action_semantics:'formal',availability:{state:'available'}}}};
t.state.currentView='main';t.state.activeItem=alpha;t.state.activeCandidateKey='';t.state.candidateQuery='';
t.state.sectorFilter='';t.state.sectorFilterCode='';t.state.sectorFilterRefs=[];t.state.candidateLimit=20;
const search=el(),more=el(),list=el(),detail=el(),count=el(),body=el(),strip=el(),sectorButton=el();
search.value='';
sectorButton.getAttribute=function(key){
  if(key==='data-sector-filter')return t.state.sectorFilter ? '' : '芯片';
  return '';
};
strip.querySelectorAll=function(){return [sectorButton];};
t.nodes.candidateSearch=search;t.nodes.candidateMore=more;t.nodes.candidateList=list;t.nodes.detailPanel=detail;
t.nodes.candidateCount=count;t.nodes.workspaceBody=el();t.nodes.candidateTools=null;t.nodes.sectorStrip=strip;
t.nodes.candidateEvidenceComparison={querySelector:function(){return body;}};
t.bind();t.refresh();
if(body.innerHTML.indexOf('600001')<0 || body.innerHTML.indexOf('600002')<0)throw Error('initial comparison missing candidates');
search.value='Alpha';search.handlers.input();
if(body.innerHTML.indexOf('600001')<0 || body.innerHTML.indexOf('600002')>=0)throw Error('search event did not refresh comparison');
search.value='ZZZ';search.handlers.input();
if(body.innerHTML.indexOf('600001')>=0 || body.innerHTML.indexOf('600002')>=0 || body.innerHTML.indexOf('当前集合没有匹配对象')<0)
  throw Error('empty search event retained stale comparison');
search.value='';search.handlers.input();
if(body.innerHTML.indexOf('600001')<0 || body.innerHTML.indexOf('600002')<0)throw Error('clearing search did not restore comparison');
t.funding();sectorButton.handlers.click({currentTarget:sectorButton});
if(body.innerHTML.indexOf('600001')<0 || body.innerHTML.indexOf('600002')>=0)throw Error('sector event did not refresh comparison');
sectorButton.handlers.click({currentTarget:sectorButton});
if(body.innerHTML.indexOf('600001')<0 || body.innerHTML.indexOf('600002')<0)throw Error('sector clear did not restore comparison');
''')

    def test_u03_formal_pending_excludes_research_waiting_reason_and_unknown_is_not_satisfied(self):
        _assert_node_contract(self, "{ rows:decisionRows,navigation:decisionNavigation,status:getCandidateStatusSummary }", r'''
const formal={id:'formal',code:'600001',name:'正式待确认',page_status:'formal_incomplete',formal_action:'可上车',status_label:'正式推荐·条件待补充',strategy_results:[{strategy_id:'main',role:'formal',formal_action:'可上车',page_status:'formal_incomplete',evidence:{summary:{status:'partial'}}}]};
const research={id:'research',code:'600002',name:'研究观察',page_status:'waiting_trigger',formal_action:null,status_label:'等待条件确认',primary_reason:'等待回踩',strategy_results:[{strategy_id:'confirming',role:'research',formal_action:null,page_status:'waiting_trigger',evidence:{summary:{status:'missing'}}}]};
const projection={items:[formal,research],featured_ids:[]};
const pending=globalThis.__auxTest.rows(projection,'decision_wait');
if(pending.length!==1 || pending[0].code!=='600001')throw Error('research waiting reason entered formal pending view');
const all=globalThis.__auxTest.rows(projection,'decision_all');
const wrappedStatus=globalThis.__auxTest.status(all[0],'decision_all');
if(wrappedStatus.identity.indexOf('正式')<0 || wrappedStatus.condition!=='正式待确认')
  throw Error('workbench wrapper lost formal identity or condition');
const nav=globalThis.__auxTest.navigation();
if(nav.find(function(x){return x.key==='decision_wait';}).label!=='正式待确认')throw Error('formal pending label is ambiguous');
const status=globalThis.__auxTest.status({code:'600002',page_status:'watch_only',primary_reason:'等待回踩',strategy_results:[{strategy_id:'confirming',role:'research',evidence:{summary:{status:'missing'}}}]},'confirming');
if(status.condition!=='条件未声明' || status.evidence!=='证据未完整' || status.risk!=='风险标签未登记')
  throw Error('unstructured waiting text was promoted to satisfied condition');
''')


if __name__ == '__main__':
    unittest.main()
