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
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

from config import (
    DAY_LOOKBACK, MIN30_LOOKBACK_DAYS, TOP_SECTOR_COUNT,
    KLINE_CACHE_FORCE_REFRESH,
    DAY_KLINE_CACHE_RETENTION_TRADING_DAYS,
    MIN30_KLINE_CACHE_RETENTION_TRADING_DAYS,
    MIN15_KLINE_CACHE_RETENTION_TRADING_DAYS,
    DAY_KLINE_INCREMENTAL_FETCH_COUNT,
    MIN30_KLINE_INCREMENTAL_FETCH_COUNT,
    MIN15_KLINE_INCREMENTAL_FETCH_COUNT,
    MIN15_LOOKBACK_BARS,
)
from .kline_cache import (
    cached_kline_if_sufficient,
    read_cached_records,
    write_cached_records,
    merge_kline_records,
    kline_dict_to_records,
    records_to_kline_dict,
    CACHE_STATS,
)

# ------------------------------------------------------------
# 路径
# ------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STOCK_CACHE_PATH = os.environ.get(
    "STOCK_NAMES_CACHE_FILE",
    os.path.join(BASE_DIR, "stock_names_cache.json"),
)
STOCK_CACHE_PATH_FALLBACK = "/Users/yangfan/yf_source/stock-shared-data/stock_names_cache.json"
STOCK_CACHE_PATH_LEGACY_FALLBACK = os.path.join(os.path.dirname(BASE_DIR), "stock_names_cache.json")

# ------------------------------------------------------------
# HTTP Session
# ------------------------------------------------------------
SESSION = requests.Session()
SESSION.trust_env = False
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
})

_EASTMONEY_BASE_URLS = [
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://push2delay.eastmoney.com/api/qt/clist/get",
]
_EASTMONEY_TIMEOUT = 15
_INDEX_SOURCE_MAX_DIFF_PCT = 0.3
_INDEX_PREV_CLOSE_MAX_DIFF_RATIO = 0.0002
_INDEX_PREV_CLOSE_MAX_DIFF_ABS = 0.05
_TZ_CN = timezone(timedelta(hours=8))
_MARKET_CLOSE_HOUR = 15
_TRUSTED_STOCK_KLINE_SOURCES = {"tencent", "eastmoney", "sina"}


class MarketDataUnavailable(RuntimeError):
    """Raised when market index data cannot be trusted enough to publish."""


class MarketDataConflict(MarketDataUnavailable):
    """Raised when multiple live market sources disagree beyond tolerance."""


def _normalize_generated_at(value=None):
    generated_at = value or datetime.now(_TZ_CN)
    if generated_at.tzinfo is None:
        return generated_at.replace(tzinfo=_TZ_CN)
    return generated_at.astimezone(_TZ_CN)


def build_market_time_metadata(required_date=None, generated_at=None):
    """Return deterministic report timing metadata without assuming today's date."""
    generated = _normalize_generated_at(generated_at)
    as_of = generated
    report_date = str(required_date or generated.date().isoformat())
    try:
        report_day = datetime.strptime(report_date, "%Y-%m-%d").date()
    except ValueError:
        report_day = generated.date()

    if generated.date() > report_day:
        as_of = datetime(
            report_day.year,
            report_day.month,
            report_day.day,
            _MARKET_CLOSE_HOUR,
            tzinfo=_TZ_CN,
        )

    is_closed = (
        as_of.date() == report_day
        and (as_of.hour, as_of.minute) >= (_MARKET_CLOSE_HOUR, 0)
    )
    return {
        "generated_at": generated.isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(timespec="seconds"),
        "bar_state": "closed" if is_closed else "intraday",
    }


def _collect_proxy_config():
    proxies = {}
    for env_key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(env_key)
        if value:
            key = env_key.lower().startswith("https") and "https" or "http"
            proxies[key] = value
    return proxies if proxies else None


