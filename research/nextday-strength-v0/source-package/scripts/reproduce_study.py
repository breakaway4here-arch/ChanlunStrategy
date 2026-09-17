#!/usr/bin/env python3
"""Reproduce every declared comparison from separate signal and outcome files."""
from __future__ import annotations
import argparse, json, math, statistics
from pathlib import Path
from collections import defaultdict
from nextday_candidates import METHODS, load_rows, number, select_day

WINDOWS = {
 'all25': ('2026-08-12','2026-09-15'),
 'older_legacy': ('2026-08-12','2026-08-26'),
 'bridge': ('2026-08-27','2026-09-01'),
 'recent10': ('2026-09-02','2026-09-15'),
 'recent_first5': ('2026-09-02','2026-09-08'),
 'recent_last5': ('2026-09-09','2026-09-15'),
}

def metric(rows: list[dict]) -> dict:
    cc = [r['cc1'] for r in rows if number(r.get('cc1'))]
    oc = [r['oc1'] for r in rows if number(r.get('oc1'))]
    def mean(key):
        vals = [r[key] for r in rows if number(r.get(key))]
        return statistics.mean(vals) if vals else None
    return {'selected':len(rows),'active_signal_dates':len({r['report_date'] for r in rows}),
      'observed_T1':len(cc),'missing_T1':len(rows)-len(cc),
      'cc1_mean':mean('cc1'),'cc1_median':statistics.median(cc) if cc else None,
      'gap1_mean':mean('gap1'),'oc1_mean':mean('oc1'),
      'oc1_median':statistics.median(oc) if oc else None,
      'nextday_gain_ge5':sum(v>=5 for v in cc),'nextday_loss_le_minus5':sum(v<=-5 for v in cc),
      'nextday_gain_ge5_ratio':sum(v>=5 for v in cc)/len(cc) if cc else None,
      'open_close_gain_ge3':sum(v>=3 for v in oc),'open_close_loss_le_minus5':sum(v<=-5 for v in oc),
      'oc2_mean':mean('oc2'),'oc3_mean':mean('oc3'),
      'oc2_observed':sum(number(r.get('oc2')) for r in rows),
      'oc3_observed':sum(number(r.get('oc3')) for r in rows),
      'entry_one_price_count':sum(r.get('entry_one_price') is True for r in rows),
      'not_realized_profit':True}

def main():
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if args.out.exists():p.error('Use a new output directory; existing results are not overwritten.')
    args.out.mkdir(parents=True)
    facts=load_rows(root/'data/signal_features.jsonl.gz')
    outcomes=load_rows(root/'data/outcome_paths.jsonl.gz')
    keys=lambda r:(r['report_date'],r['instrument_id'])
    out={keys(r):r for r in outcomes}
    if len(out)!=len(outcomes):raise ValueError('Duplicate outcome key')
    days=sorted({r['report_date'] for r in facts})
    full=[dict(r,**{k:v for k,v in out.get(keys(r),{}).items() if k not in ('report_date','instrument_id')}) for r in facts]
    selections={}
    for method in METHODS:
        chosen=[]
        for day in days:
            # Selection is completed without accessing the outcome map.
            signals=select_day(facts,day,method)
            for s in signals:
                o=out.get(keys(s),{})
                chosen.append(dict(s,**{k:v for k,v in o.items() if k not in ('report_date','instrument_id')}))
        selections[method]=chosen
    summary={}
    for label,(start,end) in WINDOWS.items():
        summary[label]={m:metric([r for r in rows if start<=r['report_date']<=end]) for m,rows in selections.items()}
    prior_days=sorted({r['report_date'] for r in selections['L1_limit_sector'] if r['report_date']<'2026-09-02'})
    summary['same_prior6_dates']={'dates':prior_days,'methods':{
      m:metric([r for r in rows if r['report_date'] in prior_days]) for m,rows in selections.items()}}
    parts={'previous8':('2026-08-21','2026-09-01'),
           'recent_first5':WINDOWS['recent_first5'],'recent_last5':WINDOWS['recent_last5'],
           'recent10':WINDOWS['recent10']}
    association={label:{str(val):metric([r for r in full if start<=r['report_date']<=end and r.get('in_limit_snapshot') is val])
                 for val in (True,False)} for label,(start,end) in parts.items()}
    sensitivity={}
    for m in ('B2_highlights_gain5','C1_solid_volume'):
        sensitivity[m]={label:metric([r for r in selections[m] if start<=r['report_date']<=end
                            and number(r.get('gap1')) and -2<=r['gap1']<=3])
                        for label,(start,end) in WINDOWS.items()}
    l1=selections['L1_limit_sector']
    summary['recent10_without0911']=metric([r for r in l1 if r['report_date']>='2026-09-02' and r['report_date']!='2026-09-11'])
    def write(name,obj):
        (args.out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    write('all_comparisons.json',summary);write('limit_up_association.json',association)
    write('opening_gap_sensitivity.json',sensitivity)
    write('selected_before_outcomes.json',selections)
    print(json.dumps({'signal_dates':len(days),'signal_rows':len(facts),'methods':len(METHODS),'out':str(args.out)},ensure_ascii=False))

if __name__=='__main__':main()
