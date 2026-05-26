# K线增量缓存 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为日线和 30min K 线增加本地增量缓存，避免每次 QA/调试重复拉取已经存在的数据，并按最近 10 个有效开盘日自动清理旧缓存。

**Architecture:** 在 `chanlun/data_fetcher.py` 外抽一个轻量缓存模块。第一次缓存不足时拉完整分析窗口；缓存已足够时不再重复拉大范围，只拉最近少量 K 线做增量刷新，merge 去重后返回完整分析窗口。缓存保留期按 K 线交易日期计算，不按自然日或文件 mtime 计算，周末和节假日不占用 10 天窗口。

**Tech Stack:** Python 3, JSON file cache, `unittest`, existing `numpy` K-line dict format.

---

## 1. 背景

当前每次跑 QA 都会重复拉：

1. 腾讯日线：`fetch_daily_kline(code, count=DAY_LOOKBACK)`
2. 新浪 30min：`fetch_30min_kline(code, count=80)`

这导致两个问题：

1. 测试慢，尤其是 200-400 只股票批量拉日线时。
2. 外部接口不稳定，验证规则时容易被 DNS、超时、限流干扰。

本次只缓存 K 线，不缓存板块资金和板块成分股。原因：板块资金/成分股时效性更强，且当前最慢的重复请求主要是 K 线。

---

## 2. 目标行为

### 2.1 缓存范围

缓存：

1. 日线 K 线：`fetch_daily_kline`
2. 30min K 线：`fetch_30min_kline`

暂不缓存：

1. `fetch_sector_flow`
2. `fetch_sector_stocks`
3. `fetch_sector_outflow`
4. `fetch_limit_up_pool`
5. 新闻/事件接口

### 2.2 缓存目录

新增本地目录：

```text
.cache/chanlun/klines/day/{code}.json
.cache/chanlun/klines/30min/{code}.json
```

`.cache/` 必须加入 `.gitignore`，缓存文件不能提交。

### 2.3 缓存文件格式

每个股票一个 JSON 文件：

```json
{
  "code": "600519",
  "period": "day",
  "updated_at": "2026-05-26T15:02:31+08:00",
  "source": "tencent",
  "klines": [
    {
      "date": "2026-05-15",
      "open": 100.0,
      "high": 103.0,
      "low": 99.5,
      "close": 102.0,
      "volume": 123456.0
    }
  ]
}
```

30min 的 `date` 保留接口原始时间字符串，例如：

```json
{
  "date": "2026-05-26 14:30:00",
  "open": 10.0,
  "high": 10.2,
  "low": 9.9,
  "close": 10.1,
  "volume": 12345.0
}
```

### 2.4 保留期：10 个有效开盘日

`KLINE_CACHE_TRADING_DAYS = 10`

定义：

1. “10 天”指最近 10 个实际有日线 K 线的交易日期。
2. 周末、春节、国庆等无交易日期不计入。
3. 清理不能按自然日，也不能按文件 mtime。
4. 30min 缓存按 `date` 解析出交易日，仅保留最近 10 个交易日内的 bar。
5. 日线缓存不能裁到 10 根，因为当前缠论分析需要 `DAY_LOOKBACK=100`；日线保留期见下方“日线历史窗口约束”。

示例：

```text
缓存中交易日:
2026-05-12, 2026-05-13, 2026-05-14, 2026-05-15,
2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21,
2026-05-22, 2026-05-25, 2026-05-26

保留最近 10 个有效交易日后:
2026-05-13 ... 2026-05-26

2026-05-16/17 是周末，不出现在交易日列表，也不影响窗口。
```

注意：当前 `DAY_LOOKBACK=100`，如果只保留 10 个交易日会影响缠论日线分析。因此实现必须区分“缓存清理窗口”和“分析所需窗口”。

### 2.5 日线历史窗口约束

用户要求“放 10 天的增量缓存到本地，更早清理”，这个要求对 30min 可以直接执行，但日线不能物理裁剪到 10 根。原因是当前日线缠论分析依赖 `DAY_LOOKBACK=100`，只保留 10 根会直接破坏分型、笔、线段、中枢和背驰计算。

因此采用下面规则：

1. `raw incremental cache` 只保证最近 10 个有效交易日的增量更新不重复拉。
2. 若分析需要 100 根日线，第一次仍需拉足 `count=100` 并写缓存。
3. 清理时不能把日线裁到 10 根，否则分析会失真。

