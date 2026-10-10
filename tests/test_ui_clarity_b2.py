"""B2 list-summary, bound history, and field-difference regressions."""

import hashlib
import json
import unittest
from pathlib import Path

from chanlun.decision_workbench import _changes
from chanlun.report_generator import _load_previous_full_projection
from tests.test_report_membership_comparison import PublishedMembershipComparisonTests
from tests.test_auxiliary_frontend import _assert_node_contract


class B2ProducerTests(PublishedMembershipComparisonTests):
    def test_price_only_record_change_keeps_legacy_changed_but_not_condition(self):
        basis = {"adjustment": "raw", "factor_vs_raw": 1}
        contract = {"strategy_identities": [{"strategy_id": "main", "strategy_version": "v1"}],
                    "strategy_version": {"main": "v1"}}
        row = {"instrument_id": "SH600001", "code": "600001", "page_status": "watch_only",
               "strategy_results": [{"strategy_id": "main", "candidate": {"price_basis": basis}}],
               "reference_price": 10, "formal_action": "仅观察", "action_reason": "等待确认"}
        previous = {"phase": "formal", "report_date": "2026-10-08", "items": [row],
                    "comparison_contract": contract, "membership_status": "available"}
        current = {"phase": "formal", "report_date": "2026-10-09",
                   "items": [dict(row, reference_price=11)], "comparison_contract": contract}
        result = _changes(current, previous)
        self.assertEqual(result["changed"], ["600001"])
        self.assertEqual(result["semantic_changed"], [])
        self.assertEqual(result["value_changed"], ["600001"])
        self.assertEqual(result["condition_comparison"]["changed_count"], 0)
        self.assertNotIn("change_details", result)
        self.assertNotIn("value_unavailable_codes", result)

    def test_semantic_and_verified_price_change_overlap_without_double_counting(self):
        basis = {"adjustment": "raw", "factor_vs_raw": 1}
        contract = {"strategy_identities": [{"strategy_id": "main", "strategy_version": "v1"}],
                    "strategy_version": {"main": "v1"}}
        old = {"instrument_id": "SH600001", "code": "600001", "page_status": "watch_only",
               "strategy_results": [{"strategy_id": "main", "candidate": {"price_basis": basis}}],
               "reference_price": 10, "action_reason": "等待确认"}
        new = dict(old, reference_price=11, action_reason="观察说明更新")
        previous = {"phase": "formal", "report_date": "2026-10-08", "items": [old],
                    "comparison_contract": contract, "membership_status": "available"}
        current = {"phase": "formal", "report_date": "2026-10-09", "items": [new],
                   "comparison_contract": contract}
        result = _changes(current, previous)
        self.assertEqual(result["changed"], ["600001"])
        self.assertEqual(result["semantic_changed"], ["600001"])
        self.assertEqual(result["value_changed"], ["600001"])
        self.assertEqual(result["condition_comparison"]["changed_count"], 1)
        self.assertEqual(result["change_details"]["600001"][0]["field"], "action_reason")

    def test_missing_price_basis_never_promotes_numeric_record_change(self):
        contract = {"strategy_identities": [{"strategy_id": "main", "strategy_version": "v1"}],
                    "strategy_version": {"main": "v1"}}
        old = {"instrument_id": "SH600001", "code": "600001", "page_status": "watch_only",
               "strategy_results": [{"strategy_id": "main"}], "reference_price": 10}
        previous = {"phase": "formal", "report_date": "2026-10-08", "items": [old],
                    "comparison_contract": contract, "membership_status": "available"}
        current = {"phase": "formal", "report_date": "2026-10-09",
                   "items": [dict(old, reference_price=11)], "comparison_contract": contract}
        result = _changes(current, previous)
        self.assertEqual(result["changed"], [])
        self.assertEqual(result["semantic_changed"], [])
        self.assertEqual(result["value_changed"], [])
        self.assertIn("600001", result["value_unavailable_codes"])

    def test_previous_projection_exposes_exact_raw_file_bytes_hash(self):
        html = self.root / self.day / "index.html"
        source = html.read_text()
        marker = "window.CHANLUN_BOOTSTRAP= "
        offset = source.index(marker) + len(marker)
        bootstrap, end = json.JSONDecoder().raw_decode(source, offset)
        bootstrap["decisionWorkbench"]["phase"] = "formal"
        html.write_text(source[:offset] + json.dumps(bootstrap, ensure_ascii=False) + source[end:])
        prior = _load_previous_full_projection(str(self.root), {self.day: {}}, "2026-01-06")
        expected = hashlib.sha256((self.data / (self.day + ".json")).read_bytes()).hexdigest()
        self.assertEqual(prior["comparison_raw_report_bytes_sha256"], expected)
        current = {"phase": "formal", "report_date": "2026-01-06",
                   "comparison_contract": {}, "items": []}
        membership = _changes(current, prior)["membership"]
        self.assertEqual(membership["previous_raw_report_bytes_sha256"], expected)

    def test_known_wording_changes_keep_original_fields_and_price_gap(self):
        contract = {"strategy_identities": [{"strategy_id": "main", "strategy_version": "v1"}],
                    "strategy_version": {"main": "v1"}}
        old = {"instrument_id": "SH605366", "code": "605366", "page_status": "watch_only",
               "strategy_results": [{"strategy_id": "main"}],
               "action_reason": "处于60日低位区间；放量2.4倍；站上MA5/MA10；突破20日平台；涨幅5.4%",
               "primary_reason": "处于60日低位区间；放量2.4倍；站上MA5/MA10；突破20日平台；涨幅5.4%",
               "next_confirmation": [], "invalidation": []}
        new = dict(old, action_reason="涨停当日不追，等待次日回踩确认",
                   primary_reason="涨停当日不追，等待次日回踩确认",
                   next_confirmation=["回踩不破突破位", "30min二买/三买", "缩量回踩后再放量"],
                   invalidation=["跌破启动参考位", "放量长阴破坏结构"])
        previous = {"phase": "formal", "report_date": "2026-09-24", "items": [old],
                    "comparison_contract": contract, "membership_status": "available"}
        current = {"phase": "formal", "report_date": "2026-09-28", "items": [new],
                   "comparison_contract": contract}
        changes = _changes(current, previous)
        self.assertEqual(changes["changed"], ["605366"])
        self.assertIn("605366", changes["value_unavailable_codes"])
        details = changes["change_details"]["605366"]
        by_field = {row["field"]: row for row in details}
        self.assertEqual(by_field["action_reason"]["before"], old["action_reason"])
        self.assertEqual(by_field["action_reason"]["after"], new["action_reason"])
        self.assertEqual(by_field["next_confirmation"]["status"], "newly_recorded")
        self.assertEqual(by_field["invalidation"]["after"], new["invalidation"])

    def test_changed_field_summary_never_copies_unknown_nested_values(self):
        contract = {"strategy_identities": [{"strategy_id": "main", "strategy_version": "v1"}],
                    "strategy_version": {"main": "v1"}}
        base = {"instrument_id": "SH600001", "code": "600001", "page_status": "watch_only",
                "strategy_results": [{"strategy_id": "main"}]}
        old = dict(base, action_reason={"secret_path": "/private/hidden", "candidate": {"kline": [1]}})
        new = dict(base, action_reason="本期只显示文字")
        previous = {"phase": "formal", "report_date": "2026-09-24", "items": [old],
                    "comparison_contract": contract, "membership_status": "available"}
        current = {"phase": "formal", "report_date": "2026-09-28", "items": [new],
                   "comparison_contract": contract}
        row = _changes(current, previous)["change_details"]["600001"][0]
        self.assertEqual(row["field"], "action_reason")
        self.assertIsNone(row["before"])
        self.assertEqual(row["before_readability"], "unreadable")
        self.assertEqual(row["after"], "本期只显示文字")
        self.assertNotIn("/private/hidden", json.dumps(row, ensure_ascii=False))

    def test_frozen_real_macro_workbenches_keep_wording_and_price_gap(self):
        fixture_path = Path(__file__).parent / "fixtures" / "b2_macro_605366_20260924_20260928.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertTrue(fixture["source_commit"].startswith("608457b2"))
        before = fixture["snapshots"]["2026-09-24"]
        after = fixture["snapshots"]["2026-09-28"]
        self.assertTrue(before["source"]["cropped"] and after["source"]["cropped"])
        self.assertEqual(before["source"]["html_size"], 3183272)
        self.assertEqual(after["source"]["html_size"], 2535524)
        changes = _changes(after, before)
        self.assertIn("605366", changes["changed"])
        self.assertIn("605366", changes["value_unavailable_codes"])
        details = {row["field"]: row for row in changes["change_details"]["605366"]}
        self.assertEqual(details["action_reason"]["before"],
                         "处于60日低位区间；放量2.4倍；站上MA5/MA10；突破20日平台；涨幅5.4%")
        self.assertEqual(details["action_reason"]["after"], "涨停当日不追，等待次日回踩确认")
        self.assertEqual(details["next_confirmation"]["status"], "newly_recorded")
        self.assertEqual(details["invalidation"]["after"], ["跌破启动参考位", "放量长阴破坏结构"])
        self.assertNotIn("candidate", json.dumps(changes.get("change_details"), ensure_ascii=False))
        self.assertNotIn("kline", fixture_path.read_text(encoding="utf-8"))


