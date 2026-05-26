# Chanlun Weak Access Control Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 GitHub Pages 上的缠论报告增加“弱保护前端 key”访问控制：带正确 `key` 的 URL 可查看全部历史日期，未带或带错 `key` 时只允许查看配置白名单中的指定日期。

**Architecture:** 保持现有 GitHub Pages 静态部署，不引入后端鉴权。访问控制只作用于前端可见性与前端允许加载的日期范围：前端读取 `?key=`，本地校验通过后开放全部日期；否则只开放 `PUBLIC_DATES` 配置中的日期。为减少明文暴露，前端不直接比较明文 key，而比较 `sha256(key + salt)` 的预置摘要值。

**Tech Stack:** Python 3 report generator, static HTML/JS in `chanlun/report_generator.py`, JSON report artifacts under `docs/`, `unittest`, browser `crypto.subtle` or embedded SHA-256 helper.

---

## 1. 边界与目标

### 1.1 这不是安全鉴权

这次方案明确是：

```text
弱保护 / 防随手看
```

不是：

```text
真正安全的后端鉴权
```

必须在 spec 和代码注释里明确：

1. 这套方案只能控制页面默认可见范围。
2. 前端代码可被查看，具备技术能力的人仍然可以绕过。
3. 不能把这套逻辑宣传成“安全访问控制”。

### 1.2 目标行为

1. 带正确 `key`：
   - 可查看全部历史日期
   - 可使用 `#pure` / `#fusion`
   - 历史 tabs 显示全部日期

2. 未带 `key` 或 `key` 错误：
   - 只可查看 `PUBLIC_DATES` 中的日期
   - 历史 tabs 只显示这些日期
   - 若当前页面日期不在 allowlist，则自动回退到 allowlist 默认日期

3. 配置：
   - `["2026-05-26"]` -> 只可看一天
   - `["2026-05-26", "2026-05-27"]` -> 只可看两天

## 2. 当前问题

当前页面里已经有一段半成品访问控制：

```javascript
var ACCESS_KEY = "02951e20-6de2-418c-8bab-463647220883";
var GRANTED = key === ACCESS_KEY;
```

但这套实现存在问题：

1. 直接把明文 UUID 写进前端。
2. 未真正把“允许日期白名单”接到历史数据渲染逻辑里。
3. 当前访问控制只是雏形，没有完整处理：
   - 默认日期回退
   - 历史 tabs 过滤
   - `data.json` 可见日期过滤
   - 错误态提示

## 3. 方案选择

### 3.1 候选方案

#### 方案 A：前端明文 key 对比

优点：

1. 改动最小
2. 实现最快

缺点：

1. 明文 UUID 直接暴露在页面源码
2. 太直白，几乎没有任何弱加固意义

#### 方案 B：前端 hash 校验

做法：

1. 配置明文 key 在生成阶段参与计算
2. 前端只保留：
   - `ACCESS_KEY_SALT`
   - `ACCESS_KEY_SHA256`
3. 页面运行时对 `?key=` 做 `sha256(key + salt)` 比对

优点：

1. 不直接暴露明文 key
2. 改动仍然较小

缺点：

1. 仍然不是安全鉴权
2. 只是混淆级别更高

#### 方案 C：前端多 key / 多 scope

本次不需要，YAGNI。

### 3.2 推荐方案

采用 **方案 B：前端 hash 校验**。

原因：

1. 满足你当前“弱保护前端 key”的目标。
2. 不需要引入后端。
3. 相比明文 key，至少不把 UUID 直接裸露在 JS 常量里。

## 4. 配置设计

### 4.1 新增配置项

建议新增到 `config.py`：

```python
ENABLE_WEAK_ACCESS_CONTROL = True

PUBLIC_DATES = ["2026-05-26"]

FULL_ACCESS_KEY = "02951e20-6de2-418c-8bab-463647220883"

FULL_ACCESS_KEY_SALT = "chanlun-report-salt-v1"
```

生成阶段再产出：

```python
FULL_ACCESS_KEY_HASH = sha256(FULL_ACCESS_KEY + FULL_ACCESS_KEY_SALT)
```

要求：