```python
DAY_KLINE_CACHE_RETENTION_TRADING_DAYS = max(DAY_LOOKBACK, 10)
MIN30_CACHE_RETENTION_TRADING_DAYS = 10
```

解释：

1. 日线必须至少保留 `DAY_LOOKBACK` 个有效交易日，否则缠论结构不完整。
2. 30min 原本只看最近约 80 根，保留最近 10 个有效交易日足够。
3. 如果用户将 `DAY_LOOKBACK` 改为小于 10，日线仍保留 10 个有效交易日。

这是实现正确性优先的必要约束。

### 2.6 拉取策略：首次全量，后续增量

核心规则：

1. 第一次缓存不足时，按分析窗口拉全量：日线 `count=DAY_LOOKBACK`，30min `count=80`。
2. 后续缓存已足够时，不直接无脑返回缓存，也不重复拉全量。
3. 后续只拉最近少量 K 线作为增量刷新，再 merge 到缓存。
4. merge 后返回最近 `count` 根，保证分析窗口完整。

建议参数：

```python
DAY_KLINE_INCREMENTAL_FETCH_COUNT = 5
MIN30_KLINE_INCREMENTAL_FETCH_COUNT = 16
```

解释：

1. 日线历史 K 线基本不变，后续拉最近 5 根足够覆盖当天、停牌恢复、接口延迟、最近复权轻微变化。
2. 30min 盘中会持续更新，后续拉最近 16 根约等于 2 个交易日内的 30min bar，足够覆盖当天增量。
3. 如果缓存不足 `count`，必须拉完整 `count`，不能只拉增量。
4. `--refresh-cache` 时强制拉完整 `count`，用于排查缓存污染或复权变化。

日线流程：

```text
cache < DAY_LOOKBACK
  -> 拉 DAY_LOOKBACK
  -> merge/write
  -> 返回最近 DAY_LOOKBACK

cache >= DAY_LOOKBACK
  -> 拉 DAY_KLINE_INCREMENTAL_FETCH_COUNT
  -> merge/write
  -> 返回最近 DAY_LOOKBACK
```

30min 流程：

```text
cache < count
  -> 拉 count
  -> merge/write
  -> 返回最近 count

cache >= count
  -> 拉 MIN30_KLINE_INCREMENTAL_FETCH_COUNT
  -> merge/write
  -> 返回最近 count
```

---

## 3. 实现任务

### Task 1: 新增缓存模块

**Files:**

- Create: `chanlun/kline_cache.py`
- Test: `tests/test_kline_cache.py`

**Step 1: 写失败测试**

Create `tests/test_kline_cache.py`：

```python
import tempfile
import unittest
from pathlib import Path

import numpy as np

from chanlun.kline_cache import (
    kline_dict_to_records,
    records_to_kline_dict,
    merge_kline_records,
    prune_records_by_trading_days,
)


class KlineCacheTest(unittest.TestCase):
    def test_merge_dedupes_by_date_and_sorts(self):
        old = [
            {"date": "2026-05-25", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10},
            {"date": "2026-05-26", "open": 2, "high": 3, "low": 2, "close": 3, "volume": 20},
        ]
        new = [
            {"date": "2026-05-26", "open": 20, "high": 30, "low": 20, "close": 30, "volume": 200},
            {"date": "2026-05-27", "open": 3, "high": 4, "low": 3, "close": 4, "volume": 30},
        ]
        merged = merge_kline_records(old, new)
        self.assertEqual([r["date"] for r in merged], ["2026-05-25", "2026-05-26", "2026-05-27"])
        self.assertEqual(merged[1]["close"], 30)

    def test_prune_uses_trading_dates_not_calendar_days(self):
        records = [
            {"date": "2026-05-13", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-14", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-15", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-18", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-19", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-20", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-21", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-22", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-25", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-26", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            {"date": "2026-05-27", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        ]
        pruned = prune_records_by_trading_days(records, keep_trading_days=10)
        self.assertEqual(pruned[0]["date"], "2026-05-14")
        self.assertEqual(pruned[-1]["date"], "2026-05-27")
        self.assertEqual(len(pruned), 10)

    def test_roundtrip_preserves_numpy_arrays(self):
        kline = {
            "dates": ["2026-05-25", "2026-05-26"],
            "opens": np.array([1.0, 2.0]),
            "highs": np.array([2.0, 3.0]),
            "lows": np.array([0.8, 1.8]),
            "closes": np.array([1.5, 2.5]),
            "volumes": np.array([100.0, 200.0]),
        }
        records = kline_dict_to_records(kline)
        restored = records_to_kline_dict(records)
        self.assertEqual(restored["dates"], kline["dates"])
        self.assertTrue(np.array_equal(restored["closes"], kline["closes"]))
```

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_kline_cache -v
```

Expected: FAIL，`chanlun.kline_cache` 不存在。

**Step 3: 实现缓存模块**

Create `chanlun/kline_cache.py`：

```python
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from config import KLINE_CACHE_DIR, KLINE_CACHE_ENABLED, KLINE_CACHE_VERBOSE