class B2FrontendTests(unittest.TestCase):
    def test_current_detail_opens_bound_target_from_empty_formal_and_blocked_reading_filters(self):
        _assert_node_contract(self,
            "({ open:openCurrentCandidateDetail, setup:normalizeWorkspace, state:state, nodes:nodes, "
            "selection:getCandidateSelection, withViews:function(views,action) { "
            "var original=getCandidateViews; getCandidateViews=function(){return {views:views,meta:{}};}; "
            "try { return action(); } finally { getCandidateViews=original; } } })", r'''
function element() {
  const classes = new Set();
  const node = { children: [], attrs: {}, hidden: false, textContent: '',
    setAttribute: function(k,v) { this.attrs[k]=String(v); },
    getAttribute: function(k) { return this.attrs[k] || null; },
    appendChild: function(x) { this.children.push(x); return x; },
    querySelector: function() { return null; }, querySelectorAll: function() { return []; },
    addEventListener: function() {}, focus: function() {},
    classList: { add: function(k) { classes.add(k); },
      remove: function(k) { classes.delete(k); },
      toggle: function(k,v) { if(v) classes.add(k); else classes.delete(k); },
      contains: function(k) { return classes.has(k); } }
  };
  let html='';
  Object.defineProperty(node,'innerHTML',{get:function(){return html;},
    set:function(v){html=String(v||''); if(!html) this.children=[];}});
  return node;
}
document.createElement=element; document.body=element();
const t=globalThis.__auxTest;
function record(index) {
  const code=String(600000+index), name=index===25?'目标研究股':'股票'+index;
  return { id:'row:'+code, instrument_id:'SH'+code, code:code, name:name,
    sector:index===25?'目标板块':'其他板块', page_status:'watch_only',
    status_label:'研究观察', formal_action:null, is_executable:false,
    candidate:{code:code,name:name,sector:index===25?'目标板块':'其他板块',
      ref:{pool:'baseline',code:code},action_semantics:'watch_only'},
    strategy_results:[{strategy_id:'baseline',role:'research',
      action_semantics:'watch_only',page_status:'watch_only'}]};
}
const rows=Array.from({length:25},function(_,index){return record(index+1);});
const data={date:'2026-10-09',workspace:{default_view:'decision_formal',
  views:{baseline:rows.map(function(row){return row.candidate;})},
  view_meta:{baseline:{role:'research',action_semantics:'watch_only',
    availability:{state:'available'}}}}};
window.CHANLUN_BOOTSTRAP={pageDate:'2026-10-09',decisionWorkbench:{
  schema_version:'decision-workbench-v1',report_date:'2026-10-09',phase:'formal',
  items:rows,featured_ids:[]}};
t.state.data=data; t.setup(data); t.state.currentView='decision_formal';
t.state.candidateQuery=''; t.state.candidateLimit=20;
t.state.sectorFilter='';t.state.sectorFilterCode='';t.state.sectorFilterRefs=[];
t.state.decisionStatusFilter='';t.state.activeItem=null;t.state.activeCandidateKey='';
t.state.detailCandidateKey='';t.state.detailTarget=null;t.state.chartInstance=null;
t.state.chartMount=null;t.state.isMobile=false;
t.nodes.tabs=null;t.nodes.description=null;t.nodes.sectorStrip=null;
t.nodes.candidateList=element();t.nodes.detailPanel=element();
t.nodes.workspaceBody=element();t.nodes.candidateTools=null;
t.nodes.candidateCount=element();t.nodes.candidateMore=element();
t.nodes.candidateSearch=element();t.nodes.candidateSearch.value='';
t.nodes.candidateEvidenceComparison=null;t.nodes.candidateQuickComparison=null;
t.nodes.drawerContent=null;

assert(t.selection('decision_formal').items.length===0,'fixture formal must be empty');
assert(t.open('600025',''), 'default current detail did not open');
let selection=t.selection(t.state.currentView);
assert(t.state.currentView==='decision_all','empty formal view kept current target hidden');
assert(selection.visibleItems.some(function(row){return row.code==='600025';}),
  'target beyond first 20 was not made visible');
assert(t.state.activeItem.workbench_item===selection.items.find(function(row){return row.code==='600025';}).workbench_item,
  'active target is not the selected view row');
assert(!t.nodes.workspaceBody.classList.contains('is-unified-empty'),
  'current detail remains hidden by empty view CSS');
assert(t.nodes.detailPanel.innerHTML.includes('目标研究股'),
  'current target detail was not rendered');
assert(!t.state.activeItem.workbench_item ||
  t.state.activeItem.workbench_item.strategy_results[0].role==='research',
  'research role was promoted to formal');

t.state.currentView='decision_all';t.state.candidateLimit=20;
t.state.candidateQuery='600001';t.nodes.candidateSearch.value='600001';
t.state.sectorFilter='其他板块';t.state.sectorFilterCode='';t.state.sectorFilterRefs=[];
assert(t.open('600025','main'),'resolved main alias kept a target-free formal view');
selection=t.selection(t.state.currentView);
assert(t.state.currentView==='decision_all' && t.state.candidateQuery==='' &&
  t.state.sectorFilter==='' && t.nodes.candidateSearch.value==='',
  'blocking reading filters were not cleared for explicit target');
assert(selection.visibleItems.some(function(row){return row.code==='600025';}) &&
  t.state.activeItem.workbench_item===selection.items.find(function(row){return row.code==='600025';}).workbench_item &&
  t.nodes.detailPanel.innerHTML.includes('目标研究股'),
  'filtered current target was replaced by first row or hidden');

t.state.candidateQuery='目标研究股';t.nodes.candidateSearch.value='目标研究股';
t.state.sectorFilter='目标板块';
assert(t.open('600025','decision_all') && t.state.candidateQuery==='目标研究股'
  && t.state.sectorFilter==='目标板块',
  'matching reading filters were cleared unnecessarily');

rows[0].page_status='formal_ready';rows[0].formal_action='可上车';
rows[0].strategy_results[0].role='formal';
t.state.currentView='decision_formal';t.state.decisionStatusFilter='formal_incomplete';
t.state.candidateQuery='';t.state.sectorFilter='';
assert(t.open('600001','main') && t.state.currentView==='decision_formal'
  && t.state.decisionStatusFilter==='' && t.state.activeItem.code==='600001'
  && t.nodes.detailPanel.innerHTML.includes('股票1'),
  'status filter hid an explicit formal target');

const rawOnly=record(26).candidate;
t.state.currentView='decision_formal';
const aliasOnly={main:[rawOnly],decision_formal:[],decision_all:[],baseline:[]};
t.withViews(aliasOnly,function(){
  assert(!t.open('600026','') && t.state.currentView==='decision_formal',
    'raw main alias bypassed its target-free resolved formal view');
});
const sourceFallback={main:[rawOnly],decision_formal:[],decision_all:[],baseline:[rawOnly]};
t.withViews(sourceFallback,function(){
  assert(t.open('600026','') && t.state.currentView==='baseline'
    && t.selection('baseline').visibleItems.some(function(row){return row.code==='600026';})
    && t.state.activeItem.ref.pool==='baseline',
    'valid source view was not selected after rejecting raw main alias');
});
assert(!t.open('',''), 'empty target code must not open a row');
''')

    def test_structured_price_record_has_separate_count_and_no_condition_claim(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,summary:renderDecisionChangesSummary,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const changes={status:'available',changed:['600001'],semantic_changed:[],value_changed:['600001'],
 condition_comparison:{status:'available',compared_count:1,changed_count:0},
 membership:{status:'available',added:[],removed:[],shared:['600001'],previous_report_date:'2026-10-08',
 previous_phase:'formal',previous_items:{'600001':{code:'600001',name:'甲',sources:['main']}}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[{code:'600001',name:'甲',page_status:'watch_only'}],changes}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render(),summary=t.summary(changes,false);
if(html.indexOf('待确认条件更新 <span>0</span>')<0||html.indexOf('价格相关记录变化 <span>1</span>')<0)
 throw Error('price-only record was counted as condition');
if(html.indexOf('data-change-kind="value"')<0||html.indexOf('状态或条件变化')>=0)
 throw Error('price-only row was labeled as a verified condition');
if(summary.indexOf('条件变化 0')<0||summary.indexOf('价格相关记录变化 1')<0)
 throw Error('summary mixed condition and price record counts');
''')

    def test_semantic_and_price_overlap_stays_one_all_row_with_both_tags(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const changes={status:'available',changed:['600001'],semantic_changed:['600001'],value_changed:['600001'],
 condition_comparison:{status:'available',compared_count:1,changed_count:1},
 change_details:{'600001':[{field:'next_confirmation',before:['旧条件'],after:['新条件'],status:'updated'}]},
 membership:{status:'available',added:[],removed:[],shared:['600001'],previous_report_date:'2026-10-08',
 previous_phase:'formal',previous_items:{'600001':{code:'600001',name:'甲',sources:['main']}}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[{code:'600001',name:'甲'}],changes}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render();
if(html.indexOf('待确认条件更新 <span>1</span>')<0||html.indexOf('价格相关记录变化 <span>1</span>')<0
 || html.indexOf('本期重点 <span>1</span>')<0||(html.match(/data-change-row=/g)||[]).length!==1)
 throw Error('overlap was double counted or lost');
if(html.indexOf('条件更新 · 价格记录')<0)throw Error('overlap lost a distinct price tag');
''')

    def test_legacy_changed_without_structured_arrays_is_visible_but_uncategorized(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,summary:renderDecisionChangesSummary,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const changes={status:'partial',changed:['600001'],
 membership:{status:'available',added:[],removed:[],shared:['600001'],previous_report_date:'2026-10-08',
 previous_phase:'formal',previous_items:{'600001':{code:'600001',name:'甲',sources:['main']}}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[{code:'600001',name:'甲'}],changes}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render(),summary=t.summary(changes,false);
if(html.indexOf('待确认条件更新 <span>—</span>')<0||html.indexOf('旧口径变化（类别未核验） <span>1</span>')<0
 || html.indexOf('data-change-kind="legacy"')<0||html.indexOf('600001')<0)
 throw Error('legacy changed was dropped or mislabeled as a condition');
if(summary.indexOf('条件变化 —')<0||summary.indexOf('旧口径变化 1（类别未核验）')<0)
 throw Error('legacy comparison summary invented a categorized count');
''')

    def test_partially_structured_changed_keeps_uncovered_legacy_member(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,summary:renderDecisionChangesSummary,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const changes={status:'partial',changed:['600001','600002'],semantic_changed:['600001'],value_changed:[],
 condition_comparison:{status:'partial',compared_count:2,changed_count:1},
 membership:{status:'available',added:[],removed:[],shared:['600001','600002'],
 previous_report_date:'2026-10-08',previous_phase:'formal',previous_items:{}},
 change_details:{'600001':[{field:'action_reason',before:'旧说明',after:'新说明',status:'updated'}],
  '600002':[{field:'action_reason',before:'上份说明',after:'本期说明',status:'updated'}]}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[{code:'600001',name:'甲'},{code:'600002',name:'乙'}],changes}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render(),summary=t.summary(changes,false);
if(html.indexOf('理由更新 <span>1</span>')<0||html.indexOf('旧口径变化（类别未核验） <span>1</span>')<0
 || html.indexOf('data-change-row="600002"')<0||html.indexOf('共 2 只')<0)
 throw Error('uncovered old changed entry was dropped');
if(summary.indexOf('旧口径变化 1（类别未核验）')<0)throw Error('summary hid uncovered old entry');
const legacy=html.slice(html.indexOf('data-change-row="600002"'),html.indexOf('id="decision-change-history-600002"'));
if(legacy.indexOf('登记文字差异 1 项，比较依据待核验')<0||legacy.indexOf('已核验文字变化')>=0)
 throw Error('legacy row borrowed verified condition status from another security');
''')

    def test_unavailable_condition_coverage_keeps_semantic_text_without_verified_count(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,summary:renderDecisionChangesSummary,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const changes={status:'partial',changed:['600001'],semantic_changed:['600001'],value_changed:[],
 condition_comparison:{status:'unavailable',compared_count:0,changed_count:null},
 membership:{status:'available',added:[],removed:[],shared:['600001'],previous_report_date:'2026-10-08',
 previous_phase:'formal',previous_items:{'600001':{code:'600001',name:'甲',sources:['main']}}},
 change_details:{'600001':[{field:'action_reason',before:'旧说明',after:'新说明',status:'updated'}]}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[{code:'600001',name:'甲'}],changes}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render(),summary=t.summary(changes,false);
if(html.indexOf('待确认条件更新 <span>—</span>')<0||html.indexOf('登记字段差异待核验 <span>1</span>')<0||html.indexOf('新说明')<0
 || html.indexOf('已核验登记条件变化')>=0||html.indexOf('已核验文字变化')>=0
 || html.indexOf('登记文字差异 1 项，比较依据待核验')<0||summary.indexOf('条件变化 —')<0)
 throw Error('unavailable coverage presented a verified condition count');
''')

    def test_raw_history_requires_same_response_byte_digest(self):
        _assert_node_contract(self, "{ decode:decodeBoundDecisionHistoryBytes }", r'''
const t=globalThis.__auxTest;window.crypto=require('crypto').webcrypto;
const bytes=new TextEncoder().encode(JSON.stringify({date:'2026-09-24',phase:'formal',
 picks_fusion:{candidates:[{code:'605366',action:'bound row'}]}}));
const expected=require('crypto').createHash('sha256').update(bytes).digest('hex');
const copy=bytes.slice();const wordAt=Buffer.from(copy).indexOf('bound row');copy[wordAt]='f'.charCodeAt(0);
Promise.all([t.decode(bytes.buffer,expected),t.decode(copy.buffer,expected).then(()=>{throw Error('mutated bytes accepted');},()=>true)])
 .then(([payload])=>{if(payload.date!=='2026-09-24')throw Error('bound bytes not parsed');});
''')

    def test_history_source_refs_select_only_named_pool_and_exact_row(self):
        _assert_node_contract(self, "{ bound:decisionHistoryBoundEntries }", r'''
const t=globalThis.__auxTest;
const payload={picks_fusion:{candidates:[{code:'605366',action:'exact source'},
 {code:'600001',action:'wrong code'}]},picks_pure:{candidates:[{code:'605366',action:'other source'}]}};
const prior={code:'605366',source_refs:[{view:'highlights',ref:{pool:'picks_fusion',code:'605366',index:0}}]};
let result=t.bound(payload,'605366',prior,{date:'2026-09-24',phase:'formal'});
if(result.status!=='available'||result.entries.length!==1||result.entries[0].record.action!=='exact source')
 throw Error('exact source ref not selected');
prior.source_refs[0].ref.index=1;
result=t.bound(payload,'605366',prior,{});
if(result.status==='available'||result.entries.length)throw Error('wrong index accepted');
delete prior.source_refs[0].ref.index;
payload.picks_fusion.candidates.push({code:'605366',action:'duplicate'});
result=t.bound(payload,'605366',prior,{});
if(result.status==='available'||result.entries.length)throw Error('ambiguous pool/code guessed');
prior.source_refs=[];result=t.bound(payload,'605366',prior,{});
if(result.status==='available'||result.entries.length)throw Error('missing refs guessed');
''')

    def test_whole_module_limits_five_unique_rows_and_filters_real_groups(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-08';
const added=['600001','600002','600003','600004','600005','600006'];
const removed=['600011','600012','600013'];
const changed=['600003','600004'];
const unavailable=['600011','600014'];
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:added.map(code=>({code,name:code})),changes:{status:'partial',
 membership:{status:'available',added,removed,shared:[],previous_report_date:'2026-09-30',
  previous_phase:'formal',previous_items:{}},changed,semantic_changed:changed,value_changed:[],
 condition_comparison:{status:'partial',compared_count:2,changed_count:2},
 change_details:{'600003':[{field:'action_reason',before:'旧三',after:'新三',status:'updated'}],
  '600004':[{field:'action_reason',before:'旧四',after:'新四',status:'updated'}]},
 unavailable_codes:unavailable}}};
t.state.data={date:day};
const buttons={};function button(group){return {handlers:{},getAttribute(k){return k==='data-change-group-toggle'?group:'';},addEventListener(k,f){this.handlers[k]=f;}};}
['all','changed','added','removed','unavailable'].forEach(k=>buttons[k]=button(k));
const target={innerHTML:'',querySelectorAll(sel){return sel==='[data-change-group-toggle]'?Object.values(buttons):[];},querySelector(){return null;}};
t.nodes.decisionChanges=target;let html=t.render();
const count=()=>((target.innerHTML.split('<div class="decision-change-list-footer">')[0]
  .match(/class="decision-change-entry"/g))||[]).length;
if(count()>5)throw Error('default whole module exceeds five securities');
if(html.indexOf('理由更新 <span>2</span>')<0 || html.indexOf('本期新出现')<0 || html.indexOf('上期有、本期未出现')<0)throw Error('complete counts lost');
buttons.removed.handlers.click({currentTarget:buttons.removed});
if(count()>5 || target.innerHTML.indexOf('600012')<0 || target.innerHTML.indexOf('600001')>=0)throw Error('removed filter did not filter actual entries');
''')

    def test_malformed_code_is_locally_ignored_and_name_is_escaped(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-08';
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[{code:'600001',name:'<img src=x onerror=alert(1)>'}],
 changes:{status:'available',membership:{status:'available',added:['__proto__','600001'],removed:[],
 shared:[],previous_report_date:'2026-09-30',previous_phase:'formal'},
 condition_comparison:{status:'available',compared_count:0,changed_count:0}}}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render();
if(html.indexOf('<img')>=0||html.indexOf('&lt;img')<0)throw Error('untrusted name not escaped');
if(html.indexOf('本期新出现 <span>1</span>')<0||html.indexOf('data-change-row="__proto__"')>=0)
 throw Error('malformed code counted or rendered');
''')

    def test_changed_original_wording_is_escaped_and_does_not_hide_price_gap(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-09-28';
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[{code:'605366',name:'宏柏新材'}],changes:{status:'partial',
 membership:{status:'available',added:[],removed:[],shared:['605366'],previous_report_date:'2026-09-24',
 previous_phase:'formal',previous_items:{'605366':{code:'605366',name:'宏柏新材',sources:['highlights']}}},
 condition_comparison:{status:'partial',compared_count:1,changed_count:1},changed:['605366'],
 semantic_changed:['605366'],value_changed:[],
 value_unavailable_codes:['605366'],value_unavailable_reasons:{'605366':'price_basis_missing'},
 change_details:{'605366':[{field:'action_reason',before:'<img src=x onerror=alert(1)>',
 after:'涨停当日不追，等待次日回踩确认',status:'updated'},
 {field:'next_confirmation',before:[],after:['回踩不破突破位'],status:'newly_recorded'}]}}}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render();
if(html.indexOf('<img')>=0||html.indexOf('&lt;img')<0)throw Error('wording HTML injected');
if(html.indexOf('本期补充了该字段')<0||html.indexOf('价基缺失')<0
 || html.indexOf('看上期记录')<0||html.indexOf('<details class="decision-change-field-diffs"')<0)
 throw Error('known textual difference or price limit was hidden');
''')

    def test_unreadable_difference_is_not_labeled_verified_wording(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-09-28';
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[{code:'600001',name:'甲'}],changes:{status:'partial',
 membership:{status:'available',added:[],removed:[],shared:['600001'],previous_report_date:'2026-09-24',
 previous_phase:'formal',previous_items:{'600001':{code:'600001',name:'甲'}}},
 changed:['600001'],semantic_changed:['600001'],value_changed:[],
 condition_comparison:{status:'partial',compared_count:1,changed_count:1},
 change_details:{'600001':[{field:'action_reason',before:null,before_readability:'unreadable',
 after:'本期文字',after_readability:'recorded',status:'unreadable'}]}}}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render();
if(html.indexOf('已核验文字变化 1 项')>=0||html.indexOf('原文不可读')<0
 || html.indexOf('登记字段差异')<0)throw Error('unreadable old field called verified wording');
''')

    def test_duplicate_structured_codes_count_once_per_group_and_in_summary(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,summary:renderDecisionChangesSummary,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-08';
const changes={status:'partial',membership:{status:'available',added:['600001','600001'],
 removed:['600002','600002'],shared:[],previous_report_date:'2026-09-30',previous_phase:'formal',
 previous_items:{'600002':{code:'600002',name:'旧股'}}},
 changed:['600001','600001'],semantic_changed:['600001','600001'],value_changed:[],
 unavailable_codes:['600002','600002'],
 change_details:{'600001':[{field:'action_reason',before:'旧理由',after:'新理由',status:'updated'}]},
 condition_comparison:{status:'partial',compared_count:1,changed_count:1}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[{code:'600001',name:'新股'}],changes}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render(),summary=t.summary(changes,false);
for(const label of ['理由更新','本期新出现','上期有、本期未出现','部分字段不可比较']){
 if(html.indexOf(label+' <span>1</span>')<0)throw Error('duplicate group count: '+label);
}
if(summary.indexOf('新增 1')<0||summary.indexOf('移出 1')<0
 || summary.indexOf('条件变化 0')<0||summary.indexOf('理由变化 1')<0)
 throw Error('summary still counted duplicate source rows');
if((html.match(/data-change-row=/g)||[]).length!==2)throw Error('duplicate visible securities');
''')

    def test_removed_research_role_from_bound_summary_is_visible(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-08';
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[],changes:{status:'partial',membership:{status:'available',
 added:[],removed:['600072'],shared:[],previous_report_date:'2026-09-30',previous_phase:'formal',
 previous_items:{'600072':{code:'600072',name:'中船科技',sources:['highlights'],
 strategy_results:[{strategy_id:'highlights',role:'research'}]}}}}}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render();