1. `FULL_ACCESS_KEY` 只在生成阶段使用，不直接注入最终 HTML。
2. 最终 HTML 中只出现：
   - `FULL_ACCESS_KEY_HASH`
   - `FULL_ACCESS_KEY_SALT`

### 4.2 日期白名单语义

`PUBLIC_DATES` 语义：

1. 未授权用户允许访问的日期集合。
2. 顺序应按日期降序或生成时的历史顺序统一。
3. 空数组表示未授权用户不可查看任何历史日报，仅显示访问受限提示。

## 5. 数据面设计

### 5.1 保持现有数据结构

本次不拆数据面，不改部署结构，继续使用：

```text
docs/data.json
docs/data/{date}.json
```

但前端必须保证：

1. 未授权时不展示非 allowlist 日期
2. 未授权时不主动加载非 allowlist 日期

### 5.2 Manifest 过滤

当前 `data.json` 内含：

```json
{
  "dates": [...],
  "reports": {...}
}
```

要求新增前端过滤函数：

```javascript
getAllowedDates(allDates, granted, publicDates)
filterHistoryData(HISTORY_DATA, allowedDates)
```

语义：

1. `granted=true`：返回全部日期
2. `granted=false`：仅返回 `PUBLIC_DATES`

## 6. 前端行为设计

### 6.1 访问控制初始化

初始化流程改成：

```text
1. 读取 URLSearchParams(window.location.search)
2. 取 key
3. 计算 sha256(key + salt)
4. 与内嵌 hash 比对
5. 得到 GRANTED
6. 基于 GRANTED 计算 allowed dates
7. 选择可见默认日期
8. 仅加载该日期可用数据
```

### 6.2 默认日期选择

新增逻辑：

```text
resolveInitialDate(PAGE_DATE, allowedDates)
```

规则：

1. 如果当前 `PAGE_DATE` 在 `allowedDates` 中，使用它。
2. 否则回退到：
   - `allowedDates[0]`，如果存在
   - 否则显示“无可公开访问日期”提示

### 6.3 未授权模式

未授权时：

1. 不再简单 `renderLimitedView()` 直接终止。
2. 而是进入“public allowlist 模式”：
   - 允许渲染 `PUBLIC_DATES` 中的报告
   - 隐藏非 allowlist 历史日期
   - 切历史时只能切 allowlist 子集

### 6.4 授权模式

授权时：

1. 允许显示全部历史 tabs
2. 允许切任意 `data.json` 中存在的日期

### 6.5 错误态与提示

要求加入明确提示：

1. `key` 缺失或无效：
   - 页面不报错
   - 仅提示“当前仅开放部分日期”

2. 当前日期不开放：
   - 提示“当前日期未公开，已切换到最近开放日期”

3. `PUBLIC_DATES=[]`：
   - 提示“当前无公开可访问日报”

## 7. 页面实现细节

### 7.1 新增前端 helper

建议新增 JS helper：

```javascript
async function sha256Hex(text) { ... }
async function resolveGranted() { ... }
function getAllowedDates(allDates, granted, publicDates) { ... }
function resolveInitialDate(pageDate, allowedDates) { ... }
function filterHistoryData(historyData, allowedDates) { ... }
```

### 7.2 页面渲染调整

要求调整：

1. `init()` 改为异步初始化。
2. `loadHistory()` 完成后，先过滤 `HISTORY_DATA`，再渲染 tabs。
3. `showHistory(dateStr)` 前先判断该日期是否在允许集合中。
4. 如果不允许，直接 return，不渲染。

### 7.3 hash 实现方式

优先方案：

1. 使用浏览器原生 `crypto.subtle.digest('SHA-256', ...)`

fallback：

1. 若兼容性需要，可注入极小的纯 JS SHA-256 实现

本项目面向现代浏览器，优先用 `crypto.subtle` 即可。

## 8. 生成链路设计

### 8.1 report_generator 注入配置

`report_generator.py` 需要把这些变量注入 HTML：

```javascript
var ACCESS_CONTROL_ENABLED = true;
var ACCESS_PUBLIC_DATES = ["2026-05-26"];
var ACCESS_KEY_SALT = "chanlun-report-salt-v1";
var ACCESS_KEY_HASH = "<sha256-hex>";
```

明确禁止再注入：

