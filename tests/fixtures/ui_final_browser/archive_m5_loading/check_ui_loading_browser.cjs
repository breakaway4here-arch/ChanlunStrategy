#!/usr/bin/env node
/* Offline M5/U14 browser acceptance: delayed, failed, and retried ECharts. */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function playwright() {
  try { return require('playwright'); } catch (error) {
    if (process.env.PLAYWRIGHT_PATH) {
      try { return require(process.env.PLAYWRIGHT_PATH); } catch (nested) { error = nested; }
    }
    return { error };
  }
}

function parseArgs(argv) {
  const options = {
    root: path.resolve(__dirname, '../../../..'),
    output: path.join('/private/tmp', 'chanlun-ui-final-loading-' + Date.now()),
    echarts: process.env.ECHARTS_PATH || '',
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--root') options.root = path.resolve(argv[++i]);
    else if (argv[i] === '--output') options.output = path.resolve(argv[++i]);
    else if (argv[i] === '--echarts') options.echarts = path.resolve(argv[++i]);
    else if (argv[i] === '--executable-path') options.executablePath = argv[++i];
  }
  return options;
}

function chart(seed) {
  const dates = Array.from({ length: 32 }, (_, i) => {
    const date = new Date(Date.UTC(2026, 7, 1 + i));
    return date.toISOString().slice(0, 10);
  });
  const closes = dates.map((_, i) => 10 + seed + i * 0.1);
  return {
    dates,
    opens: closes.map((v) => v - 0.05),
    highs: closes.map((v) => v + 0.12),
    lows: closes.map((v) => v - 0.12),
    closes,
    volumes: dates.map((_, i) => 1000 + i),
    volume_units: dates.map(() => 'hands'),
    volume_raw_units: dates.map(() => 'shares'),
    volume_sources: dates.map(() => 'synthetic-loading-fixture'),
    chart_annotations: { markPoints: [{ name: '测试信号', coord: [dates[dates.length - 1], closes[closes.length - 1]] }] },
    buy_points: [{ type: '测试买点', price: closes[closes.length - 1] }],
  };
}

function fixture() {
  const makeRow = (code, name, rank, seed) => Object.assign({
    code, name, sector: '合成板块', view_rank: rank,
    action_semantics: 'formal',
    ref: { pool: 'picks_fusion', code },
    price_basis: { adjustment: 'qfq', factor_vs_raw: 1 },
    data_status: { daily: 'verified', latest_date: '2026-09-11', stale: false, is_final: true },
    decision_engine_v1: { total_score: 60 },
    formal_decision_contract: {
      action: '可上车', action_reason: '合成加载验收样本',
      reference_price: 10, invalidation_price: 9, intended_horizon: 3,
    },
  }, chart(seed));
  const first = makeRow('600001', '延迟验收样本一', 1, 0);
  const second = makeRow('600002', '延迟验收样本二', 2, 1);
  const history = Array.from({ length: 20 }, (_, i) => ({ date: `2026-08-${String(i + 1).padStart(2, '0')}`, score: 50 + i, ma3: 49 + i }));
  const report = {
    date: '2026-09-11',
    data_quality: { as_of: '2026-09-11T15:05:00+08:00', is_official: true, bar_state: 'closed', market_status: 'verified' },
    selection_input_health: {
      schema_version: 2,
      status: 'verified',
      formal: { status: 'verified', formal_actions_allowed: true },
    },
    market_sentiment_history: history,
    workspace: {
      default_view: 'main',
      views: { main: [first, second] },
      view_meta: { main: { role: 'formal', action_semantics: 'formal', availability: { state: 'available' } } },
    },
    picks_fusion: [first, second],
  };
  return {
    report,
    evidence: {
      schema_version: 1,
      report_date: '2026-09-11',
      views: {
        main: [first, second].map((row) => ({
          code: row.code,
          summary: { status: 'available', as_of: '2026-09-11', name: row.name, sector: row.sector },
          daily_structure: { status: 'available', as_of: '2026-09-11', summary: '合成日线证据' },
          sublevel_30m: { status: 'available', as_of: '2026-09-11', summary: '合成确认依据' },
          price_evidence: { status: 'available', as_of: '2026-09-11' },
        })),
      },
    },
  };
}

