"""User-visible stock facts must preserve dates, units and strategy identity."""
import unittest

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
 pool_quality:{volume_ratio20:2,money20:1321736781.95,market_cap:1006.9068,circulating_market_cap:892.7889},
 workbench_item:{formal_action:null,contracts:{},strategy_results:[]}};
const html=t.render(item);
for(const s of ['较20日均量','2.00倍','20日均成交额','13.22亿','总市值','1006.91亿','结构参考','10.00','+10.00%'])assert(html.includes(s),'missing '+s);
assert(!html.includes('今日成交额')&&!html.includes('止损价'),'invented market or risk semantics');
assert(html.includes('非失效位'),'reference role is ambiguous');
const missing=t.render({workbench_item:{contracts:{},strategy_results:[]}});
assert(!missing.includes('0.00'),'absent data became zero');
''')

    def test_twenty_day_volume_does_not_relabel_an_upstream_five_day_ratio(self):
        _assert_node_contract(self, "{render:renderCandidateFactPanel,state:state}", r'''
const t=globalThis.__auxTest;t.state.data={date:'2026-09-11'};
const item={data_status:{daily:'verified',latest_date:'2026-09-11',is_final:true,stale:false},
 volumes:[...Array(20).fill(100),200],pool_quality:{volume_ratio20:9.99}};
const html=t.render(item);
assert(html.includes('2.00倍')&&!html.includes('9.99倍'),'upstream ratio mislabelled as 20-day');
for(const volumes of [[100,200],[...Array(20).fill(0),200],[...Array(19).fill(100),null,200]]){
 assert(!t.render({...item,volumes}).includes('较20日均量'),'insufficient volume fabricated a ratio');
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