if(html.indexOf('中船科技')<0||html.indexOf('研究观察')<0)
 throw Error('bound research role was hidden for removed member');
''')

    def test_show_all_and_collapse_change_visible_rows_without_touching_counts(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-08';
const added=['600001','600002','600003','600004','600005','600006','600007'];
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:added.map(code=>({code,name:code})),changes:{status:'available',
 membership:{status:'available',added,removed:[],shared:[],previous_report_date:'2026-09-30',previous_phase:'formal'},
 condition_comparison:{status:'available',compared_count:0,changed_count:0}}}};
t.state.data={date:day};const button={handlers:{},addEventListener(k,f){this.handlers[k]=f;}};
const target={innerHTML:'',querySelectorAll(sel){return sel==='[data-change-show-all]'?[button]:[];},querySelector(){return null;}};
t.nodes.decisionChanges=target;
const count=()=>((target.innerHTML.match(/class="decision-change-entry"/g))||[]).length;
t.render();if(count()!==5||target.innerHTML.indexOf('本期新出现 <span>7</span>')<0)throw Error('default count wrong');
button.handlers.click();if(count()!==7||target.innerHTML.indexOf('收起')<0)throw Error('show all did not expand');
button.handlers.click();if(count()!==5||target.innerHTML.indexOf('查看全部')<0)throw Error('collapse did not restore five');
''')

    def test_history_buttons_declare_local_panel_and_initially_collapsed(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-08';
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[],changes:{status:'partial',
 membership:{status:'available',added:[],removed:['600072'],shared:[],previous_report_date:'2026-09-30',
 previous_phase:'formal',previous_items:{'600072':{code:'600072',name:'中船科技',sources:['main']}}}}}};