def _fetch_eastmoney_json(params):
    """
    fetch EASTMONEY clist API with:
      1) 优先走代理（若配置）
      2) 失败后回退直连
      3) push2 / push2delay 双源兜底
    """
    proxy_settings = _collect_proxy_config()
    last_error = None

    # 先按 proxy -> base-url 组合尝试
    if proxy_settings:
        for url in _EASTMONEY_BASE_URLS:
            try:
                resp = SESSION.get(url, params=params, timeout=_EASTMONEY_TIMEOUT, proxies=proxy_settings)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_error = e
                print(f"[WARN] 东方财富请求（代理）失败: {url} -> {e}")

    # 再按无代理 -> base-url 尝试
    for url in _EASTMONEY_BASE_URLS:
        try:
            resp = SESSION.get(url, params=params, timeout=_EASTMONEY_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_error = e
            print(f"[WARN] 东方财富请求（直连）失败: {url} -> {e}")

    raise last_error


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
    for p in (STOCK_CACHE_PATH, STOCK_CACHE_PATH_FALLBACK, STOCK_CACHE_PATH_LEGACY_FALLBACK):
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
    params = {
        "pn": "1", "pz": str(top_n), "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fid": "f62",
        "fs": "m:90+t:2",
        "fields": "f12,f14,f3,f62,f184,f66",
    }
    try:
        data = _fetch_eastmoney_json(params)
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
    all_stocks = []
    page = 1
    while True:
        params = {
            "pn": str(page), "pz": "200", "po": "0", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": f"b:{sector_code}",
            "fields": "f12,f14,f3,f2,f20,f21",
        }
        try:
            data = _fetch_eastmoney_json(params)
            stock_data = data.get("data")
            if not stock_data:
                break
            items = stock_data.get("diff", [])
            if not items:
                break
            for it in items:
                market_cap = _market_cap_to_yi(it.get("f20"))
                circulating_market_cap = _market_cap_to_yi(it.get("f21"))
                all_stocks.append({
                    "code": it.get("f12", ""),
                    "name": it.get("f14", "-"),
                    "change_pct": it.get("f3", 0),
                    "close": it.get("f2", 0),
                    "market_cap": market_cap,
                    "circulating_market_cap": circulating_market_cap,
                    "float_market_cap": circulating_market_cap,
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


def _safe_float(value):
    if value is None:
        return None
    try:
        value = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _market_cap_to_yi(value):
    number = _safe_float(value)
    if number is None:
        return None
    if abs(number) > 10000:
        return round(number / 100_000_000.0, 4)
    return number


def _extract_eastmoney_amount(parts):
    # fields2 order starts at f51. EastMoney 通常把 f57 放在 index=6。
    if len(parts) <= 6:
        return None
    return _safe_float(parts[6])


def _ensure_amounts_array(values):
    if values is None:
        return None
    arr = []
    for v in values:
        f = _safe_float(v)
        if f is None:
            arr.append(float("nan"))
        else:
            arr.append(f)
    if not arr:
        return None
    return np.array(arr, dtype=float)


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


def _fetch_daily_kline_tencent_plain_remote(code, count=DAY_LOOKBACK):
    """Fetch unadjusted daily kline from Tencent. Indexes do not need qfq."""
    tc = _tencent_code(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={tc},day,,,{count}"
    try:
        resp = SESSION.get(url, timeout=15)
        data = resp.json()
        stock_data = data.get("data", {}).get(tc, {})
        klines = stock_data.get("day", [])
        if not klines:
            return None
        return _parse_tencent_kline(klines[-count:])
    except Exception as e:
        print(f"[ERROR] 腾讯非复权日线失败 {code}: {e}")
        return None


def _fetch_daily_kline_eastmoney_remote(code, count=DAY_LOOKBACK):
    """获取日线K线。东方财富历史K线 API。"""
    params = {
        "secid": _em_secid(code),
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": str(count),
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    try:
        resp = SESSION.get(url, params=params, timeout=15)
        data = resp.json()
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return None
        raw_lines = []
        amounts = []
        for line in klines:
            parts = str(line).split(",")
            if len(parts) < 6:
                continue
            # 统一为腾讯解析格式: 日期, 开盘, 收盘, 最高, 最低, 成交量
            raw_lines.append([parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]])
            amounts.append(_extract_eastmoney_amount(parts))
        if not raw_lines:
            return None
        kline = _parse_tencent_kline(raw_lines)
        amount_array = _ensure_amounts_array(amounts)
        if amount_array is not None:
            kline["amounts"] = amount_array
        return kline
    except Exception as e:
        print(f"[ERROR] 东方财富日线失败 {code}: {e}")
        return None


def _fetch_daily_kline_sina_daily_remote(code, count=DAY_LOOKBACK):
    """Fetch daily kline from Sina daily endpoint."""
    sc = _sina_code(code)
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={sc}&scale=240&datalen={count}"
    )
    try:
        resp = SESSION.get(
            url,
            timeout=15,
            headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": SESSION.headers.get("User-Agent", "Mozilla/5.0"),
            },
        )
        klines = resp.json()
        raw_lines = []
        for item in klines or []:
            raw_lines.append([
                item["day"],
                item["open"],
                item["close"],
                item["high"],
                item["low"],
                item["volume"],
            ])
        if not raw_lines:
            return None
        return _parse_tencent_kline(raw_lines[-count:])
    except Exception as e:
        print(f"[ERROR] 新浪日线失败 {code}: {e}")
        return None


def _fetch_daily_kline_sina_quote_remote(code, count=DAY_LOOKBACK):
    """Fetch latest index quote from Sina and synthesize a 2-bar kline."""
    sc = _sina_code(code)
    url = f"https://hq.sinajs.cn/list={sc}"
    try:
        resp = SESSION.get(
            url,
            timeout=10,
            headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": SESSION.headers.get("User-Agent", "Mozilla/5.0"),
            },
        )
        text = resp.text
        if '="' not in text:
            return None
        payload = text.split('="', 1)[1].rsplit('"', 1)[0]
        parts = payload.split(",")
        if len(parts) < 31:
            return None
        open_price = float(parts[1])
        prev_close = float(parts[2])
        current = float(parts[3])
        high = float(parts[4])
        low = float(parts[5])
        volume = float(parts[8] or 0)
        quote_date = parts[30]
        if not quote_date or prev_close <= 0 or current <= 0:
            return None
        return {
            "dates": [quote_date, quote_date],
            "opens": np.array([prev_close, open_price]),
            "highs": np.array([prev_close, high]),
            "lows": np.array([prev_close, low]),
            "closes": np.array([prev_close, current]),
            "volumes": np.array([0.0, volume]),
        }
    except Exception as e:
        print(f"[ERROR] 新浪实时指数失败 {code}: {e}")
        return None


def _latest_date(kline):
    dates = (kline or {}).get("dates", [])
    return str(dates[-1]).split(" ")[0] if dates else ""


def _kline_latest_date(kline):
    dates = (kline or {}).get("dates", [])
    return str(dates[-1]).split(" ")[0] if dates else ""


def build_kline_status(kline, required_date=None, source="unknown"):
    if not kline:
        return {
            "daily": "missing",
            "latest_date": "",
            "source": source,
            "bars": 0,
            "stale": True,
        }

    latest_date = _kline_latest_date(kline)
    bars = len(kline.get("closes", []))
    if required_date and latest_date != required_date:
        return {
            "daily": "stale_cache",
            "latest_date": latest_date,
            "source": kline.get("source", source),
            "bars": bars,
            "stale": True,
        }

    return {
        "daily": "verified",
        "latest_date": latest_date,
        "source": kline.get("source", source),
        "bars": bars,
        "stale": False,
    }


def _latest_change_pct(kline):
    closes = (kline or {}).get("closes", [])
    if closes is None or len(closes) < 2:
        return None
    prev = float(closes[-2])
    curr = float(closes[-1])
    if prev <= 0:
        return None
    return (curr - prev) / prev * 100


def _close_matches(expected, actual):
    expected = float(expected)
    actual = float(actual)
    tolerance = max(_INDEX_PREV_CLOSE_MAX_DIFF_ABS, abs(expected) * _INDEX_PREV_CLOSE_MAX_DIFF_RATIO)
    return abs(expected - actual) <= tolerance


def _cached_index_kline(code, count):
    records = sorted(read_cached_records("day", code), key=lambda r: r["date"])
    if len(records) < max(2, min(20, count)):
        return None
    return records_to_kline_dict(records[-count:])


def _splice_realtime_index_bar(history, quote, count, source, required_date=None):
    if not history or not quote:
        return None
    if len(history.get("closes", [])) < max(2, min(20, count) - 1):
        return None
    if len(quote.get("closes", [])) < 2:
        return None

    quote_date = _latest_date(quote)
    if required_date and quote_date != required_date:
        return None

    history_close = float(history["closes"][-1])
    quote_prev_close = float(quote["closes"][-2])
    if not _close_matches(history_close, quote_prev_close):
        return None

    history_records = kline_dict_to_records(history)
    today_record = {
        "date": quote_date,
        "open": float(quote["opens"][-1]),
        "high": float(quote["highs"][-1]),
        "low": float(quote["lows"][-1]),
        "close": float(quote["closes"][-1]),
        "volume": float(quote["volumes"][-1]),
    }
    merged = merge_kline_records(history_records, [today_record])
    result = records_to_kline_dict(merged[-count:])
    result["source"] = source
    return result


def _validate_index_kline(code, source, kline, required_date=None, min_bars=2):
    if not kline or len(kline.get("closes", [])) < min_bars:
        raise MarketDataUnavailable(f"{source} {code} 无有效指数K线")
    latest = _latest_date(kline)
    if required_date and latest != required_date:
        raise MarketDataUnavailable(f"{source} {code} 指数日期{latest}不是报告日{required_date}")
    chg = _latest_change_pct(kline)
    if chg is None:
        raise MarketDataUnavailable(f"{source} {code} 指数涨跌幅无法验算")
    return chg


def fetch_verified_index_kline(code, count=DAY_LOOKBACK, required_date=None):
    """Fetch index daily kline from live sources only; stale cache is not accepted."""
    min_bars = 2 if count <= 3 else min(20, count)
    sources = [
        ("tencent", _fetch_daily_kline_remote),
        ("tencent_plain", _fetch_daily_kline_tencent_plain_remote),
        ("eastmoney", _fetch_daily_kline_eastmoney_remote),
        ("sina_daily", _fetch_daily_kline_sina_daily_remote),
    ]
    if count <= 3:
        sources.append(("sina_quote", _fetch_daily_kline_sina_quote_remote))

    valid = []
    errors = []
    fetched = {}
    for source, fetcher in sources:
        kline = fetcher(code, count=count)
        fetched[source] = kline
        try:
            chg = _validate_index_kline(
                code, source, kline, required_date=required_date, min_bars=min_bars
            )
        except MarketDataUnavailable as e:
            errors.append(str(e))
            continue
        valid.append((source, kline, chg))

    if count > 3 and required_date:
        quote = _fetch_daily_kline_sina_quote_remote(code, count=2)
        splice_sources = [
            ("sina_daily+sina_quote", fetched.get("sina_daily")),
            ("cache+sina_quote", _cached_index_kline(code, count)),
        ]
        for source, history in splice_sources:
            kline = _splice_realtime_index_bar(
                history, quote, count=count, source=source, required_date=required_date
            )
            try:
                chg = _validate_index_kline(
                    code, source, kline, required_date=required_date, min_bars=min_bars
                )
            except MarketDataUnavailable as e:
                errors.append(str(e))
                continue
            valid.append((source, kline, chg))

    if not valid:
        raise MarketDataUnavailable(f"{code} 指数多源取数失败: {'; '.join(errors)}")

    base_source, base_kline, base_chg = valid[0]
    for source, _kline, chg in valid[1:]:
        if abs(chg - base_chg) > _INDEX_SOURCE_MAX_DIFF_PCT:
            raise MarketDataConflict(
                f"{code} 指数源冲突: {base_source}={base_chg:.2f}%, {source}={chg:.2f}%"
            )

    result = dict(base_kline)
    result["source"] = base_source
    return result


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
            cached["source"] = "tencent"
            CACHE_STATS["day_hit"] += 1
            return cached
        CACHE_STATS["day_miss"] += 1
        return remote

    cached = cached_kline_if_sufficient("day", code, count)
    if cached is not None:
        cached["source"] = "kline_cache"
        CACHE_STATS["day_hit"] += 1
        print(f"  [CACHE FALLBACK] day {code} remote failed, using cache")
        return cached
    CACHE_STATS["day_miss"] += 1
    return None


def fetch_shanghai_index(required_date=None):
    """获取上证指数日线"""
    return fetch_verified_index_kline("000001", count=DAY_LOOKBACK, required_date=required_date)


# ============================================================
# 分钟 K 线 — 新浪
# ============================================================
def _fetch_sina_minute_kline_remote(code, scale, count):
    """Fetch minute kline from Sina."""
    sc = _sina_code(code)
    datalen = min(count, 240)
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={sc}&scale={scale}&datalen={datalen}"
    )
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
        print(f"[ERROR] 获取{scale}分钟K线失败 {code}: {e}")
        return None


