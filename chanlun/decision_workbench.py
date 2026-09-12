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


def _validated_price_basis(value):
    """Accept only a source-shaped, finite price-basis mapping."""
    raw = _map(value)
    if "by_instrument" in raw:
        entries = raw.get("by_instrument")
        if not isinstance(entries, dict) or not entries:
            return None
        normalized = {}
        for code, entry in entries.items():
            code = _text(code)
            basis = _validated_price_basis(entry)
            if not code or basis is None or "by_instrument" in basis:
                return None
            normalized[code] = basis
        result = copy.deepcopy(raw)
        result["scope"] = "per_instrument"
        result["by_instrument"] = normalized
        for field_name in ("missing_codes", "invalid_codes", "conflict_codes"):
            if field_name in result:
                raw_codes = result[field_name]
                if not isinstance(raw_codes, (list, tuple, set, frozenset)):
                    return None
                result[field_name] = sorted({
                    _text(code) for code in raw_codes if _text(code)
                })
        return result
    adjustment = _text(raw.get('adjustment')).lower()
    factor = _number(raw.get('factor_vs_raw'))
    if adjustment not in ('raw', 'qfq', 'hfq') or factor is None or factor <= 0:
        return None
    raw_price = raw.get('raw_current_price')
    adjusted_price = raw.get('adjusted_current_price')
    if raw_price is not None or adjusted_price is not None:
        raw_price = _number(raw_price)
        adjusted_price = _number(adjusted_price)
        if raw_price is None or adjusted_price is None or raw_price <= 0 or adjusted_price <= 0:
            return None
        expected = adjusted_price / raw_price
        if not math.isfinite(expected) or abs(expected - factor) > max(1e-9, abs(factor) * 1e-6):
            return None
    return copy.deepcopy(raw)


def _price_basis_signature(value):
    basis = _validated_price_basis(value)
    if basis is None or 'by_instrument' in basis:
        return None
    return (
        _text(basis.get('adjustment')).lower(),
        round(float(basis.get('factor_vs_raw')), 12),
    )


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
    market = prefix or suffix
    if not market:
        # Beijing exchange codes include the six-digit 92xxxx range.  Check
        # that prefix before the generic 9/5/6 Shanghai fallback so a bare
        # 920001 remains the same instrument as an explicit BJ920001.
        market = (
            'BJ' if digits.startswith('92')
            else 'SH' if digits[0] in '569'
            else 'BJ' if digits[0] in '48'
            else 'SZ'
        )
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


def _watch_anchor(value, report_date, candidate_basis=None):
    """Validate an explicit observation anchor without deriving one from quotes."""
    raw = _map(value)
    missing = []
    anchor_value = _number(
        raw.get('value', raw.get('price', raw.get('reference_price')))
    )
    if anchor_value is None or anchor_value <= 0:
        missing.append('value')
    source = _text(raw.get('source'))
    if not source:
        missing.append('source')
    reference_date = _day(raw.get('reference_date') or raw.get('as_of'))
    if not reference_date:
        missing.append('reference_date')
    raw_basis = _map(raw.get('price_basis') or raw.get('basis'))
    basis = _validated_price_basis(raw_basis)
    if basis is None:
        missing.append('price_basis')
    purpose = _text(raw.get('purpose') or raw.get('usage'))
    if not purpose:
        missing.append('purpose')
    if reference_date and report_date and reference_date > report_date:
        missing.append('future_reference_date')
    expiry = _day(raw.get('expires_at') or raw.get('expiry_date') or raw.get('valid_until'))
    if expiry and report_date and expiry < report_date:
        missing.append('anchor_expired')
    if raw.get('invalidated') is True:
        missing.append('anchor_invalidated')
    candidate_signature = _price_basis_signature(candidate_basis)
    if isinstance(candidate_basis, dict) and candidate_basis:
        if basis is None:
            pass
        elif candidate_signature is None:
            missing.append('candidate_price_basis_invalid')
        elif _price_basis_signature(basis) != candidate_signature:
            missing.append('price_basis_conflict')
    elif basis:
        missing.append('candidate_price_basis_missing')
    if missing:
        reason = '缺少可验证观察锚点'
        if 'future_reference_date' in missing:
            reason = '观察锚点日期晚于报告日期'
        elif 'anchor_expired' in missing:
            reason = '观察锚点已过期'
        elif 'anchor_invalidated' in missing:
            reason = '观察锚点已失效'
        elif 'price_basis_conflict' in missing:
            reason = '观察锚点价基与候选不一致'
        elif 'candidate_price_basis_missing' in missing:
            reason = '候选价基未提供，观察锚点不可比'
        elif 'candidate_price_basis_invalid' in missing:
            reason = '候选价基无效，观察锚点不可比'
        return {
            'status': 'missing' if not raw else 'invalid',
            'value': None,
            'source': source,
            'reference_date': reference_date,
            'price_basis': copy.deepcopy(basis),
            'purpose': purpose,
            'missing_fields': missing,
            'reason': reason,
        }
    return {
        'status': 'verified',
        'value': anchor_value,
        'source': source,
        'reference_date': reference_date,
        'price_basis': copy.deepcopy(basis),
        'purpose': purpose,
        'missing_fields': [],
        'reason': '',
    }


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
    watch_anchor = _watch_anchor(
        row.get('watch_anchor'), report_date, row.get('price_basis')
    )
    watch_price = (
        watch_anchor.get('value')
        if watch_anchor.get('status') == 'verified' else None
    )
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
    elif next_steps and invalidation and watch_anchor.get('status') == 'verified':
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
            'next_confirmation': next_steps, 'invalidation': invalidation,
            'watch_anchor': watch_anchor, 'watch_reference_price': watch_price,
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
              'watch_anchor': copy.deepcopy(selected['watch_anchor']),
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
              'price_basis': copy.deepcopy(row.get('price_basis'))
              if isinstance(row.get('price_basis'), dict) else None,
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


