#!/usr/bin/env python3
"""Offline research selectors. Pure signal-day input; no network, DB or production imports.

The L1 rule is exploratory, not a validated trading strategy. It does NOT alter
formal membership, scores or execution flags. Input: normalized same-day facts
from this research package, not the raw production report schema.
"""
from __future__ import annotations
import argparse
import copy
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

METHODS = (
    'B0_original_highlights', 'B1_all_gain5', 'B2_highlights_gain5',
    'C1_solid_volume', 'C2_not_extended', 'C3_sector', 'C4_breakout',
    'C5_trend_health', 'L0_limit_early', 'L1_limit_sector',
)

def number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def load_rows(path: Path) -> list[dict]:
    opener = gzip.open if path.name.endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]

def minutes(value: Any) -> float:
    if not isinstance(value, str):
        return float('inf')
    try:
        parts = value.split(':')
        hh, mm = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return float('inf')
    return hh * 60 + mm if 9 <= hh <= 15 and 0 <= mm < 60 else float('inf')

def accepts(row: dict, method: str) -> bool:
    chg, vol, cp = (row.get(k) for k in ('f_change_pct', 'f_volume_ratio', 'close_position'))
    if method == 'B0_original_highlights':
        return row.get('is_highlight') is True
    if method == 'B1_all_gain5':
        return number(chg)
    if method == 'B2_highlights_gain5':
        return row.get('is_highlight') is True and number(chg)
    solid = (number(chg) and chg >= 4 and number(cp) and cp >= .75
             and number(vol) and 1.5 <= vol <= 4)
    if method == 'C1_solid_volume':
        return solid
    if method == 'C2_not_extended':
        return solid and number(row.get('vs_ma20')) and row['vs_ma20'] <= 15
    if method == 'C3_sector':
        return (number(chg) and chg >= 4 and number(cp) and cp >= .75
                and number(row.get('sector_limit_n')) and row['sector_limit_n'] >= 2)
    if method == 'C4_breakout':
        return solid and row.get('breakout20') is True
    if method == 'C5_trend_health':
        return (number(chg) and chg >= 4
                and row.get('f_alignment') in ('bullish', 'repairing')
                and row.get('f_fomo') in ('low', 'medium'))
    if method.startswith('L'):
        # Complete same-day source is needed for THIS comparable historical ranking.
        # Missing/partial source dates are reported as not-evaluated for this rule,
        # never as a reason to stop publication or erase the original candidate list.
        return (row.get('in_limit_snapshot') is True
                and row.get('limit_status') == 'verified_complete'
                and number(row.get('board_n')))
    raise ValueError('Unknown method: ' + method)

def rank_key(row: dict, method: str) -> tuple:
    identity = str(row['instrument_id'])
    if method == 'B0_original_highlights':
        r = row.get('highlight_rank')
        return (r if number(r) else float('inf'), identity)
    if method == 'L0_limit_early':
        return (minutes(row.get('first_limit_time')), identity)
    if method == 'L1_limit_sector':
        count, board = row.get('own_limit_sector_count'), row.get('board_n')
        return (0 if number(count) else 1, -count if number(count) else 0,
                0 if number(board) else 1, -board if number(board) else 0,
                minutes(row.get('first_limit_time')), identity)
    return (-row['f_change_pct'], identity)

def select_day(rows: list[dict], date: str, method: str = 'L1_limit_sector', k: int = 5) -> list[dict]:
    if method not in METHODS or not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError('Invalid method or k')
    current = [r for r in rows if r.get('report_date') == date]
    ids = [r.get('instrument_id') for r in current]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Duplicate or missing security identity for ' + date)
    qualified = sorted((r for r in current if accepts(r, method)), key=lambda r: rank_key(r, method))
    result = []
    for rank, row in enumerate(qualified[:k], 1):
        copied = copy.deepcopy(row)
        copied['research_method'] = method
        copied['research_rank'] = rank
        copied['result_type'] = 'exploratory_next_day_candidate'
        copied['not_a_trade_instruction'] = True
        result.append(copied)
    return result

def main() -> None:
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, default=root/'data/signal_features.jsonl.gz')
    p.add_argument('--date', required=True)
    p.add_argument('--method', choices=METHODS, default='L1_limit_sector')
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if args.out.resolve() == args.input.resolve() or args.out.exists():
        p.error('Output must be a new path, not an input or existing file.')
    rows = load_rows(args.input)
    if args.date not in {r['report_date'] for r in rows}:
        p.error('No frozen signal rows for this date; no network backfill is performed.')
    selected = select_day(rows, args.date, args.method)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({'date': args.date, 'status': 'research_only',
        'method': args.method, 'original_universe_unchanged': True, 'selected': selected,
        'warning': 'Not validated production recommendations; outcome data not read. '
                   'Zero candidates never blocks the original report.'},
        ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'status':'research_only','selected':len(selected),'output':str(args.out)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