def _fetch_30min_kline_remote(code, count=80):
    """
    获取30分钟K线。新浪 API。
    返回: {"dates": [...], "opens": [...], "highs": [...], "lows": [...], "closes": [...], "volumes": [...]}
    """
    return _fetch_sina_minute_kline_remote(code, scale=30, count=count)


def _fetch_15min_kline_remote(code, count=MIN15_LOOKBACK_BARS):
    """
    获取15分钟K线。罗姐池需要至少177根来计算生命线。
    """
    return _fetch_sina_minute_kline_remote(code, scale=15, count=count)


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


def fetch_15min_kline(code, count=MIN15_LOOKBACK_BARS, force_refresh=False):
    """Fetch 15min kline with incremental cache support."""
    force = force_refresh or KLINE_CACHE_FORCE_REFRESH or _FORCE_REFRESH_CACHE
    cached_records = read_cached_records("15min", code)
    cached_enough = len(cached_records) >= count

    if force:
        remote_count = count
    elif cached_enough:
        remote_count = min(MIN15_KLINE_INCREMENTAL_FETCH_COUNT, count)
    else:
        remote_count = count

    remote = _fetch_15min_kline_remote(code, count=remote_count)

    if remote:
        merged = merge_kline_records(cached_records, kline_dict_to_records(remote))
        write_cached_records(
            "15min", code, merged,
            source="sina",
            keep_trading_days=MIN15_KLINE_CACHE_RETENTION_TRADING_DAYS,
        )
        CACHE_STATS["15min_write"] = CACHE_STATS.get("15min_write", 0) + 1
        cached = cached_kline_if_sufficient("15min", code, count)
        if cached is not None:
            CACHE_STATS["15min_hit"] = CACHE_STATS.get("15min_hit", 0) + 1
            return cached
        CACHE_STATS["15min_miss"] = CACHE_STATS.get("15min_miss", 0) + 1
        return remote

    cached = cached_kline_if_sufficient("15min", code, count)
    if cached is not None:
        CACHE_STATS["15min_hit"] = CACHE_STATS.get("15min_hit", 0) + 1
        print(f"  [CACHE FALLBACK] 15min {code} remote failed, using cache")
        return cached
    CACHE_STATS["15min_miss"] = CACHE_STATS.get("15min_miss", 0) + 1
    return None


