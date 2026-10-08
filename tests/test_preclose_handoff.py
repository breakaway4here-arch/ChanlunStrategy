"""Fixed-input regressions for the October 8 preclose handoff."""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from chanlun.preclose_notify import publish_preclose_snapshot

from chanlun.preclose_contract import build_preclose_snapshot, build_public_preclose_view
from chanlun.preclose_pipeline import PreclosePipelineConfig
from preclose_run import run_scheduled_preclose
from tests.test_preclose_frontend import _assert_node_contract

CN = timezone(timedelta(hours=8))
DATE = '2026-08-28'


class HandoffWindowTests(unittest.TestCase):
    def test_shared_schedule_import_without_zoneinfo(self):
        code = '''
import builtins
from datetime import datetime, timedelta
original_import = builtins.__import__
def without_zoneinfo(name, *args, **kwargs):
    if name == "zoneinfo":
        raise ImportError("Python 3.7 has no zoneinfo")
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_zoneinfo
from chanlun.preclose_schedule import normalize_preclose_datetime
value = normalize_preclose_datetime(datetime(2026, 8, 28, 14, 50))
assert value.utcoffset() == timedelta(hours=8)
assert value.isoformat() == "2026-08-28T14:50:00+08:00"
'''
        completed = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def run_fixed(self, start, acquire_seconds=0, publish_seconds=0, rewind=False):
        elapsed = [0.0]
        configs = []
        def clock():
            return start + timedelta(seconds=0 if rewind else elapsed[0])
        def builder(date, as_of, **kwargs):
            elapsed[0] += acquire_seconds
            return {'trade_date': date, 'as_of': as_of, 'daily': [], 'min30': {}, 'market': {}}
        def runner(inputs, config, **kwargs):
            configs.append(config)
            return build_preclose_snapshot(config.trade_date, config.as_of, config.generated_at,
                                           {}, config.source_sha)
        def publisher(path, **kwargs):
            elapsed[0] += publish_seconds
            frozen = json.loads(Path(path).read_text())
            return {'publish': {'success': True, 'snapshot_id': frozen['snapshot_id'],
                                'content_hash': frozen['content_hash']}, 'notifications': {}}
        with tempfile.TemporaryDirectory() as directory:
            result = run_scheduled_preclose(root=directory, formal_market_db=Path(directory)/'db',
                env_file=Path(directory)/'env', source_sha='test', now=clock,
                monotonic=lambda: elapsed[0], trading_day_check=lambda *args: True,
                runtime_builder=builder, pipeline_runner=runner, publisher=publisher, notify=False)
        return result, configs

    def test_205_second_acquisition_still_runs_and_delivers_before_1456(self):
        result, configs = self.run_fixed(datetime(2026, 8, 28, 14, 45, tzinfo=CN), 205)
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].deadline_seconds, 419)
        self.assertEqual(result['exit_code'], 0)

    def test_late_start_has_only_remaining_window(self):
        result, configs = self.run_fixed(datetime(2026, 8, 28, 14, 50, tzinfo=CN))
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].deadline_seconds, 324)
        self.assertEqual(result['exit_code'], 0)

    def test_config_accepts_660_but_rejects_nonfinite_and_over_budget(self):
        values = dict(trade_date=DATE, as_of=DATE+'T14:45:00+08:00',
            generated_at=DATE+'T14:45:00+08:00', source_sha='test', run_id='test')
        self.assertEqual(PreclosePipelineConfig(**values, deadline_seconds=660).deadline_seconds, 660)
        for invalid in (661, 0, float('nan'), float('inf')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                PreclosePipelineConfig(**values, deadline_seconds=invalid)

    def test_late_start_wall_clock_rewind_cannot_restore_budget(self):
        result, configs = self.run_fixed(datetime(2026, 8, 28, 14, 50, tzinfo=CN), 350, rewind=True)
        self.assertEqual(configs, [])
        self.assertEqual(result['exit_code'], 1)

    def test_readback_that_finishes_at_deadline_is_not_delivery_success(self):
        result, _ = self.run_fixed(datetime(2026, 8, 28, 14, 50, tzinfo=CN), publish_seconds=360)
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['run_status'], 'deadline_exceeded')

    def test_scheduled_cli_passes_requested_total_budget(self):
        import preclose_run
        with patch('preclose_run.run_scheduled_preclose', return_value={'exit_code': 0}) as run:
            preclose_run.main(['--scheduled', '--source-sha', 'test', '--deadline-seconds', '660'])
        self.assertEqual(run.call_args.kwargs.get('deadline_seconds'), 660)

    def test_shanghai_timezone_and_hard_boundaries(self):
        tokyo = timezone(timedelta(hours=9))
        for clock, expected in (
            (datetime(2026, 8, 28, 15, 50, tzinfo=tokyo), 'completed'),
            (datetime(2026, 8, 28, 14, 44, 59, tzinfo=CN), 'outside_preclose_window'),
            (datetime(2026, 8, 28, 14, 56, tzinfo=CN), 'outside_preclose_window'),
        ):
            with self.subTest(clock=clock):
                result, _ = self.run_fixed(clock)
                self.assertEqual(result['status'], expected)

    def test_direct_pipeline_late_generated_time_caps_runtime(self):
        from chanlun.preclose_pipeline import run_preclose_pipeline
        from tests.test_preclose_pipeline import _market_inputs, _components, FixedClock
        clock = FixedClock()
        config = PreclosePipelineConfig(trade_date='2026-08-27', as_of='2026-08-27T14:47:00+08:00',
            generated_at='2026-08-27T14:55:00+08:00', source_sha='test', run_id='late-direct',
            deadline_seconds=660, monotonic=clock)
        self.assertEqual(config.deadline_seconds, 60)
        result = run_preclose_pipeline(_market_inputs(), config=config,
            components=_components([], clock=clock, deadline_during_daily=True))
        self.assertEqual(result['status'], 'deadline_exceeded')

    def test_real_publish_get_uses_remaining_shared_budget_and_date_identity(self):
        from tests.test_preclose_notify import FakeResponse
        snapshot = build_preclose_snapshot(DATE, DATE+'T14:45:00+08:00', DATE+'T14:48:00+08:00', {}, 'test')
        remaining = [5.0]
        timeouts = []
        def put(*args, **kwargs):
            timeouts.append(kwargs['timeout']); remaining[0] -= 4.0
            return FakeResponse(payload={'revision': 1})
        def get(*args, **kwargs):
            timeouts.append(kwargs['timeout'])
            return FakeResponse(payload=dict(snapshot))
        result = publish_preclose_snapshot(snapshot, api_base='https://test.example', write_token='test',
            put=put, get=get, timeout=6, budget_remaining=lambda: remaining[0])
        self.assertTrue(result['success'])
        self.assertEqual(timeouts, [5.0, 1.0])
        mismatch = publish_preclose_snapshot(snapshot, api_base='https://test.example', write_token='test',
            put=lambda *args, **kwargs: FakeResponse(payload={}),
            get=lambda *args, **kwargs: FakeResponse(payload=dict(snapshot, trade_date='2026-08-27')))
        self.assertFalse(mismatch['success'])
        self.assertFalse(mismatch['trade_date_matches'])


