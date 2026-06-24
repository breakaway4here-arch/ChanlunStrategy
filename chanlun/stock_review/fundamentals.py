"""Lightweight fundamentals collection for stock review.

Fetches basic company data from EastMoney. Missing fields are tracked in
`missing_fields` rather than shown as "None". Never blocks the chanlun
structure report on fundamental data failures.

Data sources (tried in order):
1. EastMoney F10 API — rich financial ratios (ROE, margins, growth, debt)
2. EastMoney push2 — real-time PE/PB/market_cap
3. Tencent qt — fallback PE/market_cap when push2 502s
Cache: 24h JSON file cache to survive API flakiness.
"""
import json
import os
import requests
from datetime import datetime, timedelta

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://emweb.securities.eastmoney.com/",
})

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), ".cache", "fundamentals")
_CACHE_TTL_HOURS = 24


def _normalize_metric(field, value):
    """Normalize implausible EastMoney numeric scales into human-readable units."""
    if value is None or not isinstance(value, (int, float)):
        return value

    limits = {
        "pe": 1000,
        "pb": 100,
        "ps": 100,
        "roe": 100,
        "gross_margin": 100,
        "net_margin": 100,
        "revenue_yoy": 1000,
        "profit_yoy": 1000,
        "deducted_profit_yoy": 1000,
        "debt_ratio": 100,
    }
    limit = limits.get(field)
    if limit is None:
        return value

    normalized = float(value)
    while abs(normalized) > limit:
        normalized /= 100.0
    return round(normalized, 4)


def _apply_normalization(result):
    for field in [
        "pe", "pb", "ps", "roe", "gross_margin", "net_margin",
        "revenue_yoy", "profit_yoy", "deducted_profit_yoy", "debt_ratio",
    ]:
        result[field] = _normalize_metric(field, result.get(field))
    return result


def _tencent_profile(code):
    """Fetch basic stock data from Tencent API as fallback.

    Returns dict with company_name, pe, market_cap, pb. Tencent API
    is more reliable than EastMoney push2 during outages.
    """
    tc = f"sh{code}" if code.startswith(("60", "68", "900")) else f"sz{code}"
    result = {}
    try:
        url = f"http://qt.gtimg.cn/q={tc}"
        resp = SESSION.get(url, timeout=10,
                           headers={"User-Agent": "Mozilla/5.0"})
        text = resp.text
        # Format: v_tc="1~name~code~price~...~PE~...~market_cap~..."
        # Strip prefix and quotes
        start = text.find('"') + 1
        end = text.rfind('"')
        if start <= 0 or end <= start:
            return result
        fields = text[start:end].split("~")
        if len(fields) < 45:
            return result
        # Known Tencent field indices (0-based)
        result["company_name"] = fields[1] if fields[1] else ""
        # PE at field 39, total market cap at 44 (in 亿 yuan)
        try:
            result["pe"] = float(fields[39]) if fields[39] else None
        except (ValueError, IndexError):
            pass
        try:
            result["market_cap"] = float(fields[44]) * 100000000 if fields[44] else None
        except (ValueError, IndexError):
            pass
        # PB at field 46
        try:
            result["pb"] = float(fields[46]) if fields[46] else None
        except (ValueError, IndexError):
            pass
    except Exception:
        pass
    return result