t.state.data={date:day};const target={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=target;const html=t.render();
if(!/data-change-history="600072"[^>]*aria-expanded="false"[^>]*aria-controls="decision-change-history-600072"/.test(html)
 || !/id="decision-change-history-600072"[^>]*hidden/.test(html))
 throw Error('history trigger does not declare a collapsed local panel');
''')

    def test_history_close_restores_clicked_trigger_focus_and_aria(self):
        _assert_node_contract(self, "{ load:loadDecisionChangeHistory,state:state }", r'''
const t=globalThis.__auxTest,day='2026-10-08';
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',items:[],changes:{status:'partial',
 membership:{status:'available',added:[],removed:['600072'],shared:[],previous_report_date:'2026-09-30',
 previous_phase:'formal',previous_items:{'600072':{code:'600072',name:'中船科技',sources:['main']}}}}}};
t.state.data={date:day,workspace:{views:{}}};
const close={handlers:{},addEventListener(k,f){this.handlers[k]=f;}};
const panel={innerHTML:'',hidden:true,querySelector(sel){return sel==='[data-change-history-close]'?close:null;}};
const trigger={attrs:{},setAttribute(k,v){this.attrs[k]=v;},focus(){this.focused=true;}};
const target={querySelector(sel){return sel==='.decision-change-history'?panel:trigger;},
 querySelectorAll(sel){return sel==='[data-change-history]'?[trigger]:[];}};