class HandoffStatusTests(unittest.TestCase):
    def browser(self, body, exposure=None):
        setup = r'''
window.CHANLUN_BOOTSTRAP={precloseApiBase:'https://preclose.example'};
window.location.pathname='/ChanlunStrategy/';
let now=Date.parse('2026-08-28T14:47:00+08:00'); Date.now=()=>now;
const timers=[];
window.setTimeout=(callback,delay)=>{timers.push({callback,delay});return timers.length;};
window.clearTimeout=(id)=>{if(timers[id-1])timers[id-1].cancelled=true;};
const t=globalThis.__precloseTest;
const classList={add:function(){},remove:function(){},toggle:function(){}};
t.nodes.precloseAdvisory={classList};t.nodes.precloseBody={innerHTML:''};
t.nodes.precloseRefresh={disabled:false};
const candidate={code:'600000',name:'浦发银行',reference_price:10};
function snapshot(status) {return {status,trade_date:'2026-08-28',content_hash:'a'.repeat(64),
  expires_at:'2026-08-28T14:56:30+08:00',pools:{main:status==='available'?[candidate]:[],h4_t3:[],acceleration:[]}};}
function response(value){return {ok:true,status:200,json:()=>Promise.resolve(value)};}
'''
        _assert_node_contract(self, exposure or '({load:loadPrecloseAdvisory,state:state,nodes:nodes,build:buildPrecloseSnapshotHtml})', setup + body)

    def test_failures_are_not_true_empty_in_public_contract(self):
        for status in ('empty', 'failed', 'deadline_exceeded', 'not_run'):
            snapshot = build_preclose_snapshot(DATE, DATE+'T14:45:00+08:00',
                DATE+'T14:48:00+08:00', {}, 'test', status=status,
                diagnostics={'secret': 'never-public'})
            public = build_public_preclose_view(snapshot, DATE+'T14:50:00+08:00')
            with self.subTest(status=status):
                self.assertEqual(public['status'], status)
                self.assertEqual(public['message'] == '本期未选出推荐票', status == 'empty')
                self.assertNotIn('secret', json.dumps(public))

    def test_frontend_retry_404_to_available_and_stop(self):
        _assert_node_contract(self, '({load:loadPrecloseAdvisory,state:state,nodes:nodes})', r'''
window.CHANLUN_BOOTSTRAP = { precloseApiBase: 'https://preclose.example' };
window.location.pathname = '/ChanlunStrategy/';
let now = Date.parse('2026-08-28T14:44:00+08:00');
Date.now = () => now;
const timers = [];
window.setTimeout = function(callback, delay) { timers.push({callback, delay}); return timers.length; };
const t = globalThis.__precloseTest;
const classList = {add:function(){},remove:function(){},toggle:function(){}};
t.nodes.precloseAdvisory = {classList}; t.nodes.precloseBody = {innerHTML:''};
let calls = 0;
window.fetch = function(url) {
  if (url.includes('reconciliation')) return Promise.resolve({ok:false,status:404});
  calls += 1;
  return Promise.resolve(calls === 1 ? {ok:false,status:404} : {ok:true,status:200,json:()=>Promise.resolve({
    status:'available',trade_date:'2026-08-28',expires_at:'2026-08-28T14:56:30+08:00',
    pools:{main:[{code:'600000',name:'浦发银行',reference_price:10}],h4_t3:[],acceleration:[]}
  })});
};
await t.load();
assert(!t.nodes.precloseBody.innerHTML.includes('本期未选出推荐票'), '404 claimed true empty');
assert(t.state.preclose.refreshTimer!==null, 'waiting did not schedule retry');
now = Date.parse('2026-08-28T14:47:30+08:00');
const retry = timers[t.state.preclose.refreshTimer - 1];
await retry.callback();
assert(calls===2 && t.nodes.precloseBody.innerHTML.includes('浦发银行'), 'retry did not render available');
assert(t.state.preclose.refreshTimer===null, 'stable result still polling');
''')

    def test_tail_window_result_can_be_read_before_cutoff(self):
        self.browser(r'''
now=Date.parse('2026-08-28T14:55:54+08:00');
let calls=0;
window.fetch=function(url){
  if(url.includes('reconciliation'))return Promise.resolve({ok:false,status:404});
  calls++;return Promise.resolve(calls===1?{ok:false,status:404}:response(snapshot('available')));
};
await t.load();
const retry=timers[t.state.preclose.refreshTimer-1];
assert(retry && retry.delay<6000,'no final in-window retry');
now=Date.parse('2026-08-28T14:55:58+08:00');
await retry.callback();
assert(calls===2 && t.nodes.precloseBody.innerHTML.includes('浦发银行'),'tail result missed');
assert(t.state.preclose.refreshTimer===null,'stable tail result kept fetching');
now=Date.parse('2026-08-28T14:56:00+08:00');
await t.load();
assert(t.state.preclose.refreshTimer===null,'scheduled refresh at or after cutoff');
''')

    def test_delayed_automatic_timer_does_not_fetch_after_cutoff(self):
        self.browser(r'''
let calls=0;
window.fetch=()=>{calls++;return Promise.resolve({ok:false,status:404});};
await t.load();
const retry=timers[t.state.preclose.refreshTimer-1];
assert(retry,'waiting did not schedule refresh');
now=Date.parse('2026-08-28T14:56:05+08:00');
await retry.callback();
assert(calls===1,'delayed automatic timer fetched after cutoff');
assert(t.state.preclose.refreshTimer===null,'late timer was not released');
await t.load();
assert(calls===2,'manual historical read was incorrectly prohibited');
''')

    def test_cutoff_waiting_shows_unavailable_and_keeps_stable_result(self):
        self.browser(r'''
now=Date.parse('2026-08-28T14:55:59+08:00');
let calls=0;
window.fetch=()=>{calls++;return Promise.resolve({ok:false,status:404});};
await t.load();
const retry=timers[t.state.preclose.refreshTimer-1];
assert(t.nodes.precloseBody.innerHTML.includes('正在等待预跑结果'),'404 waiting state missing');
now=Date.parse('2026-08-28T14:56:05+08:00');
await retry.callback();
assert(calls===1,'expired automatic timer made new request');
assert(!t.nodes.precloseBody.innerHTML.includes('正在等待'),'cutoff still claims waiting');
assert(t.nodes.precloseBody.innerHTML.includes('暂不可用'),'cutoff lost unknown result state');
assert(!t.nodes.precloseBody.innerHTML.includes('未运行'),'missing result invented not_run');
await t.load();
assert(calls===2,'manual historical read was incorrectly prohibited');
const stable=snapshot('available');
t.render(stable,now);
const html=t.nodes.precloseBody.innerHTML;
await retry.callback();
assert(t.nodes.precloseBody.innerHTML===html,'stale callback replaced stable result');
''', '({load:loadPrecloseAdvisory,state:state,nodes:nodes,render:renderPrecloseSnapshot})')

    def test_network_failure_recovers_manual_refresh_prevents_concurrent_requests(self):
        self.browser(r'''
let calls=0, release;
window.fetch=(url)=>{
  if(url.includes('reconciliation'))return Promise.resolve({ok:false,status:404});
  calls++;if(calls===1)return Promise.reject(new Error('network'));
  return new Promise(resolve=>{release=()=>resolve(response(snapshot('available')));});
};
await t.load();
assert(t.state.preclose.refreshTimer!==null,'temporary failure did not retry');
const first=t.load(),second=t.load();
assert(calls===2 && first===second,'duplicate refresh made concurrent fetches');
assert(t.nodes.precloseRefresh.disabled,'refresh remains enabled during request');
release();await first;
assert(t.nodes.precloseBody.innerHTML.includes('浦发银行'),'manual refresh did not recover');
assert(!t.nodes.precloseRefresh.disabled,'manual refresh was not restored');
''')

    def test_true_empty_stable_failed_and_expired_stop_polling(self):
        for status in ('empty', 'failed', 'deadline_exceeded', 'not_run', 'expired'):
            with self.subTest(status=status):
                self.browser("window.fetch=(url)=>Promise.resolve(url.includes('reconciliation')?{ok:false,status:404}:response(snapshot('" + status + "')));await t.load();assert(t.state.preclose.refreshTimer===null,'stable state still polling');")

    def test_wrong_date_is_rejected_and_old_request_cannot_replace_new_day(self):
        self.browser(r'''
let release,calls=0;
window.fetch=(url)=>{
 if(url.includes('reconciliation'))return Promise.resolve({ok:false,status:404});
 calls++;if(calls===1)return new Promise(resolve=>{release=()=>resolve(response(snapshot('available')));});
 const current=snapshot('empty');current.trade_date='2026-08-29';return Promise.resolve(response(current));
};
const old=t.load();
now=Date.parse('2026-08-29T00:00:01+08:00');
await t.load();release();await old;
assert(t.state.preclose.snapshot.trade_date==='2026-08-29','late old response replaced current date');
assert(!t.nodes.precloseBody.innerHTML.includes('浦发银行'),'old candidates crossed Shanghai day');
window.fetch=()=>Promise.resolve(response(snapshot('available')));
await t.load();
assert(t.state.preclose.snapshot===null,'wrong report date was accepted');
''')

    def test_reconciliation_timeout_aborts_shared_request(self):
        self.browser(r'''
window.AbortController=AbortController;
let reconciliationSignal;
window.fetch=(url,options)=>{
 if(url.includes('reconciliation')){
   reconciliationSignal=options.signal;return new Promise(()=>{});
 }
 return Promise.resolve(response(snapshot('available')));
};
const request=t.load();
for(let index=0;index<8;index++)await Promise.resolve();
const timeout=timers.find(timer=>timer.delay===6000);
assert(reconciliationSignal,'reconciliation did not receive signal');
timeout.callback();await request;
assert(reconciliationSignal.aborted,'timed out reconciliation was not aborted');
assert(t.nodes.precloseBody.innerHTML.includes('浦发银行'),'reconciliation error cleared valid snapshot');
''')

    def test_expired_failure_and_legacy_expired_do_not_claim_true_empty(self):
        self.browser(r'''
const failed=snapshot('expired');failed.result_status='failed';
assert(!t.build(failed,now).includes('本期未选出推荐票'),'expired failed masquerades as empty');
assert(t.build(failed,now).includes('预跑失败'),'expired failure lost original state');
assert(!t.build(snapshot('expired'),now).includes('本期未选出推荐票'),'legacy expired invented true empty');
''')