def _eastmoney_profile(code):
    """Fetch basic company profile + financial indicators from EastMoney.

    Falls back to Tencent API for PE/market_cap when EastMoney is unavailable.
    """
    secid = f"1.{code}" if code.startswith(("60", "68", "900")) else f"0.{code}"

    result = {}
    em_ok = False
    # Profile: name, industry, PE, PB, market_cap
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": secid,
            "fields": "f57,f58,f100,f116,f117,f162,f167,f173",
        }
        resp = SESSION.get(url, params=params, timeout=10)
        if resp.status_code == 200 and resp.text.strip().startswith("{"):
            data = resp.json().get("data", {})
            if data:
                result["company_name"] = data.get("f58", "")
                result["industry"] = data.get("f100", "")
                result["pe"] = data.get("f162")
                result["pb"] = data.get("f167")
                result["market_cap"] = data.get("f116")
                em_ok = True
    except Exception:
        pass

    # Fallback: Tencent API for PE and market_cap
    if not em_ok:
        tc = _tencent_profile(code)
        if tc.get("company_name") and not result.get("company_name"):
            result["company_name"] = tc["company_name"]
        if tc.get("pe") is not None:
            result["pe"] = tc["pe"]
        if tc.get("market_cap") is not None:
            result["market_cap"] = tc["market_cap"]

    # Financial data: ROE, revenue_yoy, profit_yoy, debt_ratio, etc.
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": secid,
            "fields": "f37,f39,f40,f41,f43,f44,f45,f46,f49,f50,f51,f52,f55,f173,f183,f184,f185,f186,f187,f188",
        }
        resp = SESSION.get(url, params=params, timeout=10)
        if resp.status_code == 200 and resp.text.strip().startswith("{"):
            data = resp.json().get("data", {})
            if data:
                result["roe"] = data.get("f37")
                result["revenue_yoy"] = data.get("f44")
                result["profit_yoy"] = data.get("f45")
                result["gross_margin"] = data.get("f49")
                result["net_margin"] = data.get("f50")
                result["debt_ratio"] = data.get("f51")
    except Exception:
        pass

    return result


def _emweb_company_profile(code):
    """Fetch company profile from EastMoney F10 CompanySurveyAjax.

    Returns dict with industry, business description, employees, region, website.
    Empty dict on failure.
    """
    prefix = "SZ" if code.startswith(("0", "3", "2")) else "SH"
    result = {}
    try:
        url = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax"
        params = {"code": f"{prefix}{code}"}
        resp = SESSION.get(url, params=params, timeout=10)
        if resp.status_code != 200 or not resp.text.strip().startswith("{"):
            return result
        data = resp.json()
        jbzl = data.get("jbzl", {})
        if not jbzl:
            return result
        result["industry"] = jbzl.get("sshy", "")
        result["industry_csrc"] = jbzl.get("sszjhhy", "")  # CSRC classification
        result["business"] = (jbzl.get("gsjj") or "").strip()
        result["employees"] = jbzl.get("gyrs", "")
        result["region"] = jbzl.get("qy", "")
        result["website"] = jbzl.get("gswz", "")
        result["company_name"] = jbzl.get("gsmc", "")
        return result
    except Exception:
        return result


def _emweb_f10_financial(code):
    """Fetch rich financial ratios from EastMoney F10 web API.

    This endpoint is more reliable than push2 for financial data (ROE,
    margins, growth rates, debt ratios). Returns dict with quarterly and
    annual figures, or empty dict on failure.
    """
    prefix = "SZ" if code.startswith(("0", "3", "2")) else "SH"
    result = {}
    try:
        url = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew"
        # type=0: quarterly reports; type=1: annual reports
        params = {"code": f"{prefix}{code}", "type": "0"}
        resp = SESSION.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return result
        data = resp.json()
        records = data.get("data", [])
        if not records:
            return result

        latest = records[0]

        # Map F10 fields to our internal format
        result["gross_margin"] = latest.get("XSMLL")           # 销售毛利率
        result["net_margin"] = latest.get("XSJLL")             # 销售净利率
        result["roe"] = latest.get("ROEJQ")                    # ROE (季度)
        result["debt_ratio"] = latest.get("ZCFZL")             # 资产负债率
        result["revenue_yoy"] = latest.get("TOTALOPERATEREVETZ")   # 营收同比
        result["profit_yoy"] = latest.get("PARENTNETPROFITTZ")     # 归母净利同比
        result["eps"] = latest.get("EPSJB")                    # 基本每股收益
        result["bps"] = latest.get("BPS")                      # 每股净资产
        result["ocf_per_share"] = latest.get("MGJYXJJE")       # 每股经营现金流
        result["interest_bearing_debt"] = latest.get("INTEREST_DEBT_RATIO")  # 有息负债率
        result["current_ratio"] = latest.get("LD")             # 流动比率
        result["quick_ratio"] = latest.get("SD")               # 速动比率
        result["deducted_profit_yoy"] = latest.get("KCFJCXSYJLRTZ")  # 扣非利润同比
        result["report_date"] = latest.get("REPORT_DATE_NAME", "")

        # Also get annual data for annual ROE
        try:
            params_annual = {"code": f"{prefix}{code}", "type": "1"}
            resp2 = SESSION.get(url, params=params_annual, timeout=10)
            if resp2.status_code == 200:
                annual_data = resp2.json().get("data", [])
                if annual_data:
                    result["roe_annual"] = annual_data[0].get("ROEJQ")
                    result["revenue_yoy_annual"] = annual_data[0].get("TOTALOPERATEREVETZ")
                    result["profit_yoy_annual"] = annual_data[0].get("PARENTNETPROFITTZ")
        except Exception:
            pass

        return result
    except Exception:
        return result


