"""Read-only, deterministic presentation of independent strategy decisions.

No strategy result, rank, price, or market fact is recomputed here. A stock
is a display entity; each strategy retains its own evidence and contract.
"""
import copy
import hashlib
import json
import math
import re
from datetime import date


WORKBENCH_SCHEMA_VERSION = 'decision-workbench-v1'
VIEW_ORDER = ('main', 'h4_t3', 'confirming', 'observation_top5', 'acceleration',
              'luojie', 'growth_quality', 'highlights', 'baseline')
FORMAL_VIEWS = frozenset(('main', 'h4_t3'))
READY_ACTIONS = frozenset(('可上车', '推荐'))
STATUS_LABELS = {
    'evidence_blocked': '暂无法判断', 'invalidated': '已失效',
    'strategy_disagreement': '策略意见不一致', 'formal_ready': '正式推荐·条件完整',
    'formal_incomplete': '正式推荐·条件待补充', 'waiting_trigger': '等待条件确认',
    'watch_only': '研究观察',
}
STATUS_ORDER = {k: i for i, k in enumerate((
    'invalidated', 'formal_ready', 'formal_incomplete', 'waiting_trigger',
    'strategy_disagreement', 'evidence_blocked', 'watch_only'))}


def _map(x):
    return x if isinstance(x, dict) else {}


def _seq(x):
    return list(x) if isinstance(x, (list, tuple)) else []


def _text(x):
    return '' if x is None else str(x).strip()


def _number(x):
    if isinstance(x, bool):
        return None
    try:
        n = float(x)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _day(x):
    s = _text(x)[:10]
    try:
        return s if date.fromisoformat(s).isoformat() == s else ''
    except ValueError:
        return ''


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    return str(x)