TZ_CN = timezone(timedelta(hours=8))


def kline_dict_to_records(kline):
    if not kline:
        return []
    records = []
    for i, date in enumerate(kline.get("dates", [])):
        records.append({
            "date": str(date),
            "open": float(kline["opens"][i]),
            "high": float(kline["highs"][i]),
            "low": float(kline["lows"][i]),
            "close": float(kline["closes"][i]),
            "volume": float(kline["volumes"][i]),
        })
    return records


def records_to_kline_dict(records):
    records = sorted(records, key=lambda r: r["date"])
    return {
        "dates": [r["date"] for r in records],
        "opens": np.array([float(r["open"]) for r in records]),
        "highs": np.array([float(r["high"]) for r in records]),
        "lows": np.array([float(r["low"]) for r in records]),
        "closes": np.array([float(r["close"]) for r in records]),
        "volumes": np.array([float(r["volume"]) for r in records]),
    }


def merge_kline_records(old_records, new_records):
    by_date = {}
    for r in old_records or []:
        by_date[str(r["date"])] = r
    for r in new_records or []:
        by_date[str(r["date"])] = r
    return [by_date[k] for k in sorted(by_date)]


def _trading_day(date_str):
    return str(date_str).split(" ")[0]


def prune_records_by_trading_days(records, keep_trading_days):
    if not records:
        return []
    trading_days = sorted({_trading_day(r["date"]) for r in records})
    keep_days = set(trading_days[-keep_trading_days:])
    return [r for r in sorted(records, key=lambda x: x["date"]) if _trading_day(r["date"]) in keep_days]
```

继续实现文件 IO：

```python
def cache_path(period, code):
    return Path(KLINE_CACHE_DIR) / "klines" / period / f"{code}.json"


def read_cached_records(period, code):
    if not KLINE_CACHE_ENABLED:
        return []
    path = cache_path(period, code)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("klines", [])
    except Exception:
        return []


