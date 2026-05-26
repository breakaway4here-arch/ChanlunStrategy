"""
数据采集模块
- 板块资金流向: 东方财富 push2.eastmoney.com
- 板块成分股:   东方财富 push2.eastmoney.com
- 日线K线:      腾讯 web.ifzq.gtimg.cn
- 30分钟K线:    新浪 money.finance.sina.com.cn

数据流: 板块资金TOP20 → 成分股列表 → 日线K线 → 30分钟K线
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import requests

from config import (
    DAY_LOOKBACK, MIN30_LOOKBACK_DAYS, TOP_SECTOR_COUNT,
    KLINE_CACHE_FORCE_REFRESH,
    DAY_KLINE_CACHE_RETENTION_TRADING_DAYS,
    MIN30_KLINE_CACHE_RETENTION_TRADING_DAYS,
    DAY_KLINE_INCREMENTAL_FETCH_COUNT,
    MIN30_KLINE_INCREMENTAL_FETCH_COUNT,
)
from .kline_cache import (
    cached_kline_if_sufficient,
    read_cached_records,
    write_cached_records,
    merge_kline_records,
    kline_dict_to_records,
    CACHE_STATS,
)

# ------------------------------------------------------------
# 路径
# ------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK_CACHE_PATH = os.path.join(os.path.dirname(BASE_DIR), "stock_names_cache.json")
STOCK_CACHE_PATH_FALLBACK = os.path.join(BASE_DIR, "..", "stock_names_cache.json")

# ------------------------------------------------------------
# HTTP Session
# ------------------------------------------------------------
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
})


# ============================================================
# 代码格式转换
# ============================================================
# 沪市指数代码（000xxx 区间中属于上证系列的部分）
_SH_INDEX_CODES = {
    "000001", "000002", "000003", "000004", "000005", "000006", "000007",
    "000008", "000009", "000010", "000011", "000012", "000013", "000015",
    "000016", "000017", "000018", "000019", "000020", "000021", "000022",
    "000025", "000026", "000027", "000028", "000029", "000030", "000031",
    "000032", "000033", "000034", "000035", "000036", "000037", "000038",
    "000039", "000040", "000041", "000042", "000043", "000044", "000045",
    "000046", "000047", "000048", "000049", "000050",
    "000051", "000052", "000053", "000054", "000055", "000056", "000057",
    "000058", "000059", "000060", "000061", "000062", "000063", "000064",
    "000300",  # 沪深300
    "000688",  # 科创50
    "000905",  # 中证500
}


def _is_sh(code):
    """判断是否沪市代码"""
    if code.startswith(("60", "68", "900")):
        return True
    if code in _SH_INDEX_CODES:
        return True
    return False


def _tencent_code(code):
    """纯数字代码 → 腾讯格式: sh600519 / sz000858"""
    return f"sh{code}" if _is_sh(code) else f"sz{code}"


def _em_secid(code):
    """纯数字代码 → 东方财富格式: 1.600519 / 0.000858"""
    return f"1.{code}" if _is_sh(code) else f"0.{code}"


def _sina_code(code):
    """纯数字代码 → 新浪格式: sh600519 / sz000858"""
    return _tencent_code(code)


# ============================================================
# 股票名称缓存
# ============================================================
def _load_stock_name_cache():
    for p in (STOCK_CACHE_PATH, STOCK_CACHE_PATH_FALLBACK):
        rp = os.path.normpath(p)
        if os.path.exists(rp):
            with open(rp, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(f"未找到 stock_names_cache.json")


def _build_code_to_name():
    cache = _load_stock_name_cache()
    return {v: k for k, v in cache.items()}


_CODE_TO_NAME = None


def get_code_to_name():
    global _CODE_TO_NAME
    if _CODE_TO_NAME is None:
        _CODE_TO_NAME = _build_code_to_name()
    return _CODE_TO_NAME


# ============================================================
# 板块资金流向 — 东方财富
# ============================================================
def fetch_sector_flow(top_n=TOP_SECTOR_COUNT):
    """
    获取行业板块资金流向 TOP N。
    返回: [{"code": "BKxxxx", "name": "板块名", "change_pct": 1.5, "flow": 123456789, "flow_str": "1.23亿"}, ...]
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": str(top_n), "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fid": "f62",
        "fs": "m:90+t:2",
        "fields": "f12,f14,f3,f62,f184,f66",
    }
    try:
        resp = SESSION.get(url, params=params, timeout=15)
        data = resp.json()
        items = data.get("data", {}).get("diff", [])
        result = []
        for it in items:
            result.append({
                "code": it.get("f12", ""),
                "name": it.get("f14", ""),
                "change_pct": it.get("f3", 0),
                "flow": it.get("f62", 0),
                "flow_str": _format_amount(it.get("f62", 0)),
            })
        return result
    except Exception as e:
        print(f"[ERROR] 获取板块资金流向失败: {e}")
        return []