```javascript
var ACCESS_KEY = "明文 uuid";
```

### 8.2 public dates 与 history dates 对齐

生成阶段必须保证：

1. `ACCESS_PUBLIC_DATES` 与 `data.json.dates` 的交集合法。
2. 若配置了一个不存在于 `data.json` 的日期，不应导致前端报错。
3. 只把实际存在的日期留在最终 allowlist。

## 9. 实现任务

### Task 1: 配置与 hash 注入

**Files:**
- Modify: `config.py`
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Step 1: 写失败测试**

覆盖：

1. HTML 中不再出现明文 `ACCESS_KEY`
2. HTML 中包含 `ACCESS_KEY_HASH`
3. HTML 中包含 `ACCESS_PUBLIC_DATES`

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

**Step 3: 最小实现**

实现：

1. 新增弱保护配置
2. 生成阶段计算 hash
3. 注入 hash/salt/public dates

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

### Task 2: 前端授权判定与默认日期回退

**Files:**
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Step 1: 写失败测试**

覆盖：

1. `init()` 改成异步授权判定
2. 当前日期不在 allowlist 时，会回退到允许日期
3. `PUBLIC_DATES=[]` 时会渲染受限提示

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

**Step 3: 最小实现**

实现：

1. `resolveGranted()`
2. `resolveInitialDate()`
3. 受限提示 UI

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

### Task 3: 历史 tabs 与 history 数据过滤

**Files:**
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Step 1: 写失败测试**

覆盖：

1. 未授权时只渲染 allowlist 日期 tabs
2. `showHistory(dateStr)` 对非 allowlist 日期无效
3. 授权时可渲染全部日期

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

**Step 3: 最小实现**

实现：

1. `getAllowedDates()`
2. `filterHistoryData()`
3. `renderHistoryTabs()` 使用过滤后的 dates

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

## 10. QA 流程

### 10.1 单测

必须通过：

```bash
python3 -m unittest tests.test_report_generator -v
python3 -m unittest discover -s tests -p 'test_*.py'
```

### 10.2 手工页面验证

验证以下场景：

1. 无 key：

```text
https://breakaway4here-arch.github.io/ChanlunStrategy/
```

预期：

1. 只看到 `PUBLIC_DATES` 中的日期
2. 若首页日期不在白名单，会自动跳到最近公开日期
3. 页面提示“当前仅开放部分日期”

2. 正确 key：

```text
https://breakaway4here-arch.github.io/ChanlunStrategy/?key=02951e20-6de2-418c-8bab-463647220883#fusion
```

预期：

1. 可以看到全部历史日期
2. `#fusion` 正常生效

3. 错误 key：

```text
https://breakaway4here-arch.github.io/ChanlunStrategy/?key=bad-key
```

预期：

1. 回退到 public allowlist 模式
2. 不暴露内部错误

### 10.3 allowlist 配置验证

分别验证：

```python
PUBLIC_DATES = ["2026-05-26"]
PUBLIC_DATES = ["2026-05-26", "2026-05-27"]
PUBLIC_DATES = []
```

预期：

1. tabs 数量正确
2. 默认日期回退正确
3. 空 allowlist 时只有受限提示，无历史内容

## 11. 风险与限制

### 11.1 明确限制

1. 这不是安全鉴权。
2. 仍然无法阻止有能力的人阅读前端逻辑后绕过。
3. 若有人直接访问公开 JSON 路径，仍可能拿到公开目录中的数据。

### 11.2 风险控制

1. 不再明文暴露 UUID。
2. 通过 allowlist 收窄默认公开范围。
3. 页面上明确使用“当前仅开放部分日期”之类文案，不误导成安全权限系统。

## 12. 自 Review 清单

这份 spec 已自 review，确认如下：

1. 明确承认这是弱保护，不伪装成安全方案。
2. 保留了你要的 `?key=` 体验。
3. 通过 `PUBLIC_DATES` 完整控制公开日期范围。
4. 不再使用明文 UUID 对比，而是 hash 比对。
5. QA 覆盖了默认日期回退、历史 tabs 过滤、空白名单这几个最容易漏掉的点。

Plan complete and saved to `docs/plans/2026-05-26-chanlun-access-control-weak-protection-spec.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?
