"""Holdings input parsing: Excel + YAML manual holdings."""
import json
import os
import re

import yaml

from .models import Holding

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse_note_cost(note):
    """Parse cost price from holding note text.

    Supports formats: 成本 35.77 / 成本:35.77 / cost 35.77 / 买入价 35.77

    Returns float or None.
    """
    if not note:
        return None
    text = str(note).strip()
    patterns = [
        r'成本\s*[:：]?\s*(\d+\.?\d*)',
        r'成本价\s*[:：]?\s*(\d+\.?\d*)',
        r'cost\s*[:：]?\s*(\d+\.?\d*)',
        r'买入价\s*[:：]?\s*(\d+\.?\d*)',
        r'持仓成本\s*[:：]?\s*(\d+\.?\d*)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None
STOCK_CACHE_PATH = os.environ.get(
    "STOCK_NAMES_CACHE_FILE",
    "/Users/yangfan/yf_source/stock-shared-data/stock_names_cache.json",
)
STOCK_CACHE_PATH_FALLBACK = os.path.join(_BASE_DIR, "..", "stock_names_cache.json")


# ── Excel column name mappings (tolerant) ──
COL_MAP = {
    "code": ["证券代码", "股票代码", "代码"],
    "name": ["证券名称", "股票名称", "名称"],
    "quantity": ["持仓数量", "当前持仓", "当前数量", "数量"],
    "cost_price": ["成本价", "持仓成本", "成本"],
    "market_price": ["市值价", "最新价", "当前价", "市价"],
    "pnl": ["浮动盈亏", "盈亏"],
    "market_value": ["市值", "持仓市值"],
}


def _map_columns(headers):
    """Map Excel headers to standardized field names using fuzzy matching."""
    mapping = {}
    for idx, h in enumerate(headers):
        h_clean = str(h).strip() if h else ""
        for field, aliases in COL_MAP.items():
            if h_clean in aliases:
                mapping[field] = idx
                break
    return mapping


def _clean_number(val):
    """Parse number from Excel cell, handling string with commas."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_excel_holdings(excel_path, account="excel_account"):
    """Parse holdings from broker Excel file with column-name tolerance."""
    try:
        import openpyxl
    except ImportError:
        print("[WARN] openpyxl not installed, cannot parse Excel")
        return []

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = rows[0]
    col_map = _map_columns(headers)

    holdings = []
    for row in rows[1:]:
        code = str(row[col_map["code"]]).strip() if "code" in col_map and row[col_map["code"]] else ""
        name = str(row[col_map["name"]]).strip() if "name" in col_map and row[col_map["name"]] else ""
        if not code and not name:
            continue

        quantity = _clean_number(row[col_map["quantity"]]) if "quantity" in col_map else None
        cost_price = _clean_number(row[col_map["cost_price"]]) if "cost_price" in col_map else None
        market_price = _clean_number(row[col_map["market_price"]]) if "market_price" in col_map else None
        market_value = _clean_number(row[col_map["market_value"]]) if "market_value" in col_map else None
        pnl = _clean_number(row[col_map["pnl"]]) if "pnl" in col_map else None

        pnl_pct = None
        if pnl is not None and cost_price and cost_price > 0 and quantity and quantity > 0:
            pnl_pct = round(pnl / (cost_price * quantity) * 100, 2)

        holdings.append(Holding(
            account=account,
            code=code,
            name=name,
            source="excel",
            quantity=quantity,
            cost_price=cost_price,
            market_price=market_price,
            market_value=market_value,
            pnl=pnl,
            pnl_pct=pnl_pct,
        ))

    return holdings


def normalize_holdings(raw_list, account="manual", source="manual"):
    """Convert raw dict list to Holding objects with strip + validation.

    Also parses cost_price from note text if cost_price is not explicitly set.
    """
    holdings = []
    for item in raw_list:
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", "")).strip()
        if not code and not name:
            continue
        note = str(item.get("note", "")).strip()
        cost_price = item.get("cost_price")
        # Parse cost from note if not explicitly provided
        if cost_price is None and note:
            cost_price = parse_note_cost(note)
        holdings.append(Holding(
            account=account,
            code=code,
            name=name,
            source=source,
            quantity=item.get("quantity"),
            cost_price=cost_price,
            note=note,
        ))
    return holdings


def merge_holdings_by_code(holdings):
    """Merge holdings by code, preserving per-account detail."""
    groups = {}
    for h in holdings:
        code = h.code if h.code else ("__unresolved__" + h.name)
        if code not in groups:
            groups[code] = {"code": h.code, "name": h.name, "accounts": []}
        groups[code]["accounts"].append({
            "account": h.account,
            "source": h.source,
            "quantity": h.quantity,
            "cost_price": h.cost_price,
            "market_price": h.market_price,
            "market_value": h.market_value,
            "pnl": h.pnl,
            "pnl_pct": h.pnl_pct,
            "note": h.note,
        })
        # Prefer non-empty name
        if h.name and not groups[code]["name"]:
            groups[code]["name"] = h.name
    return groups


def _load_name_cache():
    """Load stock name ↔ code cache."""
    for p in (STOCK_CACHE_PATH, STOCK_CACHE_PATH_FALLBACK):
        rp = os.path.normpath(p)
        if os.path.exists(rp):
            with open(rp, "r", encoding="utf-8") as f:
                return json.load(f)
    return {}


def resolve_names(holdings):
    """Resolve stock names to codes using name cache.

    Returns: (resolved, unresolved, ambiguous)
    """
    cache = _load_name_cache()
    name_to_code = {k: v for k, v in cache.items()}  # name -> code
    code_to_name = {v: k for k, v in cache.items()}  # code -> name

    resolved = []
    unresolved = []
    ambiguous = []

    for h in holdings:
        # Already has code, try to fill name
        if h.code and not h.name:
            name = code_to_name.get(h.code, "")
            h.name = name
            resolved.append(h)
            continue

        # Already has name and code
        if h.code and h.name:
            resolved.append(h)
            continue

        # Only has name, try to resolve
        if h.name and not h.code:
            code = name_to_code.get(h.name, "")
            if code:
                h.code = code
                resolved.append(h)
            else:
                unresolved.append(h)
            continue

        # Neither code nor name
        unresolved.append(h)

    return resolved, unresolved, ambiguous


def load_accounts(config_path="holdings/accounts.yaml"):
    """Load holdings from accounts config YAML.

    Returns list of Holding objects from all accounts.
    """
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    full_path = os.path.join(base, config_path)

    if not os.path.exists(full_path):
        print(f"[WARN] accounts config not found: {full_path}")
        return []

    with open(full_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    all_holdings = []
    for acct in config.get("accounts", []):
        name = acct.get("name", "unknown")
        acct_type = acct.get("type", "manual")

        if acct_type == "excel":
            path = acct.get("path", "")
            abs_path = os.path.normpath(os.path.join(os.path.dirname(full_path), path))
            if os.path.exists(abs_path):
                all_holdings.extend(parse_excel_holdings(abs_path, account=name))
            else:
                print(f"[WARN] Excel not found: {abs_path}")

        elif acct_type == "manual":
            raw = acct.get("holdings", [])
            all_holdings.extend(normalize_holdings(raw, account=name, source="manual"))

    return all_holdings
