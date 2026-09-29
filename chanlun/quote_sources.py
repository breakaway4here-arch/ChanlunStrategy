"""Bounded full-A quote fallback; raw prices, hands, CNY, explicit source time.

Inventory completeness and valid quote coverage are deliberately separate.
No login cookies, DB writes, historical price substitution or strategy rules.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .identity import normalize_identity
from .industry_metadata import _is_a_share_identity

CN = timezone(timedelta(hours=8))
LIST_BASE = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.'


def symbol(row):
    identity = normalize_identity(row)
    if identity.asset_type != 'stock' or not _is_a_share_identity(identity.as_dict()):
        raise ValueError('not an A-share identity')
    return identity.exchange.lower() + identity.code


def valid_quote(row, now):
    try:
        symbol(row)
        stamp = datetime.fromisoformat(row['quote_asof'])
        if stamp.utcoffset() is None:
            return False
        stamp = stamp.astimezone(CN)
        if stamp.date() != now.date() or stamp > now + timedelta(seconds=60):
            return False
        if now.hour >= 15:
            if stamp.hour < 15:
                return False
        elif (now - stamp).total_seconds() > 180:
            return False
        if row.get('quote_source') not in ('eastmoney', 'sina', 'tencent'):
            return False
        if row.get('volume_unit') != 'hands' or row.get('amount_unit') != 'CNY':
            return False
        values = [float(row[k]) for k in ('open','high','low','current_price','prev_close','volume','amount')]
        if not all(math.isfinite(v) for v in values) or min(values[:5]) <= 0 or min(values[5:]) <= 0:
            return False
        op, hi, lo, close, prev, vol, amount = values
        average = amount / (vol * 100)
        return hi >= max(op, lo, close) and lo <= min(op, hi, close) and lo * .98 <= average <= hi * 1.02
    except (TypeError, ValueError, KeyError, OverflowError):
        return False


def parse_quotes(text, source, now):
    result = {}
    pattern = r'(?:var\s+hq_str_|v_)((?:sh|sz|bj)\d{6})="([^"\r\n]*)"\s*;'
    duplicates = set()
    for code, body in re.findall(pattern, text):
        try:
            p = body.split(',' if source == 'sina' else '~')
            row = {'asset_type':'stock', 'exchange':code[:2].upper(), 'code':code[2:]}
            if source == 'sina':
                row.update(name=p[0], open=float(p[1]), prev_close=float(p[2]), current_price=float(p[3]),
                           high=float(p[4]), low=float(p[5]), volume=float(p[8])/100, amount=float(p[9]),
                           quote_asof=datetime.fromisoformat(p[30]+'T'+p[31]).replace(tzinfo=CN).isoformat(),
                           volume_raw_unit='shares')
            elif source == 'tencent':
                if p[2] != code[2:]:
                    continue
                # Tencent's STAR quote feed reports shares, unlike main/GEM/BJ hands.
                raw_unit = 'shares' if code.startswith(('sh688', 'sh689')) else 'hands'
                row.update(name=p[1], open=float(p[5]), prev_close=float(p[4]), current_price=float(p[3]),
                           high=float(p[33]), low=float(p[34]), volume=float(p[6])/(100 if raw_unit=='shares' else 1), amount=float(p[35].split('/')[2]),
                           quote_asof=datetime.strptime(p[30], '%Y%m%d%H%M%S').replace(tzinfo=CN).isoformat(),
                           volume_raw_unit=raw_unit)
            else:
                raise ValueError('unknown provider')
            row.update(quote_source=source, volume_unit='hands', amount_unit='CNY',
                       volume_source=source, amount_source=source, amount_available=True,
                       price_basis='raw', fetched_at=now.isoformat(),
                       change_pct=round((row['current_price']/row['prev_close']-1)*100, 4))
            if code in result:
                duplicates.add(code)
            if valid_quote(row, now):
                result[code] = row
        except (IndexError, ValueError, TypeError, ZeroDivisionError, OverflowError):
            continue
    for code in duplicates:
        result.pop(code, None)
    return result


def _get(session, url, params):
    response = session.get(url, params=params, timeout=10,
                           headers={'Referer':'https://finance.sina.com.cn/', 'User-Agent':'Mozilla/5.0'})
    response.raise_for_status()
    return response


def _sina_universe(session, batch_size, deadline):
    count = int(_get(session, LIST_BASE+'getHQNodeStockCount', {'node':'hs_a'}).json())
    if not 1 <= count <= 10000:
        raise ValueError('invalid universe count')
    rows = {}
    for page in range(1, (count+batch_size-1)//batch_size+1):
        if time.monotonic() >= deadline:
            raise ValueError('universe deadline exceeded')
        data = None
        for attempt in range(2):
            try:
                data = _get(session, LIST_BASE+'getHQNodeData',
                            {'node':'hs_a','page':page,'num':batch_size,'sort':'symbol','asc':1}).json()
                if isinstance(data, list) and data:
                    break
            except Exception:
                data = None
            if attempt == 0 and time.monotonic()+2 < deadline:
                time.sleep(2)
        if not isinstance(data, list) or not data:
            raise ValueError('missing universe page')
        for item in data:
            code = str(item.get('symbol') or '')
            row = {'code':str(item.get('code') or ''),'exchange':code[:2].upper(),
                   'asset_type':'stock','name':str(item.get('name') or '')}
            if symbol(row) != code or code in rows:
                raise ValueError('duplicate or inconsistent universe identity')
            row.update(is_st='ST' in row['name'].upper(), delisting_risk='退' in row['name'])
            rows[code] = row
    after = int(_get(session, LIST_BASE+'getHQNodeStockCount', {'node':'hs_a'}).json())
    if len(rows) != count or after != count:
        raise ValueError('universe count changed or pages missing')
    return rows


def _metadata(rows, db_path, day):
    if db_path is None:
        return
    conn = None
    try:
        conn = sqlite3.connect(Path(db_path).resolve().as_uri()+'?mode=ro', uri=True)
        conn.execute('PRAGMA query_only=ON')
        records = conn.execute('''SELECT i.asset_type,i.exchange,i.code,m.as_of,m.metadata_json
            FROM instruments i JOIN stock_meta_asof m ON m.instrument_id=i.instrument_id
            WHERE m.as_of=(SELECT MAX(x.as_of) FROM stock_meta_asof x
                          WHERE x.instrument_id=i.instrument_id AND x.as_of<=?)''', (day,))
        for asset, exchange, code, as_of, raw in records:
            if asset != 'stock':
                continue
            row = rows.get(exchange.lower()+code)
            if row is None:
                continue
            meta = json.loads(raw)
            if not isinstance(meta, dict):
                continue
            for field in ('industry','listed_date'):
                if not row.get(field) and meta.get(field):
                    row[field] = meta[field]
                    row[field+'_as_of'] = as_of
                    row[field+'_source'] = 'market_history.stock_meta_asof'
    except (sqlite3.Error, OSError, ValueError, TypeError):
        pass  # Optional static metadata never substitutes prices.
    finally:
        if conn is not None:
            conn.close()


def fetch_quotes(eastmoney_fetcher, *, session, now=None, cache_dir=None, db_path=None, batch_size=80):
    now = now or datetime.now(CN)
    now = now.replace(tzinfo=CN) if now.tzinfo is None else now.astimezone(CN)
    batch_size = min(80, max(1, int(batch_size)))
    deadline = time.monotonic()+180
    inventory, valid, attempts = {}, {}, []
    universe_source = ''
    cache_path = Path(cache_dir)/('quotes-'+now.date().isoformat()+'.json') if cache_dir else None
    if cache_path and cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text())
            collected = datetime.fromisoformat(cache['fetched_at'])
            fresh = (collected.date()==now.date() and collected<=now and
                     (0 <= (now-collected).total_seconds() <= 180 or collected.hour>=15))
            cached = cache['rows']
            if cache.get('schema_version') != 1 or cache.get('universe_source') not in ('eastmoney','sina_hs_a'):
                fresh = False
            inventory = {symbol(row):dict(row) for row in cached} if fresh else {}
            if len(inventory) != cache['requested']:
                inventory = {}
            universe_source = cache['universe_source'] if inventory else ''
        except (ValueError, KeyError, TypeError, OSError):
            inventory = {}
    if not inventory:
        try:
            primary, info = eastmoney_fetcher(return_diagnostics=True)
        except Exception as exc:
            primary, info = [], {'error':type(exc).__name__}
        primary = primary if isinstance(primary, list) else []
        info = info if isinstance(info, dict) else {}
        primary_rows = {}
        try:
            primary_rows = {symbol(row):dict(row) for row in primary}
            primary_complete = bool(info.get('complete') and len(primary_rows)==len(primary)==info.get('requested')==info.get('unique') and primary)
        except (ValueError, TypeError):
            primary_complete = False
        attempts.append({'source':'eastmoney','complete':primary_complete,'received':len(primary_rows)})
        if primary_complete:
            inventory, universe_source = primary_rows, 'eastmoney'
        else:
            try:
                inventory, universe_source = _sina_universe(session,batch_size,deadline), 'sina_hs_a'
                # Keep successful EM prices only for identities in the verified alternate universe.
                for code,row in primary_rows.items():
                    if code in inventory:
                        inventory[code].update(row)
            except Exception as exc:
                return list(primary_rows.values()), {'complete':False,'requested':info.get('requested'),
                    'unique':len(primary_rows),'error':'alternate_universe_'+type(exc).__name__,
                    'reason': str(exc)[:160] if isinstance(exc, ValueError) else 'request_failed', 'attempts':attempts}
    for code,row in inventory.items():
        if valid_quote(row,now):
            valid[code] = dict(row)
    for provider in ('sina','tencent'):
        pending = sorted(set(inventory)-set(valid))
        consecutive_empty = 0
        for offset in range(0,len(pending),batch_size):
            if time.monotonic() >= deadline:
                break
            batch = pending[offset:offset+batch_size]
            url = ('https://hq.sinajs.cn/list=' if provider=='sina' else 'https://qt.gtimg.cn/q=') + ','.join(batch)
            try:
                parsed = parse_quotes(_get(session,url,{}).text,provider,now)
                accepted = {code:row for code,row in parsed.items() if code in batch}
                valid.update(accepted)
                consecutive_empty = 0 if accepted else consecutive_empty+1
                attempts.append({'source':provider,'requested':len(batch),'valid':len(accepted)})
            except Exception as exc:
                consecutive_empty += 1
                attempts.append({'source':provider,'requested':len(batch),'valid':0,'error':type(exc).__name__})
            if consecutive_empty >= 2:
                # Do not let a dead provider consume the entire shared time budget.
                break
    price_fields = ('current_price','change_pct','open','high','low','prev_close','volume','amount')
    for code,row in inventory.items():
        if code in valid:
            row.update(valid[code])
            row['quote_status']='valid'
        else:
            for field in price_fields:
                row[field]=None
            row['quote_status']='unavailable'
    _metadata(inventory,db_path,now.date().isoformat())
    rows = [inventory[code] for code in sorted(inventory)]
    diagnostic = {'complete':True,'requested':len(rows),'unique':len(rows),'fetched':len(rows),
                  'universe_source':universe_source, 'valid_quotes':len(valid),
                  'missing_quote_symbols':sorted(set(inventory)-set(valid)),
                  'quote_sources':dict(Counter(row['quote_source'] for row in valid.values())),
                  'fetched_at':now.isoformat(),'attempts':attempts}
    if cache_path:
        tmp = None
        try:
            cache_path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=cache_path.parent,delete=False) as h:
                tmp=Path(h.name)
                json.dump({'schema_version':1,'rows':rows,'requested':len(rows),'universe_source':universe_source,'fetched_at':now.isoformat()},h,ensure_ascii=False)
            os.replace(tmp,cache_path)
        except OSError:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    return rows, diagnostic
