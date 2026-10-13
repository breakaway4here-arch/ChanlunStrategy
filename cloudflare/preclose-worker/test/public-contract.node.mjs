// Pure projection/HTTP-read checks: no Durable Object, listener or Miniflare starts.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';

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
const { publicSnapshot, handleRequest, PrecloseSnapshot } = module.exports;
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

// Exercise the actual storage methods with an in-memory SQL boundary only.
// No platform object is constructed and no Worker service is started.
function storedReader(snapshot, reconciliation) {
  const records = {
    snapshots: {revision:1, content_hash:snapshot.content_hash, body:JSON.stringify(snapshot)},
    reconciliations: reconciliation && {revision:3, content_hash:reconciliation.content_hash, body:JSON.stringify(reconciliation)},
  };
  const calls=[];
  const reader=Object.create(PrecloseSnapshot.prototype);
  reader.ctx={storage:{sql:{exec(sql,...args) {
    calls.push(sql);
    if(sql.startsWith('SELECT')) return {toArray:()=>[records[sql.includes('FROM snapshots')?'snapshots':'reconciliations']].filter(Boolean)};
    if(sql.includes('INSERT INTO reconciliations')) records.reconciliations={revision:args[0],content_hash:args[1],body:args[2]};
    return {toArray:()=>[]};
  }}}};
  return {reader,calls,records};
}
function reconciliationBody(status='unchanged') {
  return {schema_version:'preclose-reconciliation-v1', trade_date:date,snapshot_id:body.snapshot_id,
    preclose_content_hash:body.content_hash,formal_content_hash:'b'.repeat(64),content_hash:'c'.repeat(64),status,
    pools:Object.fromEntries(['main','h4_t3','acceleration'].map(key=>[key,{
      retained:[],added_after_close:[],removed_after_close:[],unchanged:true,
      details:{formal_order:[],secret:'internal-audit'},
    }])),diagnostics:{secret:'internal-audit'}};
}
for(const status of ['failed','deadline_exceeded','not_run',undefined]) {
  test('legacy '+status+' unchanged becomes unavailable on actual GET without storage writes',async()=>{
    const legacy=reconciliationBody();
    legacy.pools.main.retained=[{code:'600000',name:'正式股',reference_price:10,secret:'internal-audit'}];
    legacy.pools.main.details.formal_order=['600000'];
    const {reader,calls,records}=storedReader({...body,status},legacy);
    const before=JSON.stringify(records);
    const response=await handleRequest(new Request('https://preclose.example/api/preclose/reconciliation?date='+date),{
      PRECLOSE_ENABLED:'true',PRE_CLOSE_SNAPSHOT:{getByName(){return reader;}}
    });
    assert.equal(response.status,200);
    const value=await response.json();
    assert.equal(value.status,'preclose_unavailable');
    assert.equal(value.pools.main.formal[0].name,'正式股');
    for(const pool of Object.values(value.pools)) {
      assert.equal(pool.unchanged,false);
      for(const field of ['retained','added_after_close','removed_after_close']) assert.equal(pool[field].length,0);
    }
    assert.notEqual(value.content_hash,legacy.content_hash);
    assert.equal(value.preclose_content_hash,body.content_hash);
    assert.equal(value.revision,3); assert.equal(response.headers.get('etag'),'"3"');
    assert.equal(response.headers.get('cache-control'),'no-store');
    assert.ok(!JSON.stringify(value).includes('internal-audit'));
    assert.equal(JSON.stringify(records),before);
    assert.ok(calls.every(sql=>sql.startsWith('SELECT')));
    assert.equal((await reader.getReconciliation()).value.content_hash,value.content_hash);
  });
}
test('reconciliation does not cross date snapshot identity or content hash',async()=>{
  for(const field of ['trade_date','snapshot_id','preclose_content_hash']) {
    const legacy={...reconciliationBody(),[field]:'mismatch'};
    const {reader}=storedReader({...body,status:'failed'},legacy);
    assert.equal(await reader.getReconciliation(),null);
  }
  const {reader,records}=storedReader({...body,status:'failed'},reconciliationBody());
  records.snapshots.body=JSON.stringify({...body,status:'failed',content_hash:'d'.repeat(64)});
  assert.equal(await reader.getReconciliation(),null);
});
test('legacy failed changed preserves formal order without price and removes all change inference',async()=>{
  const value=reconciliationBody('changed');
  value.pools.main.retained=[{code:'600001',name:'原正式股',reference_price:10}];
  value.pools.main.added_after_close=[{code:'600002',name:'缺参考价正式股'}];
  value.pools.main.removed_after_close=[{code:'600003',name:'旧预跑股',reference_price:12}];
  value.pools.main.details.formal_order=['600002','600001'];
  const {reader}=storedReader({...body,status:'failed'},value);
  const actual=(await reader.getReconciliation()).value;
  assert.equal(actual.status,'preclose_unavailable');
  assert.equal(actual.pools.main.formal.map(row=>row.code).join(','),'600002,600001');
  assert.ok(!JSON.stringify(actual).includes('旧预跑股'));
});
test('normal empty and archived available comparisons and formal pending stay unchanged',async()=>{
  for(const status of ['empty','available']) {
    const snapshot={...body,status,pools:{...body.pools,main:status==='available'?[{code:'600000',name:'有效股',reference_price:10}]:[]}};
    const legacy=reconciliationBody(status==='available'?'changed':'unchanged');
    const {reader}=storedReader(snapshot,legacy);
    assert.equal((await reader.getReconciliation()).value.status,legacy.status);
    assert.equal((await reader.getReconciliation()).value.content_hash,legacy.content_hash);
  }
  const {reader}=storedReader({...body,status:'failed'},reconciliationBody('formal_pending'));
  assert.equal((await reader.getReconciliation()).value.status,'formal_pending');
});
test('new unavailable PUT and GET preserve publisher hash and reject comparison of failed snapshot',async()=>{
  const {reader}=storedReader({...body,status:'failed'},null);
  await assert.rejects(()=>reader.putReconciliation(reconciliationBody(),null));
  const value=reconciliationBody('preclose_unavailable');
  for(const pool of Object.values(value.pools)) {
    pool.unchanged=false; pool.formal=[]; pool.details={status:'preclose_unavailable'};
  }
  const result=await reader.putReconciliation(value,null);
  assert.equal(result.status,'created');
  const read=(await reader.getReconciliation()).value;
  assert.equal(read.status,'preclose_unavailable');
  assert.equal(read.content_hash,value.content_hash);
  assert.equal((await reader.putReconciliation(value,null)).status,'idempotent');
  for(const field of ['retained','added_after_close','removed_after_close']) {
    const invalid=structuredClone(value); invalid.pools.main[field]=[{code:'600000',name:'误报',reference_price:10}];
    await assert.rejects(()=>reader.putReconciliation(invalid,1));
  }
  const unsafe=structuredClone(value);unsafe.pools.main.unchanged=true;
  await assert.rejects(()=>reader.putReconciliation(unsafe,1));
  const missing=structuredClone(value);delete missing.pools.acceleration;
  await assert.rejects(()=>reader.putReconciliation(missing,1));
});
test('Python-produced unavailable contract retains content hash through actual Worker PUT and GET',async()=>{
  const fixture=JSON.parse(readFileSync(new URL('../../../tests/fixtures/preclose/reconciliation-unavailable.json',import.meta.url),'utf8'));
  const {reader}=storedReader(fixture.snapshot,null);
  assert.equal((await reader.putReconciliation(fixture.reconciliation,null)).status,'created');
  const response=await handleRequest(new Request('https://preclose.example/api/preclose/reconciliation?date='+fixture.snapshot.trade_date),{
    PRECLOSE_ENABLED:'true',PRE_CLOSE_SNAPSHOT:{getByName(){return reader;}}
  });
  assert.equal(response.status,200);
  const result=await response.json();
  for(const field of ['content_hash','preclose_content_hash','formal_content_hash','trade_date','snapshot_id']) {
    assert.equal(result[field],fixture.reconciliation[field]);
  }
  assert.equal(result.status,'preclose_unavailable');
  assert.deepEqual(result.pools.main.formal,fixture.formal.main);
  assert.ok(!JSON.stringify(result).includes('details'));
  assert.ok(!JSON.stringify(result).includes('diagnostics'));
});
