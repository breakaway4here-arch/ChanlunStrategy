"""B2 page behavior on fixed published-workbench inputs."""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract
from tests.test_psy12_shadow_frontend import _valid_market_fixture


class ReadabilityB2Tests(unittest.TestCase):
    def test_live_header_market_bar_mounts_one_base_psy_sentence(self):
        _assert_node_contract(self, "{ render:renderHeader,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest;
const mount={innerHTML:''};
t.nodes.headerTitle={textContent:''};t.nodes.headerSubtitle={textContent:''};
t.nodes.headerMetrics={innerHTML:''};t.nodes.marketDecisionSummary=mount;
t.nodes.marketIcepoint=null;t.nodes.marketEvidence=null;
window.CHANLUN_BOOTSTRAP={pageDate:'2026-10-09'};
const actual=JSON.parse(fs.readFileSync('docs/data/2026-10-09.json','utf8'));
assert(actual.psy12.status==='available'&&actual.psy12.up_days===7
  &&actual.psy12.valid_days===12,'real report fixture changed');
t.state.data=actual;t.render();
assert((mount.innerHTML.match(/class="psy12-basic-sentence"/g)||[]).length===1,
  'live market bar omitted or duplicated PSY basis');
assert(mount.innerHTML.includes('最近12个有效观察日中，有7天指数平均上涨（上涨日占比58.3%）'),
  'real report PSY meaning did not reach live bar');
assert(!mount.innerHTML.includes('影子分</span>')&&!mount.innerHTML.includes('affects_production'),
  'shadow contract leaked into default market bar');
t.state.data={date:'2026-10-09',psy12:{status:'available',valid_days:12,up_days:0,score:0}};
t.render();
assert((mount.innerHTML.match(/class="psy12-basic-sentence"/g)||[]).length===1
  &&mount.innerHTML.includes('有0天指数平均上涨（上涨日占比0%）'),
  'true zero was lost or appended twice');
t.state.data={date:'2026-10-09',psy12:{status:'unavailable',valid_days:7,up_days:null,score:null}};
t.render();
assert((mount.innerHTML.match(/class="psy12-basic-sentence"/g)||[]).length===1
  &&mount.innerHTML.includes('有效观察记录不足，暂不统计')
  &&!mount.innerHTML.includes('有0天'),
  'missing base was rendered as zero or stale prior report');
''')

    def test_source_only_change_is_secondary_with_honest_empty_focus(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const changes={status:'available',semantic_changed:[],value_changed:[],
  condition_comparison:{status:'available',compared_count:1,changed_count:0},
  membership:{status:'available',added:[],removed:[],shared:['600001'],
    previous_report_date:'2026-10-08',previous_phase:'formal',source:'published_html_bootstrap',
    previous_items:{'600001':{code:'600001',name:'甲',sources:['main']}}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',items:[{code:'600001',name:'甲',sources:['observation_top5']}],changes}};
t.state.data={date:day};t.nodes.decisionChanges={innerHTML:'',querySelectorAll(){return [];}};
const html=t.render();
const main=html.slice(0,html.indexOf('decision-change-secondary'));
assert(main.includes('本期没有已核验的新出现或条件更新'),'source-only became a focus');
assert(!main.includes('data-change-row="600001"'),'source-only row visible by default');
assert(html.includes('来源记录更新 <span>1</span>')
  &&html.includes('data-change-row="600001"'),'source-only detail lost');
''')

    def test_unexplained_semantic_change_is_unverified_not_supplement(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,summary:renderDecisionChangesSummary,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const changes={status:'partial',semantic_changed:['600001'],value_changed:[],
  condition_comparison:{status:'partial',compared_count:1,changed_count:1},
  membership:{status:'available',added:[],removed:[],shared:['600001'],
    previous_report_date:'2026-10-08',previous_phase:'formal',source:'published_html_bootstrap',
    previous_items:{'600001':{code:'600001',name:'甲',sources:['main']}}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',items:[{code:'600001',name:'甲',sources:['main']}],changes}};
t.state.data={date:day};t.nodes.decisionChanges={innerHTML:'',querySelectorAll(){return [];}};
const html=t.render(),summary=t.summary(changes,false);
assert(html.includes('登记字段差异待核验 <span>1</span>')
  &&html.includes('本期可核验变化不足'),'missing field diff was not identified');
assert(!html.includes('本期补充了登记字段')&&!summary.includes('本期补充字段 1'),
  'missing diff falsely called a newly recorded field');
''')

    def test_reason_only_update_keeps_originals_without_condition_claim(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,summary:renderDecisionChangesSummary,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const changes={status:'available',semantic_changed:['600001'],value_changed:[],
  change_details:{'600001':[{field:'primary_reason',before:'上期理由原文',after:'本期理由原文',
    before_readability:'recorded',after_readability:'recorded',status:'updated'}]},
  condition_comparison:{status:'available',compared_count:1,changed_count:1},
  membership:{status:'available',added:[],removed:[],shared:['600001'],
    previous_report_date:'2026-10-08',previous_phase:'formal',source:'published_html_bootstrap',
    previous_items:{'600001':{code:'600001',name:'甲',sources:['main']}}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',items:[{code:'600001',name:'甲',sources:['main'],
    primary_reason:'本期理由原文',next_confirmation:['原条件未变']}],changes}};
t.state.data={date:day};t.nodes.decisionChanges={innerHTML:'',querySelectorAll(){return [];}};
const html=t.render(),summary=t.summary(changes,false);
assert(html.includes('理由更新 <span>1</span>')&&html.includes('data-change-kind="reason"'),
  'reason update missing from semantic focus');
assert(html.includes('上期：上期理由原文；本期：本期理由原文'),'original wording lost');
assert(html.includes('待确认条件更新 <span>0</span>')&&summary.includes('条件变化 0')
  &&summary.includes('理由变化 1'),'reason-only text was called a condition update');
''')

    def test_condition_precedes_reason_and_status_uses_its_own_label(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,summary:renderDecisionChangesSummary,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const details={
  '600001':[{field:'next_confirmation',before:['旧条件'],after:['新条件'],status:'updated'}],
  '600002':[{field:'primary_reason',before:'旧理由',after:'新理由',status:'updated'}],
  '600003':[{field:'page_status',before:'watch_only',after:'waiting_trigger',status:'updated'}]};
const changes={status:'available',semantic_changed:['600002','600003','600001'],value_changed:[],
  change_details:details,condition_comparison:{status:'available',compared_count:3,changed_count:3},
  membership:{status:'available',added:[],removed:[],shared:['600001','600002','600003'],
    previous_report_date:'2026-10-08',previous_phase:'formal',source:'published_html_bootstrap',
    previous_items:{}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',items:['600001','600002','600003'].map(code=>({code,name:code})),changes}};
t.state.data={date:day};t.nodes.decisionChanges={innerHTML:'',querySelectorAll(){return [];}};
const html=t.render(),summary=t.summary(changes,false);
const focus=html.slice(0,html.indexOf('decision-change-secondary'));
assert(focus.indexOf('data-change-row="600001"')<focus.indexOf('data-change-row="600002"')
  &&focus.indexOf('data-change-row="600002"')<focus.indexOf('data-change-row="600003"'),
  'semantic priorities did not put real condition first');
assert(html.includes('待确认条件更新 <span>1</span>')&&html.includes('理由更新 <span>1</span>')
  &&html.includes('状态或动作更新 <span>1</span>'),'field classes were merged');
assert(summary.includes('条件变化 1')&&summary.includes('理由变化 1')
  &&summary.includes('状态或动作变化 1'),'header summary mislabeled a field');
''')

    def test_default_focuses_verified_changes_and_keeps_other_records_accessible(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest, day='2026-10-09';
const items=Array.from({length:7},(_,i)=>({code:String(600001+i),name:'本期'+i,
  action_reason:'已登记理由'+i,next_confirmation:['核对量能','核对结构','第三项'],sources:['main']}));
const previous={}; previous['600001']={code:'600001',name:'旧名',sources:['main']};
previous['600099']={code:'600099',name:'已退出',sources:['main']};
const changes={status:'available',semantic_changed:['600001'],value_changed:['600007'],
  change_details:{'600001':[{field:'next_confirmation',before:['旧条件'],after:['新条件'],status:'updated',
    before_readability:'recorded',after_readability:'recorded'}]},
  condition_comparison:{status:'available',compared_count:1,changed_count:1},
  membership:{status:'available',added:items.slice(1).map(x=>x.code),removed:['600099'],
    shared:['600001'],previous_items:previous,previous_report_date:'2026-10-08',
    previous_phase:'formal',source:'published_html_bootstrap'}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',items,changes}};
t.state.data={date:day};const mount={innerHTML:'',querySelectorAll(){return [];}};
t.nodes.decisionChanges=mount;const html=t.render();
assert(html.includes('本期值得重看的变化'),'wrong title');
assert(html.includes('2026-10-08')&&html.includes(day)&&html.includes('全部已发布候选'),'scope absent');
const visible=html.split('<div class="decision-change-list-footer">')[0];
assert((visible.match(/data-change-row=/g)||[]).length===5,'default is not five');
assert(visible.indexOf('data-change-row="600001"')<visible.indexOf('data-change-row="600002"'),
  'verified condition did not precede new member');
assert(!visible.includes('data-change-row="600099"')&&!visible.includes('data-change-row="600007"'),
  'old exit or price-only record displaced the focus');
assert(html.includes('上期有、本期未出现')&&html.includes('价格相关记录变化'),
  'secondary records lost');
assert(visible.includes('已登记理由')&&visible.includes('核对量能')&&visible.includes('核对结构')
  &&!visible.includes('第三项'),'reason or bounded recorded conditions absent');
assert(visible.includes('查看个股')&&html.includes('看上期记录'),'actions unclear');
''')

    def test_source_change_stays_shared_and_new_field_is_not_claimed_as_strategy_change(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const changes={status:'partial',semantic_changed:['600001'],value_changed:[],
  change_details:{'600001':[{field:'next_confirmation',before:[],after:['本期补录'],
    status:'newly_recorded',before_readability:'not_recorded',after_readability:'recorded'}]},
  condition_comparison:{status:'partial',compared_count:1,changed_count:1},
  membership:{status:'available',added:[],removed:[],shared:['600001'],
    previous_report_date:'2026-10-08',previous_phase:'formal',source:'published_html_bootstrap',
    previous_items:{'600001':{code:'600001',name:'甲',sources:['main']}}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',items:[{code:'600001',name:'甲',sources:['observation_top5'],
    action_reason:'观察原因',next_confirmation:['本期补录']}],changes}};
t.state.data={date:day};t.nodes.decisionChanges={innerHTML:'',querySelectorAll(){return [];}};
const html=t.render();
assert(html.includes('来源记录更新'),'shared member source update hidden');
assert(!html.includes('本期新出现 <span>1</span>')&&!html.includes('上期有、本期未出现 <span>1</span>'),
  'source swap was called a whole-list enter or exit');
assert(html.includes('本期补充了该字段')&&!html.includes('已核验登记条件变化'),
  'newly recorded field was called a verified strategy change: '+html.slice(0,1400));
''')

    def test_unknown_membership_and_condition_never_fabricate_zero(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',items:[{code:'600001',name:'甲'}],
  changes:{status:'comparison_unavailable',added:['600001'],membership:{status:'unavailable',
    added:null,removed:null,reason:'no_previous_report',source:'legacy_json_view'}}}};
t.state.data={date:day};t.nodes.decisionChanges={innerHTML:'',querySelectorAll(){return [];}};
const html=t.render();
assert(html.includes('本期可核验变化不足'),'unknown was described as no change');
assert(!html.includes('本期没有已核验的新出现或条件更新'),'false complete comparison');
assert(html.includes('旧视图比较记录（完整成员未核验）')
  &&html.indexOf('data-change-row="600001"')>html.indexOf('decision-change-secondary'),
  'legacy local row was promoted to a verified focus');
assert(html.includes('查看个股')||html.includes('当前个股'),'current candidate route lost');
''')

    def test_conflicting_member_directions_are_not_both_claimed(self):
        _assert_node_contract(self, "{ render:renderDecisionChangesPanel,summary:renderDecisionChangesSummary,state:state,nodes:nodes }", r'''
const t=globalThis.__auxTest,day='2026-10-09';
const changes={status:'partial',semantic_changed:[],value_changed:[],
  condition_comparison:{status:'partial',compared_count:0,changed_count:0},
  membership:{status:'available',added:['600001','600002'],removed:['600001','600003'],shared:[],
    previous_report_date:'2026-10-08',previous_phase:'formal',source:'published_html_bootstrap',
    previous_items:{'600001':{code:'600001',name:'冲突股',sources:['main']},
      '600003':{code:'600003',name:'上期股',sources:['main']}}}};
window.CHANLUN_BOOTSTRAP={pageDate:day,decisionWorkbench:{schema_version:'decision-workbench-v1',
  report_date:day,phase:'formal',items:[{code:'600001',name:'冲突股'},
    {code:'600002',name:'本期股'}],changes}};
t.state.data={date:day};t.nodes.decisionChanges={innerHTML:'',querySelectorAll(){return [];}};
const html=t.render(),summary=t.summary(changes,false);
assert(html.includes('本期新出现 <span>1</span>')&&html.includes('上期有、本期未出现 <span>1</span>')
  &&html.includes('成员进出记录冲突 <span>1</span>'),'conflict not isolated');
assert((html.match(/data-change-row="600001"/g)||[]).length===1,'conflict duplicated');
assert(summary.includes('新增 1')&&summary.includes('移出 1')&&summary.includes('成员记录冲突 1'),
  'summary counted conflicting member as both entering and exiting');
''')

    def test_history_summary_keeps_original_sources_under_one_closed_section(self):
        _assert_node_contract(self, "{ history:renderDecisionChangeHistory }", r'''
const t=globalThis.__auxTest;
const before=[{source:'正式主推',record:{code:'600001',primary_reason:'上期原文理由',
  strategy_results:[{strategy_id:'main',role:'formal',primary_reason:'上期来源理由'}]}}];
const after=[{source:'研究观察',record:{code:'600001',primary_reason:'本期原文理由',
  strategy_results:[{strategy_id:'observation_top5',role:'research',primary_reason:'本期来源理由'}]}}];
const html=t.history('600001',after,before,{current:{date:'2026-10-09',phase:'formal'},
  previous:{date:'2026-10-08',phase:'formal'},changeDetails:[{field:'action_reason',
    before:'旧条件原文',after:'新条件原文',status:'updated'}]});
assert(html.includes('上期理由：')&&html.includes('上期原文理由')
  &&html.includes('本期理由：')&&html.includes('本期原文理由'),
  'short reasons were lost');
assert(html.includes('旧条件原文')&&html.includes('新条件原文'),
  'actual difference was replaced with a generic label');
assert(html.includes('<details class="decision-history-raw"><summary>原始记录与依据</summary>')
  &&html.includes('正式主推')&&html.includes('观察 Top5'),
  'bound source records were merged or removed');
''')

    def test_shadow_remains_folded_without_a_second_basic_sentence(self):
        _assert_node_contract(self, "{ market:renderMarketTemperatureCard,stacks:buildAuxiliaryStacks }",
                              _valid_market_fixture() + r'''
const t=globalThis.__auxTest;
const data=Object.assign({},base,{psy12_shadow:Object.assign({},base.psy12_shadow,{
  status:'unavailable',reason:'missing_formal_components',missing_formal_components:['turnover'],
  shadow_score_with_psy12:null,delta_vs_formal:null})});
const market=t.market(data),research=t.stacks(data).research;
assert(!market.includes('class="psy12-basic-sentence"'),
  'inactive market card kept a second default PSY sentence');
assert(market.includes('<details class="psy12-market-advanced"><summary>实验与运行详情</summary>')
  &&!market.includes('<details class="psy12-market-advanced" open'),
  'shadow audit is still expanded by default');
assert(research.includes('成交额组件不可用')&&research.includes('影子评测进度'),
  'shadow limits no longer accessible');
''')


if __name__ == "__main__":
    unittest.main()