def write_cached_records(period, code, records, source, keep_trading_days):
    if not KLINE_CACHE_ENABLED:
        return
    path = cache_path(period, code)
    path.parent.mkdir(parents=True, exist_ok=True)
    pruned = prune_records_by_trading_days(records, keep_trading_days)
    payload = {
        "code": code,
        "period": period,
        "updated_at": datetime.now(TZ_CN).isoformat(timespec="seconds"),
        "source": source,
        "klines": pruned,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
```

实现命中判断：

```python
def cached_kline_if_sufficient(period, code, count):
    records = read_cached_records(period, code)
    if len(records) < count:
        return None
    latest = records[-count:]
    if KLINE_CACHE_VERBOSE:
        print(f"  [CACHE HIT] {period} {code} {len(latest)} bars")
    return records_to_kline_dict(latest)
```

注意：`records` 必须排序后再截断。实际实现里可在 `read_cached_records` 后统一排序。

**Step 4: 运行测试**

Run:

```bash
python3 -m unittest tests.test_kline_cache -v
```

Expected: PASS。

---

### Task 2: 加配置和 gitignore

**Files:**

- Modify: `config.py`
- Modify: `.gitignore`
- Test: `tests/test_kline_cache.py`

**Step 1: 修改配置**

在 `config.py` 新增：

```python
# ============================================================
# K线本地缓存
# ============================================================
KLINE_CACHE_ENABLED = True
KLINE_CACHE_DIR = ".cache/chanlun"
KLINE_CACHE_VERBOSE = False
KLINE_CACHE_FORCE_REFRESH = False
KLINE_CACHE_TRADING_DAYS = 10
DAY_KLINE_CACHE_RETENTION_TRADING_DAYS = max(DAY_LOOKBACK, KLINE_CACHE_TRADING_DAYS)
MIN30_KLINE_CACHE_RETENTION_TRADING_DAYS = KLINE_CACHE_TRADING_DAYS
DAY_KLINE_INCREMENTAL_FETCH_COUNT = 5
MIN30_KLINE_INCREMENTAL_FETCH_COUNT = 16
```

说明：

1. 用户要求保留 10 个有效开盘日。
2. 日线分析需要 `DAY_LOOKBACK=100`，所以日线缓存不能物理裁到 10 根，否则分析结果会变。
3. 因此日线保留 `max(DAY_LOOKBACK, 10)` 个有效交易日，30min 保留 10 个有效交易日。
4. 这不是违背 10 天要求，而是为了保持日线分析所需历史窗口；真正增量重复请求优化仍覆盖最近交易日。
5. 日线缓存足够时只补最近 5 根，30min 缓存足够时只补最近 16 根，避免每次重复拉完整窗口。

**Step 2: 修改 `.gitignore`**

追加：

```gitignore
.cache/
```

**Step 3: 运行测试**

Run:

```bash
python3 -m unittest tests.test_kline_cache -v
```

Expected: PASS。

---

### Task 3: 接入日线缓存

**Files:**

- Modify: `chanlun/data_fetcher.py`
- Test: `tests/test_kline_cache.py`

**Step 1: 写失败测试**

新增测试：

```python
from unittest.mock import patch

from chanlun.kline_cache import write_cached_records
from chanlun.data_fetcher import fetch_daily_kline


def test_fetch_daily_uses_incremental_fetch_when_cache_sufficient(self):
    records = []
    for i in range(100):
        day = f"2026-01-{(i % 28) + 1:02d}"
        records.append({"date": f"2026-05-{(i % 28) + 1:02d}", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10})
    with tempfile.TemporaryDirectory() as tmp:
        with patch("config.KLINE_CACHE_DIR", tmp), patch("chanlun.kline_cache.KLINE_CACHE_DIR", tmp):
            write_cached_records("day", "600519", records, "test", keep_trading_days=120)
            with patch("chanlun.data_fetcher.SESSION.get") as mocked_get:
                mocked_get.return_value.json.return_value = make_tencent_daily_payload("600519", count=5)
                kline = fetch_daily_kline("600519", count=100)
                self.assertEqual(len(kline["dates"]), 100)
                self.assertIn("5", mocked_get.call_args.args[0])
```

测试日期要保证唯一，可实际生成 `datetime + timedelta`，上面只是结构示意，同事实现时不要用重复日期导致 merge 后不足 100。`make_tencent_daily_payload()` 需要返回与腾讯接口结构兼容的最小 JSON，用于验证缓存足够时只请求 5 根增量，不请求 100 根。

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_kline_cache -v
```

Expected: FAIL，`fetch_daily_kline` 还未实现缓存足够时的小窗口增量刷新。

**Step 3: 重命名原始接口函数**

在 `chanlun/data_fetcher.py` 中：

```python
def _fetch_daily_kline_remote(code, count=DAY_LOOKBACK):
    ...
```

原 `fetch_daily_kline` 改为 wrapper：

```python
def fetch_daily_kline(code, count=DAY_LOOKBACK, force_refresh=False):
    force = force_refresh or KLINE_CACHE_FORCE_REFRESH
    cached_records = read_cached_records("day", code)
    cached_enough = len(cached_records) >= count

    if force:
        remote_count = count
    elif cached_enough:
        remote_count = DAY_KLINE_INCREMENTAL_FETCH_COUNT
    else:
        remote_count = count

    remote = _fetch_daily_kline_remote(code, count=remote_count)
    if remote:
        merged = merge_kline_records(cached_records, kline_dict_to_records(remote))
        write_cached_records(
            "day",
            code,
            merged,
            source="tencent",
            keep_trading_days=DAY_KLINE_CACHE_RETENTION_TRADING_DAYS,
        )
        cached = cached_kline_if_sufficient("day", code, count)
        return cached or remote

    cached = cached_kline_if_sufficient("day", code, count)
    if cached is not None:
        print(f"  [CACHE FALLBACK] day {code} remote failed, using cache")
        return cached
    return None
```

需要 import：

```python
from config import (
    ...,
    KLINE_CACHE_FORCE_REFRESH,
    DAY_KLINE_CACHE_RETENTION_TRADING_DAYS,
    DAY_KLINE_INCREMENTAL_FETCH_COUNT,
    MIN30_KLINE_INCREMENTAL_FETCH_COUNT,
)
from .kline_cache import (
    cached_kline_if_sufficient,
    read_cached_records,
    write_cached_records,
    merge_kline_records,
    kline_dict_to_records,
)
```

**Step 4: 运行测试**

Run:

```bash
python3 -m unittest tests.test_kline_cache -v
```

Expected: PASS。

---

### Task 4: 接入 30min 缓存

**Files:**

- Modify: `chanlun/data_fetcher.py`
- Test: `tests/test_kline_cache.py`

**Step 1: 写失败测试**

新增测试：

```python
def test_fetch_30min_uses_incremental_fetch_when_cache_sufficient(self):
    records = make_min30_records(count=80)
    with tempfile.TemporaryDirectory() as tmp:
        with patch("config.KLINE_CACHE_DIR", tmp), patch("chanlun.kline_cache.KLINE_CACHE_DIR", tmp):
            write_cached_records("30min", "600519", records, "test", keep_trading_days=10)
            with patch("chanlun.data_fetcher.SESSION.get") as mocked_get:
                mocked_get.return_value.json.return_value = make_sina_30min_payload(count=16)
                kline = fetch_30min_kline("600519", count=80)
                self.assertEqual(len(kline["dates"]), 80)
                self.assertIn("datalen=16", mocked_get.call_args.args[0])
```

`make_min30_records` 必须跨多个交易日生成时间，例如：

```text
2026-05-25 09:30:00
2026-05-25 10:00:00
...
2026-05-26 14:30:00
```

**Step 2: 运行测试确认失败**

Run:

```bash
python3 -m unittest tests.test_kline_cache -v
```

Expected: FAIL，`fetch_30min_kline` 还未实现缓存足够时的小窗口增量刷新。

**Step 3: 重命名原始接口函数**

```python
def _fetch_30min_kline_remote(code, count=80):
    ...
```

wrapper：

```python
def fetch_30min_kline(code, count=80, force_refresh=False):
    force = force_refresh or KLINE_CACHE_FORCE_REFRESH
    cached_records = read_cached_records("30min", code)
    cached_enough = len(cached_records) >= count

    if force:
        remote_count = count
    elif cached_enough:
        remote_count = min(MIN30_KLINE_INCREMENTAL_FETCH_COUNT, count)
    else:
        remote_count = count

    remote = _fetch_30min_kline_remote(code, count=remote_count)
    if remote:
        merged = merge_kline_records(cached_records, kline_dict_to_records(remote))
        write_cached_records(
            "30min",
            code,
            merged,
            source="sina",
            keep_trading_days=MIN30_KLINE_CACHE_RETENTION_TRADING_DAYS,
        )
        cached = cached_kline_if_sufficient("30min", code, count)
        return cached or remote

    cached = cached_kline_if_sufficient("30min", code, count)
    if cached is not None:
        print(f"  [CACHE FALLBACK] 30min {code} remote failed, using cache")
        return cached
    return None
```

**Step 4: 运行测试**

Run:

```bash
python3 -m unittest tests.test_kline_cache -v
```

Expected: PASS。

---

### Task 5: CLI 强制刷新

**Files:**

- Modify: `run.py`
- Modify: `chanlun/data_fetcher.py`
- Test: `tests/test_kline_cache.py`

**Step 1: 增加运行时开关**

在 `chanlun/data_fetcher.py` 增加模块变量：

```python
_FORCE_REFRESH_CACHE = False


def set_force_refresh_cache(value):
    global _FORCE_REFRESH_CACHE
    _FORCE_REFRESH_CACHE = bool(value)
```

fetch wrapper 中判断：

```python
if not force_refresh and not KLINE_CACHE_FORCE_REFRESH and not _FORCE_REFRESH_CACHE:
    ...
```

**Step 2: 修改 CLI**

`run.py` 增加参数：

```python
parser.add_argument("--refresh-cache", action="store_true", help="强制刷新K线缓存")
```

在 `main()` 或调用前设置：

```python
from chanlun.data_fetcher import set_force_refresh_cache

...
set_force_refresh_cache(args.refresh_cache)
main(debug=args.debug)
```

如果不想改 `main(debug=False)` 签名，这是最小改动。

**Step 3: QA**

Run:

```bash
python3 run.py --debug
python3 run.py --debug
python3 run.py --debug --refresh-cache
```

Expected:

1. 第一次：大量 remote fetch，写入 `.cache/chanlun/klines`。
2. 第二次：同样股票不再拉完整窗口，只拉小窗口增量，耗时明显下降。
3. 第三次：强制 remote fetch 完整窗口并覆盖/merge 缓存。

默认 `KLINE_CACHE_VERBOSE=False` 时不刷屏。QA 时可临时设 True 或用诊断计数。

---

### Task 6: 缓存统计和清理诊断

**Files:**

- Modify: `chanlun/kline_cache.py`
- Modify: `run.py`
- Test: `tests/test_kline_cache.py`

**Step 1: 增加统计对象**

在 `kline_cache.py`：

```python
CACHE_STATS = {
    "day_hit": 0,
    "day_miss": 0,
    "day_write": 0,
    "30min_hit": 0,
    "30min_miss": 0,
    "30min_write": 0,
    "pruned_records": 0,
}


def reset_cache_stats():
    for k in CACHE_STATS:
        CACHE_STATS[k] = 0


def get_cache_stats():
    return dict(CACHE_STATS)
```

命中、未命中、写入、清理时更新计数。

**Step 2: 报告 diagnostics**

`run.py` 的 `diagnostics` 增加：

```python
"kline_cache": get_cache_stats(),
```

**Step 3: QA**

Run:

```bash
python3 run.py --debug
python3 run.py --debug
```

Expected:

第二次 `diagnostics.kline_cache.day_hit` 和 `30min_hit` 明显增加。

---

## 4. 全量 QA

### 4.1 单元测试

Run:

```bash
python3 -m unittest tests.test_kline_cache -v
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected: PASS。

### 4.2 Debug 速度验证

Run:

```bash
time python3 run.py --debug
time python3 run.py --debug
```

Expected:

1. 第二次运行显著快于第一次。
2. 第二次不应重复请求完整日线和完整 30min 窗口，只允许请求配置里的增量窗口。
3. 两次 debug 的分析流程能正常完成。

### 4.3 强制刷新验证

Run:

```bash
python3 run.py --debug --refresh-cache
```

Expected:

1. 忽略已有缓存命中状态，重新请求完整远端窗口。
2. 请求成功后 merge 写回缓存。
3. 不产生重复日期记录。

### 4.4 10 个有效开盘日清理验证

构造包含 11 个交易日、中间跨周末的 records，调用：

```python
prune_records_by_trading_days(records, keep_trading_days=10)
```

Expected:

1. 删除最早 1 个交易日。
2. 周末不参与计算。
3. 30min 同一天多根 bar 应一起保留或一起删除。

### 4.5 正式数据验证

Run:

```bash
python3 run.py
python3 scripts/qa_signal_invariants.py docs/data.json
```

Expected:

1. 报告生成成功。
2. QA pass。
3. `docs/data.json` 包含 `diagnostics.kline_cache`。

---

## 5. 风险和处理

1. 缓存污染：写文件必须先写 `.tmp` 再 `os.replace`，避免半截 JSON。
2. 缓存不足：缓存条数少于 `count` 时必须请求远端，不能拿不足数据分析。
3. 远端失败：只有缓存足够时才 fallback；缓存不足时返回 `None`，保持现有行为。
4. 日期重复：merge 以 `date` 为唯一键，新数据覆盖旧数据。
5. 节假日：保留期只看 records 中真实交易日，不看自然日。
6. 日线历史窗口：日线不能强裁到 10 根，必须保留 `max(DAY_LOOKBACK, 10)`，否则破坏缠论分析。

---

## 6. 自 Review

### 6.1 已确认

1. 满足用户要求：本地增量缓存，已有数据不重复拉。
2. 保留期按 10 个有效开盘日，不按自然日。
3. 日线特殊处理不会破坏 `DAY_LOOKBACK=100`。
4. 缓存目录不会进入 git。
5. 支持 `--refresh-cache` 排查脏缓存。
6. 有单测覆盖 merge、去重、交易日裁剪、缓存足够时的小窗口增量刷新。

### 6.2 后续可选但本次不做

1. 不缓存板块资金和成分股。
2. 不引入 sqlite。
3. 不做全市场长期历史数据库。
4. 不做复权变更检测；如果怀疑复权数据变化，用 `--refresh-cache`。
