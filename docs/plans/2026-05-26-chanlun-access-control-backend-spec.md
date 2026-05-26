# Chanlun Access Control Via Existing Backend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 GitHub Pages 上的缠论报告增加真正有效的访问控制：带有效访问码的用户可查看全部日期与完整数据，未带访问码的用户只能查看配置允许的指定日期。

**Architecture:** 前端页面仍由 GitHub Pages 托管，但访问权限判断和受保护数据分发全部迁移到现有后端服务。GitHub Pages 只保留静态壳和公开 allowlist manifest；完整历史 JSON、不公开日期的全量数据、历史聚合数据不再公开暴露在 `docs/` 下，而是由后端鉴权后返回。

**Tech Stack:** Existing backend service, Python 3 report generator, static GitHub Pages frontend, JSON report artifacts, `unittest`.

---

## 1. 背景与目标

### 1.1 当前状态

当前页面：

```text
https://breakaway4here-arch.github.io/ChanlunStrategy/
```

是纯静态 GitHub Pages。

当前报告数据暴露方式：

```text
docs/index.html
docs/data.json
docs/data/{date}.json
docs/{date}/index.html
```

这意味着只要用户知道这些公开 JSON 路径，就可以绕过前端逻辑直接看数据。因此：

1. 任何纯前端 `uuid`、hash、混淆、加密方案都不是真正安全。
2. 如果继续把完整数据公开放在 `docs/data/*.json`，后端鉴权也没有意义。

### 1.2 目标行为

目标访问行为：

1. 带有效访问码：
   - 可看全部日期。
   - 可看完整历史聚合。
   - 可切换 pure / fusion。
   - 可访问完整受保护日报 JSON。

2. 不带访问码：
   - 只能看配置允许的日期白名单，例如 `["2026-05-26"]`。
   - 历史回顾只显示这些白名单日期。
   - 不能通过猜 URL 直接拿到未授权日期的全量 JSON。

3. 白名单日期配置：
   - 例如 `["2026-05-26"]`，只允许公开看这一天。
   - 例如 `["2026-05-26", "2026-05-27"]`，只允许公开看这两天。

## 2. 非目标

1. 不做多角色权限模型。
2. 不做用户体系、账号密码登录。
3. 不做前端假加密或仅 UI 隐藏式访问控制。
4. 不在本次改动里迁移整个站点出 GitHub Pages。

## 3. 设计结论

### 3.1 推荐方案

采用：

```text
GitHub Pages 静态壳
-> 现有后端做 access code 校验
-> 后端返回 access scope
-> 前端按 scope 拉取允许的数据
```

关键原则：

1. **真正受保护的数据不能继续公开放在 `docs/data/*.json`。**
2. 前端是否展示某日期，不再自己决定，而由后端返回权限范围。
3. 公共模式只暴露 allowlist 日期的精简或完整数据；非 allowlist 历史必须经后端鉴权获取。

### 3.2 两类数据面

拆成两套数据面：

#### A. Public Data Plane

供未授权访问使用，仍可放 GitHub Pages：

```text
docs/public-manifest.json
docs/public-data/{date}.json
```

只包含 allowlist 日期。

#### B. Protected Data Plane

供授权访问使用，不能再公开放 GitHub Pages：

```text
backend /api/chanlun/report-manifest
backend /api/chanlun/report/{date}
backend /api/chanlun/history
```

或后端返回短时签名下载 URL，但数据本体必须在非公开存储。

## 4. 数据与权限模型

### 4.1 访问码配置

后端配置：

```python
CHANLUN_ACCESS_CODES = {
    "02951e20-6de2-418c-8bab-463647220883": {
        "scope": "full",
        "expires_at": None,
        "label": "default-full-access",
    },
}
```

要求：

1. 访问码只保存在后端配置或密钥管理中。
2. 前端不再内嵌明文 access code。
3. 后端可后续扩展到多 code，但本次先支持单个或少量静态 code。

### 4.2 公共日期白名单配置

建议新增配置：

```python
CHANLUN_PUBLIC_DATES = ["2026-05-26"]
```

语义：

1. 未授权用户可查看这些日期。
2. 授权用户不受此限制。
3. 空数组表示未授权用户不可查看任何日报内容。

### 4.3 Access Scope 响应

后端校验成功后返回：

```json
{
  "granted": true,
  "scope": "full",
  "allowed_dates": ["2026-05-26", "2026-05-27", "2026-05-28"],
  "history_enabled": true,
  "expires_at": "2026-06-30T23:59:59+08:00"
}
```

未授权或无 code 时返回：

```json
{
  "granted": false,
  "scope": "public",
  "allowed_dates": ["2026-05-26"],
  "history_enabled": true
}
```

## 5. 前后端架构

### 5.1 前端改造原则

前端页面仍从 GitHub Pages 打开，但初始化流程改成：

```text
load query param key
-> call backend /api/chanlun/access/resolve
-> get access scope
-> decide public vs protected data source
-> render allowed dates only
```

前端不再直接假设：

```text
data/{PAGE_DATE}.json
data.json
```

永远存在且全部可公开访问。

