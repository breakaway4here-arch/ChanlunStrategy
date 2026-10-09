// Pure projection/HTTP-read checks: no Durable Object, listener or Miniflare starts.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { build } = require('esbuild');
const compiled = await build({
  entryPoints: [fileURLToPath(new URL('../src/index.ts', import.meta.url))],
  bundle: true, write: false, platform: 'node', format: 'cjs',
  plugins: [{ name: 'pure-workers-base', setup(builder) {
    builder.onResolve({filter:/^cloudflare:workers$/}, () => ({path:'workers',namespace:'pure'}));
    builder.onLoad({filter:/.*/,namespace:'pure'}, () => ({contents:'export class DurableObject {}',loader:'js'}));
  }}],
});
const module = { exports: {} };
vm.runInNewContext(compiled.outputFiles[0].text, {module, exports: module.exports,
  require, Date, Response, Request, Headers, URL, TextEncoder, crypto:globalThis.crypto});
const { publicSnapshot, handleRequest } = module.exports;
const date = '2026-08-28';
const body = {schema_version:'preclose-selection-v1',strategy_version:'preclose-1445-v2',
  mode:'preclose_advisory',trade_date:date,snapshot_id:`preclose:${date}:${'a'.repeat(16)}`,
  content_hash:'a'.repeat(64),source_sha:'test',as_of:date+'T14:45:00+08:00',
  generated_at:date+'T14:48:00+08:00',expires_at:date+'T14:56:30+08:00',
  is_final:false,affects_formal:false,pools:{main:[],h4_t3:[],acceleration:[]},diagnostics:{secret:'audit'}};
for (const [status,message] of Object.entries({empty:'本期未选出推荐票',
  failed:'预跑失败，暂不提供候选',deadline_exceeded:'预跑超时，暂不提供候选',not_run:'本期预跑未运行'})) {
  test('Worker preserves '+status+' without internal audit', () => {
    const result = publicSnapshot({...body,status},1,Date.parse(date+'T14:50:00+08:00'));
    assert.equal(result.status,status); assert.equal(result.message,message);
    assert.equal(result.result_status,status); assert.ok(!JSON.stringify(result).includes('audit'));
    assert.equal(Object.values(result.pools).flat().length,0);
  });
}
test('abnormal available without candidates is failure', () => {
  assert.equal(publicSnapshot({...body,status:'available'},1,Date.parse(date+'T14:50:00+08:00')).status,'failed');
});
test('expired retains original failure status and does not invent candidates', () => {
  const result=publicSnapshot({...body,status:'failed'},1,Date.parse(body.expires_at));
  assert.equal(result.status,'expired'); assert.equal(result.result_status,'failed');
  assert.equal(Object.values(result.pools).flat().length,0);
});
test('valid available retains exact date/hash and whitelists public candidates', () => {
  const result=publicSnapshot({...body,status:'available',pools:{...body.pools,
    main:[{code:'600000',name:'浦发银行',reference_price:10,score:99}]}},1,Date.parse(date+'T14:55:59+08:00'));
  assert.equal(result.status,'available'); assert.equal(result.trade_date,date);
  assert.equal(result.snapshot_id,body.snapshot_id); assert.equal(result.content_hash,body.content_hash);
  assert.ok(!JSON.stringify(result).includes('score'));
});
test('actual GET route preserves state and no-store without starting a runtime', async () => {
  const value=publicSnapshot({...body,status:'deadline_exceeded'},1,Date.parse(date+'T14:50:00+08:00'));
  const response=await handleRequest(new Request('https://preclose.example/api/preclose/latest?date='+date),{
    PRECLOSE_ENABLED:'true',PRE_CLOSE_SNAPSHOT:{getByName(requestDate){assert.equal(requestDate,date);
      return {getPublicSnapshot:async()=>({revision:1,value})};}}
  });
  assert.equal(response.status,200); assert.equal(response.headers.get('cache-control'),'no-store');
  assert.equal((await response.json()).status,'deadline_exceeded');
});
