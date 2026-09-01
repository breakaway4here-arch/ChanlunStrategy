# 14:45 预跑封存回看 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 14:45 预跑在 14:56:30 后停止产生动作但保留公开票池，并在网页中以默认折叠的“已封存”卡片长期回看。

**Architecture:** Durable Object 继续保存同一冻结快照和内容哈希；Python/Worker 的公开投影把 `expired` 解释为“不可操作但可回看”，仅保留三池的公开候选字段。前端用原生 `<details>` 区分活跃展开态和到期折叠态，不把预跑写入正式报告或决策链路。

**Tech Stack:** Python 3 `unittest`、TypeScript/Vitest、原生 JavaScript/CSS、Cloudflare Workers + SQLite Durable Objects、GitHub Pages、launchd 非回归检查。

---

### Task 1: 用 Python 公共合同锁定“到期但可回看”

**Files:**
- Modify: `tests/test_preclose_contract.py:103-117`
- Modify: `chanlun/preclose_contract.py:186-230`

**Step 1: Write the failing test**

把到期断言改为：

```python
public = build_public_preclose_view(snapshot, now=now)
self.assertEqual(public["status"], "expired")
self.assertEqual(public["pools"]["main"], [
    {"code": "300998", "name": "宁波方正", "reference_price": 26.86}
])
self.assertIn("已封存", public["message"])
self.assertFalse(public["is_final"])
self.assertFalse(public["affects_formal"])
```

同时保留空池和失败状态仍返回空池的测试，防止内部失败伪装成历史结果。

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_preclose_contract -v
```

Expected: FAIL，现有到期投影会清空 `pools.main`。

**Step 3: Write minimal implementation**

在 `build_public_preclose_view()` 中分开计算：

```python
available = source.get("status") == "available" and not expired
replayable = source.get("status") == "available" and expired
show_pools = available or replayable
```

只有 `show_pools` 才复制三池；到期文案改为：

```python
"预跑已封存，仅供回看；14:57后不再依据预跑清单新增动作"
```

不得更改 `expires_at`、`content_hash`、`is_final=False` 或 `affects_formal=False`。

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest tests.test_preclose_contract -v
```

Expected: PASS。

**Step 5: Commit**

```bash
git add chanlun/preclose_contract.py tests/test_preclose_contract.py
git commit -m "fix: 保留已封存预跑公开票池"
```

### Task 2: 让 Worker 到期响应保留白名单三池

**Files:**
- Modify: `cloudflare/preclose-worker/test/index.test.ts:145-158`
- Modify: `cloudflare/preclose-worker/src/index.ts:158-183`

**Step 1: Write the failing test**

把 inclusive expiry 测试改为：

```typescript
expect(body.status).toBe("expired");
expect(body.pools).toEqual({
  main: [{ code: "300998", name: "宁波方正", reference_price: 26.86 }],
  h4_t3: [],
  acceleration: [],
});
expect(body.message).toContain("已封存");
expect(JSON.stringify(body)).not.toContain("internal_reason");
expect(JSON.stringify(body)).not.toContain("score");
```

继续断言 `Cache-Control: no-store`、允许 Origin 的 CORS、恶意 Origin 403 和 `is_final=false/affects_formal=false`。

**Step 2: Run test to verify it fails**

Run:

```bash
npm test --prefix cloudflare/preclose-worker -- --run
```

Expected: FAIL，现有 `publicSnapshot()` 在 expired 时返回空池。

**Step 3: Write minimal implementation**

将 Worker 的公开投影改为：

```typescript
const replayable = snapshot.status === "available" && expired;
const showPools = available || replayable;
for (const key of POOL_KEYS) {
  pools[key] = showPools
    ? snapshot.pools[key].map(normalizeCandidate).filter(Boolean) as PrecloseCandidate[]
    : [];
}
```

到期 `message` 使用“已封存”文案。不要修改 Durable Object 存储、migration、ETag 或内容哈希计算。

**Step 4: Run Worker tests and types**

Run:

```bash
npm test --prefix cloudflare/preclose-worker -- --run
npm run typecheck --prefix cloudflare/preclose-worker
npx wrangler types src/worker-configuration.d.ts --include-runtime=false --check
```

Expected: 全部 exit 0。

**Step 5: Commit**

```bash
git add cloudflare/preclose-worker/src/index.ts cloudflare/preclose-worker/test/index.test.ts
git commit -m "fix: 封存后保留预跑公开结果"
```

### Task 3: 用折叠卡片区分动作失效与历史回看