### 5.2 后端接口

建议复用现有服务新增以下接口。

#### 5.2.1 `POST /api/chanlun/access/resolve`

请求：

```json
{
  "access_code": "02951e20-6de2-418c-8bab-463647220883"
}
```

或无 code：

```json
{
  "access_code": ""
}
```

响应：

```json
{
  "granted": false,
  "scope": "public",
  "allowed_dates": ["2026-05-26"],
  "history_enabled": true,
  "token": "optional short-lived session token"
}
```

说明：

1. 若后端已有 session/cookie 体系，可直接下发 cookie。
2. 若没有，返回短时 token，后续接口用 `Authorization: Bearer <token>`。

#### 5.2.2 `GET /api/chanlun/report-manifest`

返回当前权限下可见日期列表：

```json
{
  "dates": ["2026-05-26", "2026-05-27"],
  "default_date": "2026-05-27",
  "scope": "full"
}
```

#### 5.2.3 `GET /api/chanlun/report/{date}`

返回指定日期完整报告 JSON。

权限规则：

1. `scope=full`：任意存在的日期可取。
2. `scope=public`：仅 `date in CHANLUN_PUBLIC_DATES` 可取。
3. 否则返回 `403`.

#### 5.2.4 `GET /api/chanlun/history`

返回当前权限下的历史聚合数据。

要求：

1. `scope=public` 只能返回 allowlist 日期子集。
2. `scope=full` 才能返回完整历史聚合。

### 5.3 报告产物拆分

必须把当前产物拆成：

#### Public Artifacts

```text
docs/index.html
docs/public-manifest.json
docs/public-data/{date}.json
```

只为公开日期生成。

#### Protected Artifacts

```text
protected_reports/{date}.json
protected_history/data.json
```

这部分不提交到 GitHub Pages 公共目录，由后端读取本地文件、对象存储或内部静态目录。

## 6. 生成链路改造

### 6.1 report_generator 输出改造

当前：

```text
docs/data/{date}.json
docs/data.json
```

改成：

1. Public 输出：
   - 仅生成 allowlist 日期对应 `docs/public-data/{date}.json`
   - 生成 `docs/public-manifest.json`

2. Protected 输出：
   - 生成受保护目录下的 `{date}.json`
   - 生成受保护历史聚合

### 6.2 运行时配置

建议新增配置项：

```python
CHANLUN_PUBLIC_DATES = ["2026-05-26"]
CHANLUN_PROTECTED_OUTPUT_DIR = "protected_reports"
CHANLUN_PUBLIC_OUTPUT_SUBDIR = "public-data"
CHANLUN_ENABLE_BACKEND_ACCESS_CONTROL = True
CHANLUN_ACCESS_BACKEND_BASE_URL = "https://your-backend.example.com"
```

### 6.3 数据复制规则

对每个报告日：

1. 始终生成 protected full JSON。
2. 若该日期在 `CHANLUN_PUBLIC_DATES`：
   - 额外复制一份到 `docs/public-data/{date}.json`
3. 若不在 allowlist：
   - 不得出现在 GitHub Pages 公共目录。

## 7. 前端页面行为

### 7.1 初始化流程

新前端初始化：

```text
1. 读取 query param key
2. 调后端 resolve 接口
3. 得到 scope / allowed_dates / token
4. 选择默认日期
5. 拉对应 report JSON
6. 渲染页面
```

### 7.2 未授权行为

未授权时：

1. 只展示 `allowed_dates` 内日期 tabs。
2. 如果当前页面日期不在 allowlist：
   - 自动跳转到 allowlist 第一项或默认项。
3. 切历史时也只能切 allowlist 日期。

### 7.3 授权行为

授权时：

1. 加载完整日期 manifest。
2. 可浏览所有历史日期。
3. `#pure` / `#fusion` hash 行为保持不变。

### 7.4 错误态

要求有明确 UI：

1. 后端不可达：
   - 显示“访问控制服务不可用”
2. 日期无权限：
   - 显示“该日期未开放访问”
3. access code 无效：
   - 按 public scope 回退，不报内部错误

## 8. 安全边界

### 8.1 必须做到

1. 非公开日期完整 JSON 不出现在 `docs/` 公共目录。
2. `docs/data.json` 不再包含所有历史完整聚合。
3. 后端接口必须再次校验 date 是否在当前 scope 内。
4. 不能只在前端隐藏日期 tab。

### 8.2 明确禁止

1. 禁止继续公开 `docs/data/{private-date}.json`
2. 禁止继续公开包含全部日期的 `docs/data.json`
3. 禁止把 access code、hash salt、签名秘钥写进前端 JS

## 9. 实现任务

### Task 1: 定义访问控制配置与受保护产物目录

**Files:**
- Modify: `config.py`
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Step 1: 写失败测试**

覆盖：

1. `CHANLUN_PUBLIC_DATES=["2026-05-26"]` 时，仅生成该日 public JSON。
2. 非 public 日期只能生成 protected JSON，不进入 `docs/public-data/`。
3. public manifest 仅列出 allowlist 日期。

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

**Step 3: 最小实现**

实现：

