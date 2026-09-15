"""User-visible stock facts must preserve dates, units and strategy identity."""
import json
import unittest

from chanlun.report_generator import _serialize_picks
from chanlun.report_view_model import build_workspace
from tests.test_auxiliary_frontend import _assert_node_contract


class CandidateBasicInfoTests(unittest.TestCase):
    def test_legacy_reference_close_is_never_used_as_current_price(self):
        _assert_node_contract(self, "{render:renderCandidateBasicInfo,state:state}", r'''
const t=globalThis.__auxTest;t.state.data={date:'2026-09-11'};
const item={close:20,reference_price:20,closes:[30,31.2],price_basis:{adjustment:'qfq'},
 data_status:{daily:'verified',latest_date:'2026-09-11',is_final:true,stale:false}};
const html=t.render(item,true);
assert(html.includes('31.20')&&!html.includes('20.00'),'reference close became current price');
assert(html.includes('前复权'),'object basis lost');
delete item.closes;
assert(!t.render(item,true).includes('20.00'),'reference-only record became a quote');
''')

    def test_price_basis_is_recovered_only_from_same_verified_source_price(self):
        _assert_node_contract(self, "{render:renderCandidateBasicInfo,state:state}", r'''
const t=globalThis.__auxTest;
const status={daily:'verified',latest_date:'2026-09-11',is_final:true,stale:false};
const raw={code:'002600',current_price:13.12,data_status:{...status,adjustment:'qfq'}};
t.state.data={date:'2026-09-11',picks_pure:[raw]};
const item={code:'002600',current_price:13.12,data_status:status,ref:{pool:'picks_pure',code:'002600'}};
assert(t.render(item,true).includes('前复权'),'verified basis dropped');
raw.current_price=15;
assert(!t.render(item,true).includes('前复权'),'basis borrowed from different price');
raw.current_price=13.12;raw.data_status.stale=true;
assert(!t.render(item,true).includes('前复权'),'basis borrowed from stale quote');
raw.data_status.stale=false;raw.current_price=true;item.current_price=1;
assert(!t.render(item,true).includes('前复权'),'boolean source price supplied a basis');
item.price_basis='raw';
assert(t.render(item,true).includes('收盘价')&&t.render(item,true).includes('不复权'),'explicit raw basis dropped');
''')

    def test_card_shows_sector_change_and_chart_price_without_changing_input(self):
        _assert_node_contract(self, "{render:renderCandidateBasicInfo,state:state}", r'''
const t=globalThis.__auxTest;t.state.data={date:'2026-09-11'};
const item={code:'002600',sector:'消费电子',current_price:13.120744,change_pct:2.02,
 data_status:{daily:'verified',latest_date:'2026-09-11',is_final:true,stale:false}};
const before=JSON.stringify(item),html=t.render(item,false);
for(const s of ['消费电子','+2.02%','13.12','图表价'])assert(html.includes(s),'missing '+s);
assert(!html.includes('收盘价'),'unknown basis became market close');
assert(JSON.stringify(item)===before,'display mutated candidate');
item.sector='<img src=x onerror=alert(1)>';item.change_pct=0;
const zero=t.render(item,false);
assert(zero.includes('0.00%')&&!zero.includes('<img'),'zero/escaping failed');
''')

    def test_stale_partial_missing_and_invalid_values_do_not_become_current_quotes(self):
        _assert_node_contract(self, "{render:renderCandidateBasicInfo,state:state}", r'''
const t=globalThis.__auxTest;t.state.data={date:'2026-09-11'};
const base={current_price:98.76,change_pct:12.34,data_status:{daily:'verified',latest_date:'2026-09-11',is_final:true,stale:false}};
for(const patch of [{stale:true},{is_final:false},{latest_date:'2026-09-10'},{daily:'failed'}]){
 const item={...base,data_status:{...base.data_status,...patch},
 reference_close_evidence:{status:'verified',reference_date:'2026-09-11',is_final:true,stale:false}},html=t.render(item,true);
 assert(!html.includes('98.76')&&!html.includes('12.34'),'invalid quote leaked');
 assert(html.includes('未核验')||html.includes('过期'),'health not explained');
}
for(const value of [null,'',true,false,Infinity]){
 const html=t.render({...base,current_price:value,change_pct:value},false);
 assert(!html.includes('0.00')&&!html.includes('1.00'),'missing value became a number');
}
''')

    def test_detail_uses_correct_volume_money_units_and_separate_reference_roles(self):
        _assert_node_contract(self, "{render:renderCandidateFactPanel,state:state}", r'''
const t=globalThis.__auxTest;t.state.data={date:'2026-09-11'};
const item={current_price:11,reference_price:10,distance_from_reference_pct:10,
 data_status:{daily:'verified',latest_date:'2026-09-11',is_final:true,stale:false},
 volumes:[...Array(20).fill(20),40],
 volume_units:Array(21).fill('hands'),volume_raw_units:Array(21).fill('hands'),volume_sources:Array(21).fill('fixture'),
 pool_quality:{volume_ratio20:2,money20:1321736781.95,liquidity_source:'amounts',liquidity_window_bars:20,market_cap:1006.9068,circulating_market_cap:892.7889},
 workbench_item:{formal_action:null,contracts:{},strategy_results:[]}};
const html=t.render(item);
for(const s of ['较20日均量','2.00倍','20日均成交额','13.22亿','总市值','1006.91亿','结构参考','10.00','用途未核验'])assert(html.includes(s),'missing '+s);
assert(!html.includes('今日成交额')&&!html.includes('止损价'),'invented market or risk semantics');
assert(!html.includes('距结构参考')&&!html.includes('+10.00%'),'unverified raw reference entered distance calculation');
const missing=t.render({workbench_item:{contracts:{},strategy_results:[]}});
assert(!missing.includes('0.00'),'absent data became zero');
''')

    def test_fact_buttons_target_the_exact_source_price_and_volume_modules(self):
        _assert_node_contract(self, "{facts:renderCandidateFactPanel,detail:buildUnifiedCandidateDetail,state:state}", r'''
const t=globalThis.__auxTest;
const status={daily:'verified',latest_date:'2026-09-14',is_final:true,stale:false};
const raw={code:'600001',current_price:11,data_status:status,
 volumes:[...Array(20).fill(100),200],volume_units:Array(21).fill('hands'),
 volume_raw_units:Array(21).fill('hands'),volume_sources:Array(21).fill('fixture'),
 pool_quality:{money20:200000000,liquidity_source:'amounts',liquidity_window_bars:20,market_cap:100}};
t.state.data={date:'2026-09-14',picks_fusion:[raw],h4_t3_pool:[{...raw,current_price:22}]};
const item={...raw,name:'多来源事实',reference_price:10,reference_price_purpose_status:'verified',
 ref:{pool:'picks_fusion',code:'600001'},workbench_item:{
  code:'600001',name:'多来源事实',status_label:'正式策略分歧',formal_action:null,
  primary_reason:'来源动作不同',is_executable:false,contracts:{},source_refs:[
   {view:'main',ref:{pool:'picks_fusion',code:'600001'}},
   {view:'h4_t3',ref:{pool:'h4_t3_pool',code:'600001'}}
  ],strategy_results:[
   {strategy_id:'main',role:'formal',formal_action:'推荐',score:88,contract:{},evidence:{price_evidence:{status:'available'},volume_and_capital:{status:'available'}}},
   {strategy_id:'h4_t3',role:'formal',formal_action:'观察',score:60,contract:{},evidence:{price_evidence:{status:'available'},volume_and_capital:{status:'available'}}}
  ]
 }};
const html=t.facts(item);
assert(html.includes('data-evidence-target="evidence-module-strategy-main-0-02"'),
 'price fact did not target its exact source module');
assert(html.includes('data-evidence-target="evidence-module-strategy-main-0-05"'),
 'volume fact did not target its exact source module');
assert(!html.includes('evidence-module-strategy-h4_t3-1-02') && !html.includes('evidence-module-strategy-h4_t3-1-05'),
 'facts from main were linked to the other formal source');
assert(/<dt>总市值<\/dt><dd>100\.00亿<\/dd>/.test(html),
 'market cap was lost or retained a false evidence button');
const detail=t.detail(item);
for(const target of ['evidence-module-strategy-main-0-02','evidence-module-strategy-main-0-05',
 'evidence-module-strategy-h4_t3-1-02','evidence-module-strategy-h4_t3-1-05']){
 assert(detail.includes('aria-labelledby="'+target+'"'),'source module prefix is not present in detail: '+target);
}
''')

    def test_ambiguous_fact_source_keeps_values_but_drops_false_buttons(self):
        _assert_node_contract(self, "{facts:renderCandidateFactPanel,state:state}", r'''
const t=globalThis.__auxTest;
const status={daily:'verified',latest_date:'2026-09-14',is_final:true,stale:false};
const raw={code:'600001',current_price:11,data_status:status,
 volumes:[...Array(20).fill(100),200],volume_units:Array(21).fill('hands'),
 volume_raw_units:Array(21).fill('hands'),volume_sources:Array(21).fill('fixture')};
t.state.data={date:'2026-09-14',picks_fusion:[raw]};
const item={...raw,reference_price:10,reference_price_purpose_status:'verified',
 ref:{pool:'picks_fusion',code:'600001'},workbench_item:{contracts:{},source_refs:[
  {view:'main',ref:{pool:'picks_fusion',code:'600001'}},
  {view:'h4_t3',ref:{pool:'picks_fusion',code:'600001'}}
 ],strategy_results:[
  {strategy_id:'main',role:'formal',evidence:{price_evidence:{},volume_and_capital:{}}},
  {strategy_id:'h4_t3',role:'formal',evidence:{price_evidence:{},volume_and_capital:{}}}
 ]}};
const html=t.facts(item);
assert(html.includes('2.00倍') && html.includes('10.00'),
 'ambiguous-source degradation dropped known fact values');
assert(!html.includes('candidate-fact-jump') && !html.includes('data-evidence-target'),
 'ambiguous source retained a false evidence button');
''')

    def test_explicit_selected_source_survives_a_same_ref_view_alias(self):
        _assert_node_contract(self, "{facts:renderCandidateFactPanel,state:state}", r'''
const t=globalThis.__auxTest;
const status={daily:'verified',latest_date:'2026-09-14',is_final:true,stale:false};
const raw={code:'600088',current_price:31,data_status:status,
 volumes:[...Array(20).fill(100),300],volume_units:Array(21).fill('hands'),
 volume_raw_units:Array(21).fill('hands'),volume_sources:Array(21).fill('fixture'),
 pool_quality:{money20:340000000,liquidity_source:'amounts',liquidity_window_bars:20}};
t.state.data={date:'2026-09-14',observation_watchlist:[raw]};
function strategy(view,pool){return {strategy_id:view,role:'research',action_semantics:'watch_only',
 candidate:{ref:{pool:pool,code:'600088'}},contract:{},
 evidence:{price_evidence:{status:'available'},volume_and_capital:{status:'available'}}};}
const item={...raw,reference_price:30,reference_price_purpose_status:'verified',
 ref:{pool:'observation_watchlist',code:'600088'},evidence_view:'observation_top5',workbench_item:{
  contracts:{},source_refs:[
   {view:'confirming',ref:{pool:'startup_watchlist',code:'600088'}},
   {view:'observation_top5',ref:{pool:'observation_watchlist',code:'600088'}},
   {view:'highlights',ref:{pool:'observation_watchlist',code:'600088'}}
  ],strategy_results:[strategy('confirming','startup_watchlist'),
   strategy('observation_top5','observation_watchlist'),
   strategy('highlights','observation_watchlist')]
 }};
const html=t.facts(item);
for(const target of ['evidence-module-strategy-observation_top5-1-02',
 'evidence-module-strategy-observation_top5-1-05']){
 assert(html.includes('data-evidence-target="'+target+'"'),
  'same-ref alias closed the reliable selected-source target: '+target);
}
assert(!html.includes('evidence-module-strategy-highlights-2-'),
 'selected facts were retargeted to the same-ref alias');
''')

    def test_selected_source_without_redundant_candidate_ref_keeps_all_fact_buttons(self):
        _assert_node_contract(self, "{facts:renderCandidateFactPanel,state:state}", r'''
const t=globalThis.__auxTest;
const status={daily:'verified',latest_date:'2026-09-14',is_final:true,stale:false};
const raw={code:'600088',current_price:31,data_status:status,
 volumes:[...Array(20).fill(100),300],volume_units:Array(21).fill('hands'),
 volume_raw_units:Array(21).fill('hands'),volume_sources:Array(21).fill('fixture'),
 pool_quality:{money20:340000000,liquidity_source:'amounts',liquidity_window_bars:20}};
t.state.data={date:'2026-09-14',observation_watchlist:[raw]};
function strategy(view,pool){return {strategy_id:view,role:'research',action_semantics:'watch_only',
 candidate:{ref:{pool:pool,code:'600088'}},contract:{},
 evidence:{price_evidence:{status:'available'},volume_and_capital:{status:'available'}}};}
const selected=strategy('observation_top5','observation_watchlist');
delete selected.candidate.ref;
const item={...raw,reference_price:30,reference_price_purpose_status:'verified',
 distance_from_reference_pct:3.33,ref:{pool:'observation_watchlist',code:'600088'},
 evidence_view:'observation_top5',workbench_item:{contracts:{},source_refs:[
  {view:'confirming',ref:{pool:'startup_watchlist',code:'600088'}},
  {view:'observation_top5',ref:{pool:'observation_watchlist',code:'600088'}}
 ],strategy_results:[strategy('confirming','startup_watchlist'),selected]}};
const html=t.facts(item);
const targets=[...html.matchAll(/data-evidence-target="([^"]+)"/g)].map(match=>match[1]);
assert(targets.length===4,'missing selected candidate ref closed reliable fact buttons: '+targets.length);
assert(targets.filter(target=>target==='evidence-module-strategy-observation_top5-1-02').length===2,
 'selected-source price buttons did not stay on observation_top5 module 02');
assert(targets.filter(target=>target==='evidence-module-strategy-observation_top5-1-05').length===2,
 'selected-source volume buttons did not stay on observation_top5 module 05');
''')

    def test_unrelated_alias_without_candidate_ref_does_not_close_selected_source_buttons(self):
        _assert_node_contract(self, "{facts:renderCandidateFactPanel,state:state}", r'''
const t=globalThis.__auxTest;
const status={daily:'verified',latest_date:'2026-09-14',is_final:true,stale:false};
const raw={code:'600088',current_price:31,data_status:status,
 volumes:[...Array(20).fill(100),300],volume_units:Array(21).fill('hands'),
 volume_raw_units:Array(21).fill('hands'),volume_sources:Array(21).fill('fixture'),
 pool_quality:{money20:340000000,liquidity_source:'amounts',liquidity_window_bars:20}};
t.state.data={date:'2026-09-14',observation_watchlist:[raw]};
function strategy(view,pool){return {strategy_id:view,role:'research',action_semantics:'watch_only',
 candidate:{ref:{pool:pool,code:'600088'}},contract:{},
 evidence:{price_evidence:{status:'available'},volume_and_capital:{status:'available'}}};}
const alias=strategy('highlights','observation_watchlist');
delete alias.candidate.ref;
const item={...raw,reference_price:30,reference_price_purpose_status:'verified',
 distance_from_reference_pct:3.33,ref:{pool:'observation_watchlist',code:'600088'},
 evidence_view:'observation_top5',workbench_item:{contracts:{},source_refs:[
  {view:'confirming',ref:{pool:'startup_watchlist',code:'600088'}},
  {view:'observation_top5',ref:{pool:'observation_watchlist',code:'600088'}},
  {view:'highlights',ref:{pool:'observation_watchlist',code:'600088'}}
 ],strategy_results:[strategy('confirming','startup_watchlist'),
  strategy('observation_top5','observation_watchlist'),alias]}};
const html=t.facts(item);
const targets=[...html.matchAll(/data-evidence-target="([^"]+)"/g)].map(match=>match[1]);
assert(targets.length===4,'missing alias candidate ref closed selected-source fact buttons: '+targets.length);
assert(targets.filter(target=>target==='evidence-module-strategy-observation_top5-1-02').length===2,
 'alias ref gap retargeted selected-source price buttons');
assert(targets.filter(target=>target==='evidence-module-strategy-observation_top5-1-05').length===2,
 'alias ref gap retargeted selected-source volume buttons');
assert(!html.includes('evidence-module-strategy-highlights-2-'),
 'selected facts were retargeted to the incomplete alias');
''')

    def test_conflicting_source_map_keeps_values_but_drops_buttons(self):
        _assert_node_contract(self, "{facts:renderCandidateFactPanel,state:state}", r'''
const t=globalThis.__auxTest;
const status={daily:'verified',latest_date:'2026-09-14',is_final:true,stale:false};
const raw={code:'600088',current_price:31,data_status:status,
 volumes:[...Array(20).fill(100),300],volume_units:Array(21).fill('hands'),
 volume_raw_units:Array(21).fill('hands'),volume_sources:Array(21).fill('fixture'),
 pool_quality:{money20:340000000,liquidity_source:'amounts',liquidity_window_bars:20}};
t.state.data={date:'2026-09-14',observation_watchlist:[raw]};
function strategy(view,pool){return {strategy_id:view,role:'research',action_semantics:'watch_only',
 candidate:{ref:{pool:pool,code:'600088'}},contract:{},
 evidence:{price_evidence:{status:'available'},volume_and_capital:{status:'available'}}};}
const item={...raw,reference_price:30,reference_price_purpose_status:'verified',
 ref:{pool:'observation_watchlist',code:'600088'},evidence_view:'observation_top5',workbench_item:{
  contracts:{},source_refs:[
   {view:'confirming',ref:{pool:'observation_watchlist',code:'600088'}}
  ],strategy_results:[strategy('confirming','startup_watchlist'),
   strategy('observation_top5','observation_watchlist')]
 }};
const html=t.facts(item);
assert(html.includes('3.00倍') && html.includes('3.40亿') && html.includes('30.00'),
 'source conflict dropped known fact values');
assert(!html.includes('candidate-fact-jump') && !html.includes('data-evidence-target'),
 'source conflict guessed an evidence source');
assert(!html.includes('evidence-module-strategy-confirming-0-'),
 'second-source facts were linked to the first source');
''')

    def test_explicit_missing_target_section_drops_only_the_button(self):
        _assert_node_contract(self, "{facts:renderCandidateFactPanel,state:state}", r'''
const t=globalThis.__auxTest;
const status={daily:'verified',latest_date:'2026-09-14',is_final:true,stale:false};
const raw={code:'600088',current_price:31,data_status:status,
 volumes:[...Array(20).fill(100),300],volume_units:Array(21).fill('hands'),
 volume_raw_units:Array(21).fill('hands'),volume_sources:Array(21).fill('fixture'),
 pool_quality:{money20:340000000,liquidity_source:'amounts',liquidity_window_bars:20}};
t.state.data={date:'2026-09-14',observation_watchlist:[raw]};
function item(sectionStatus){return {...raw,reference_price:30,reference_price_purpose_status:'verified',
 ref:{pool:'observation_watchlist',code:'600088'},evidence_view:'observation_top5',workbench_item:{
  contracts:{},source_refs:[{view:'observation_top5',ref:{pool:'observation_watchlist',code:'600088'}}],
  strategy_results:[{strategy_id:'observation_top5',role:'research',action_semantics:'watch_only',
   candidate:{ref:{pool:'observation_watchlist',code:'600088'}},contract:{},evidence:{
    price_evidence:sectionStatus===undefined?{}:{status:sectionStatus},
    volume_and_capital:sectionStatus===undefined?{}:{status:sectionStatus}}}]
 }};}
const missing=t.facts(item('missing'));
assert(missing.includes('3.00倍') && missing.includes('3.40亿') && missing.includes('30.00'),
 'missing target section dropped known fact values');
assert(!missing.includes('candidate-fact-jump') && !missing.includes('data-evidence-target'),
 'explicit missing target section created an empty evidence jump');
const legacyAvailable=t.facts(item(undefined));
assert(legacyAvailable.includes('evidence-module-strategy-observation_top5-0-02')
 && legacyAvailable.includes('evidence-module-strategy-observation_top5-0-05'),
 'legacy section with actual evidence but no status lost compatibility');
''')

    def test_money20_labels_distinguish_actual_estimate_unverified_and_missing(self):
        _assert_node_contract(self, "{render:renderCandidateFactPanel,state:state}", r'''
const t=globalThis.__auxTest;t.state.data={date:'2026-09-11'};
const status={daily:'verified',latest_date:'2026-09-11',is_final:true,stale:false};
function renderQuality(poolQuality){
 return t.render({data_status:status,pool_quality:poolQuality,workbench_item:{contracts:{},strategy_results:[]}});
}
const actual=renderQuality({money20:150000000,liquidity_source:'amounts',liquidity_window_bars:20});
assert(actual.includes('20日均成交额')&&actual.includes('1.50亿'),'real turnover label/value missing');
assert(!actual.includes('估算20日均成交额')&&!actual.includes('来源未核验'),'real turnover mislabeled');
const proxy=renderQuality({money20:150000000,liquidity_source:'volume_price_proxy',liquidity_window_bars:20});
assert(proxy.includes('估算20日均成交额')&&proxy.includes('1.50亿'),'proxy was not labeled estimated');
const legacy=renderQuality({money20:150000000,liquidity_source:'amounts'});
assert(legacy.includes('成交额来源未核验'),'old positive money20 was silently verified');
assert(!legacy.includes('1.50亿'),'unattested old money20 value leaked');
const missing=renderQuality({money20:null,liquidity_source:'missing',liquidity_window_bars:0});
assert(!missing.includes('低流动性')&&!missing.includes('0.00亿'),'missing quantity became a negative fact');
''')

    def test_serialized_report_to_workspace_to_js_preserves_money20_provenance(self):
        base = {
            "code": "600001",
            "name": "数量口径样本",
            "best_buy_point": {"type": "候选", "index": 1, "price": 10.0},
            "dates": ["2026-09-10", "2026-09-11"],
            "opens": [9.8, 10.0],
            "highs": [10.2, 10.5],
            "lows": [9.7, 9.9],
            "closes": [10.0, 10.4],
            "volumes": [100.0, 120.0],
            "data_status": {
                "daily": "verified", "latest_date": "2026-09-11",
                "is_final": True, "stale": False,
            },
            "market_cap": 100,
            "ret20": 10,
            "industry": "测试行业",
            "decision_engine_v1": {
                "decision_code": "recommend", "decision": "推荐",
            },
        }
        cases = [
            ("amounts", 20, "20日均成交额", "估算20日均成交额", False),
            ("volume_price_proxy", 20, "估算20日均成交额", "成交额来源未核验", False),
            ("amounts", None, "成交额来源未核验", "1.50亿", False),
            ("missing", 0, "仅展示本期已有数据", "低流动性", True),
        ]
        for index, (source, window, expected, forbidden, missing) in enumerate(cases):
            raw = dict(base, code=f"60000{index + 1}")
            raw["money20"] = None if missing else 150_000_000
            raw["liquidity_source"] = source
            if window is not None:
                raw["liquidity_window_bars"] = window
            serialized = _serialize_picks([raw])[0]
            workspace = build_workspace({
                "date": "2026-09-11", "picks_fusion": [serialized],
                "picks_pure": [], "startup_watchlist": [],
                "next_day_boom": {"candidates": []},
                "luojie_pool": {"candidates": []},
                "selection_input_health": {
                    "schema_version": 2, "status": "verified",
                    "formal": {
                        "status": "verified", "formal_actions_allowed": True,
                        "all_formal_actions_allowed": True,
                    },
                    "by_strategy": {
                        "daily_fusion": {
                            "status": "verified", "formal_actions_allowed": True,
                        },
                    },
                },
            })
            item = workspace["views"]["main"][0]
            script = f"""
const t=globalThis.__auxTest;
t.state.data={json.dumps({'date': '2026-09-11', 'picks_fusion': [serialized]}, ensure_ascii=False)};
const html=t.render({json.dumps(item, ensure_ascii=False)});
assert(html.includes({json.dumps(expected, ensure_ascii=False)}),'missing expected provenance label: {source}/{window}');
assert(!html.includes({json.dumps(forbidden, ensure_ascii=False)}),'forbidden provenance claim leaked: {source}/{window}');
"""
            _assert_node_contract(
                self,
                "{render:renderCandidateFactPanel,state:state}",
                script,
            )

    def test_twenty_day_volume_does_not_relabel_an_upstream_five_day_ratio(self):
        _assert_node_contract(self, "{render:renderCandidateFactPanel,state:state}", r'''
const t=globalThis.__auxTest;t.state.data={date:'2026-09-11'};
const item={data_status:{daily:'verified',latest_date:'2026-09-11',is_final:true,stale:false},
 volumes:[...Array(20).fill(100),200],volume_units:Array(21).fill('hands'),
 volume_raw_units:Array(21).fill('hands'),volume_sources:Array(21).fill('fixture'),pool_quality:{volume_ratio20:9.99}};
const html=t.render(item);
assert(html.includes('2.00倍')&&!html.includes('9.99倍'),'upstream ratio mislabelled as 20-day');
for(const volumes of [[100,200],[...Array(20).fill(0),200],[...Array(19).fill(100),null,200]]){
 assert(!t.render({...item,volumes}).includes('较20日均量'),'insufficient volume fabricated a ratio');
}
for(const patch of [
 {volume_units:[...Array(8).fill('unknown'),...Array(13).fill('hands')]},
 {volume_raw_units:Array(21).fill('unknown')},
 {volume_sources:Array(21).fill('')},
 {volume_units:undefined,volume_unit:'hands'}
]){
 assert(!t.render({...item,...patch}).includes('较20日均量'),'unverified volume window fabricated a ratio');
}
''')

    def test_unified_detail_places_basic_facts_before_chart_and_preserves_action(self):
        _assert_node_contract(self, "{render:buildUnifiedCandidateDetail,state:state}", r'''
const t=globalThis.__auxTest;t.state.data={date:'2026-09-11'};
const item={code:'000636',name:'风华高科',sector:'元件',current_price:55.99,change_pct:10,
 data_status:{daily:'verified',latest_date:'2026-09-11',is_final:true,stale:false},
 workbench_item:{code:'000636',name:'风华高科',status_label:'研究观察',formal_action:null,
 primary_reason:'等待回踩',next_confirmation:['回踩确认'],invalidation:['结构失效'],strategy_results:[],contracts:{}}};
const before=JSON.stringify(item),html=t.render(item);
assert(html.includes('元件')&&html.includes('+10.00%'),'unified header dropped basics');
assert(html.indexOf('candidate-basic-info')<html.indexOf('K线图表'),'facts hidden below chart');
assert(html.includes('研究观察')&&html.includes('下一确认')&&html.includes('结构失效'),'decision chain changed');
assert(!html.includes('正式动作：'),'research promoted');
assert(JSON.stringify(item)===before,'input changed');
''')