# ============================================================
# 板块成分股 — 东方财富
# ============================================================
def fetch_sector_stocks(sector_code):
    """
    获取板块内成分股列表。
    返回: [{"code": "600519", "name": "贵州茅台", "change_pct": 1.5}, ...]
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    all_stocks = []
    page = 1
    while True:
        params = {
            "pn": str(page), "pz": "200", "po": "0", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": f"b:{sector_code}",
            "fields": "f12,f14,f3,f2",
        }
        try:
            resp = SESSION.get(url, params=params, timeout=15)
            data = resp.json()
            stock_data = data.get("data")
            if not stock_data:
                break
            items = stock_data.get("diff", [])
            if not items:
                break
            for it in items:
                all_stocks.append({
                    "code": it.get("f12", ""),
                    "name": it.get("f14", "-"),
                    "change_pct": it.get("f3", 0),
                    "close": it.get("f2", 0),
                })
            if len(items) < 200:
                break
            page += 1
        except Exception as e:
            print(f"[ERROR] 获取板块 {sector_code} 成分股失败: {e}")
            break
    return all_stocks


# ============================================================
# K线缓存强制刷新开关
# ============================================================
_FORCE_REFRESH_CACHE = False


def set_force_refresh_cache(value):
    global _FORCE_REFRESH_CACHE
    _FORCE_REFRESH_CACHE = bool(value)


# ============================================================
# 日线 K 线 — 腾讯
# ============================================================
def _parse_tencent_kline(raw_lines):
    """
    解析腾讯K线数据。
    格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
    """
    dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for line in raw_lines:
        if len(line) < 6:
            continue
        dates.append(line[0])
        opens.append(float(line[1]))
        closes.append(float(line[2]))
        highs.append(float(line[3]))
        lows.append(float(line[4]))
        volumes.append(float(line[5]))
    return {
        "dates": dates,
        "opens": np.array(opens),
        "highs": np.array(highs),
        "lows": np.array(lows),
        "closes": np.array(closes),
        "volumes": np.array(volumes),
    }


def _fetch_daily_kline_remote(code, count=DAY_LOOKBACK):
    """
    获取日线K线（前复权）。腾讯 API。
    返回: {"dates": [...], "opens": [...], "highs": [...], "lows": [...], "closes": [...], "volumes": [...]}
    """
    tc = _tencent_code(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc},day,,,{count},qfq"
    try:
        resp = SESSION.get(url, timeout=15)
        data = resp.json()
        stock_data = data.get("data", {}).get(tc, {})
        # qfqday: 前复权日线
        klines = stock_data.get("qfqday", stock_data.get("day", []))
        if not klines:
            return None
        return _parse_tencent_kline(klines)
    except Exception as e:
        print(f"[ERROR] 获取日线失败 {code}: {e}")
        return None


def fetch_daily_kline(code, count=DAY_LOOKBACK, force_refresh=False):
    """Fetch daily kline with incremental cache support."""
    force = force_refresh or KLINE_CACHE_FORCE_REFRESH or _FORCE_REFRESH_CACHE
    cached_records = read_cached_records("day", code)
    cached_enough = len(cached_records) >= count

    if force:
        remote_count = count
    elif cached_enough:
        remote_count = DAY_KLINE_INCREMENTAL_FETCH_COUNT
    else:
        remote_count = count

    remote = _fetch_daily_kline_remote(code, count=remote_count)
    CACHE_STATS["day_miss" if remote is None else "day_hit"] += 0  # placeholder

    if remote:
        merged = merge_kline_records(cached_records, kline_dict_to_records(remote))
        write_cached_records(
            "day", code, merged,
            source="tencent",
            keep_trading_days=DAY_KLINE_CACHE_RETENTION_TRADING_DAYS,
        )
        CACHE_STATS["day_write"] += 1
        cached = cached_kline_if_sufficient("day", code, count)
        if cached is not None:
            CACHE_STATS["day_hit"] += 1
            return cached
        CACHE_STATS["day_miss"] += 1
        return remote

    cached = cached_kline_if_sufficient("day", code, count)
    if cached is not None:
        CACHE_STATS["day_hit"] += 1
        print(f"  [CACHE FALLBACK] day {code} remote failed, using cache")
        return cached
    CACHE_STATS["day_miss"] += 1
    return None


def fetch_shanghai_index():
    """获取上证指数日线"""
    return fetch_daily_kline("000001", count=DAY_LOOKBACK)


# ============================================================
# 30分钟 K 线 — 新浪
# ============================================================
def _fetch_30min_kline_remote(code, count=80):
    """
    获取30分钟K线。新浪 API（最大约100根）。
    返回: {"dates": [...], "opens": [...], "highs": [...], "lows": [...], "closes": [...], "volumes": [...]}
    """
    sc = _sina_code(code)
    # 新浪API datalen上限约100，取min(count, 100)
    datalen = min(count, 100)
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sc}&scale=30&datalen={datalen}"
    try:
        resp = SESSION.get(url, timeout=15)
        klines = resp.json()
        if not klines:
            return None

        dates, opens, highs, lows, closes, volumes = [], [], [], [], [], []
        for k in klines:
            dates.append(k["day"])
            opens.append(float(k["open"]))
            highs.append(float(k["high"]))
            lows.append(float(k["low"]))
            closes.append(float(k["close"]))
            volumes.append(float(k["volume"]))

        return {
            "dates": dates,
            "opens": np.array(opens),
            "highs": np.array(highs),
            "lows": np.array(lows),
            "closes": np.array(closes),
            "volumes": np.array(volumes),
        }
    except Exception as e:
        print(f"[ERROR] 获取30分钟K线失败 {code}: {e}")
        return None


def fetch_30min_kline(code, count=80, force_refresh=False):
    """Fetch 30min kline with incremental cache support."""
    force = force_refresh or KLINE_CACHE_FORCE_REFRESH or _FORCE_REFRESH_CACHE
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
            "30min", code, merged,
            source="sina",
            keep_trading_days=MIN30_KLINE_CACHE_RETENTION_TRADING_DAYS,
        )
        CACHE_STATS["30min_write"] += 1
        cached = cached_kline_if_sufficient("30min", code, count)
        if cached is not None:
            CACHE_STATS["30min_hit"] += 1
            return cached
        CACHE_STATS["30min_miss"] += 1
        return remote

    cached = cached_kline_if_sufficient("30min", code, count)
    if cached is not None:
        CACHE_STATS["30min_hit"] += 1
        print(f"  [CACHE FALLBACK] 30min {code} remote failed, using cache")
        return cached
    CACHE_STATS["30min_miss"] += 1
    return None


# ============================================================
# K 线通用入口（用于 market indices 等场景）
# ============================================================
def fetch_kline(code, klt="101", count=DAY_LOOKBACK, fqt="1"):
    """
    通用K线获取入口。
    klt: 101=日线, 30=30分钟 (兼容旧接口)
    """
    if klt in ("101", "day", "1d"):
        return fetch_daily_kline(code, count=count)
    elif klt in ("30", "min30", "30min"):
        return fetch_30min_kline(code, count=count)
    else:
        return fetch_daily_kline(code, count=count)


# ============================================================
# 批量获取
# ============================================================
def batch_fetch_daily_klines(stocks, max_workers=10):
    """
    并发批量获取日线。
    stocks: [{"code": "600519", "name": "茅台", "sector": "...", ...}, ...]
    返回: [{"code": ..., "name": ..., "sector": ..., "klines": {...}}, ...]
    """
    results = []

    def _fetch_one(stock):
        code = stock["code"]
        klines = fetch_daily_kline(code)
        if not klines:
            print(f"  [DEBUG] {code} {stock.get('name','')} 拉取失败")
            return None
        if len(klines.get("closes", [])) < 60:
            print(f"  [DEBUG] {code} {stock.get('name','')} K线不足60根(实际{len(klines.get('closes',[]))})，可能新股/停牌")
            return None
        return {
            "code": code,
            "name": stock.get("name", ""),
            "sector": stock.get("sector", ""),
            "change_pct": stock.get("change_pct", 0),
            "klines": klines,
        }

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in stocks}
        for future in as_completed(futures):
            res = future.result()
            if res:
                results.append(res)
    return results


def batch_fetch_30min_klines(stocks, max_workers=8):
    """
    并发批量获取30分钟K线。
    """
    results = []

    def _fetch_one(stock):
        code = stock["code"]
        klines = fetch_30min_kline(code)
        if klines and len(klines.get("closes", [])) >= 40:
            return {"code": code, "name": stock.get("name", ""), "klines": klines}
        return None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in stocks}
        for future in as_completed(futures):
            res = future.result()
            if res:
                results.append(res)
    return results


# ============================================================
# Phase 1 主流程
# ============================================================
def collect_daily_data():
    """
    完整数据采集流程:
    1. 获取 TOP20 资金流入板块
    2. 获取板块成分股（去重）
    3. 批量获取成分股日线
    4. 获取上证指数日线
    """
    print("=" * 60)
    print("Phase 1: 数据采集")
    print("=" * 60)

    print("[1/4] 获取板块资金流向 TOP20 ...")
    sectors = fetch_sector_flow(TOP_SECTOR_COUNT)
    if not sectors:
        # API 不可用时（如周末），使用热门板块兜底
        FALLBACK_SECTORS = [
            ("BK0480", "人工智能"), ("BK0477", "汽车零部件"), ("BK0473", "新能源车"),
            ("BK0476", "半导体"), ("BK0479", "机器人概念"), ("BK0481", "算力概念"),
            ("BK0416", "电子"), ("BK0470", "专用设备"), ("BK0483", "通信设备"),
            ("BK0445", "计算机应用"), ("BK0422", "通用设备"), ("BK0429", "化工合成材料"),
            ("BK0451", "家用轻工"), ("BK0465", "自动化设备"), ("BK0409", "电力"),
            ("BK0472", "光学光电子"), ("BK0459", "国防军工"), ("BK0485", "化学制药"),
            ("BK0474", "光伏概念"), ("BK0447", "建筑装饰"),
        ]
        sectors = [{"code": c, "name": n, "change_pct": 0, "flow": 0, "flow_str": "0"}
                   for c, n in FALLBACK_SECTORS]
        print(f"  板块API超时，使用兜底 {len(sectors)} 个板块")
    else:
        print(f"  获取到 {len(sectors)} 个板块")
    for s in sectors[:5]:
        print(f"    {s['name']}: 净流入 {s['flow_str']}")

    print("[2/4] 获取板块成分股 ...")
    seen_codes = set()
    all_stocks = []
    for sector in sectors:
        stocks = fetch_sector_stocks(sector["code"])
        for st in stocks:
            if st["code"] not in seen_codes:
                seen_codes.add(st["code"])
                st["sector"] = sector["name"]
                all_stocks.append(st)
    print(f"  共 {len(all_stocks)} 只成分股（去重后）")

    print(f"[3/4] 批量获取日线（{len(all_stocks)} 只）...")
    t0 = time.time()
    stocks_with_kline = batch_fetch_daily_klines(all_stocks)
    elapsed = time.time() - t0
    print(f"  获取到 {len(stocks_with_kline)} 只有效日线数据，耗时 {elapsed:.1f}s")

    print("[4/4] 获取上证指数日线 ...")
    sh_kline = fetch_shanghai_index()
    print(f"  上证数据: {len(sh_kline['closes']) if sh_kline else 0} 根K线")

    print("Phase 1 完成\n")
    return {
        "sectors": sectors,
        "sh_index": sh_kline,
        "stocks": stocks_with_kline,
    }


def collect_30min_data(target_stocks):
    """
    为目标池股票拉取30分钟K线。
    """
    if not target_stocks:
        return []
    print(f"  批量获取30分钟K线（{len(target_stocks)} 只）...")
    t0 = time.time()
    results = batch_fetch_30min_klines(target_stocks)
    print(f"  获取到 {len(results)} 只，耗时 {time.time() - t0:.1f}s")
    return results


# ============================================================
# 资金流出 — 东方财富
# ============================================================
def fetch_sector_outflow(top_n=5):
    """
    获取行业板块资金流出 TOP N（净流出最大）。
    复用 fetch_sector_flow 相同 API，改为升序排列取负值最大。
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": str(top_n * 3), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fid": "f62",
        "fs": "m:90+t:2",
        "fields": "f12,f14,f3,f62,f184,f66",
    }
    try:
        resp = SESSION.get(url, params=params, timeout=15)
        data = resp.json()
        items = data.get("data", {}).get("diff", [])
        result = []
        for it in items:
            flow = it.get("f62", 0)
            if flow is not None and flow < 0:
                result.append({
                    "code": it.get("f12", ""),
                    "name": it.get("f14", ""),
                    "change_pct": it.get("f3", 0),
                    "flow": flow,
                    "flow_str": _format_amount(flow),
                })
                if len(result) >= top_n:
                    break
        return result
    except Exception as e:
        print(f"[ERROR] 获取板块资金流出失败: {e}")
        return []


