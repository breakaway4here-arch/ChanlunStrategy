"""Optional KPL context and last-resort daily bars; never a publication gate."""
import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

from .identity import normalize_identity

CN = timezone(timedelta(hours=8))
_lock = threading.Lock()
_last_request = 0.0
_cooldown_until = 0.0
_anonymous_device_id = str(uuid.uuid4())


def _cache_root():
    from config import MARKET_HISTORY_DB_PATH
    return Path(MARKET_HISTORY_DB_PATH).parent / 'kaipanla'


def _request(url, data, *, cache_dir=None, now=None):
    """One anonymous request, short timeout, cached successes and failed attempts."""
    global _last_request, _cooldown_until
    now = now or datetime.now(CN)
    root = Path(cache_dir) if cache_dir is not None else _cache_root()
    key = hashlib.sha256(json.dumps(['kpl-v1',url,data],sort_keys=True).encode()).hexdigest()
    path = root / (key+'.json')
    with _lock:
        try:
            saved = json.loads(path.read_text())
            stamp = datetime.fromisoformat(saved['fetched_at'])
            age = (now-stamp).total_seconds()
            if (stamp.date()==now.date() and 0<=age<900
                    and (stamp.hour>=15)==(now.hour>=15)):
                return saved.get('payload')
        except (OSError, ValueError, TypeError, KeyError):
            pass
        if time.monotonic() < _cooldown_until:
            return None
        delay = .5-(time.monotonic()-_last_request)
        if delay>0:
            time.sleep(delay)
        payload = None
        try:
            with requests.Session() as session:
                session.trust_env=False
                body=dict(data)
                headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.kaipanla.com/'}
                if url.startswith('https://apphwhq.longhuvip.com/'):
                    body['DeviceID']=_anonymous_device_id
                    headers={'User-Agent':'Dalvik/2.1.0 (Linux; U; Android 9)',
                             'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'}
                response=session.post(url,data=body,timeout=(2,4),headers=headers)
                response.raise_for_status()
                raw=response.json()
                shape_ok=isinstance(raw,dict)
                if shape_ok and data.get('a')=='GetKLineDay':
                    shape_ok=str(raw.get('StockID'))==str(data.get('StockID')) and isinstance(raw.get('x'),list) and bool(raw['x'])
                if shape_ok and data.get('a')=='GetPlateInfo_w38':
                    shape_ok=bool(raw.get('date')) and isinstance(raw.get('list'),list)
                if shape_ok and str(raw.get('errcode'))=='0':
                    payload=raw
                    payload['_fetched_at']=now.isoformat()
                else:
                    _cooldown_until=time.monotonic()+60
        except (requests.RequestException, ValueError):
            _cooldown_until=time.monotonic()+60
        finally:
            _last_request=time.monotonic()
        tmp=None
        try:
            root.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=root,delete=False) as handle:
                tmp=Path(handle.name)
                json.dump({'fetched_at':now.isoformat(),'payload':payload},handle,ensure_ascii=False)
            os.replace(tmp,path)
        except OSError:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        return payload


def parse_themes(raw, report_date):
    empty={'status':'unavailable','source':'kaipanla','affects_formal':False,'groups':[]}
    try:
        if not isinstance(raw,dict) or str(raw.get('errcode'))!='0':
            return empty
        actual=datetime.strptime(str(raw.get('date','')),'%Y-%m-%d').date()
        target=datetime.strptime(report_date,'%Y-%m-%d').date()
        if actual>target:
            return empty
        groups=[]
        for group in raw.get('list') or []:
            if not isinstance(group,dict):
                continue
            stocks=[]
            for item in group.get('StockList') or []:
                if not isinstance(item,list) or len(item)<18:
                    continue
                try:
                    identity=normalize_identity(str(item[0]),asset_type='stock')
                except ValueError:
                    continue
                stocks.append({'code':identity.code,'name':str(item[1]),'reason':str(item[17] or '')[:2000]})
            if stocks:
                groups.append({'code':str(group.get('ZSCode') or ''),
                               'name':str(group.get('ZSName') or ''),'stocks':stocks})
        return dict(empty,status=('available' if actual==target else 'previous_day') if groups else 'unavailable',
                    data_date=actual.isoformat(),report_date=report_date,groups=groups,
                    coverage='returned_sample',fetched_at=raw.get('_fetched_at'))
    except (TypeError,ValueError):
        return empty