# ============================================================
# K 线通用入口（用于 market indices 等场景）
# ============================================================
def fetch_kline(code, klt="101", count=DAY_LOOKBACK, fqt="1"):
    """
    通用K线获取入口。
    klt: 101=日线, 30=30分钟, 15=15分钟 (兼容旧接口)
    """
    if klt in ("101", "day", "1d"):
        return fetch_daily_kline(code, count=count)
    elif klt in ("30", "min30", "30min"):
        return fetch_30min_kline(code, count=count)
    elif klt in ("15", "min15", "15min"):
        return fetch_15min_kline(code, count=count)
    else:
        return fetch_daily_kline(code, count=count)


# ============================================================
# 批量获取
# ============================================================
def batch_fetch_daily_klines(
    stocks, max_workers=10, required_date=None, allow_stale=False, force_refresh=False
):
    """
    并发批量获取日线。
    stocks: [{"code": "600519", "name": "茅台", "sector": "...", ...}, ...]
    返回: [{"code": ..., "name": ..., "sector": ..., "sector_tags": [...], "klines": {...}, "data_status": {...}}, ...]
    """
    results = []

    def _fetch_one(stock):
        code = stock["code"]
        klines = fetch_daily_kline(code, force_refresh=force_refresh)
        kline_source = (klines or {}).get("source") or stock.get("source") or "tencent"
        status = build_kline_status(
            klines, required_date=required_date, source=kline_source,
        )
        stock["data_status"] = status

        if not klines or len(klines.get("closes", [])) < 60:
            if status["daily"] == "missing":
                print(f"  [DEBUG] {code} {stock.get('name','')} 拉取失败")
            else:
                print(f"  [DEBUG] {code} {stock.get('name','')} K线不足60根(实际{len(klines.get('closes',[]))})，可能新股/停牌")
            status["daily"] = "missing"
            status["stale"] = required_date is not None
            stock["data_status"] = status
            return None

        if status["daily"] != "verified" and not allow_stale:
            print(
                f"  [STALE] {code} {stock.get('name','')} "
                f"latest={status['latest_date']} required={required_date}"
            )
            return None

        amounts = stock.get("amounts")
        if amounts is None and isinstance(klines, dict):
            amounts = klines.get("amounts")

        return {
            "code": code,
            "name": stock.get("name", ""),
            "sector": stock.get("sector", ""),
            "sector_tags": list(stock.get("sector_tags", [])),
            "sector_rank": stock.get("sector_rank"),
            "sector_flow": stock.get("sector_flow"),
            "sector_strength_label": stock.get("sector_strength_label", ""),
            "change_pct": stock.get("change_pct", 0),
            "market_cap": stock.get("market_cap"),
            "circulating_market_cap": stock.get("circulating_market_cap"),
            "float_market_cap": stock.get("float_market_cap"),
            "amount": stock.get("amount"),
            "amounts": amounts,
            "klines": klines,
            "data_status": status,
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


def batch_fetch_15min_klines(stocks, max_workers=8):
    """
    并发批量获取15分钟K线。
    """
    results = []

    def _fetch_one(stock):
        code = stock["code"]
        klines = fetch_15min_kline(code)
        if klines and len(klines.get("closes", [])) >= 180:
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
def collect_daily_data(required_date=None, allow_missing_index=False, generated_at=None):
    """
    完整数据采集流程:
    1. 获取 TOP20 资金流入板块
    2. 获取板块成分股（去重）
    3. 批量获取成分股日线
    4. 获取上证指数日线
    """
    print("=" * 60)
    time_metadata = build_market_time_metadata(
        required_date=required_date,
        generated_at=generated_at,
    )
    print("Phase 1: 数据采集")
    print("=" * 60)

    print("[1/4] 获取板块资金流向 TOP20 ...")
    used_fallback_sector_source = False
    warnings = []
    fallback_used = False
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
        used_fallback_sector_source = True
        fallback_used = True
        warnings.append("板块资金流向接口不可用，使用静态TOP20板块兜底")
        print(f"  板块API超时，使用兜底 {len(sectors)} 个板块")
    else:
        print(f"  获取到 {len(sectors)} 个板块")
    for s in sectors[:5]:
        print(f"    {s.get('name','')}: 净流入 {s.get('flow_str', '0')}")

    print("[2/4] 获取板块成分股 ...")
    stock_map = {}
    consecutive_failures = 0
    sector_source = "fallback_static" if used_fallback_sector_source else "eastmoney"
    stock_pool_source = "sector_components"
    for sector_rank, sector in enumerate(sectors, start=1):
        stocks = fetch_sector_stocks(sector["code"])
        if not stocks:
            consecutive_failures += 1
            # 连续 5 个板块全部失败 → 代理大概率已挂，直接放弃剩余请求
            if consecutive_failures >= 5:
                print(f"  连续 {consecutive_failures} 个板块API失败，跳过剩余板块")
                break
        else:
            consecutive_failures = 0
        for st in stocks:
            code = st["code"]
            if code in stock_map:
                tags = stock_map[code].setdefault("sector_tags", [])
                if sector["name"] not in tags and sector["name"] != stock_map[code].get("sector", ""):
                    tags.append(sector["name"])
            else:
                sector_strength_label = (
                    sector.get("sector_strength_label")
                    or sector.get("strength_label")
                    or f"资金流入TOP{sector_rank}"
                )
                stock_map[code] = {
                    "code": code,
                    "name": st.get("name", ""),
                    "change_pct": st.get("change_pct", 0),
                    "sector": sector["name"],
                    "sector_tags": [sector["name"]],
                    "sector_rank": sector_rank,
                    "sector_flow": sector.get("flow"),
                    "sector_strength_label": sector_strength_label,
                    "market_cap": st.get("market_cap"),
                    "circulating_market_cap": st.get("circulating_market_cap"),
                    "float_market_cap": st.get("float_market_cap"),
                    "amount": st.get("amount"),
                    "amounts": st.get("amounts"),
                }
    print(f"  共 {len(stock_map)} 只成分股（去重后）")

    if not stock_map:
        from pathlib import Path
        from config import KLINE_CACHE_DIR
        cache_dir = Path(KLINE_CACHE_DIR) / "klines" / "day"
        if cache_dir.exists():
            cached = list(cache_dir.glob("*.json"))
            code_to_name = get_code_to_name()
            for f in cached:
                code = f.stem
                # 跳过非标准6位代码（如指数）
                if not code or len(code) != 6 or not code.isdigit():
                    continue
                # 跳过北交所/新三板（92/87/83/43开头）
                if code[:2] in ("92", "87", "83", "43"):
                    continue
                name = code_to_name.get(code, code)
                stock_map[code] = {
                    "code": code,
                    "name": name,
                    "change_pct": 0,
                    "sector": "",
                    "sector_tags": [],
                    "sector_rank": None,
                    "sector_flow": None,
                    "sector_strength_label": "",
                    "source": "kline_cache",
                }
            if stock_map:
                print(f"  [FALLBACK] 板块API全部不可用，从 K线缓存恢复 {len(stock_map)} 只股票")
                stock_pool_source = "kline_cache"
                sector_source = "fallback_static"
                fallback_used = True
                warnings.append("板块成分抓取失败，从 K线缓存恢复股票池")
                warnings.append("板块API全部不可用，使用 K线缓存兜底")
            else:
                print(f"  [FALLBACK] K线缓存中无可用股票")
                warnings.append("K线缓存为空，无法回退")

    all_stocks = list(stock_map.values())
    print(f"[3/4] 批量获取日线（{len(all_stocks)} 只）...")
    t0 = time.time()
    stocks_with_kline = batch_fetch_daily_klines(
        all_stocks,
        required_date=required_date,
        allow_stale=allow_missing_index,
        force_refresh=time_metadata["bar_state"] == "closed",
    )
    elapsed = time.time() - t0
    print(f"  获取到 {len(stocks_with_kline)} 只有效日线数据，耗时 {elapsed:.1f}s")

    stale_stock_count = 0
    missing_daily_count = 0
    for st in all_stocks:
        status = st.get("data_status") or {}
        if status.get("daily") == "stale_cache":
            stale_stock_count += 1
        elif status.get("daily") == "missing":
            missing_daily_count += 1

    print("[4/4] 获取上证指数日线 ...")
    index_error = ""
    try:
        sh_kline = fetch_shanghai_index(required_date=required_date)
    except MarketDataUnavailable as e:
        if not allow_missing_index:
            raise
        index_error = str(e)
        sh_kline = None
        print(f"  [PREVIEW] 上证指数未校验，继续生成预览: {index_error}")
    print(f"  上证数据: {len(sh_kline['closes']) if sh_kline else 0} 根K线")

    if not sectors:
        sector_source = "empty"

    report_date = required_date or ""
    dates_match = bool(
        report_date
        and _latest_date(sh_kline) == report_date
        and stocks_with_kline
        and all(
            (st.get("data_status") or {}).get("latest_date") == report_date
            for st in stocks_with_kline
        )
    )
    stock_sources_trusted = bool(
        stocks_with_kline
        and all(
            (st.get("data_status") or {}).get("source") in _TRUSTED_STOCK_KLINE_SOURCES
            for st in stocks_with_kline
        )
    )
    sources_trusted = bool(
        sh_kline
        and sector_source == "eastmoney"
        and stock_sources_trusted
        and not fallback_used
    )

    data_quality = {
        "report_date": report_date,
        **time_metadata,
        "is_trading_day": bool(sh_kline),
        "is_official": bool(
            sh_kline
            and stocks_with_kline
            and not allow_missing_index
            and not fallback_used
            and dates_match
            and sources_trusted
            and time_metadata["bar_state"] == "closed"
            and stale_stock_count == 0
            and missing_daily_count == 0
        ),
        "sources_trusted": sources_trusted,
        "market_status": "verified" if sh_kline else "unverified",
        "stock_pool_source": stock_pool_source,
        "sector_source": sector_source,
        "stale_stock_count": stale_stock_count,
        "missing_daily_count": missing_daily_count,
        "missing_30min_count": 0,
        "fallback_used": fallback_used,
        "warnings": warnings,
    }

    print("Phase 1 完成\n")
    return {
        "sectors": sectors,
        "sh_index": sh_kline,
        "stocks": stocks_with_kline,
        "index_error": index_error,
        "data_quality": data_quality,
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


def collect_15min_data(target_stocks):
    """
    为目标池股票拉取15分钟K线。
    """
    if not target_stocks:
        return []
    print(f"  批量获取15分钟K线（{len(target_stocks)} 只）...")
    t0 = time.time()
    results = batch_fetch_15min_klines(target_stocks)
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
    params = {
        "pn": "1", "pz": str(top_n * 3), "po": "0", "np": "1",
        "fltt": "2", "invt": "2",
        "fid": "f62",
        "fs": "m:90+t:2",
        "fields": "f12,f14,f3,f62,f184,f66",
    }
    try:
        data = _fetch_eastmoney_json(params)
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