# ============================================================
# 涨停板池 — 东方财富
# ============================================================
def fetch_limit_up_pool(date_str=None):
    """
    获取当日涨停板池。东方财富 getTopicZTPool 接口。
    返回: [{"code": ..., "name": ..., "price": ..., "change_pct": ...,
             "sector": ..., "lianban": ..., "first_time": ..., "fund": ..., "zhaban": ...}, ...]
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    url = "https://push2ex.eastmoney.com/getTopicZTPool"
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": "0",
        "pagesize": "200",
        "sort": "fbt:asc",
        "date": date_str,
    }
    try:
        resp = SESSION.get(url, params=params, timeout=15)
        data = resp.json()
        pool = data.get("data", {}).get("pool", [])
        if not pool:
            return []
        result = []
        for it in pool:
            try:
                result.append({
                    "code": it.get("c", ""),
                    "name": it.get("n", ""),
                    "price": it.get("p", 0) / 1000.0 if it.get("p") else 0,
                    "change_pct": it.get("zdp", 0),
                    "sector": it.get("hybk", ""),
                    "lianban": it.get("lbc", 0),
                    "first_time": _fmt_btime(it.get("fbt", "")),
                    "fund": it.get("fund", 0),
                    "zhaban": it.get("zbc", 0),
                })
            except Exception:
                continue
        return result
    except Exception as e:
        print(f"[ERROR] 获取涨停板池失败: {e}")
        return []


def _fmt_btime(raw):
    """格式化首次封板时间 HHmmss → HH:mm"""
    if not raw or len(raw) < 4:
        return raw
    return f"{raw[:2]}:{raw[2:4]}"


# ============================================================
# 工具函数
# ============================================================
def _format_amount(amount):
    if amount is None:
        return "0"
    amount = float(amount)
    if abs(amount) >= 1e8:
        return f"{amount / 1e8:.2f}亿"
    if abs(amount) >= 1e4:
        return f"{amount / 1e4:.0f}万"
    return str(int(amount))


def is_st_stock(name):
    """Check if stock name indicates ST or delisting risk."""
    if not name:
        return False
    upper = name.upper()
    if "ST" in upper:
        return True
    if "退市" in name or "退" in name:
        return True
    return False