**Files:**
- Modify: `tests/test_preclose_frontend.py:129-166`
- Modify: `chanlun/report_assets/report-v2.js:581-647`
- Modify: `chanlun/report_assets/report-v2.css:378-500`
- Modify: `chanlun/report_assets/report-v2.css:5645-5674`

**Step 1: Write the failing frontend contract**

到期 HTML 必须满足：

```javascript
assert(expired.includes('<details class="preclose-snapshot-card preclose-snapshot-archived">'));
assert(!expired.includes('<details class="preclose-snapshot-card preclose-snapshot-archived" open>'));
assert(expired.includes('14:45预跑 · 已封存'));
assert(expired.includes('主推 1只｜H4 T+3 0只｜加速 1只'));
assert(expired.includes('宁波方正') && expired.includes('参考 26.86'));
assert(expired.includes('仅供回看'));
assert(!expired.includes('<button') && !expired.includes('<a '));
```

活跃快照必须带 `open`；统一空池仍为“本期未选出推荐票”。

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_preclose_frontend -v
```

Expected: FAIL，现有到期 HTML 只有警告条。

**Step 3: Implement the renderer**

在 `buildPrecloseSnapshotHtml()` 中始终先规范化三池并计算计数。输出：

```html
<details class="preclose-snapshot-card preclose-snapshot-archived">
  <summary>
    <strong>14:45预跑 · 已封存</strong>
    <span>主推 1只｜H4 T+3 0只｜加速 1只</span>
    <small>快照 aaaaaaaa</small>
  </summary>
  <div class="preclose-snapshot-content">...</div>
</details>
```

活跃态使用同一结构但加 `open` 和 active class。到期提示只说明“已封存，仅供回看；14:57后不再新增动作”。三池候选继续使用 `<div>`。

**Step 4: Implement responsive CSS**

为 summary 增加清晰的展开图标、计数层级和 focus 样式；390px 下 summary 纵向换行，三池继续单列，禁止横向溢出。不要改变正式候选卡和盘后复核布局。

**Step 5: Run frontend tests**

Run:

```bash
python3 -m unittest tests.test_preclose_frontend tests.test_auxiliary_frontend -v
node --check chanlun/report_assets/report-v2.js
```

Expected: PASS、exit 0。

**Step 6: Commit**

```bash
git add chanlun/report_assets/report-v2.js chanlun/report_assets/report-v2.css tests/test_preclose_frontend.py
git commit -m "feat: 折叠展示已封存预跑结果"
```

### Task 4: 同步 Pages 资产并做隔离回归

**Files:**
- Modify: `docs/assets/report-v2.js`
- Modify: `docs/assets/report-v2.css`
- Modify: `scripts/repair_auxiliary_decision_snapshot.py`
- Modify: `docs/index.html`、`docs/compare/index.html` 与现存日期入口的资源版本参数
- Test: `tests/test_preclose_formal_isolation.py`
- Test: `tests/test_preclose_e2e.py`
- Test: `tests/test_preclose_compare.py`

**Step 1: Copy canonical assets mechanically**

Run:

```bash
cp chanlun/report_assets/report-v2.js docs/assets/report-v2.js
cp chanlun/report_assets/report-v2.css docs/assets/report-v2.css
cmp chanlun/report_assets/report-v2.js docs/assets/report-v2.js
cmp chanlun/report_assets/report-v2.css docs/assets/report-v2.css
```

Expected: 两个 `cmp` exit 0。

**Step 2: Refresh approved asset hashes and report entrypoint versions**

将历史修复器的 `APPROVED_ASSET_SHA256` 更新为本次已审查的 canonical JS/CSS SHA。随后调用仓库现有 `refresh_report_asset_versions()`，只更新真实 `<link>`/`<script>` 的 `?v=` 参数，不改变正式报告正文：

```bash
python3 -c "from chanlun.report_generator import _report_asset_version, refresh_report_asset_versions; version=_report_asset_version(); print(version, len(refresh_report_asset_versions('docs', version)))"
```

Expected: 历史修复器资产保护测试和已检入入口版本测试均 PASS。

**Step 3: Run isolation and reconciliation tests**

Run:

```bash
python3 -m unittest \
  tests.test_preclose_contract \
  tests.test_preclose_frontend \
  tests.test_preclose_formal_isolation \
  tests.test_preclose_e2e \
  tests.test_preclose_compare -v