def fetch_themes(report_date, *, cache_dir=None):
    try:
        raw=_request('https://apphwhq.longhuvip.com/w1/api/index.php',{
            'c':'DailyLimitResumption','a':'GetPlateInfo_w38','st':'100','Index':'0',
            'Day':str(report_date),'apiv':'w42','PhoneOSNew':'1','VerSion':'5.21.0.2'},cache_dir=cache_dir)
        return parse_themes(raw,report_date)
    except Exception:
        # Optional context cannot stop the report, including local cache errors.
        return {'status':'unavailable','source':'kaipanla','affects_formal':False,'groups':[]}


def parse_daily(raw, identity, *, now=None):
    now=now or datetime.now(CN)
    try:
        identity=normalize_identity(identity)
        if identity.asset_type!='stock' or not isinstance(raw,dict) or str(raw.get('errcode'))!='0' or str(raw.get('StockID'))!=identity.code:
            return None
        dates,y,vol,amount=(raw.get(k) for k in ('x','y','vol','bal'))
        if not all(isinstance(v,list) for v in (dates,y,vol,amount)) or not dates or len({len(v) for v in (dates,y,vol,amount)})!=1:
            return None
        result={k:[] for k in ('dates','opens','closes','highs','lows','volumes','amounts')}
        previous=None
        try:
            source_time=datetime.fromtimestamp(float(raw.get('Time')),CN)
        except (TypeError,ValueError,OverflowError,OSError):
            source_time=None
        for d,ohlc,v,a in zip(dates,y,vol,amount):
            day=datetime.strptime(str(d),'%Y%m%d').date()
            if previous is not None and day<=previous:
                return None
            previous=day
            if day>now.date() or (day==now.date() and (now.hour<15 or source_time is None
                    or source_time.date()!=day or source_time.hour<15)):
                continue
            if not isinstance(ohlc,list) or len(ohlc)!=4:
                return None
            op,cl,hi,lo=map(float,ohlc);v=float(v);a=float(a)
            if not all(np.isfinite(x) for x in (op,cl,hi,lo,v,a)) or min(op,cl,hi,lo)<=0 or min(v,a)<0 or hi<max(op,cl,lo) or lo>min(op,cl,hi):
                return None
            for key,value in zip(result,(day.isoformat(),op,cl,hi,lo,v,a)):
                result[key].append(value)
        if not result['dates']:
            return None
        for key in result:
            if key!='dates':result[key]=np.asarray(result[key],dtype=float)
        result.update(source='kaipanla',adjustment='qfq',volume_unit='hands',volume_raw_unit='hands',
                      volume_source='kaipanla',amount_unit='CNY',amount_source='kaipanla',
                      amount_available=result['amounts']>0, fetched_at=raw.get('_fetched_at'),
                      data_time=source_time.isoformat() if source_time else None)
        return result
    except (TypeError,ValueError,KeyError,OverflowError):
        return None


def fetch_daily(identity, count, *, now=None, cache_dir=None):
    try:
        identity=normalize_identity(identity)
        if identity.asset_type!='stock':
            return None
        raw=_request('https://pchis.kaipanla.com/w1/api/index.php',{
            'c':'StockLineData','a':'GetKLineDay','StockID':identity.code,'Index':'0','st':str(count)},
            cache_dir=cache_dir,now=now)
        parsed=parse_daily(raw,identity,now=now)
        if parsed is not None:
            for key in ('dates','opens','highs','lows','closes','volumes','amounts','amount_available'):
                parsed[key]=parsed[key][-count:]
        return parsed
    except Exception:
        return None