function pageHtml(payload) {
  const report = payload.report;
  return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
    + '<meta name="viewport" content="width=device-width,initial-scale=1">'
    + '<link rel="stylesheet" href="report-v2.css">'
    + '</head><body><div id="app"></div><script>'
    + 'window.CHANLUN_BOOTSTRAP={pageDate:"2026-09-11",accessControlEnabled:false,top10ApiBase:"",precloseApiBase:"",inlineReportData:'
    + JSON.stringify(report).replace(/</g, '\\u003c') + ','
    + 'recommendationEvidence:' + JSON.stringify(payload.evidence).replace(/</g, '\\u003c') + '};'
    + 'window.CHANLUN_CHART_LIBRARY={url:"echarts-5.4.3.min.js",version:"5.4.3"};'
    + '</script><script defer src="report-v2.js"></script></body></html>';
}

function wait(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

async function runMode(browser, options, mode, viewport, source, css, echarts) {
  const context = await browser.newContext({ viewport, reducedMotion: 'reduce' });
  const page = await context.newPage();
  const requests = [];
  const external = [];
  const errors = [];
  const chartBody = Buffer.concat([
    echarts,
    Buffer.from(`
(function () {
  var library = window.echarts;
  window.__chanlunChartInitRecords = [];
  if (!library || typeof library.init !== 'function') return;
  var originalInit = library.init;
  library.init = function (dom) {
    window.__chanlunChartInitRecords.push({
      id: dom && dom.id || '',
      connected: Boolean(dom && dom.isConnected),
    });
    return originalInit.apply(this, arguments);
  };
})();
`, 'utf8'),
  ]);
  let libraryRequests = 0;
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('requestfailed', (request) => {
    if (/^https?:/i.test(request.url())) external.push(request.url());
  });
  await context.route('**/*', async (route) => {
    const url = route.request().url();
    if (url.endsWith('/report-v2.js')) return route.fulfill({ status: 200, contentType: 'application/javascript', body: source });
    if (url.endsWith('/report-v2.css')) return route.fulfill({ status: 200, contentType: 'text/css', body: css });
    if (url.endsWith('/echarts-5.4.3.min.js')) {
      libraryRequests += 1;
      requests.push({ mode, request: libraryRequests, at: Date.now() });
      if (mode === 'delay' && libraryRequests === 1) await wait(10000);
      if (mode === 'error' && libraryRequests === 1) return route.abort();
      if (mode === 'retry' && libraryRequests === 1) return route.abort();
      return route.fulfill({ status: 200, contentType: 'application/javascript', body: chartBody });
    }
    if (url.endsWith('/data/comparison-index.json')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ dates: [], reports: {} }) });
    if (url.startsWith('file:')) return route.continue();
    return route.abort();
  });
  const result = { mode, viewport: viewport.name, libraryRequests: 0, errors, external, checks: [], failure: null };
  try {
    const started = Date.now();
    await page.goto('file://' + path.join(options.output, 'runner.html'), { waitUntil: 'domcontentloaded', timeout: 5000 });
    try {
      await page.locator('.candidate-row').first().waitFor({ state: 'visible', timeout: 3000 });
    } catch (error) {
      const diagnostic = await page.evaluate(() => ({
        readyState: document.readyState,
        body: document.body?.innerText?.slice(0, 800) || '',
        globalError: document.querySelector('#globalError')?.innerText || '',
        report: Boolean(window.REPORT_DATA),
        bootstrap: Boolean(window.CHANLUN_BOOTSTRAP),
        shell: document.querySelectorAll('.report-shell').length,
      }));
      error.message += ' diagnostic=' + JSON.stringify(diagnostic);
      throw error;
    }
    result.domContentMs = Date.now() - started;
    result.checks.push('header/list/text-before-chart-ready');
    if (mode === 'delay') {
      if (result.domContentMs >= 3000) throw new Error('列表被图表库延迟阻塞: ' + result.domContentMs + 'ms');
      var mobileInitialReady = false;
      if (viewport.name === 'mobile-390') {
        await page.waitForFunction(() => document.querySelector('#detailPanel .detail-empty')
          ?.textContent.includes('选择后查看详情'), { timeout: 3000 });
        await page.waitForFunction(() => Boolean(window.echarts), { timeout: 15000 });
        const initial = await page.evaluate(() => ({
          detail: document.querySelector('#detailPanel')?.innerText || '',
          records: window.__chanlunChartInitRecords || [],
        }));
        if (!initial.detail.includes('选择后查看详情')
            || initial.records.some((record) => record.id === 'chartCanvas' || !record.connected)) {
          throw new Error('手机首页等待图表库时存在 detached 图表实例: ' + JSON.stringify(initial));
        }
        mobileInitialReady = true;
        result.mobileInitial = initial;
        result.checks.push('mobile-initial-idle-no-detached-chart');
      }
      await page.locator('[data-code="600002"]').click();
      if (!mobileInitialReady) {
        await page.locator('#chartCanvas [data-chart-library-state="loading"]').waitFor({ state: 'visible', timeout: 1000 });
      }
      await page.waitForFunction(() => Boolean(window.echarts && window.echarts.getInstanceByDom(document.querySelector('#chartCanvas'))), { timeout: 15000 });
      const ready = await page.evaluate(() => ({
        detail: document.querySelector('#mobileDrawerContent')?.innerText
          || document.querySelector('#detailPanel')?.innerText || '',
        stockChart: Boolean(window.echarts.getInstanceByDom(document.querySelector('#chartCanvas'))),
        sentimentChart: Boolean(window.echarts.getInstanceByDom(document.querySelector('#marketSentimentChart'))),
        library: window.getChartLibraryState(),
        records: window.__chanlunChartInitRecords || [],
      }));
      if (!ready.detail.includes('延迟验收样本二') || !ready.stockChart
          || (viewport.name === 'mobile-390'
            && !ready.records.some((record) => record.id === 'chartCanvas' && record.connected))) {
        throw new Error('延迟完成后旧股票回流或个股图表未就绪: ' + JSON.stringify(ready));
      }
      result.ready = ready;
      if (viewport.name === 'mobile-390') {
        await page.locator('#mobileDrawerClose').click();
        await page.waitForFunction(() => document.querySelector('#mobileDrawer')?.getAttribute('aria-hidden') === 'true');
        result.checks.push('mobile-click-chart-ready-and-close');
      }
      await page.evaluate(() => window.initReportV2());
      const afterInit = await page.evaluate(() => ({ shells: document.querySelectorAll('.report-shell').length, rows: document.querySelectorAll('.candidate-row').length }));
      if (afterInit.shells !== 1 || afterInit.rows !== 2) throw new Error('重复业务初始化未被阻止: ' + JSON.stringify(afterInit));
      result.checks.push('current-stock-only-ready-and-single-init');
    } else {
      await page.locator('#chartCanvas [data-chart-library-state="error"]').waitFor({ state: 'visible', timeout: 3000 });
      await page.locator('[data-code="600002"]').click();
      await page.locator('#chartCanvas [data-chart-library-state="error"]').waitFor({ state: 'visible', timeout: 1000 });
      if (mode === 'retry') {
        await page.evaluate(() => {
          const button = document.querySelector('#chartCanvas [data-chart-library-retry]');
          if (!button) throw new Error('retry button missing');
          button.click();
          button.click();
        });
        await page.locator('#chartCanvas [data-chart-library-state="loading"]').waitFor({ state: 'visible', timeout: 1000 });
        await page.locator('#marketSentimentChart [data-chart-library-state="loading"]').waitFor({ state: 'visible', timeout: 1000 });
        await page.waitForFunction(() => Boolean(
          window.echarts
          && window.echarts.getInstanceByDom(document.querySelector('#chartCanvas'))
          && window.echarts.getInstanceByDom(document.querySelector('#marketSentimentChart'))
        ), { timeout: 5000 });
        const ready = await page.evaluate(() => ({
          detail: document.querySelector('#detailPanel')?.innerText || '',
          stockChart: Boolean(window.echarts.getInstanceByDom(document.querySelector('#chartCanvas'))),
          sentimentChart: Boolean(window.echarts.getInstanceByDom(document.querySelector('#marketSentimentChart'))),
        }));
        if (!ready.detail.includes('延迟验收样本二') || !ready.stockChart || !ready.sentimentChart) {
          throw new Error('失败后切股再重试未恢复当前个股图与市场情绪图: ' + JSON.stringify(ready));
        }
        result.ready = ready;
        result.checks.push('failure-visible-and-user-retry');
      } else {
        const failure = await page.locator('#chartCanvas [data-chart-library-state="error"]').innerText();
        if (!failure.includes('图表')) throw new Error('图表失败状态缺少用户文案: ' + failure);
        if ((await page.locator('.candidate-row').count()) !== 2) throw new Error('图表失败破坏候选列表');
        result.checks.push('failure-isolated-from-workbench');
      }
    }
    await page.screenshot({ path: path.join(options.output, `${mode}-${viewport.name}.png`), fullPage: false });
    result.libraryRequests = libraryRequests;
    if (mode === 'retry' && libraryRequests !== 2) throw new Error('重试没有形成一次失败+一次成功的单例加载: ' + libraryRequests);
    if (mode !== 'retry' && libraryRequests !== 1) throw new Error('图表库加载次数异常: ' + libraryRequests);
    if (errors.length) throw new Error('pageerror: ' + errors.join('; '));
    if (external.length) throw new Error('外部请求未被隔离: ' + external.join(', '));
  } catch (error) {
    result.failure = { message: error.message, stack: error.stack };
  } finally {
    await context.close();
  }
  return result;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  fs.mkdirSync(options.output, { recursive: true });
  const loaded = playwright();
  if (loaded.error) { console.error('SKIP Playwright: ' + loaded.error.message); process.exitCode = 2; return; }
  if (!options.echarts || !fs.existsSync(options.echarts)) { console.error('SKIP missing ECharts cache'); process.exitCode = 2; return; }
  if (!fs.existsSync(options.executablePath)) { console.error('SKIP missing Chrome'); process.exitCode = 2; return; }
  const source = fs.readFileSync(path.join(options.root, 'chanlun/report_assets/report-v2.js'));
  const css = fs.readFileSync(path.join(options.root, 'chanlun/report_assets/report-v2.css'));
  const echarts = fs.readFileSync(options.echarts);
  fs.writeFileSync(path.join(options.output, 'runner.html'), pageHtml(fixture()));
  const browser = await loaded.chromium.launch({ executablePath: options.executablePath, headless: true, chromiumSandbox: true });
  const evidence = { sourceHash: crypto.createHash('sha256').update(source).digest('hex'), modes: [] };
  const viewports = [
    { name: 'desktop-1440', width: 1440, height: 900 },
    { name: 'desktop-1366', width: 1366, height: 768 },
    { name: 'mobile-390', width: 390, height: 844 },
  ];
  try {
    // Exercise the real delayed library path at every supported release viewport.
    for (const viewport of viewports) {
      evidence.modes.push(await runMode(browser, options, 'delay', viewport, source, css, echarts));
    }
    // Failure and user retry use the primary desktop viewport to keep the
    // output small while preserving the same singleton loader path.
    for (const mode of ['error', 'retry']) {
      evidence.modes.push(await runMode(browser, options, mode, viewports[0], source, css, echarts));
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(options.output, 'browser.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify(evidence, null, 2));
  if (evidence.modes.some((item) => item.failure)) process.exitCode = 1;
}

main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