```

Expected: PASS。重点确认 expired 展示不写正式 DB、账本、日报或 comparison。

**Step 4: Run existing Top10 non-regression**

Run:

```bash
npm test --prefix cloudflare/top10-worker
```

Expected: PASS。

**Step 5: Commit**

```bash
git add docs/assets/report-v2.js docs/assets/report-v2.css \
  scripts/repair_auxiliary_decision_snapshot.py docs/index.html docs/compare/index.html docs/*/index.html
git commit -m "chore: 同步预跑封存页面资产"
```

### Task 5: 全量验证并整理一个最终提交

**Files:**
- Verify all files changed by Tasks 1-4

**Step 1: Run full verification**

Run:

```bash
python3 -m unittest discover -s tests
npm test --prefix cloudflare/preclose-worker -- --run
npm run typecheck --prefix cloudflare/preclose-worker
npm test --prefix cloudflare/top10-worker
python3 -m py_compile chanlun/preclose_contract.py
node --check chanlun/report_assets/report-v2.js
git diff --check
```

Expected: 所有命令 exit 0。

**Step 2: Re-fetch and rebase/squash safely**

再次 `git fetch origin`，确认 `origin/main` 是最终提交祖先。在独立 worktree 中把设计、计划和实现整理为一个干净提交；不得 stash、reset 或清理源 checkout 的 24 项用户修改。

Final title:

```text
fix: 封存后保留预跑结果回看
```

**Step 3: Re-run focused tests after final history rewrite**

Run Task 4 的聚焦 Python 测试、Worker 测试、Top10 测试和 `git diff --check`。

### Task 6: 推送 main、更新 production-runtime 与发布 Pages

**Files:**
- Production worktree: `.worktrees/production-runtime`

**Step 1: Push feature branch and fast-forward main**

确认远端 main 未变化且为提交祖先后，通过仓库现有安全流程推送功能分支并 fast-forward `main`。回读远端 SHA。

**Step 2: Fast-forward production-runtime**

只在 2026-09-01 正式 daily-report 和 reconcile 全部结束后执行：

```bash
git pull --ff-only origin main
```

确认 runtime clean、`.cache/chanlun` 共享软链接未改变、launchd 仍指向绝对 runtime 路径。

**Step 3: Verify Pages assets**

等待 GitHub Pages 发布，逐字节比较线上 `assets/report-v2.js`、`assets/report-v2.css` 与 production-runtime；根页和历史页均需 HTTP 200。

### Task 7: 发布 Worker 并回读真实封存快照

**Files:**
- Worker directory: `cloudflare/preclose-worker`

**Step 1: Dry-run**

Run the repository’s credential-safe Wrangler flow:

```bash
npx wrangler deploy --dry-run --cwd <production-runtime>/cloudflare/preclose-worker
```

Expected: 只有独立 SQLite Durable Object `PRE_CLOSE_SNAPSHOT`、允许 Origin 和 `PRECLOSE_ENABLED`，无新 migration 或 Top10 binding。

**Step 2: Deploy**

正式 deploy，记录 Worker version/deployment ID 和 100% traffic。回读 secret 名称但不得打印值。

**Step 3: Read back the existing 2026-09-01 snapshot**

允许 Pages Origin 的 GET 必须：

- `status=expired`；
- identity/hash 仍为 `preclose:2026-09-01:544b6c41a8d7e60f` / `544b6c41...e9295`；
- 三池为主推 5、H4 0、加速 0；
- 只含公开候选字段；
- `no-store` 和精确 CORS；
- 恶意 Origin 403。

Top10 继续要求 HTTP 200、ETag `watchlist-20260820-01`、body SHA `6f819f...92fb`。

### Task 8: 真实线上截图验收与回退验证

**Files:**
- Evidence: `.cache/chanlun/preclose/evidence/screenshots/2026-09-01-sealed-history/`

**Step 1: Screenshot collapsed state**

真实线上根页和 `/2026-09-01/` 历史页分别检查：

- 1440×900；
- 1366×768；
- 390px。

默认必须折叠并显示“14:45预跑 · 已封存”、三池计数和快照短哈希，零横向溢出。

**Step 2: Screenshot expanded state**

展开后必须看到 5 只股票和参考价、安全提示、统一空态；不得出现按钮、链接、评分或内部原因。盘后复核仍独立显示。

**Step 3: Verify action boundary**

14:57 后 Worker 状态仍为 `expired`，前端没有任何执行控件，正式 DB/ledger/report/comparison hash 不因展开回看发生变化。

**Step 4: Verify rollback path**

Worker 回退只允许向前部署上一公开投影版本；Pages 可向前提交恢复上一资产。确认无需 Durable Object migration 回滚，不承诺生命周期变化后的简单 rollback。

**Step 5: Update the ongoing goal evidence**

记录本功能完成证据，但完整 goal 仍需真实 WxPusher 业务成功、手机到达及剩余 25 项门槛，证据未齐不得 `update_goal(complete)`。
