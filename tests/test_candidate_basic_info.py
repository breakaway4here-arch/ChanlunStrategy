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
for(const s of ['较20日均量','2.00倍','20日均成交额','13.22亿','总市值','1006.91亿','结构参考','10.00','+10.00%'])assert(html.includes(s),'missing '+s);
assert(!html.includes('今日成交额')&&!html.includes('止损价'),'invented market or risk semantics');
assert(html.includes('非失效位'),'reference role is ambiguous');
const missing=t.render({workbench_item:{contracts:{},strategy_results:[]}});
assert(!missing.includes('0.00'),'absent data became zero');
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
