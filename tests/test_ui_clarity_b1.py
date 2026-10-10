"""B1 research-page hierarchy and evidence-preserving summaries."""

import unittest

from tests.test_auxiliary_frontend import _assert_node_contract


class TestResearchClarityB1(unittest.TestCase):
    def test_current_identity_historical_folding_and_horizon_progress(self):
        _assert_node_contract(self, "({ render: renderStrategyScorecards })", r"""
const raw = JSON.parse(fs.readFileSync('docs/data/2026-10-08.json', 'utf8'));
const data = {date: raw.date, strategy_scorecards: raw.strategy_scorecards,
  strategy_run_manifest: raw.strategy_run_manifest, diagnostics: raw.diagnostics};
const html = globalThis.__auxTest.render(data);
assert(html.includes('策略验证进度'), 'progress title missing');
assert(html.indexOf('class="strategy-scorecard is-current"') < html.indexOf('读数说明'),
  'reading guide pushed current results below technical explanation');
assert((html.match(/class="strategy-scorecard is-current"/g) || []).length === 5,
  'current five return identities were not separated');
assert((html.match(/class="strategy-scorecard is-history"/g) || []).length === 7,
  'seven older return identities were not folded');
assert(html.includes('<details class="strategy-history-records"'), 'history is not native details');
assert(html.includes('T+1：成熟 127&#47;100'), 'single-horizon mature sample progress missing');
assert(html.includes('成熟覆盖日 8&#47;20') && html.includes('成熟覆盖月 1&#47;2'),
  'mature horizon coverage was replaced with overall active dates/months');
assert(!html.includes('门控运行诊断'), 'gate remained in return progress');
const missingStatus = JSON.parse(JSON.stringify(data));
delete missingStatus.strategy_run_manifest[4].run_status;
const partial = globalThis.__auxTest.render(missingStatus);
assert(partial.includes('本期运行状态未记录'), 'manifest identity with absent status lost');
assert((partial.match(/class="strategy-scorecard is-current"/g) || []).length === 5,
  'manifest identity with absent status was sent to history');
const wrongPolicy = JSON.parse(JSON.stringify(data));
wrongPolicy.strategy_scorecards.research[0].policy_version = 'different-policy';
wrongPolicy.strategy_scorecards.research[0].comparison_identity.policy_version = 'different-policy';
const wrongPolicyHtml = globalThis.__auxTest.render(wrongPolicy);
assert((wrongPolicyHtml.match(/class="strategy-scorecard is-current"/g) || []).length === 4,
  'same-version different-policy research group merged into current');
const uncertain = globalThis.__auxTest.render(Object.assign({}, data, { strategy_run_manifest: [] }));
assert(uncertain.includes('身份未核实') && !uncertain.includes('历史记录 · 7'),
  'missing manifest guessed historical identity');
""")

    def test_legacy_scorecards_are_readable_once_in_history(self):
        _assert_node_contract(self, "({ build: buildAuxiliaryStacks })", r"""
const html = globalThis.__auxTest.build({strategy_scorecards: [
  {strategy: 'daily_fusion', version: 'old-v1', sample_size: 3}
]}).research;
assert((html.match(/历史旧口径/g) || []).length === 1,
  'legacy record was duplicated in current progress and history');
assert(html.indexOf('策略验证进度') < html.indexOf('历史记录'),
  'legacy history preceded current progress');
assert(html.includes('old-v1'), 'legacy version was lost');
""")

    def test_gate_diagnosis_is_current_signal_count_with_cumulative_detail(self):
        _assert_node_contract(self, "({ build: buildAuxiliaryStacks })", r"""
const raw = JSON.parse(fs.readFileSync('docs/data/2026-10-08.json', 'utf8'));
const html = globalThis.__auxTest.build(raw).research;
assert(html.includes('5个本期身份') && !html.includes('15个评测分组'),
  'progress badge still counts hidden gate and historical identities');
assert(html.includes('数据与运行诊断') && html.includes('观察筛选运行情况'),
  'gate not placed in diagnostics');
assert(html.includes('本期 2026-10-08 处理 72 条信号 · 仅作观察'),
  'current signal count lost');
assert(html.includes('本版本累计') && html.includes('270'), 'ledger count lost');
assert(html.includes('规则判定 推荐 / 观察 / 拒绝：3 / 77 / 190'),
  'rule result lost from details');
assert(html.indexOf('策略验证进度') < html.indexOf('H4 上游样本实验')
  && html.indexOf('H4 上游样本实验') < html.indexOf('数据与运行诊断')
  && html.indexOf('数据与运行诊断') < html.indexOf('历史记录'),
  'research modules out of order');
const unsafeRun = JSON.parse(JSON.stringify(raw));
const unsafeGate = unsafeRun.strategy_run_manifest.find(function (row) {
  return row.strategy === 'observation_gate';
});
unsafeGate.run_status = 'unavailable';
unsafeGate.reason = 'reader failed at /srv/private/account/token=demo-secret';
const unsafeGateSummary = globalThis.__auxTest.build(unsafeRun).research
  .split('<details class="strategy-gate-card is-current">')[1].split('</summary>')[0];
assert(!unsafeGateSummary.includes('/srv/private') && !unsafeGateSummary.includes('demo-secret')
  && unsafeGateSummary.includes('详见诊断'),
  'raw gate failure leaked into collapsed summary');
const missingCount = JSON.parse(JSON.stringify(raw));
missingCount.strategy_run_manifest.find(function (row) {
  return row.strategy === 'observation_gate';
}).signal_count = null;
const missingCountHtml = globalThis.__auxTest.build(missingCount).research;
assert(missingCountHtml.includes('处理信号数未记录')
  && !missingCountHtml.includes('处理 0 条信号'),
  'missing current signal count was fabricated as zero');
const noGate = JSON.parse(JSON.stringify(raw));
noGate.strategy_scorecards.gates = [];
const noGateHtml = globalThis.__auxTest.build(noGate).research;
assert(noGateHtml.includes('暂无门控记录') && !noGateHtml.includes('已有累计账本仅供历史查阅'),
  'missing gate ledger was described as historical records');
const stale = JSON.parse(JSON.stringify(raw));
stale.strategy_run_manifest = [];
const staleHtml = globalThis.__auxTest.build(stale).research;
assert(staleHtml.includes('本期运行状态未记录'), 'historical gate treated as current');
assert(!staleHtml.includes('本期 2026-10-08 处理 72 条信号'), 'historical count claimed current');
""")

    def test_h4_no_sample_is_compact_and_failures_stay_visible(self):
        _assert_node_contract(self, "({ render: renderShadowEvaluations })", r"""
const raw = JSON.parse(fs.readFileSync('docs/data/2026-10-08.json', 'utf8'));
const empty = globalThis.__auxTest.render(raw);
assert(empty.includes('H4 上游样本实验'), 'H4 title missing');
assert(empty.includes('暂无可评测样本 · 本期形态未命中'), 'verified empty conclusion missing');
assert(empty.includes('<details class="shadow-experiment-details"'), 'full audit not folded');
assert(empty.indexOf('暂无可评测样本') < empty.indexOf('正式 SHA'), 'technical grid precedes conclusion');
const otherGate = JSON.parse(JSON.stringify(raw));
otherGate.h4_t3_pool.diagnostics.microstate_count = 1;
const otherGateHtml = globalThis.__auxTest.render(otherGate);
assert(!otherGateHtml.includes('本期形态未命中'),
  'zero final pool was guessed to be a shape miss despite one shape sample');
const wrongVersion = JSON.parse(JSON.stringify(raw));
wrongVersion.h4_t3_pool.strategy_version = 'another-model';
assert(!globalThis.__auxTest.render(wrongVersion).includes('本期形态未命中'),
  'another H4 model version supplied the shape conclusion');
const failed = JSON.parse(JSON.stringify(raw));
failed.shadow_evaluations.collection_health.status = 'collection_failed';
failed.shadow_evaluations.collection_health.error_code = 'provider_failed';
const failureHtml = globalThis.__auxTest.render(failed);
assert(failureHtml.includes('影子采集失败') && !failureHtml.includes('暂无可评测样本'),
  'collection failure disguised as empty pool');
const waiting = JSON.parse(JSON.stringify(raw));
waiting.shadow_evaluations.outcome_maturity.t3.right_censored = 2;
waiting.shadow_evaluations.experiments[0].outcome_maturity.t3.right_censored = 2;
const waitingHtml = globalThis.__auxTest.render(waiting);
assert(waitingHtml.includes('跟踪 2 个样本，等待目标交易日结果'), 'pending target status missing');
const experimentFailure = JSON.parse(JSON.stringify(raw));
experimentFailure.shadow_evaluations.experiments[0].status = 'unavailable';
experimentFailure.shadow_evaluations.experiments[0].error = 'shape_input_missing';
const experimentFailureHtml = globalThis.__auxTest.render(experimentFailure);
assert(experimentFailureHtml.includes('单项实验暂不可用')
  && !experimentFailureHtml.includes('暂无可评测样本'),
  'experiment input failure disguised as verified empty');
const inactiveFormal = JSON.parse(JSON.stringify(raw));
inactiveFormal.shadow_evaluations.experiments[0].active = false;
const inactiveHtml = globalThis.__auxTest.render(inactiveFormal);
assert(inactiveHtml.includes('暂无可评测样本') && !inactiveHtml.includes('未启用'),
  'formal active=false incorrectly closed shadow research');
const proven = JSON.parse(JSON.stringify(raw));
proven.shadow_evaluations.experiments[0].sample_size = 1;
proven.shadow_evaluations.experiments[0].mean_close_return = 2.5;
proven.shadow_evaluations.outcome_maturity.t1.mature = 1;
proven.shadow_evaluations.experiments[0].outcome_maturity.t1.mature = 1;
const provenHtml = globalThis.__auxTest.render(proven);
assert(provenHtml.includes('已有 1 个可核验样本') && provenHtml.includes('+2.50%'),
  'valid result lost behind empty summary');
const partialResult = JSON.parse(JSON.stringify(proven));
partialResult.shadow_evaluations.collection_health.status = 'partial';
const partialResultHtml = globalThis.__auxTest.render(partialResult);
assert(partialResultHtml.includes('已有 1 个可核验样本')
  && partialResultHtml.includes('采集部分成功'),
  'partial collection hid its verified result');
const partialWaiting = JSON.parse(JSON.stringify(waiting));
partialWaiting.shadow_evaluations.collection_health.status = 'partial';
const partialWaitingHtml = globalThis.__auxTest.render(partialWaiting);
assert(partialWaitingHtml.includes('跟踪 2 个样本，等待目标交易日结果')
  && partialWaitingHtml.includes('采集部分成功'),
  'partial collection hid pending targets');
const partialUnknown = JSON.parse(JSON.stringify(raw));
partialUnknown.shadow_evaluations.collection_health.status = 'partial';
const partialUnknownHtml = globalThis.__auxTest.render(partialUnknown);
assert(partialUnknownHtml.includes('采集部分成功')
  && !partialUnknownHtml.includes('本期形态未命中'),
  'partial collection was described as verified normal empty');
const disabled = JSON.parse(JSON.stringify(raw));
disabled.shadow_evaluations.mode = 'off';
const disabledHtml = globalThis.__auxTest.render(disabled);
assert(disabledHtml.includes('未启用') && !disabledHtml.includes('暂无可评测样本'),
  'explicitly disabled shadow mislabeled empty');
""")

    def test_h4_contract_breaks_and_backend_errors_are_visible_collapsed(self):
        _assert_node_contract(self, "({ shadow: renderShadowEvaluations, diagnostics: renderDiagnosticsCard })", r"""
const raw = JSON.parse(fs.readFileSync('docs/data/2026-10-08.json', 'utf8'));
for (const change of [
  {promotion_eligible: true}, {affects_production: true},
  {entry_mode: 'delay1_open'}, {intended_horizon: 2}
]) {
  const broken = JSON.parse(JSON.stringify(raw));
  Object.assign(broken.shadow_evaluations.experiments[0], change);
  const html = globalThis.__auxTest.shadow(broken);
  const beforeDetails = html.split('<details class="shadow-experiment-details"')[0];
  assert(!beforeDetails.includes('暂无可评测样本'), 'broken experiment showed normal zero summary');
  assert(beforeDetails.includes('异常') || beforeDetails.includes('不可用'),
    'experiment contract problem was hidden in technical details');
}
const errorHtml = globalThis.__auxTest.diagnostics({
  selection_input_health: {status: 'ok', formal: {
    formal_actions_allowed: true, all_formal_actions_allowed: true, invalid_codes: []
  }},
  diagnostics: {decision_brief: {status: 'error', error: '模拟方向复核超时'}}
});
const visible = errorHtml.split('<details class="diagnostics-details"')[0];
assert(visible.includes('影响范围：今日方向模型复核') && visible.includes('模拟方向复核超时'),
  'current backend error scope and reason hidden inside collapsed diagnostics');
for (const technical of [
  'reader failed at /srv/private/account/token=demo-secret',
  'reader failed at C:\\private\\account\\token=demo-secret',
  'request failed https://example.invalid/run?api_key=demo-secret',
  'Traceback\nFile /srv/private/account/token=demo-secret',
  '方向复核超时 /srv/private/account/token=demo-secret',
  '方向复核超时 sk-proj-demo-secret /srv/private/account',
  '方向复核超时 sk-proj-demo-secret'
]) {
  const secretHtml = globalThis.__auxTest.diagnostics({
    selection_input_health: {status: 'ok', formal: {
      formal_actions_allowed: true, all_formal_actions_allowed: true, invalid_codes: []
    }}, diagnostics: {recommendation_ledger: {status: 'error', error: technical}}
  });
  const summary = secretHtml.split('<details class="diagnostics-details"')[0];
  assert(summary.includes('影响范围：推荐归因账本'), 'safe error scope missing');
  assert(!summary.includes('demo-secret') && !summary.includes('sk-proj-')
    && !summary.includes('/srv/private')
    && !summary.includes('C:\\private') && !summary.includes('api_key=')
    && !summary.includes('Traceback'), 'raw technical error leaked in default summary');
  assert(summary.includes('详见诊断'), 'safe error explanation missing');
}
const partialInputHtml = globalThis.__auxTest.diagnostics({
  selection_input_health: {status: 'partial', formal: {
    formal_actions_allowed: true, all_formal_actions_allowed: false,
    blocked_strategies: ['h4_t3', 'unknown_strategy'],
    invalid_codes: ['002352', 'bad<script>', '002352', '600001', '300001', '000001']
  }}, diagnostics: {}
});
const partialInputSummary = partialInputHtml.split('<details class="diagnostics-details"')[0];
assert(partialInputSummary.includes('部分策略输入未核验：H4 T+3')
  && partialInputSummary.includes('002352'),
  'validated partial input scope disappeared from default summary');
assert(partialInputSummary.includes('共4只') && !partialInputSummary.includes('共5只'),
  'duplicate affected codes inflated the visible stock count');
assert(!partialInputSummary.includes('unknown_strategy')
  && !partialInputSummary.includes('bad&lt;script&gt;')
  && !partialInputSummary.includes('bad<script>'),
  'unvalidated strategy or code entered trusted summary');
const researchFailureHtml = globalThis.__auxTest.diagnostics({
  selection_input_health: {status: 'error', error: '研究池输入失败', formal: {
    formal_actions_allowed: true, all_formal_actions_allowed: true, invalid_codes: []
  }}, diagnostics: {}
});
const researchFailureSummary = researchFailureHtml.split('<details class="diagnostics-details"')[0];
assert(researchFailureSummary.includes('研究池输入失败')
  && !researchFailureSummary.includes('部分策略输入未核验'),
  'research-only failure was misreported as formal input blockage');
const healthyHtml = globalThis.__auxTest.diagnostics({
  selection_input_health: {status: 'ok', formal: {
    formal_actions_allowed: true, all_formal_actions_allowed: true, invalid_codes: []
  }}, diagnostics: {data_quality: {status: 'ok'}}
});
assert(!healthyHtml.includes('diagnostic-alert-summary')
  && healthyHtml.includes('<details class="diagnostics-details"'),
  'normal diagnostics were expanded or made noisy');
""")

    def test_historical_disabled_registration_does_not_claim_current_shutdown(self):
        _assert_node_contract(self, "({ card: renderScorecardV2Card })", r"""
const raw = JSON.parse(fs.readFileSync('docs/data/2026-10-08.json', 'utf8'));
const disabled = raw.strategy_scorecards.research.find(function (item) {
  return item.strategy === 'next_day_boom' && item.evaluation_status === 'disabled';
});
assert(disabled, 'fixed disabled registration missing');
const current = globalThis.__auxTest.card(raw, disabled, 'current');
assert(current.includes('本期未启用'), 'matched current disabled meaning lost');
const history = globalThis.__auxTest.card(raw, disabled, 'history');
const unknown = globalThis.__auxTest.card(Object.assign({}, raw, {strategy_run_manifest: []}), disabled, 'unknown');
assert(!history.includes('本期未启用') && history.includes('历史登记'),
  'historical disabled registration claimed current shutdown');
assert(!unknown.includes('本期未启用') && unknown.includes('身份未核实'),
  'unknown identity claimed current shutdown');
""")

    def test_psy_research_has_base_summary_and_one_full_audit(self):
        _assert_node_contract(self, "({ build: buildAuxiliaryStacks })", r"""
const raw = JSON.parse(fs.readFileSync('docs/data/2026-10-08.json', 'utf8'));
const research = globalThis.__auxTest.build(raw).research;
assert(research.includes('上涨持续性（PSY12）'), 'research summary label missing');
assert(research.includes('PSY12') && research.includes('50') && research.includes('6 / 12'),
  'available base value disappeared with missing shadow score');
assert(research.includes('成交额组件不可用'), 'shadow component gap hidden');
assert(research.includes('<details class="psy12-research-audit"'),
  'mounted research has no reachable full PSY12 audit');
assert((research.match(/<span>正式分<\/span>/g) || []).length === 1,
  'full formal/shadow audit missing or duplicated in research');
const audit = research.split('<details class="psy12-research-audit"')[1];
assert(audit.includes('<span>正式分</span><strong>33</strong>')
  && audit.includes('<span>影子分</span><strong>—</strong>')
  && audit.includes('<span>差值</span><strong>—</strong>'),
  'available formal score or null shadow/delta was lost');
const next = JSON.parse(fs.readFileSync('docs/data/2026-10-09.json', 'utf8'));
const nextHtml = globalThis.__auxTest.build(next).research;
assert(nextHtml.includes('58') && nextHtml.includes('7 / 12'), 'next-day base facts were hard coded');
""")