def _int_or_none(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        return None
    return int(number)


def _coverage(report):
    """Project recorded coverage facts; never infer missing counts as zero."""
    quality = _map(report.get('data_quality'))
    eligibility = _map(_map(quality.get('universe_builder')).get('eligibility'))
    excluded = _map(eligibility.get('excluded'))
    selection = _map(report.get('selection_input_health'))
    formal = _map(selection.get('formal'))
    by_strategy = _map(selection.get('by_strategy'))
    quantity = _map(_map(by_strategy.get('daily_fusion')).get('quantity'))
    if not quantity:
        quantity = _map(_map(by_strategy.get('h4_t3')).get('quantity'))
    sublevels = _map(selection.get('sublevels'))
    minute = _map(sublevels.get('30m'))
    diagnostics = _map(report.get('diagnostics'))
    funnel = _map(diagnostics.get('candidate_funnel'))
    stage_counts = _map(funnel.get('stage_counts'))
    first_failure = _map(funnel.get('first_failure_counts'))
    universe = _map(quality.get('universe_builder'))
    minute_diag = _map(diagnostics.get('sublevel_upgrade_fusion'))
    if not minute:
        minute = minute_diag or _map(diagnostics.get('sublevel_upgrade_pure'))

    formal_status = _text(formal.get('status')) or _text(selection.get('status'))
    actions_allowed = formal.get('formal_actions_allowed')
    if not isinstance(actions_allowed, bool):
        actions_allowed = None
    formal_summary = {
        'status': formal_status or 'unknown',
        'actions_allowed': actions_allowed,
    }
    instrument_value = eligibility.get('instrument_count')
    if instrument_value is None:
        instrument_value = stage_counts.get('full_a')
    eligible_value = eligibility.get('eligible_count')
    if eligible_value is None:
        eligible_value = stage_counts.get('eligible')
    eligibility_summary = {
        'instrument_count': _int_or_none(instrument_value),
        'eligible_count': _int_or_none(eligible_value),
        'excluded': {
            key: _int_or_none(excluded.get(key))
            for key in ('nonfinal_bars', 'stale_latest_bar')
        },
    }
    retrieval_value = stage_counts.get('retrieval')
    if retrieval_value is None:
        retrieval_value = universe.get('final_count')
    full_a_value = stage_counts.get('full_a')
    if full_a_value is None:
        # The activated universe builder records the same denominator outside
        # the funnel.  Use it only as a source-backed fallback.
        full_a_value = eligibility.get('instrument_count')
    retrieval_summary = {
        'full_a': _int_or_none(full_a_value),
        'retrieval': _int_or_none(retrieval_value),
        'first_failure': _int_or_none(first_failure.get('retrieval')),
        'mode': _text(universe.get('retrieval_mode')) or None,
        'base_count': _int_or_none(universe.get('base_count')),
        'overlay_count': _int_or_none(universe.get('overlay_count')),
    }
    requested = _int_or_none(
        minute.get('requested_count', minute.get('requested_30min'))
    )
    verified = _int_or_none(
        minute.get('verified_count', minute.get('fetched_30min'))
    )
    missing = _int_or_none(minute.get('missing_count'))
    if missing is None and requested is not None and verified is not None:
        missing = max(0, requested - verified)
    reported_minute_status = _text(minute.get('status'))
    minute_status = reported_minute_status or (
        'verified' if requested is not None and verified == requested
        else 'partial' if requested is not None and verified is not None
        else 'unknown'
    )
    minute_summary = {
        'requested': requested,
        'verified': verified,
        'missing': missing,
        'status': minute_status,
    }
    quantity_required = _int_or_none(quantity.get('required_count'))
    quantity_available = _int_or_none(quantity.get('available_count'))
    quantity_pending = _int_or_none(len(_seq(quantity.get('pending_codes'))))
    quantity_coverage = _number(quantity.get('coverage'))
    quantity_minimum = _number(quantity.get('minimum_coverage'))
    quantity_summary = {
        'status': _text(quantity.get('status')) or 'unknown',
        'required': quantity_required,
        'available': quantity_available,
        'pending': quantity_pending,
        'coverage': quantity_coverage,
        'minimum_coverage': quantity_minimum,
    }
    snapshot = _map(selection.get('market_close_snapshot'))
    if not snapshot:
        snapshot = _map(quality.get('market_close_snapshot'))
    snapshot_status = _text(snapshot.get('status')) or 'unknown'
    snapshot_pending_codes = sorted({
        _text(code) for code in _seq(snapshot.get('identity_pending_codes'))
        if _text(code)
    })
    snapshot_summary = {
        'status': snapshot_status,
        'coverage': _number(snapshot.get('coverage')),
        'minimum_coverage': _number(snapshot.get('minimum_coverage')),
        'available': _int_or_none(snapshot.get('coverage_numerator')),
        'required': _int_or_none(snapshot.get('coverage_denominator')),
        'pending': _int_or_none(snapshot.get('identity_pending_rows')),
        'pending_codes': snapshot_pending_codes,
        'reason': _text(snapshot.get('reason')) or None,
    }
    relation_conflict = (
        requested is not None and verified is not None and verified > requested
    ) or (
        requested is not None and verified is not None and missing is not None
        and missing != requested - verified
    )
    if relation_conflict:
        minute_summary['status'] = 'conflict'
    elif requested is None or verified is None:
        # A producer status cannot certify a denominator that was not emitted.
        minute_summary['status'] = 'unknown'
    elif verified < requested and minute_summary['status'] == 'verified':
        minute_summary['status'] = 'partial'
    known = any(value is not None for value in (
        eligibility_summary['instrument_count'],
        eligibility_summary['eligible_count'],
        retrieval_summary['full_a'],
        retrieval_summary['retrieval'],
        minute_summary['requested'],
        minute_summary['verified'],
        quantity_summary['required'],
        quantity_summary['available'],
    ))
    eligibility_conflict = (
        eligibility_summary['instrument_count'] is not None
        and eligibility_summary['eligible_count'] is not None
        and eligibility_summary['eligible_count']
        > eligibility_summary['instrument_count']
    )
    retrieval_conflict = (
        retrieval_summary['full_a'] is not None
        and retrieval_summary['retrieval'] is not None
        and retrieval_summary['retrieval'] > retrieval_summary['full_a']
    )
    reasons = []
    if not formal_status or actions_allowed is None:
        reasons.append('formal_input_unrecorded')
    elif formal_status != 'verified' or actions_allowed is False:
        reasons.append('formal_input_unavailable')
    if relation_conflict:
        reasons.append('minute30_coverage_conflict')
    elif minute_summary['status'] == 'conflict':
        reasons.append('minute30_coverage_conflict')
    elif minute_summary['status'] in ('partial', 'unavailable') or (
        minute_summary['missing'] is not None and minute_summary['missing'] > 0
    ):
        reasons.append('minute30_coverage_partial')
    if quantity and quantity_summary['status'] == 'unavailable':
        reasons.append('quantity_coverage_unavailable')
    elif quantity and (
        quantity_summary['status'] == 'partial'
        or quantity_summary['pending'] not in (None, 0)
    ):
        reasons.append('quantity_coverage_partial')
    if snapshot and snapshot_summary['status'] == 'partial':
        reasons.append('identity_coverage_partial')
    elif snapshot and snapshot_summary['status'] not in ('complete', 'partial'):
        reasons.append('market_close_snapshot_unavailable')
    if retrieval_summary['full_a'] is None or retrieval_summary['retrieval'] is None:
        reasons.append('retrieval_coverage_unrecorded')
    if (
        minute_summary['requested'] is None
        or minute_summary['verified'] is None
        or minute_summary['status'] == 'unknown'
    ):
        reasons.append('minute30_coverage_unrecorded')
    if (
        eligibility_summary['instrument_count'] is None
        or eligibility_summary['eligible_count'] is None
    ):
        reasons.append('eligibility_coverage_unrecorded')
    elif eligibility_conflict:
        reasons.append('eligibility_coverage_conflict')
    if retrieval_conflict:
        reasons.append('retrieval_coverage_conflict')
    if any(value not in (None, 0) for value in eligibility_summary['excluded'].values()):
        reasons.append('historical_window_exclusions')
    if not known:
        status = 'unknown'
    elif 'formal_input_unavailable' in reasons:
        status = 'blocked'
    elif reasons:
        status = 'partial'
    else:
        status = 'verified'
    return {
        'status': status,
        'formal': formal_summary,
        'eligibility': eligibility_summary,
        'retrieval': retrieval_summary,
        'minute30': minute_summary,
        'quantity': quantity_summary,
        'market_close_snapshot': snapshot_summary,
        'reasons': reasons,
    }


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
    return dict(states, title=title, reason=reason, coverage=_coverage(report), total_items=len(items),
                executable_items=sum(x['is_executable'] for x in items),
                blocked_by_price=sum(any(b.startswith('missing_') for b in x['blocked_reasons']) for x in items),
                health_blocking_reasons=health['blocking_reasons'] + health['fact_blocking_reasons'])


def _comparison(report, strategies):
    """Build an explicit comparison identity from declared run metadata only."""
    identities = []
    basis_invalid = False
    basis_candidates = []
    manifest_statuses = {}
    scorecard_statuses = {}
    if isinstance(report.get('strategy_run_manifest'), (list, tuple)):
        manifest = report.get('strategy_run_manifest')
        manifest_present = True
    elif isinstance(report.get('run_manifest'), (list, tuple)):
        manifest = report.get('run_manifest')
        manifest_present = True
    else:
        manifest = []
        manifest_present = False
    if manifest_present:
        for raw in manifest:
            raw = _map(raw)
            strategy_id = _text(raw.get('strategy_id') or raw.get('strategy'))
            version = _text(raw.get('strategy_version') or raw.get('version'))
            if strategy_id and version:
                run_status = _text(raw.get('run_status'))
                if run_status:
                    manifest_statuses[strategy_id] = run_status
                raw_basis = raw.get('price_basis')
                basis = _validated_price_basis(raw_basis) if raw_basis is not None else None
                if raw_basis not in (None, '') and basis is None:
                    basis_invalid = True
                elif basis is not None:
                    basis_candidates.append(basis)
                identities.append({
                    'strategy_id': strategy_id,
                    'strategy_version': version,
                    'policy_version': _text(raw.get('policy_version')) or None,
                    'source_pool': _text(raw.get('source_pool')) or None,
                    'entry_mode': _text(raw.get('entry_mode')) or None,
                    'intended_horizon': raw.get('intended_horizon'),
                    'research_tier': _text(raw.get('research_tier')) or None,
                })
    scorecards = _map(report.get('strategy_scorecards'))
    report_date = _day(report.get('date') or report.get('trade_date'))
    if not manifest_present and isinstance(scorecards, dict):
        for group in ('formal', 'baselines', 'research'):
            for raw in _seq(scorecards.get(group)):
                raw = _map(raw)
                if _day(raw.get('latest_report_date') or raw.get('report_date')) != report_date:
                    continue
                identity = _map(raw.get('comparison_identity'))
                strategy_id = _text(identity.get('strategy') or raw.get('strategy'))
                version = _text(identity.get('version') or raw.get('version'))
                if strategy_id and version:
                    run_status = _text(raw.get('latest_run_status'))
                    if run_status:
                        scorecard_statuses[strategy_id] = run_status
                    raw_basis = identity.get('price_basis')
                    if raw_basis is None:
                        raw_basis = raw.get('price_basis')
                    basis = _validated_price_basis(raw_basis) if raw_basis is not None else None
                    if raw_basis not in (None, '') and basis is None:
                        basis_invalid = True
                    elif basis is not None:
                        basis_candidates.append(basis)
                    identities.append({
                        'strategy_id': strategy_id,
                        'strategy_version': version,
                        'policy_version': _text(identity.get('policy_version') or raw.get('policy_version')) or None,
                        'source_pool': _text(identity.get('source_pool') or raw.get('source_pool')) or None,
                        'entry_mode': _text(identity.get('entry_mode') or raw.get('entry_mode')) or None,
                        'intended_horizon': identity.get('intended_horizon', raw.get('intended_horizon')),
                        'research_tier': _text(identity.get('research_tier') or raw.get('research_tier')) or None,
                    })
    declared_version = _text(report.get('strategy_version'))
    if not identities and declared_version:
        identities = [{'strategy_id': 'declared', 'strategy_version': declared_version}]
    unique = {}
    for identity in identities:
        key = json.dumps(_clean(identity), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        unique[key] = identity
    identities = sorted(unique.values(), key=lambda item: (
        _text(item.get('strategy_id')), _text(item.get('research_tier')),
        _text(item.get('strategy_version')), _text(item.get('source_pool')),
    ))
    versions = {}
    for identity in identities:
        strategy_id = _text(identity.get('strategy_id'))
        version = _text(identity.get('strategy_version'))
        if strategy_id and strategy_id not in versions:
            versions[strategy_id] = version
        elif strategy_id and versions.get(strategy_id) != version:
            versions[strategy_id] = None
    versions = versions or None
    declared = _map(report.get('comparison_identity'))
    basis = None
    for candidate in (
        declared.get('price_basis'),
        report.get('price_basis'),
        _map(_map(report.get('data_quality')).get('price_basis')) or None,
    ):
        if candidate in (None, ''):
            continue
        validated = _validated_price_basis(candidate)
        if validated is None:
            basis_invalid = True
        elif basis is None:
            basis = validated
    if basis is None:
        if basis_candidates:
            basis = copy.deepcopy(basis_candidates[0])
    strategy_run_status = manifest_statuses or scorecard_statuses
    basis_status = (
        'invalid' if basis_invalid
        else 'verified' if basis is not None
        else 'missing'
    )
    basis_scope = None
    if isinstance(basis, dict):
        basis_scope = (
            'per_instrument' if 'by_instrument' in basis else 'report'
        )
    return {
        'price_basis': _clean(basis) if basis is not None else None,
        'price_basis_invalid': basis_invalid,
        'price_basis_status': basis_status,
        'price_basis_scope': basis_scope,
        'strategy_version': versions,
        'strategy_run_status': strategy_run_status or None,
        'strategy_identities': identities or None,
    }


def _item_price_basis(item):
    """Resolve a candidate's own basis; never use another stock's factor."""
    rows = _seq(item.get('strategy_results'))
    if not rows:
        rows = [item]
    signatures = []
    saw_basis = False
    missing = False
    invalid = False
    for strategy in rows:
        candidate = _map(strategy.get('candidate')) if isinstance(strategy, dict) else _map(strategy)
        raw = candidate.get('price_basis')
        if raw in (None, ''):
            missing = True
            continue
        saw_basis = True
        signature = _price_basis_signature(raw)
        if signature is None:
            invalid = True
        else:
            signatures.append(signature)
    if invalid:
        return {'status': 'invalid'}
    if not saw_basis or missing:
        return {'status': 'missing'}
    if not signatures or len(set(signatures)) != 1:
        return {'status': 'conflict'}
    return {'status': 'verified', 'signature': signatures[0]}


_VIEW_STRATEGY_IDS = {
    'main': 'daily_fusion',
    'h4_t3': 'h4_t3',
    'confirming': 'observation_gate',
    'observation_top5': 'observation_gate',
    'acceleration': 'next_day_boom',
    'luojie': 'luojie_pool',
    'growth_quality': 'daily_pure',
    'baseline': 'daily_pure',
}


def _item_strategy_groups(item):
    groups = set()
    for strategy in _seq(item.get('strategy_results')):
        if not isinstance(strategy, dict):
            continue
        value = _text(strategy.get('strategy_id'))
        if value:
            groups.add(_VIEW_STRATEGY_IDS.get(value, value))
    if not groups and item.get('strategy_id'):
        value = _text(item.get('strategy_id'))
        groups.add(_VIEW_STRATEGY_IDS.get(value, value))
    return groups


def _identity_groups(contract):
    groups = {}
    for identity in _seq(_map(contract).get('strategy_identities')):
        if not isinstance(identity, dict):
            continue
        strategy_id = _text(identity.get('strategy_id'))
        if not strategy_id:
            continue
        stable = {
            key: identity.get(key)
            for key in (
                'strategy_id', 'strategy_version', 'policy_version',
                'source_pool', 'entry_mode', 'intended_horizon', 'research_tier',
            )
        }
        signature = json.dumps(
            _clean(stable), ensure_ascii=False, sort_keys=True,
            separators=(',', ':'),
        )
        groups.setdefault(strategy_id, set()).add(signature)
    return groups


def _changes(current, previous):
    previous = _map(previous)
    unavailable = {'status': 'comparison_unavailable'}
    if not previous:
        return unavailable
    if current['phase'] != previous.get('phase') or current['report_date'] < _text(previous.get('report_date')):
        return dict(unavailable, reason='phase_or_date_mismatch')
    contract = current['comparison_contract']
    old_contract = _map(previous.get('comparison_contract'))
    if not contract.get('strategy_identities'):
        return dict(unavailable, reason='comparison_contract_unavailable_or_changed')
    if not old_contract.get('strategy_identities'):
        return dict(unavailable, reason='previous_comparison_contract_unavailable')
    current_groups = _identity_groups(contract)
    previous_groups = _identity_groups(old_contract)
    changed_identity_groups = {
        strategy_id for strategy_id in set(current_groups) | set(previous_groups)
        if current_groups.get(strategy_id, set()) != previous_groups.get(strategy_id, set())
    }
    current_versions = _map(contract.get('strategy_version'))
    previous_versions = _map(old_contract.get('strategy_version'))
    changed_identity_groups.update(
        strategy_id for strategy_id in set(current_versions) | set(previous_versions)
        if current_versions.get(strategy_id) != previous_versions.get(strategy_id)
    )
    bad_statuses = {
        'unavailable', 'data_unavailable', 'partial', 'conflict',
        'blocked', 'error',
    }
    unavailable_strategies = {
        strategy_id for strategy_id, status in (
            _map(contract.get('strategy_run_status')).items()
        ) if _text(status).lower() in bad_statuses
    }
    unavailable_strategies.update(
        strategy_id for strategy_id, status in (
            _map(old_contract.get('strategy_run_status')).items()
        ) if _text(status).lower() in bad_statuses
    )
    health_unavailable = []
    for projection in (current, previous):
        health = _map(projection.get('health'))
        if _text(health.get('status')) not in ('verified', ''):
            health_unavailable.extend(_seq(health.get('fact_blocking_reasons')))
    before = {x['instrument_id']: x for x in _seq(previous.get('items')) if x.get('instrument_id')}
    after = {x['instrument_id']: x for x in current['items']}
    unavailable_codes = set(
        x.get('code') for x in list(before.values()) + list(after.values())
        if x.get('page_status') in ('evidence_blocked', 'strategy_disagreement', 'invalidated')
        and x.get('code')
    )
    def item_strategy_ids(item):
        return _item_strategy_groups(item)

    strategy_bad_ids = set()
    strategy_bad_codes = set()
    for item in list(before.values()) + list(after.values()):
        if item_strategy_ids(item) & unavailable_strategies:
            code = item.get('code')
            if code:
                unavailable_codes.add(code)
                strategy_bad_codes.add(code)
                strategy_bad_ids.add(item.get('instrument_id'))
        if _item_strategy_groups(item) & changed_identity_groups:
            code = item.get('code')
            if code:
                unavailable_codes.add(code)
                strategy_bad_codes.add(code)
                strategy_bad_ids.add(item.get('instrument_id'))
    unavailable_codes = sorted(unavailable_codes)
    bad_ids = {
        x.get('instrument_id') for x in list(before.values()) + list(after.values())
        if x.get('page_status') in ('evidence_blocked', 'strategy_disagreement', 'invalidated')
    }
    bad_ids.update(strategy_bad_ids)
    before = {key: value for key, value in before.items() if key not in bad_ids}
    after = {key: value for key, value in after.items() if key not in bad_ids}
    if changed_identity_groups and not before and not after:
        return dict(
            unavailable,
            reason='comparison_identity_changed',
            unavailable_strategies=sorted(changed_identity_groups | unavailable_strategies),
        )
    if health_unavailable and not before and not after:
        return dict(unavailable, reason='comparison_health_unavailable')
    def semantic(x):
        return (
            x.get('formal_action'), x.get('page_status'), x.get('action_reason'),
            x.get('primary_reason'), x.get('next_confirmation'),
            x.get('invalidation'),
        )
    def price_semantic(x):
        anchor = _map(x.get('watch_anchor'))
        return (
            _clean(x.get('contracts')),
            x.get('reference_price'),
            anchor.get('value'),
        )
    changed = []
    value_unavailable = []
    value_unavailable_reasons = {}
    for key in sorted(after.keys() & before.keys()):
        current_basis = _item_price_basis(after[key])
        previous_basis = _item_price_basis(before[key])
        basis_compatible = (
            current_basis.get('status') == 'verified'
            and previous_basis.get('status') == 'verified'
            and current_basis.get('signature') == previous_basis.get('signature')
        )
        if not basis_compatible:
            value_unavailable.append(after[key]['code'])
            if current_basis.get('status') == 'conflict' or previous_basis.get('status') == 'conflict':
                value_unavailable_reasons[after[key]['code']] = 'price_basis_conflict'
            elif current_basis.get('status') == 'invalid' or previous_basis.get('status') == 'invalid':
                value_unavailable_reasons[after[key]['code']] = 'price_basis_invalid'
            elif (
                current_basis.get('status') == 'verified'
                and previous_basis.get('status') == 'verified'
            ):
                value_unavailable_reasons[after[key]['code']] = 'price_basis_changed'
            else:
                value_unavailable_reasons[after[key]['code']] = 'price_basis_missing'
        if semantic(after[key]) != semantic(before[key]):
            changed.append(after[key]['code'])
        elif price_semantic(after[key]) != price_semantic(before[key]):
            if basis_compatible:
                changed.append(after[key]['code'])
    result = {'status': 'partial' if unavailable_codes or health_unavailable or unavailable_strategies or changed_identity_groups or value_unavailable or contract.get('price_basis_invalid') or old_contract.get('price_basis_invalid') else 'available',
            'previous_report_date': previous.get('report_date'),
            'previous_phase': previous.get('phase'),
            'added': [after[k]['code'] for k in sorted(after.keys() - before.keys())],
            'removed': [before[k]['code'] for k in sorted(before.keys() - after.keys())],
            'changed': changed}
    if unavailable_codes:
        result['unavailable_codes'] = unavailable_codes
        result['unavailable_reasons'] = {
            code: (
                'candidate_strategy_unavailable'
                if code in strategy_bad_codes
                else 'candidate_evidence_unavailable'
            )
            for code in unavailable_codes
        }
    if unavailable_strategies:
        result['unavailable_strategies'] = sorted(unavailable_strategies)
    if changed_identity_groups:
        result['unavailable_strategies'] = sorted(
            set(result.get('unavailable_strategies', [])) | changed_identity_groups
        )
        result['identity_comparison_status'] = 'partial_strategy_identity'
    if health_unavailable:
        result['health_reasons'] = list(dict.fromkeys(health_unavailable))
    if value_unavailable:
        result['value_comparison_status'] = 'unavailable_price_basis_missing'
        result['value_comparison_reason'] = '单股价基缺失、冲突或换基，仅比较成员变化与非价格状态'
        result['value_unavailable_codes'] = sorted(set(value_unavailable))
        result['value_unavailable_reasons'] = {
            code: value_unavailable_reasons.get(code, 'price_basis_missing')
            for code in sorted(set(value_unavailable))
        }
    elif contract.get('price_basis_invalid') or old_contract.get('price_basis_invalid'):
        result['value_comparison_status'] = 'unavailable_price_basis_missing'
        result['value_comparison_reason'] = '全局价基声明无效，仅比较成员变化与非价格状态'
    return result


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
                       'watch_anchor': x.get('watch_anchor'),
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