t.load('600072',target,trigger);
if(panel.hidden||trigger.attrs['aria-expanded']!=='true'||!close.handlers.click)
 throw Error('history did not expand next to selected row');
close.handlers.click();
if(!panel.hidden||trigger.attrs['aria-expanded']!=='false'||!trigger.focused)
 throw Error('history close did not restore actual trigger focus');
''')

    def test_history_reads_only_bound_bytes_and_keeps_previous_overview(self):
        _assert_node_contract(self, "{ load:loadDecisionChangeHistory,state:state }", r'''
const t=globalThis.__auxTest,day='2026-10-08';window.crypto=require('crypto').webcrypto;
const previous={date:'2026-09-30',data_quality:{is_official:true,bar_state:'closed'},
 picks_fusion:{candidates:[{code:'600072',name:'中船科技',action:'上份原始动作',
 primary_reason:'上份原始依据'}]}};
const bytes=new TextEncoder().encode(JSON.stringify(previous));
const digest=require('crypto').createHash('sha256').update(bytes).digest('hex');
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',snapshot_id:'current',items:[],changes:{status:'partial',
 membership:{status:'available',added:[],removed:['600072'],shared:[],
 previous_report_date:'2026-09-30',previous_phase:'formal',previous_raw_report_bytes_sha256:digest,
 previous_items:{'600072':{code:'600072',name:'中船科技',sources:['highlights'],
 source_refs:[{view:'highlights',ref:{pool:'picks_fusion',code:'600072'}}]}}}}}};
