#!/usr/bin/env node
/*
 * Deterministic browser acceptance for the decision workbench.
 *
 * The page is loaded from a generated file:// fixture.  The report JS/CSS is
 * read from --root, ECharts is served from the caller's local cache, and all
 * other network requests are aborted.  No report, account, token, holding,
 * save, push, or service endpoint is involved.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawnSync } = require('child_process');

function parseArgs(argv) {
  const result = {
    root: path.resolve(__dirname, '..'),
    fixture: path.resolve(__dirname, '..', 'tests/fixtures/ui_final_browser/build_fixture.py'),
    output: '',
    echarts: process.env.ECHARTS_PATH || '',
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === '--root') result.root = path.resolve(argv[++index]);
    else if (value === '--fixture') result.fixture = path.resolve(argv[++index]);
    else if (value === '--output') result.output = path.resolve(argv[++index]);
    else if (value === '--echarts') result.echarts = path.resolve(argv[++index]);
    else if (value === '--executable-path') result.executablePath = argv[++index];
    else if (value === '--help' || value === '-h') {
      console.log('Usage: NODE_PATH=<playwright-node-path> node scripts/check_ui_final_browser.cjs [options]');
      console.log('  --root <worktree>       source JS/CSS worktree (default: repository root)');
      console.log('  --fixture <builder.py>  deterministic fixture builder');
      console.log('  --output <directory>    private screenshot/JSON output directory');
      console.log('  --echarts <file>        local ECharts 5.4.3 file');
      process.exit(0);
    }
  }
  return result;
}

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function loadPlaywright() {
  try {
    return require('playwright');
  } catch (error) {
    const explicit = process.env.PLAYWRIGHT_PATH;
    if (explicit) {
      try { return require(explicit); } catch (nested) { error = nested; }
    }
    return { error };
  }
}

function buildFixture(options) {
  const child = spawnSync('/usr/bin/python3', [options.fixture], {
    cwd: options.root,
    env: Object.assign({}, process.env, { PYTHONPATH: options.root }),
    encoding: 'utf8',
    maxBuffer: 50 * 1024 * 1024,
  });
  if (child.status !== 0) {
    throw new Error('fixture builder failed: ' + (child.stderr || child.stdout || 'unknown error').trim());
  }
  try {
    return JSON.parse(child.stdout);
  } catch (error) {
    throw new Error('fixture builder returned invalid JSON: ' + error.message);
  }
}

function htmlFor(payload, legacy) {
  const report = JSON.stringify(payload.report).replace(/</g, '\\u003c');
  const workbench = legacy ? 'null' : JSON.stringify(payload.workbench).replace(/</g, '\\u003c');
  const evidence = legacy ? 'null' : JSON.stringify(payload.recommendation_evidence).replace(/</g, '\\u003c');
  return '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8">'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">'
    + '<title>合成浏览器验收报告</title><link rel="stylesheet" href="report-v2.css">'
    + '</head><body><div id="app"></div><script>'
    + 'window.CHANLUN_BOOTSTRAP={'
    + 'pageDate:"2026-09-11",isFileProtocol:true,accessControlEnabled:false,'
    + 'top10ApiBase:"",precloseApiBase:"",decisionWatchlistUrl:"",'
    + 'inlineReportData:' + report + ','
    + 'decisionWorkbench:' + workbench + ','
    + 'recommendationEvidence:' + evidence
    + '};</script><script src="https://cdn.bootcdn.net/ajax/libs/echarts/5.4.3/echarts.min.js"></script>'
    + '<script defer src="report-v2.js"></script></body></html>';
}

function makeOutputDirectory(requested) {
  if (requested) {
    fs.mkdirSync(requested, { recursive: true });
    return requested;
  }
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14);
  const directory = path.join('/private/tmp', 'chanlun-ui-final-browser-' + stamp);
  fs.mkdirSync(directory, { recursive: true });
  return directory;
}

function assertCondition(condition, message, details) {
  if (!condition) {
    const error = new Error(message);
    if (details !== undefined) error.details = details;
    throw error;
  }
}

async function waitForReport(page) {
  await page.waitForFunction(() => Boolean(
    window.REPORT_DATA && document.querySelector('.workspace-tab')
  ), { timeout: 15000 });
  await page.locator('.workspace-tab').first().waitFor({ state: 'visible', timeout: 10000 });
}

async function candidateCodes(page) {
  return page.locator('.candidate-row').evaluateAll((rows) => rows.map((row) => row.dataset.code));
}

async function comparisonCodes(page) {
  return page.locator('.candidate-evidence-table tbody tr').evaluateAll((rows) => rows.map((row) => {
    const text = row.querySelector('th')?.textContent || '';
    const match = text.match(/\d{6}/);
    return match ? match[0] : '';
  }).filter(Boolean));
}

function strategyContractExpectations(payload) {
  const labels = { main: '正式主推', h4_t3: 'H4 T+3', confirming: '等确认' };
  const expectations = [];
  Object.entries(labels).forEach(([strategyId, label]) => {
    const item = (payload.workbench?.items || []).find((candidate) =>
      (candidate.strategy_results || []).some((result) => result.strategy_id === strategyId));
    const result = (item?.strategy_results || []).find((candidate) => candidate.strategy_id === strategyId);
    if (!result) return;
    const contract = result.contract || {};
    const action = result.formal_action || (result.role === 'research' ? '仅观察' : '本期未声明正式动作');
    const finiteContractNumber = (value) => {
      if (value === null || value === undefined || value === '') return null;
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    };
    expectations.push({
      code: item.code,
      label,
      action,
      horizon: contract.intended_horizon,
      referencePrice: finiteContractNumber(contract.reference_price),
      invalidationPrice: finiteContractNumber(contract.invalidation_price),
      score: finiteContractNumber(result.score),
    });
  });
  return expectations;
}

function normalizeHorizon(value) {
  const text = String(value ?? '').trim().toUpperCase().replace(/\s+/g, '');
  if (!text) return '';
  return text.startsWith('T+') ? text : (/^\d+$/.test(text) ? `T+${text}` : text);
}

function contractSourceSegment(sourceText, label) {
  const prefix = `${label}：`;
  return String(sourceText || '').split('；').find((segment) => segment.startsWith(prefix)) || '';
}

function contractNumberFromSegment(segment, label) {
  const match = String(segment || '').match(new RegExp(`${label}\\s*(-?\\d+(?:\\.\\d+)?)`));
  return match ? Number(match[1]) : null;
}

function assertEquivalentContractNumber(segment, label, expected, sourceLabel, code) {
  if (expected === null) return;
  const actual = contractNumberFromSegment(segment, label);
  assertCondition(actual !== null && Number.isFinite(actual),
    `来源策略合同缺少${sourceLabel} ${code} 的${label}`, { sourceLabel, code, segment });
  assertCondition(Math.abs(actual - expected) < 1e-9,
    `来源策略合同${sourceLabel} ${code} 的${label}不一致`, { sourceLabel, code, expected, actual, segment });
}

function assertStrategyContractSegment(sourceText, expected) {
  const segment = contractSourceSegment(sourceText, expected.label);
  assertCondition(segment, `来源策略合同缺失: ${expected.label} ${expected.code}`, {
    sourceLabel: expected.label, code: expected.code, sourceText,
  });
  assertCondition(segment.includes(`${expected.label}：${expected.action}`),
    `来源策略动作不一致: ${expected.label} ${expected.code}`, { expected, segment });
  if (expected.horizon === undefined || expected.horizon === null || expected.horizon === '') {
    assertCondition(segment.includes('周期未声明'),
      `来源策略周期缺失: ${expected.label} ${expected.code}`, { expected, segment });
  } else {
    const expectedHorizon = normalizeHorizon(expected.horizon);
    const actualHorizon = normalizeHorizon(segment.match(/周期\s*([^·；]+)/)?.[1] || '');
    assertCondition(actualHorizon === expectedHorizon,
      `来源策略周期不一致: ${expected.label} ${expected.code}`, {
        expected: expectedHorizon, actual: actualHorizon, segment,
      });
  }
  assertEquivalentContractNumber(segment, '参考价', expected.referencePrice, expected.label, expected.code);
  assertEquivalentContractNumber(segment, '失效位', expected.invalidationPrice, expected.label, expected.code);
  if (expected.score !== null) {
    const actualScore = contractNumberFromSegment(segment, '分数');
    assertCondition(actualScore !== null && Math.round(actualScore) === Math.round(expected.score),
      `来源策略分数不一致: ${expected.label} ${expected.code}`, {
        expected: Math.round(expected.score), actual: actualScore, segment,
      });
  }
}

async function countText(page) {
  return page.locator('#candidateCount').textContent();
}

async function clickAllTab(page) {
  const all = page.locator('.workspace-tab').filter({ hasText: '全部' }).first();
  await all.waitFor({ state: 'visible', timeout: 10000 });
  await all.click();
  await page.waitForFunction(() => document.querySelector('#candidateCount')?.textContent.includes('/'));
}

async function checkLayout(page, width, height) {
  const layout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    bodyClientWidth: document.body.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
    title: document.title,
  }));
  assertCondition(layout.scrollWidth <= layout.clientWidth + 1,
    '页面存在横向溢出', { width, height, layout });
  assertCondition(layout.bodyScrollWidth <= layout.bodyClientWidth + 1,
    'body 存在横向溢出', { width, height, layout });
  return layout;
}

async function checkCandidateContract(page, payload) {
  await clickAllTab(page);
  await page.locator('#candidateMore').click();
  await page.waitForFunction(() => document.querySelector('#candidateCount')?.textContent === '显示 25 / 25');
  const rows = await page.locator('.candidate-row').count();
  assertCondition(rows === payload.cases.paging_total, '加载更多没有展示完整25只候选', { rows });

  const statusByCode = await page.locator('.candidate-row').evaluateAll((items) => Object.fromEntries(
    items.map((item) => [item.dataset.code, item.dataset.status])
  ));
  Object.entries(payload.expected).forEach(([code, expected]) => {
    assertCondition(statusByCode[code] === expected.page_status,
      '候选状态与合成 workbench 合同不一致: ' + code,
      { expected: expected.page_status, actual: statusByCode[code] });
  });

  const listText = await page.locator('#candidateList').innerText();
  assertCondition(listText.includes('正式') && listText.includes('研究观察'),
    '正式/研究身份标签没有同时出现在完整清单');
  const researchText = await page.locator('[data-code="600004"]').innerText();
  assertCondition(researchText.includes('研究观察') && !researchText.includes('可上车'),
    '研究候选混入正式动作', { researchText });
  const incompleteText = await page.locator('[data-code="600002"]').innerText();
  assertCondition(incompleteText.includes('正式推荐·条件待补充') && incompleteText.includes('正式'),
    '正式缺价样本丢失正式身份或待补充状态', { incompleteText });
  await page.locator('[data-code="600002"]').click();
  const incompleteDetail = await page.locator('#detailPanel').innerText();
  assertCondition(incompleteDetail.includes('正式动作：可上车'),
    '正式缺价样本详情没有保留原正式动作', { incompleteDetail });

  const comparison = page.locator('#candidateEvidenceComparison');
  await comparison.locator('summary').click();
  const compare = await comparisonCodes(page);
  assertCondition(compare.length === payload.cases.paging_total,
    '全部清单的比较表受分页可见行数影响', { compareLength: compare.length });
  for (const expected of strategyContractExpectations(payload)) {
    const row = page.locator('.candidate-evidence-table tbody tr').filter({ hasText: expected.code }).first();
    await row.waitFor({ state: 'visible', timeout: 10000 });
    const sourceText = await row.locator('td').nth(0).innerText();
    assertStrategyContractSegment(sourceText, expected);
  }

  const initialList = await candidateCodes(page);
  assertCondition(initialList.length === 25, '全部清单未显示25行');
  await page.locator('#candidateSearch').fill('完整正式样本');
  await page.waitForFunction(() => document.querySelector('#candidateCount')?.textContent.includes('1 / 1'));
  assertCondition((await comparisonCodes(page)).length === 1, '有结果搜索未同步比较集合');
  await page.locator('#candidateSearch').fill('不存在的合成代码');
  await page.waitForFunction(() => document.querySelector('#candidateCount')?.textContent.includes('0 / 0'));
  assertCondition((await comparison.innerText()).includes('当前集合没有匹配对象'),
    '无结果搜索没有清空比较集合');
  await page.locator('#candidateSearch').fill('');
  await page.waitForFunction(() => document.querySelector('#candidateCount')?.textContent.includes('20 / 25'));
  assertCondition((await comparisonCodes(page)).length === 25, '清空搜索未恢复完整比较集合');

  const chipButton = page.locator('[data-sector-filter="芯片"]').first();
  await chipButton.click();
  await page.waitForFunction(() => document.querySelector('#candidateCount')?.textContent.includes(' / '));
  const filteredCodes = await candidateCodes(page);
  const filteredTotal = Number((await countText(page)).match(/\/\s*(\d+)/)?.[1] || 0);
  const filteredCompareCodes = await comparisonCodes(page);
  assertCondition(filteredTotal > 0 && filteredTotal < 25, '板块筛选没有缩小当前集合', { filteredTotal });
  assertCondition(filteredCompareCodes.length === filteredTotal,
    '板块筛选的比较集合与列表总集合不一致', {
      filteredCodes, filteredCompareCodes, filteredTotal,
    });
  await page.locator('.funding-mainline-clear').click();
  await page.waitForFunction(() => document.querySelector('#candidateCount')?.textContent.includes('20 / 25'));
  assertCondition((await comparisonCodes(page)).length === 25, '清空板块筛选未恢复完整集合');
  return { rows, comparisonRows: compare.length, initialList };
}

async function checkChartLifecycle(page) {
  await page.locator('[data-code="600001"]').click();
  await page.locator('#chartCanvas').waitFor({ state: 'visible', timeout: 10000 });
  const chartReady = await page.waitForFunction(() => {
    const mount = document.querySelector('#chartCanvas');
    return Boolean(window.echarts && mount && window.echarts.getInstanceByDom(mount));
  }, { timeout: 10000 }).then(() => true).catch(() => false);
  assertCondition(chartReady, '完整正式样本没有挂载真实 ECharts 实例');

  const before = await page.evaluate(() => {
    const chart = window.echarts.getInstanceByDom(document.querySelector('#chartCanvas'));
    chart.dispatchAction({ type: 'dataZoom', start: 20, end: 65 });
    const option = chart.getOption() || {};
    const zoom = (option.dataZoom || []).find((item) => item && item.type !== 'inside') || (option.dataZoom || [])[0] || {};
    return { start: zoom.start, end: zoom.end, startValue: zoom.startValue, endValue: zoom.endValue };
  });
  const structure = page.locator('[data-chart-layer="structure"]').first();
  await structure.click();
  const after = await page.evaluate(() => {
    const chart = window.echarts.getInstanceByDom(document.querySelector('#chartCanvas'));
    const option = chart.getOption() || {};
    const zoom = (option.dataZoom || []).find((item) => item && item.type !== 'inside') || (option.dataZoom || [])[0] || {};
    return { start: zoom.start, end: zoom.end, startValue: zoom.startValue, endValue: zoom.endValue };
  });
  assertCondition(
    (before.startValue === undefined || before.startValue === after.startValue)
      && (before.endValue === undefined || before.endValue === after.endValue)
      && (before.startValue !== undefined || before.start === undefined || Math.abs(before.start - after.start) < 0.01)
      && (before.endValue !== undefined || before.end === undefined || Math.abs(before.end - after.end) < 0.01),
    '缩放后切换结构图层没有保持窗口', { before, after }
  );

  await page.locator('[data-code="600006"]').click();
  const noDailyText = await page.locator('#detailPanel').innerText();
  assertCondition(/无法展示可验证 K\s*线/.test(noDailyText), '无日线样本没有保留明确的K线缺口', { noDailyText });
  await page.locator('[data-code="600007"]').click();
  await page.locator('#chartCanvas').waitFor({ state: 'visible', timeout: 10000 });
  const partialQuantity = await page.locator('[data-chart-quantity-status]').getAttribute('data-chart-quantity-status');
  assertCondition(partialQuantity === 'partial', '部分量能样本没有显示partial证据状态', { partialQuantity });
  await page.locator('[data-code="600001"]').click();
  const remount = await page.evaluate(() => ({
    canvases: document.querySelectorAll('#chartCanvas').length,
    hasInstance: Boolean(window.echarts.getInstanceByDom(document.querySelector('#chartCanvas'))),
    quantityStatus: document.querySelector('[data-chart-quantity-status]')?.getAttribute('data-chart-quantity-status') || '',
  }));
  assertCondition(remount.canvases === 1 && remount.hasInstance, '同股重挂载后图表实例缺失', remount);
  return { before, after, remount };
}

async function checkMobileLifecycle(page) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(250);
  await page.locator('.candidate-row').first().click();
  await page.locator('#mobileDrawer.is-open').waitFor({ state: 'visible', timeout: 10000 });
  await page.locator('#mobileDrawerClose').click();
  await page.waitForFunction(() => document.querySelector('#mobileDrawer')?.getAttribute('aria-hidden') === 'true');
  const focusCode = await page.evaluate(() => document.activeElement?.getAttribute('data-code') || '');
  assertCondition(Boolean(focusCode), '手机详情关闭后没有恢复列表焦点', { focusCode });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(350);
  const desktop = await checkLayout(page, 1440, 900);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(350);
  const mobileState = await page.evaluate(() => ({
    ariaHidden: document.querySelector('#mobileDrawer')?.getAttribute('aria-hidden'),
    selected: document.querySelector('.candidate-row.is-selected')?.getAttribute('data-code') || '',
  }));
  assertCondition(mobileState.ariaHidden === 'true' && mobileState.selected, '390→1440→390 丢失选中状态或抽屉焦点', mobileState);
  await page.locator('.candidate-row.is-selected').click();
  await page.locator('#mobileDrawer.is-open').waitFor({ state: 'visible', timeout: 10000 });
  const mobile = await checkLayout(page, 390, 844);
  return { focusCode, desktop, mobile, mobileState };
}

async function runLegacyCheck(page, legacyPath) {
  await page.goto('file://' + legacyPath, { waitUntil: 'load', timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('#decisionOverview')?.textContent.includes('旧版报告'), { timeout: 15000 });
  const text = await page.locator('#decisionOverview').innerText();
  assertCondition(text.includes('旧版报告'), '缺 workspace 的旧版报告没有明确能力边界', { text });
  return { text: text.slice(0, 160) };
}

async function run() {
  const options = parseArgs(process.argv.slice(2));
  const output = makeOutputDirectory(options.output);
  const evidence = {
    status: 'RUNNING',
    root: options.root,
    fixture: path.relative(options.root, options.fixture),
    output,
    viewports: [],
    checks: [],
    failures: [],
    pending: [
      { id: 'M3', reason: 'M3 待读验收：阅读摘要、同页锚点、候选密度与只读我的关注。' },
      { id: 'M4', reason: 'M4 待读验收：变化下钻、最多三只比较与历史入口。' },
      { id: 'M5', reason: 'M5 待读验收：图表库非阻塞加载、延迟/失败/重试。' },
    ],
    network: { abortedExternal: [], unexpected: [] },
  };
  let browser = null;
  let fixture;
  try {
    if (!fs.existsSync(options.root)) throw new Error('source root does not exist: ' + options.root);
    if (!fs.existsSync(options.fixture)) throw new Error('fixture builder does not exist: ' + options.fixture);
    if (!options.echarts || !fs.existsSync(options.echarts)) {
      throw new Error('ECharts 5.4.3 cache is missing; pass --echarts <local-file>');
    }
    const jsPath = path.join(options.root, 'chanlun/report_assets/report-v2.js');
    const cssPath = path.join(options.root, 'chanlun/report_assets/report-v2.css');
    const jsBody = fs.readFileSync(jsPath);
    const cssBody = fs.readFileSync(cssPath);
    fixture = buildFixture(options);
    assertCondition(fixture.cases.fixture_only === true, 'fixture is not marked synthetic');
    const misaligned = fixture.negatives?.misaligned_volume;
    assertCondition(misaligned && misaligned.volumes.length < misaligned.dates.length,
      'fixture 缺少成交量短数组负例');
    evidence.fixtureHash = sha256(JSON.stringify(fixture.workbench));
    evidence.fixtureNegative = {
      code: misaligned.code,
      dateBars: misaligned.dates.length,
      volumeBars: misaligned.volumes.length,
      expected: 'fail-closed-misaligned-array',
    };
    evidence.source = { js: sha256(jsBody), css: sha256(cssBody) };
    const runnerPath = path.join(output, 'runner.html');
    const legacyPath = path.join(output, 'legacy.html');
    fs.writeFileSync(runnerPath, htmlFor(fixture, false));
    const legacyPayload = Object.assign({}, fixture, {
      report: Object.assign({}, fixture.report), workbench: null,
      recommendation_evidence: null,
    });
    delete legacyPayload.report.workspace;
    fs.writeFileSync(legacyPath, htmlFor(legacyPayload, true));

    const loaded = loadPlaywright();
    if (loaded.error) {
      evidence.status = 'SKIP';
      evidence.skip = 'Playwright dependency unavailable: ' + loaded.error.message;
      fs.writeFileSync(path.join(output, 'browser.json'), JSON.stringify(evidence, null, 2));
      console.log(JSON.stringify(evidence, null, 2));
      process.exitCode = 2;
      return;
    }
    const { chromium } = loaded;
    if (!fs.existsSync(options.executablePath)) {
      evidence.status = 'SKIP';
      evidence.skip = 'Chrome executable unavailable: ' + options.executablePath;
      fs.writeFileSync(path.join(output, 'browser.json'), JSON.stringify(evidence, null, 2));
      console.log(JSON.stringify(evidence, null, 2));
      process.exitCode = 2;
      return;
    }
    browser = await chromium.launch({
      executablePath: options.executablePath,
      headless: true,
      chromiumSandbox: true,
    });

    const viewports = [[1440, 900], [1366, 768], [390, 844]];
    for (const [width, height] of viewports) {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: 'reduce' });
      const page = await context.newPage();
      const viewportEvidence = { width, height, checks: [], failures: [], pageErrors: [], consoleErrors: [] };
      page.on('pageerror', (error) => viewportEvidence.pageErrors.push(error.message));
      page.on('console', (message) => {
        if (message.type() === 'error') viewportEvidence.consoleErrors.push(message.text());
      });
      page.on('requestfailed', (request) => {
        const url = request.url();
        if (/^https?:/i.test(url)) evidence.network.abortedExternal.push({ url, failure: request.failure()?.errorText || '' });
        else evidence.network.unexpected.push({ url, failure: request.failure()?.errorText || '' });
      });
      await context.route('**/*', async (route) => {
        const url = route.request().url();
        if (url.includes('echarts/5.4.3/echarts.min.js')) {
          await route.fulfill({ status: 200, contentType: 'application/javascript', body: fs.readFileSync(options.echarts) });
          return;
        }
        if (url.endsWith('/report-v2.js')) {
          await route.fulfill({ status: 200, contentType: 'application/javascript', body: jsBody });
          return;
        }
        if (url.endsWith('/report-v2.css')) {
          await route.fulfill({ status: 200, contentType: 'text/css', body: cssBody });
          return;
        }
        if (url.endsWith('/data/comparison-index.json')) {
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ dates: [], reports: {} }) });
          return;
        }
        if (url.startsWith('file:')) {
          await route.continue();
          return;
        }
        await route.abort();
      });
      try {
        await page.goto('file://' + runnerPath, { waitUntil: 'load', timeout: 30000 });
        await waitForReport(page);
        await page.screenshot({ path: path.join(output, `${width}-home.png`), fullPage: false });
        viewportEvidence.layout = await checkLayout(page, width, height);
        viewportEvidence.checks.push({ name: 'layout', status: 'passed' });

        if (width === 1440) {
          try {
            viewportEvidence.contract = await checkCandidateContract(page, fixture);
            viewportEvidence.checks.push({ name: 'candidate-contract', status: 'passed' });
          } catch (error) {
            viewportEvidence.failures.push({ name: 'candidate-contract', error: error.message, details: error.details });
          }
          try {
            viewportEvidence.chart = await checkChartLifecycle(page);
            viewportEvidence.checks.push({ name: 'chart-lifecycle', status: 'passed' });
            await page.screenshot({ path: path.join(output, '1440-detail.png'), fullPage: false });
          } catch (error) {
            viewportEvidence.failures.push({ name: 'chart-lifecycle', error: error.message, details: error.details });
          }
          try {
            await page.locator('[data-code="600010"]').click();
            await page.locator('#detailPanel').waitFor({ state: 'visible', timeout: 10000 });
            const mismatch = await page.evaluate(() => {
              const modules = Array.from(document.querySelectorAll('#detailPanel [data-evidence-module="04"]'));
              const module = modules.find((item) => {
                const text = item.textContent || '';
                return text.includes('15m') || text.includes('15分钟');
              });
              const heading = module?.querySelector('h3')?.textContent || '';
              return {
                evidenceModuleFound: Boolean(module),
                evidenceHas15m: Boolean(module),
                heading,
                headingHas30m: /30分钟/.test(heading),
              };
            });
            assertCondition(!mismatch.evidenceHas15m || !mismatch.headingHas30m,
              '15分钟证据被展示在固定30分钟标题下，存在周期错配', mismatch);
            viewportEvidence.checks.push({ name: 'timeframe-contract', status: 'passed', mismatch });
          } catch (error) {
            viewportEvidence.failures.push({ name: 'timeframe-contract', error: error.message, details: error.details });
          }
          try {
            viewportEvidence.legacy = await runLegacyCheck(page, legacyPath);
            viewportEvidence.checks.push({ name: 'legacy-workspace-boundary', status: 'passed' });
            await page.goto('file://' + runnerPath, { waitUntil: 'load', timeout: 30000 });
            await waitForReport(page);
          } catch (error) {
            viewportEvidence.failures.push({ name: 'legacy-workspace-boundary', error: error.message, details: error.details });
          }
        }
        if (width === 390) {
          try {
            viewportEvidence.mobile = await checkMobileLifecycle(page);
            viewportEvidence.checks.push({ name: 'mobile-drawer-and-transition', status: 'passed' });
            await page.screenshot({ path: path.join(output, '390-detail.png'), fullPage: false });
          } catch (error) {
            viewportEvidence.failures.push({ name: 'mobile-drawer-and-transition', error: error.message, details: error.details });
          }
        }
        if (viewportEvidence.pageErrors.length) {
          viewportEvidence.failures.push({ name: 'pageerror', error: 'pageerror emitted', details: viewportEvidence.pageErrors });
        }
      } catch (error) {
        viewportEvidence.failures.push({ name: 'viewport-bootstrap', error: error.message, details: error.details });
      } finally {
        evidence.viewports.push(viewportEvidence);
        await context.close();
      }
    }
    evidence.failures = evidence.viewports.flatMap((viewport) => viewport.failures.map((failure) => Object.assign({ viewport: viewport.width }, failure)));
    evidence.status = evidence.failures.length ? 'FAIL' : 'PASS';
  } catch (error) {
    evidence.status = 'FAIL';
    evidence.failures.push({ name: 'runner', error: error.message, details: error.details });
  } finally {
    if (browser) await browser.close();
    fs.writeFileSync(path.join(output, 'browser.json'), JSON.stringify(evidence, null, 2));
  }
  console.log(JSON.stringify(evidence, null, 2));
  if (evidence.status === 'FAIL') process.exitCode = 1;
}

run().catch((error) => {
  console.error(error.stack || error.message || error);
  process.exitCode = 1;
});