1. 新增 public/protected 输出目录配置。
2. 拆分 public manifest 与 protected artifacts。
3. 停止默认写全量 `docs/data.json` 作为公开历史聚合。

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

### Task 2: 新增后端 access resolve / manifest / report 接口

**Files:**
- Modify: existing backend service routes/controllers
- Modify: existing backend service config
- Test: backend access-control tests

**Step 1: 写失败测试**

覆盖：

1. 有效 access code 返回 `scope=full`
2. 无 code 返回 `scope=public`
3. public scope 下访问非 allowlist 日期返回 `403`
4. full scope 下访问任意存在日期返回 `200`

**Step 2: 运行测试确认失败**

Run:

```bash
<backend test command>
```

**Step 3: 最小实现**

新增：

1. `/api/chanlun/access/resolve`
2. `/api/chanlun/report-manifest`
3. `/api/chanlun/report/{date}`
4. `/api/chanlun/history`

要求：

1. access code 校验在后端完成。
2. session token 或 cookie 必须有过期时间。
3. 每个受保护接口都做 scope 校验。

**Step 4: 跑测试**

Run:

```bash
<backend test command>
```

### Task 3: 改造前端初始化与日期切换

**Files:**
- Modify: `chanlun/report_generator.py`
- Test: `tests/test_report_generator.py`

**Step 1: 写失败测试**

覆盖：

1. 页面初始化脚本不再写死 `data/{PAGE_DATE}.json`
2. 前端会调用后端 resolve / manifest 接口
3. public 模式下只能渲染 allowlist 日期 tabs
4. 当前页面日期不在 allowlist 时会回退到默认允许日期

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

**Step 3: 最小实现**

实现：

1. 初始化先 resolve access
2. 根据 scope 选择 public 或 protected data source
3. history tabs 基于 allowed dates 渲染
4. 页面保留 pure/fusion hash 切换

**Step 4: 跑测试**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

### Task 4: 收敛公开数据暴露面

**Files:**
- Modify: `chanlun/report_generator.py`
- Modify: deploy/publish script if any
- Test: `tests/test_report_generator.py`

**Step 1: 写失败测试**

覆盖：

1. 未授权公开目录中不存在非 allowlist 日期 JSON。
2. 公开历史 manifest 不包含未授权日期。
3. 旧 `docs/data.json` 若保留，只能是 public 子集，不能再是完整历史。

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_report_generator -v
```

**Step 3: 实现**

要求：

1. GitHub Pages 发布目录仅包含 public artifacts。
2. protected artifacts 不进入 Pages 发布产物。

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
<backend test command>
```

### 10.2 手工访问验证

验证以下 URL：

1. 无 key：

```text
https://breakaway4here-arch.github.io/ChanlunStrategy/
```

预期：

1. 只能看到 `CHANLUN_PUBLIC_DATES` 中的日期。
2. 非 allowlist 日期不会出现在历史 tabs。

2. 带有效 key：

```text
https://breakaway4here-arch.github.io/ChanlunStrategy/?key=02951e20-6de2-418c-8bab-463647220883#fusion
```

预期：

1. 可看到完整日期列表。
2. 可切换到非 public 日期。

3. 带无效 key：

```text
https://breakaway4here-arch.github.io/ChanlunStrategy/?key=bad-key
```

预期：

1. 回退到 public scope。
2. 不暴露内部错误。

### 10.3 安全验证

必须人工验证：

1. 直接访问 GitHub Pages 下不存在：
   - `docs/data/{private-date}.json`
   - 含全部历史的 `docs/data.json`
2. 未授权调用后端 `/api/chanlun/report/{private-date}` 返回 `403`
3. 授权调用返回 `200`

### 10.4 回归验证

至少用：

```text
CHANLUN_PUBLIC_DATES = ["2026-05-26"]
CHANLUN_PUBLIC_DATES = ["2026-05-26", "2026-05-27"]
CHANLUN_PUBLIC_DATES = []
```

三组配置分别验证行为。

## 11. 风险与回滚

### 11.1 风险

1. 只改了前端，忘了收口公开 JSON，导致“看起来有权限，实际全都能直接下载”。
2. 后端接口有权限判断，但部署脚本仍把 protected JSON 发到 GitHub Pages。
3. 历史 tabs 改造后 public / full manifest 混用，日期切换错乱。

### 11.2 回滚

可分层回滚：

1. 后端 access resolve 保留，但全部回退到 public only。
2. 前端暂时禁用 key 解锁，保留 allowlist 日期公开模式。

但禁止回滚到“全量历史继续公开，只在前端做隐藏”。

## 12. 自 Review 清单

这份 spec 已自 review，确认如下：

1. 明确指出了 GitHub Pages 静态站不能做真鉴权的根因。
2. 明确要求受保护数据退出公共 `docs/data*.json` 暴露面。
3. 访问码只在后端保存，不进入前端。
4. public allowlist 和 full access 都有清晰的接口语义。
5. QA 包含了真正的安全验证，不只是 UI 验证。

Plan complete and saved to `docs/plans/2026-05-26-chanlun-access-control-backend-spec.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?