t.state.data={date:day,workspace:{views:{}}};
const panel={innerHTML:'',hidden:true,querySelector(){return null;},querySelectorAll(){return [];}};
const target={querySelector(){return panel;},querySelectorAll(){return [];}};
let fetchCount=0;window.fetch=function(url){fetchCount++;if(url!=='data/2026-09-30.json')throw Error('wrong raw path');
 return Promise.resolve({ok:true,arrayBuffer(){return Promise.resolve(bytes.buffer);},json(){throw Error('json bypassed bytes');}});};
t.load('600072',target);
setTimeout(()=>{if(fetchCount!==1||panel.innerHTML.indexOf('上份原始动作')<0
 || panel.innerHTML.indexOf('中船科技')<0)throw Error('bound historical row or overview missing: '+panel.innerHTML.slice(-500));},20);
''')

    def test_receipt_without_exact_refs_stays_on_overview_without_fetch(self):
        _assert_node_contract(self, "{ load:loadDecisionChangeHistory,state:state }", r'''
const t=globalThis.__auxTest,day='2026-10-08';window.crypto=require('crypto').webcrypto;
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',snapshot_id:'current',items:[],changes:{status:'partial',
 membership:{status:'available',source:'published_receipt',added:[],removed:['600072'],shared:[],
 previous_report_date:'2026-09-30',previous_phase:'formal',
 previous_raw_report_bytes_sha256:'a'.repeat(64),previous_items:{'600072':{code:'600072',
 name:'中船科技',sources:['main'],source_refs:[{view:'main'}]}}}}}};