def _empty_result(name=""):
    return {
        "company_name": name,
        "industry": None,
        "industry_csrc": None,
        "business": None,
        "employees": None,
        "region": None,
        "website": None,
        "market_cap": None,
        "pe": None,
        "pb": None,
        "ps": None,
        "roe": None,
        "gross_margin": None,
        "net_margin": None,
        "revenue_yoy": None,
        "profit_yoy": None,
        "deducted_profit_yoy": None,
        "operating_cashflow": None,
        "accounts_receivable": None,
        "inventory": None,
        "debt_ratio": None,
        "interest_bearing_debt": None,
        "goodwill": None,
        "cash": None,
        "source": "unknown",
        "updated_at": "",
        "missing_fields": [],
        "risk_flags": [],
        "status": "ok",
    }


def _cache_path(code):
    """Return cache file path for a stock code."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{code}.json")


def _load_cache(code):
    """Load cached fundamentals if within TTL. Returns dict or None."""
    path = _cache_path(code)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        updated = data.get("updated_at", "")
        if updated:
            cached_time = datetime.strptime(updated, "%Y-%m-%d %H:%M")
            if datetime.now() - cached_time > timedelta(hours=_CACHE_TTL_HOURS):
                return None
        return data
    except Exception:
        return None


def _save_cache(code, data):
    """Save fundamentals to cache."""
    try:
        path = _cache_path(code)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


def _count_valid_fields(result):
    """Count non-None data fields in result."""
    key_fields = ["pe", "pb", "roe", "revenue_yoy", "profit_yoy",
                  "gross_margin", "net_margin", "debt_ratio", "market_cap", "industry"]
    return sum(1 for k in key_fields if result.get(k) is not None)


def _merge_financials(result, source_data, prefix=""):
    """Merge financial ratio fields from source into result, only filling None."""
    field_map = {
        "roe": "roe",
        "gross_margin": "gross_margin",
        "net_margin": "net_margin",
        "debt_ratio": "debt_ratio",
        "revenue_yoy": "revenue_yoy",
        "profit_yoy": "profit_yoy",
        "deducted_profit_yoy": "deducted_profit_yoy",
        "operating_cashflow": "ocf_per_share",
        "interest_bearing_debt": "interest_bearing_debt",
    }
    for result_key, source_key in field_map.items():
        if result.get(result_key) is None and source_data.get(source_key) is not None:
            result[result_key] = source_data[source_key]

    # Extra fields from F10
    extra_fields = ["eps", "bps", "current_ratio", "quick_ratio",
                    "report_date", "roe_annual", "ocf_per_share"]
    for key in extra_fields:
        if source_data.get(key) is not None:
            result[key] = source_data[key]


def fetch_fundamentals(code, name):
    """Fetch lightweight fundamental data for a stock.

    Returns a dict with all expected fields. Missing data is left as None
    and tracked in missing_fields. Never raises on failure.

    Data pipeline:
    1. push2 profile → PE, PB, market_cap, industry (real-time)
    2. F10 API → ROE, margins, growth, debt ratios (quarterly + annual)
    3. Tencent API → fallback PE/market_cap
    4. 24h file cache → survive API flakiness
    """
    if not code:
        r = _empty_result(name)
        r["status"] = "degraded"
        r["missing_fields"].append("无股票代码")
        return r

    result = _empty_result(name)
    sources = []

    # 1. Real-time data from push2 profile (PE, PB, market_cap)
    try:
        profile = _eastmoney_profile(code)
        if profile.get("company_name"):
            result["company_name"] = profile["company_name"]
        if profile.get("industry"):
            result["industry"] = profile["industry"]
        result["pe"] = profile.get("pe")
        result["pb"] = profile.get("pb")
        result["market_cap"] = profile.get("market_cap")
        result["roe"] = profile.get("roe")
        result["revenue_yoy"] = profile.get("revenue_yoy")
        result["profit_yoy"] = profile.get("profit_yoy")
        result["gross_margin"] = profile.get("gross_margin")
        result["net_margin"] = profile.get("net_margin")
        result["debt_ratio"] = profile.get("debt_ratio")
        _apply_normalization(result)
        sources.append("push2")
    except Exception:
        pass

    # 1.3 Company profile from F10 (industry, business description, employees, region)
    try:
        cp = _emweb_company_profile(code)
        if cp:
            if not result.get("industry") and cp.get("industry"):
                result["industry"] = cp["industry"]
            if cp.get("industry_csrc"):
                result["industry_csrc"] = cp["industry_csrc"]
            if cp.get("business"):
                result["business"] = cp["business"]
            if cp.get("employees"):
                result["employees"] = cp["employees"]
            if cp.get("region"):
                result["region"] = cp["region"]
            if cp.get("website"):
                result["website"] = cp["website"]
            if cp.get("company_name") and not result.get("company_name"):
                result["company_name"] = cp["company_name"]
            if "f10_profile" not in sources:
                sources.append("f10_profile")
    except Exception:
        pass

    # 1.5 Fallback: Tencent API for PB when push2 returns null
    if result.get("pb") is None:
        try:
            tc = _tencent_profile(code)
            if tc.get("pb") is not None:
                result["pb"] = tc["pb"]
        except Exception:
            pass

    # 2. Financial ratios from F10 API (more reliable, richer data)
    try:
        f10 = _emweb_f10_financial(code)
        if f10:
            _merge_financials(result, f10)
            if "f10" not in sources:
                sources.append("f10")
    except Exception:
        pass

    result["source"] = "+".join(sources) if sources else "unknown"
    result["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 3. Cache: save if enough data, otherwise merge from cached fallback
    valid_count = _count_valid_fields(result)
    if valid_count >= 3:
        _save_cache(code, result)
    elif valid_count < 3:
        cached = _load_cache(code)
        if cached:
            for key in ["industry", "business", "pe", "pb", "ps", "roe",
                        "gross_margin", "net_margin", "revenue_yoy", "profit_yoy",
                        "debt_ratio", "market_cap", "company_name",
                        "employees", "region", "website"]:
                if result.get(key) is None and cached.get(key) is not None:
                    result[key] = cached[key]
            result["source"] = result["source"] + "+cache"
            if not result.get("updated_at") or result["updated_at"] == datetime.now().strftime("%Y-%m-%d %H:%M"):
                result["updated_at"] = cached.get("updated_at", "")

    # 4. Track missing fields
    check_fields = ["industry", "business", "pe", "pb", "ps", "roe",
                    "gross_margin", "net_margin", "revenue_yoy", "profit_yoy",
                    "deducted_profit_yoy", "operating_cashflow",
                    "debt_ratio", "cash", "market_cap", "employees", "region"]
    result["missing_fields"] = [f for f in check_fields if result.get(f) is None]

    # 5. Check ST or delisting risk
    if name and ("ST" in name.upper() or "退市" in name or "退" in name):
        result["risk_flags"].append("ST或退市风险")

    return result