def _hash(x):
    return hashlib.sha256(json.dumps(_clean(x), ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _instrument(code):
    s = _text(code).upper()
    match = re.fullmatch(r'(?:(SH|SZ|BJ))?(\d{1,6})(?:\.(SH|SZ|BJ))?', s)
    if not match:
        return '', ''
    prefix, digits, suffix = match.groups()
    if prefix and suffix and prefix != suffix:
        return '', ''
    digits = digits.zfill(6)
    market = prefix or suffix or ('SH' if digits[0] in '569' else 'BJ' if digits[0] in '48' else 'SZ')
    return digits, market + digits


def _lines(*values):
    out = []
    for value in values:
        if isinstance(value, dict):
            value = value.get('items')
        for v in _seq(value):
            text = _text(v.get('text') or v.get('label')) if isinstance(v, dict) else _text(v)
            if text and text not in out:
                out.append(text)
    return out


def _evidence(evidence, view, instrument, report_date):
    if _day(evidence.get('report_date')) != report_date:
        return {}
    for row in _seq(_map(evidence.get('views')).get(view)):
        if _instrument(_map(row).get('code'))[1] == instrument:
            return _map(row)
    return {}


def _health(report, phase, report_date):
    quality = _map(report.get('data_quality'))
    formal = _map(_map(report.get('selection_input_health')).get('formal'))
    allowed = formal.get('formal_actions_allowed') is True and formal.get('status', 'verified') == 'verified'
    blockers = []
    if phase == 'formal' and not allowed:
        blockers.append('formal动作策略暂未授权')
    fact_blockers = []
    if not report_date or _day(quality.get('as_of') or report.get('as_of')) != report_date:
        fact_blockers.append('报告事实时间缺失或不属于本交易日')
    if quality.get('market_status') != 'verified':
        fact_blockers.append('报告行情尚未核验')
    if phase == 'formal' and (quality.get('is_official') is not True or quality.get('bar_state') != 'closed'):
        fact_blockers.append('本期不是已核验的正式收盘结果')
    return {'status': 'verified' if not fact_blockers else 'unavailable',
            'formal_actions_allowed': allowed, 'blocking_reasons': blockers,
            'fact_blocking_reasons': fact_blockers,
            'blocked_strategies': _seq(formal.get('blocked_strategies'))}


def _strategy(row, view, meta, evidence, report_date, phase, health, index):
    code, instrument = _instrument(row.get('code'))
    semantics = row.get('action_semantics') or meta.get('action_semantics') or (
        'formal' if view in FORMAL_VIEWS else 'upstream_only' if view == 'baseline' else 'watch_only')
    formal = view in FORMAL_VIEWS and semantics == 'formal'
    contract = copy.deepcopy(_map(row.get('formal_decision_contract'))) if formal else {}
    ev = _evidence(evidence, view, instrument, report_date)
    blockers = list(health['fact_blocking_reasons'])
    if formal:
        blockers += health['blocking_reasons']
        strategy_name = {'main': 'daily_fusion', 'h4_t3': 'h4_t3'}[view]
        if strategy_name in health['blocked_strategies']:
            blockers.append('本策略输入尚未通过核验')
        if _map(meta.get('availability')).get('state') in ('unavailable', 'disabled', 'partial'):
            blockers.append('本策略结果当前不可用')
        if any(value in ('conflict', 'invalid') for value in _map(row.get('formal_decision_contract_diagnostics')).values()):
            blockers.append('正式策略合同存在冲突或无效声明')
    ds = _map(row.get('data_status'))
    if ds.get('stale') is True or (ds.get('latest_date') and _day(ds['latest_date']) != report_date):
        blockers.append('个股行情已过期')
    if phase == 'formal' and ds.get('is_final') is False:
        blockers.append('个股行情尚未收盘确认')
    if row.get('incident_review_only'):
        blockers.append('策略输入异常，仅供追溯')
    for key in ('summary', 'daily_structure') + (('price_evidence',) if formal else ()):
        section = _map(ev.get(key))
        status = section.get('status')
        if status not in ('available', 'partial'):
            blockers.append(key + '：' + {'conflict': '证据冲突', 'stale': '证据过期'}.get(status, '证据不足'))
        if section.get('as_of') and _day(section['as_of']) != report_date:
            blockers.append(key + '：证据日期不一致')
        if section.get('stale') is True or (phase == 'formal' and section.get('is_final') is False):
            blockers.append(key + '：非当日终局证据')
    # Confirmation is necessary only where the strategy actually requires it.
    requires_30m = formal and (view == 'main' or contract.get('requires_30m') is True)
    sublevel = _map(ev.get('sublevel_30m'))
    if requires_30m and sublevel.get('status') != 'available':
        if not (sublevel.get('status') == 'not_applicable' and contract.get('requires_30m') is False):
            blockers.append('30分钟确认依据不足')
    if sublevel.get('status') == 'available' and sublevel.get('as_of') and _day(sublevel['as_of']) != report_date:
        blockers.append('30分钟确认日期不一致')
    missing = []
    if formal:
        required = ['reference_price', 'invalidation_price'] + _lines(contract.get('required_fields'))
        for field in dict.fromkeys(required):
            n = _number(contract.get(field))
            if field.endswith('_price') and (n is None or n <= 0):
                missing.append('missing_' + field)
            elif not field.endswith('_price') and not _text(contract.get(field)):
                missing.append('missing_' + field)
        if not contract.get('action'):
            missing.append('missing_formal_action')
    risk = _map(ev.get('risk_and_next'))
    next_steps = _lines(risk.get('next_confirmation'), risk.get('confirmation_triggers'),
                        row.get('next_confirmation'), row.get('confirmation_triggers'))
    invalidation = _lines(risk.get('cancel_conditions'), risk.get('invalidation_conditions'),
                         row.get('cancel_conditions'), row.get('invalidation_conditions'))
    watch_price = _number(row.get('watch_reference_price'))
    action = _text(contract.get('action')) if formal else None
    structural_reason = _text(_map(ev.get('daily_structure')).get('summary') or row.get('structural_reason'))
    watch_reason = _text(row.get('watch_reason') or row.get('primary_reason') or row.get('page_action_reason'))
    reason = _text(contract.get('action_reason')) if formal else watch_reason
    if blockers:
        state = 'evidence_blocked'
    elif row.get('invalidated') is True or risk.get('invalidated') is True:
        state = 'invalidated'
    elif formal and action in READY_ACTIONS:
        state = 'formal_incomplete' if missing else 'formal_ready'
    elif next_steps and invalidation and watch_price is not None and watch_price > 0:
        state = 'waiting_trigger'
    else:
        state = 'watch_only'
    score = _number(_map(row.get('decision_engine_v1')).get('total_score')) if formal else None
    if score is not None and not 0 <= score <= 100:
        score = None
    return {'strategy_id': view, 'role': 'formal' if formal else 'research',
            'action_semantics': semantics, 'view_rank': row.get('view_rank', index + 1),
            'formal_action': action, 'contract': contract, 'score': score,
            'page_status': state, 'blocking_reasons': list(dict.fromkeys(blockers)),
            'missing_fields': missing, 'primary_reason': reason or '本期尚无完整关注理由',
            'structural_reason': structural_reason, 'watch_reason': watch_reason,
            'next_confirmation': next_steps, 'invalidation': invalidation, 'watch_reference_price': watch_price,
            'evidence': copy.deepcopy(ev), 'candidate': copy.deepcopy(row)}


def _merge(strategies, report_date, phase, snapshot_id):
    formal = [s for s in strategies if s['role'] == 'formal']
    selected = (formal or strategies)[0]
    actions = list(dict.fromkeys(s['formal_action'] for s in formal if s['formal_action']))
    blockers = list(dict.fromkeys(b for s in (formal or [selected]) for b in s['blocking_reasons']))
    disagreement = len(actions) > 1
    state = selected['page_status']
    if blockers:
        state = 'evidence_blocked'
    elif disagreement:
        state = 'strategy_disagreement'
    elif formal and any(s['page_status'] == 'formal_incomplete' for s in formal):
        state = 'formal_incomplete'
    row = selected['candidate']; code, instrument = _instrument(row.get('code'))
    score_values = set(s['score'] for s in formal)
    score = next(iter(score_values)) if len(score_values) == 1 else None
    action = actions[0] if len(actions) == 1 else None
    conditions = selected['contract']
    missing = list(dict.fromkeys(b for s in formal for b in s['missing_fields']))
    result = {'id': ':'.join((report_date, phase, snapshot_id, instrument)),
              'code': code, 'instrument_id': instrument, 'name': _text(row.get('name')) or code,
              'sector': row.get('sector', ''), 'page_status': state,
              'status_label': STATUS_LABELS[state], 'formal_action': action,
              'action': action or STATUS_LABELS[state], 'score': score,
              'is_executable': state == 'formal_ready',
              'execution_status': 'ready' if state == 'formal_ready' else 'blocked' if blockers or disagreement else 'waiting',
              'action_reason': selected['primary_reason'], 'primary_reason': selected['primary_reason'],
              'structural_reason': selected['structural_reason'], 'watch_reason': selected['watch_reason'],
              'next_confirmation': selected['next_confirmation'], 'invalidation': selected['invalidation'],
              'evidence_status': 'unavailable' if blockers else 'available',
              'blocking_reasons': [_blocker_label(b) for b in blockers + (['strategy_conflict'] if disagreement else []) + missing],
              'blocked_reasons': blockers + (['strategy_conflict'] if disagreement else []) + missing,
              'sources': [s['strategy_id'] for s in strategies],
              'source_refs': [{'view': s['strategy_id'], 'ref': s['candidate'].get('ref', {})} for s in strategies],
              'strategy_results': strategies, 'strategy_actions': [{'source': s['strategy_id'], 'action': s['formal_action'] or '仅观察'} for s in strategies],
              'strategy_contracts': [{'source': s['strategy_id'], 'contract': s['contract']} for s in formal],
              'contracts': conditions, 'reference_price': _number(conditions.get('reference_price')) if formal else None,
              'risk_flags': _lines(*(s['candidate'].get('risk_flags') for s in strategies)),
              'candidate': row, 'evidence_view': selected['strategy_id'],
              'chart_ref': copy.deepcopy(row.get('ref', {})),
              'summary_explanation': selected['primary_reason']}
    result['watch_reference_price'] = selected.get('watch_reference_price')
    if disagreement:
        result['strategy_conflicts'] = [{'source': s['strategy_id'], 'action': s['formal_action']} for s in formal]
    return result


def _blocker_label(value):
    labels = {'missing_reference_price': '缺少有效参考价', 'missing_invalidation_price': '缺少有效失效位',
              'missing_formal_action': '正式动作尚未提供', 'strategy_conflict': '正式策略意见不一致',
              'formal动作策略暂未授权': '策略输入尚未核验，正式动作已封闭'}
    return labels.get(value, value.replace('summary：', '结构摘要：').replace('daily_structure：', '日线结构：').replace('price_evidence：', '价格依据：'))


def _summary(report, workspace, items, health):
    views = _map(workspace.get('views')); meta = _map(workspace.get('view_meta'))
    states = {}
    for view in ('main', 'h4_t3'):
        count = len(_seq(views.get(view)))
        availability = _map(_map(meta.get(view)).get('availability'))
        state = availability.get('state') or ('available' if count else 'unavailable')
        states[view] = {'count': count, 'state': state, 'reason': availability.get('reason', '')}
    if any(s['count'] for s in states.values()):
        title = '正式主推 {} 只，H4 独立策略 {} 只'.format(states['main']['count'], states['h4_t3']['count'])
    elif all(s['state'] == 'verified_empty' for s in states.values()):
        title = '本期暂无正式推荐'
    else:
        title = '本期暂无正式推荐，部分策略状态待核验'
    unavailable = [{'main': '正式主推', 'h4_t3': 'H4'}[key] for key, value in states.items()
                   if value['state'] not in ('available', 'verified_empty')]
    if unavailable and any(value['count'] for value in states.values()):
        title += '；' + '、'.join(unavailable) + '状态待核验'
    if health['fact_blocking_reasons'] or health['blocking_reasons']:
        title = '本期执行判断已封闭，需先核验数据。' + title
    diagnostic = _map(_map(report.get('diagnostics')).get('fusion_admission'))
    before, after = diagnostic.get('input_count'), diagnostic.get('output_count')
    reason = '筛选原因未完整记录'
    if (isinstance(before, int) and not isinstance(before, bool) and isinstance(after, int)
            and not isinstance(after, bool) and 0 <= after <= before
            and len(_seq(report.get('picks_pure'))) == before
            and len(_seq(report.get('picks_fusion'))) == after):
        reason = '{} 只基础候选经融合筛选剩 {} 只，正式主推 {} 只。'.format(before, after, states['main']['count'])
        if diagnostic.get('dropped_by_ma'):
            reason += '其中 {} 只未通过均线条件。'.format(diagnostic['dropped_by_ma'])
    return dict(states, title=title, reason=reason, total_items=len(items),
                executable_items=sum(x['is_executable'] for x in items),
                blocked_by_price=sum(any(b.startswith('missing_') for b in x['blocked_reasons']) for x in items),
                health_blocking_reasons=health['blocking_reasons'] + health['fact_blocking_reasons'])


def _comparison(report, strategies):
    versions = {s['strategy_id']: _text(_map(s['candidate'].get('decision_engine_v1')).get('version')) for s in strategies if s['role'] == 'formal'}
    return {'price_basis': report.get('price_basis') or _map(report.get('data_quality')).get('price_basis'),
            'strategy_version': report.get('strategy_version') or (versions if versions and all(versions.values()) else None)}


def _changes(current, previous):
    previous = _map(previous)
    unavailable = {'status': 'comparison_unavailable'}
    if not previous:
        return unavailable
    if current['phase'] != previous.get('phase') or current['report_date'] < _text(previous.get('report_date')):
        return dict(unavailable, reason='phase_or_date_mismatch')
    contract = current['comparison_contract']
    if not all(contract.values()) or contract != previous.get('comparison_contract'):
        return dict(unavailable, reason='comparison_contract_unavailable_or_changed')
    if any(_map(p.get('health')).get('status') != 'verified' for p in (current, previous)):
        return dict(unavailable, reason='comparison_health_unavailable')
    before = {x['instrument_id']: x for x in _seq(previous.get('items')) if x.get('instrument_id')}
    after = {x['instrument_id']: x for x in current['items']}
    if any(x.get('page_status') == 'evidence_blocked' for x in list(before.values()) + list(after.values())):
        return dict(unavailable, reason='candidate_evidence_unavailable')
    def semantic(x):
        return (x.get('formal_action'), x.get('page_status'), x.get('next_confirmation'), x.get('invalidation'))
    return {'status': 'available', 'previous_report_date': previous.get('report_date'),
            'previous_phase': previous.get('phase'),
            'added': [after[k]['code'] for k in sorted(after.keys() - before.keys())],
            'removed': [before[k]['code'] for k in sorted(before.keys() - after.keys())],
            'changed': [after[k]['code'] for k in sorted(after.keys() & before.keys()) if semantic(after[k]) != semantic(before[k])]}


def build_decision_workbench(report, workspace, evidence, *, phase='formal', snapshot_id='', previous=None):
    report, workspace, evidence = _map(report), _map(workspace), _map(evidence)
    report_date = _day(report.get('date') or report.get('trade_date'))
    as_of = _text(_map(report.get('data_quality')).get('as_of') or report.get('as_of'))
    snapshot_id = _text(snapshot_id) or '{}:{}:{}'.format(phase, report_date, _hash({'workspace': workspace, 'as_of': as_of})[:16])
    health = _health(report, phase, report_date)
    grouped, strategies = {}, []
    views = _map(workspace.get('views')); meta = _map(workspace.get('view_meta'))
    order = list(VIEW_ORDER) + sorted(set(views) - set(VIEW_ORDER))
    for view in order:
        for index, row in enumerate(_seq(views.get(view))):
            row = _map(row); _, instrument = _instrument(row.get('code'))
            if not instrument:
                continue
            strategy = _strategy(row, view, _map(meta.get(view)), evidence, report_date, phase, health, index)
            strategies.append(strategy); grouped.setdefault(instrument, []).append(strategy)
    items = [_merge(s, report_date, phase, snapshot_id) for s in grouped.values()]
    def priority(item):
        strategy = item['strategy_results'][0]
        rank = _number(strategy['view_rank']) or 1
        lane = 1 if strategy['strategy_id'] == 'h4_t3' else 0
        return (STATUS_ORDER[item['page_status']], rank * 2 + lane, item['instrument_id'])
    items.sort(key=priority)
    result = {'schema_version': WORKBENCH_SCHEMA_VERSION, 'report_date': report_date,
              'phase': phase, 'snapshot_id': snapshot_id, 'as_of': as_of, 'health': health,
              'summary': _summary(report, workspace, items, health), 'items': items,
              'featured_ids': [x['id'] for x in items if x['page_status'] in ('formal_ready', 'formal_incomplete', 'waiting_trigger')][:5],
              'comparison_contract': _comparison(report, strategies)}
    result['changes'] = _changes(result, previous)
    result['payload_hash'] = _hash({'summary': result['summary'], 'items': [
        {k: x[k] for k in ('instrument_id', 'formal_action', 'page_status', 'contracts', 'next_confirmation', 'invalidation')} for x in items]})
    return _clean(result)


def notification_semantics(projection):
    """Business facts only: explanation copy and snapshot IDs are not events."""
    p = _map(projection)
    def contract_facts(value):
        contract = _map(_map(value).get('contract'))
        return {'source': value.get('source'), 'action': contract.get('action'),
                'conditions': {key: contract.get(key) for key in (
                    'reference_price', 'invalidation_price', 'intended_horizon', 'position_band',
                    'pressure_price', 'target_price', 'requires_30m', 'required_fields')}}
    return {'date': p.get('report_date'), 'phase': p.get('phase'),
            'items': [{'code': x.get('instrument_id') or x.get('code'),
                       'action': x.get('formal_action'), 'status': x.get('page_status'),
                       'next': x.get('next_confirmation'), 'invalidation': x.get('invalidation'),
                       'watch_reference_price': x.get('watch_reference_price'),
                       'strategies': sorted((contract_facts(c) for c in _seq(x.get('strategy_contracts'))),
                                            key=lambda c: _text(c['source'])),
                       'prices': {k: _map(x.get('contracts')).get(k) for k in ('reference_price', 'invalidation_price')}}
                      for x in sorted(_seq(p.get('items')), key=lambda x: _text(x.get('instrument_id') or x.get('code')))]}


def build_preclose_workbench(snapshot):
    """Adapt only the existing three-field advisory, without inventing actions."""
    source = _map(snapshot); items = {}; labels = {'main': '主推预跑', 'h4_t3': 'H4预跑', 'acceleration': '加速观察'}
    for view, label in labels.items():
        for row in _seq(_map(source.get('pools')).get(view)):
            row = _map(row); code, identity = _instrument(row.get('code')); price = _number(row.get('reference_price'))
            if not code or price is None or price <= 0 or not row.get('name'):
                continue
            item = items.setdefault(identity, {'id': identity, 'code': code, 'name': row['name'],
                'page_status': 'watch_only', 'status_label': '盘中观察', 'formal_action': None,
                'primary_reason': '', 'next_confirmation': [], 'invalidation': [], 'references': []})
            item['references'].append('{}参考{:.2f}'.format(label, price))
    rows = list(items.values()) if source.get('status') == 'available' else []
    return {'schema_version': WORKBENCH_SCHEMA_VERSION, 'phase': 'preclose',
            'report_date': _day(source.get('trade_date')), 'items': rows,
            'featured_ids': [row['id'] for row in rows[:3]],
            'summary': {'title': '盘中候选 {} 只，本消息最多展示 3 只'.format(len(rows)),
                        'reason': '预跑快照只含参考价，尚不能凭此形成完整执行条件。'}}


def format_decision_notification(projection, *, heading='盘后复核'):
    """The text channel renders the same facts as the workbench."""
    p = _map(projection); summary = _map(p.get('summary'))
    lines = ['【{} · {}】'.format(heading, p.get('report_date', '')), _text(summary.get('title')),
             _text(summary.get('reason'))]
    selected = set(_seq(p.get('featured_ids')))
    rows = [x for x in _seq(p.get('items')) if x.get('id') in selected]
    for row in rows[:3]:
        lines.append('{} {}｜{}'.format(row['name'], row['code'], row.get('status_label', '观察')))
        if p.get('phase') == 'preclose':
            lines.append('；'.join(row.get('references', [])))
            continue
        lines.append(_text(row.get('primary_reason')))
        for result in _seq(row.get('strategy_contracts')):
            contract = _map(result.get('contract'))
            def price(key):
                value = _number(contract.get(key))
                return '{:.2f}'.format(value) if value is not None and value > 0 else '待补充'
            label = {'main': '主推', 'h4_t3': 'H4'}.get(result.get('source'), '正式策略')
            lines.append('{}：{} · 参考{} · 失效{}'.format(label, contract.get('action') or '待核验',
                                                      price('reference_price'), price('invalidation_price')))
        if row.get('blocking_reasons'):
            lines.append('当前限制：' + '；'.join(row['blocking_reasons'][:3]))
        lines.append('下一确认：' + '；'.join(_seq(row.get('next_confirmation'))) if row.get('next_confirmation') else '下一确认：具体条件待补充')
        lines.append('失效：' + '；'.join(_seq(row.get('invalidation'))) if row.get('invalidation') else '失效：具体条件待补充')
    if not rows and _seq(p.get('items')):
        lines.append('观察对象的确认条件仍待补充，完整清单见网页。')
    if p.get('phase') == 'preclose':
        lines.append('14:56:30前有效；14:57后不再下单')
        lines.append('详情：https://breakaway4here-arch.github.io/ChanlunStrategy/')
        return '\n'.join(x for x in lines if x)
    lines.append('盘后快照供后续核验，交易前需重新确认有效性。')
    if _day(p.get('report_date')):
        lines.append('详情：https://breakaway4here-arch.github.io/ChanlunStrategy/{}/'.format(p['report_date']))
    return '\n'.join(x for x in lines if x)