t.state.data={date:day,workspace:{views:{}}};
const panel={innerHTML:'',hidden:true,querySelector(){return null;}};
const target={querySelector(){return panel;},querySelectorAll(){return [];}};
let requested=0;window.fetch=()=>{requested++;throw Error('receipt ref unexpectedly fetched');};
t.load('600072',target);
if(requested||panel.innerHTML.indexOf('中船科技')<0||panel.innerHTML.indexOf('原始条件缺少完整绑定依据')<0)
 throw Error('receipt did not stay on bound overview');
''')

    def test_missing_raw_phase_cannot_be_rendered_as_full_previous_record(self):
        _assert_node_contract(self, "{ load:loadDecisionChangeHistory,state:state }", r'''
const t=globalThis.__auxTest,day='2026-10-08';window.crypto=require('crypto').webcrypto;
const previous={date:'2026-09-30',picks_fusion:{candidates:[{code:'600072',action:'unverified phase action'}]}};
const bytes=new TextEncoder().encode(JSON.stringify(previous));
const digest=require('crypto').createHash('sha256').update(bytes).digest('hex');
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',snapshot_id:'current',items:[],changes:{status:'partial',
 membership:{status:'available',added:[],removed:['600072'],shared:[],previous_report_date:'2026-09-30',
 previous_phase:'formal',previous_raw_report_bytes_sha256:digest,previous_items:{'600072':{code:'600072',
 name:'中船科技',sources:['highlights'],source_refs:[{view:'highlights',ref:{pool:'picks_fusion',code:'600072'}}]}}}}}};
t.state.data={date:day,workspace:{views:{}}};
const panel={innerHTML:'',hidden:true,querySelector(){return null;}};
const target={querySelector(){return panel;},querySelectorAll(){return [];}};
window.fetch=()=>Promise.resolve({ok:true,arrayBuffer(){return Promise.resolve(bytes.buffer);}});
t.load('600072',target);
setTimeout(()=>{if(panel.innerHTML.indexOf('unverified phase action')>=0||panel.innerHTML.indexOf('中船科技')<0)
 throw Error('date-only raw result was treated as formal full history');},20);
''')

    def test_async_history_update_restores_title_focus_only_when_focus_stayed_inside(self):
        _assert_node_contract(self, "{ load:loadDecisionChangeHistory,state:state }", r'''
const t=globalThis.__auxTest,day='2026-10-08';window.crypto=require('crypto').webcrypto;
const prior={date:'2026-09-30',data_quality:{is_official:true,bar_state:'closed'},
 picks_fusion:{candidates:[{code:'600072',action:'原动作'}]}};
const bytes=new TextEncoder().encode(JSON.stringify(prior));
const digest=require('crypto').createHash('sha256').update(bytes).digest('hex');
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',snapshot_id:'current',items:[],changes:{status:'partial',
 membership:{status:'available',added:[],removed:['600072'],shared:[],previous_report_date:'2026-09-30',
 previous_phase:'formal',previous_raw_report_bytes_sha256:digest,previous_items:{'600072':{code:'600072',
 name:'中船科技',sources:['highlights'],source_refs:[{view:'highlights',ref:{pool:'picks_fusion',code:'600072'}}]}}}}}};
t.state.data={date:day,workspace:{views:{}}};let focused=0;
const panel={innerHTML:'',hidden:true,contains(el){return !!(el&&el.inside);},
 querySelector(sel){if(sel!=='.decision-history-timeline h3')return null;
 return {inside:true,focus(){focused++;document.activeElement=this;},scrollIntoView(){}};}};
const target={querySelector(){return panel;},querySelectorAll(){return [];}};
let resolveFetch;window.fetch=()=>new Promise(resolve=>resolveFetch=resolve);
t.load('600072',target);
if(focused!==1)throw Error('initial title not focused');
resolveFetch({ok:true,arrayBuffer(){return Promise.resolve(bytes.buffer);}});
setTimeout(()=>{
 if(focused!==2)throw Error('async replacement dropped title focus');
 t.load('600072',target);if(focused!==3)throw Error('second open did not focus title');
 document.activeElement={inside:false};
 resolveFetch({ok:true,arrayBuffer(){return Promise.resolve(bytes.buffer);}});
 setTimeout(()=>{if(focused!==3)throw Error('async update stole focus after user moved away');},20);
},20);
''')

    def test_pending_history_response_cannot_outlive_source_ref_change(self):
        _assert_node_contract(self, "{ load:loadDecisionChangeHistory,state:state }", r'''
const t=globalThis.__auxTest,day='2026-10-08';window.crypto=require('crypto').webcrypto;
const previous={date:'2026-09-30',data_quality:{is_official:true,bar_state:'closed'},
 picks_fusion:{candidates:[{code:'600072',action:'stale action'}]},
 picks_pure:{candidates:[{code:'600072',action:'new ref action'}]}};
const bytes=new TextEncoder().encode(JSON.stringify(previous));
const digest=require('crypto').createHash('sha256').update(bytes).digest('hex');
const item={code:'600072',name:'中船科技',sources:['highlights'],
 source_refs:[{view:'highlights',ref:{pool:'picks_fusion',code:'600072'}}]};
const changes={status:'partial',membership:{status:'available',added:[],removed:['600072'],shared:[],
 previous_report_date:'2026-09-30',previous_phase:'formal',previous_raw_report_bytes_sha256:digest,
 previous_items:{'600072':item}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',snapshot_id:'current',items:[],changes}};
t.state.data={date:day,workspace:{views:{}}};
const panel={innerHTML:'',hidden:true,querySelector(){return null;},querySelectorAll(){return [];}};
const target={querySelector(){return panel;},querySelectorAll(){return [];}};
let resolveFetch;window.fetch=()=>new Promise(resolve=>resolveFetch=resolve);
t.load('600072',target);
item.source_refs[0].ref.pool='picks_pure';
resolveFetch({ok:true,arrayBuffer(){return Promise.resolve(bytes.buffer);}});
setTimeout(()=>{if(panel.innerHTML.indexOf('stale action')>=0||panel.innerHTML.indexOf('new ref action')>=0)
 throw Error('prior response used a changed source ref');},20);
''')

    def test_pending_history_response_cannot_outlive_raw_digest_change(self):
        _assert_node_contract(self, "{ load:loadDecisionChangeHistory,state:state }", r'''
const t=globalThis.__auxTest,day='2026-10-08';window.crypto=require('crypto').webcrypto;
const previous={date:'2026-09-30',data_quality:{is_official:true,bar_state:'closed'},
 picks_fusion:{candidates:[{code:'600072',action:'stale action'}]}};
const bytes=new TextEncoder().encode(JSON.stringify(previous));
const digest=require('crypto').createHash('sha256').update(bytes).digest('hex');
const membership={status:'available',added:[],removed:['600072'],shared:[],
 previous_report_date:'2026-09-30',previous_phase:'formal',previous_raw_report_bytes_sha256:digest,
 previous_items:{'600072':{code:'600072',name:'中船科技',sources:['highlights'],
 source_refs:[{view:'highlights',ref:{pool:'picks_fusion',code:'600072'}}]}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',snapshot_id:'current',items:[],changes:{status:'partial',membership}}};
t.state.data={date:day,workspace:{views:{}}};
const panel={innerHTML:'',hidden:true,querySelector(){return null;}};
const target={querySelector(){return panel;},querySelectorAll(){return [];}};
let resolveFetch;window.fetch=()=>new Promise(resolve=>resolveFetch=resolve);
t.load('600072',target);membership.previous_raw_report_bytes_sha256='b'.repeat(64);
resolveFetch({ok:true,arrayBuffer(){return Promise.resolve(bytes.buffer);}});
setTimeout(()=>{if(panel.innerHTML.indexOf('stale action')>=0)
 throw Error('prior digest response overwrote new binding');},20);
''')

    def test_two_stock_history_requests_keep_only_latest_visible_detail(self):
        _assert_node_contract(self, "{ load:loadDecisionChangeHistory,state:state }", r'''
const t=globalThis.__auxTest,day='2026-10-08';window.crypto=require('crypto').webcrypto;
const prior={date:'2026-09-30',data_quality:{is_official:true,bar_state:'closed'},
 picks_fusion:{candidates:[{code:'600001',action:'old first action'},
 {code:'600002',action:'new second action'}]}};
const bytes=new TextEncoder().encode(JSON.stringify(prior));
const digest=require('crypto').createHash('sha256').update(bytes).digest('hex');
const members={};['600001','600002'].forEach(code=>members[code]={code,name:code,sources:['highlights'],
 source_refs:[{view:'highlights',ref:{pool:'picks_fusion',code}}]});
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
 report_date:day,phase:'formal',snapshot_id:'current',items:[],changes:{status:'partial',
 membership:{status:'available',added:[],removed:['600001','600002'],shared:[],
 previous_report_date:'2026-09-30',previous_phase:'formal',previous_raw_report_bytes_sha256:digest,
 previous_items:members}}}};
t.state.data={date:day,workspace:{views:{}}};
function holder(){const panel={innerHTML:'',hidden:true,querySelector(){return null;}};
 return {panel,querySelector(){return panel;},querySelectorAll(){return [];}};}
const first=holder(),second=holder(),pending=[];
window.fetch=()=>new Promise(resolve=>pending.push(resolve));
t.load('600001',first);t.load('600002',second);
pending[1]({ok:true,arrayBuffer(){return Promise.resolve(bytes.buffer);}});
pending[0]({ok:true,arrayBuffer(){return Promise.resolve(bytes.buffer);}});
setTimeout(()=>{if(second.panel.innerHTML.indexOf('new second action')<0
 || first.panel.innerHTML.indexOf('old first action')>=0)
 throw Error('late first-stock response overwrote latest detail');},25);
''')


if __name__ == "__main__":
    unittest.main()
