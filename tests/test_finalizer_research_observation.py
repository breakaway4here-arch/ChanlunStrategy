"""Strict source-bound B observation exception; no report or database writes."""
import copy
import json
import unittest
from pathlib import Path

from chanlun.report_view_model import build_workspace
from scripts.repair_strategy_scorecard_snapshot import (
    _workspace_upstream_contract_violations, protected_report_digest,
    rebuild_strategy_scorecard_report,
)


def report():
    raw=dict(code='002176',name='合成观察',identity_key='stock|SZ|002176',
        tier='watch',view='observation',source_channel='low_position',
        research_observation_projection=True,affects_formal=False,is_executable=False,
        eligible_for_l1_v0=False,formal_actions_allowed=False,
        reason_code='alignment_without_confirmation',observation_status='pending_confirmation',
        minute30_input_status='verified',minute30_confirmation_status='pending')
    result=dict(date='2026-09-30',picks_pure=[],observation_watchlist=[raw])
    result['workspace']=build_workspace(result)
    return result


class FinalizerResearchObservationTests(unittest.TestCase):
    def real_report(self, rebuild_workspace=True):
        value=json.loads((Path(__file__).resolve().parents[1]/'docs/data/2026-09-30.json').read_text())
        if rebuild_workspace:value['workspace']=build_workspace(value)
        return value

    def rebuild(self,value):
        scorecards=dict(schema_version=2,thresholds={},formal=[],baselines=[],research=[],gates=[],classification_failures=[])
        return rebuild_strategy_scorecard_report(value,report_date='2026-09-30',
            scorecards=scorecards,review_diagnostics={'status':'ok'})
    def blocked(self,value,view='observation_top5'):
        return '002176' in _workspace_upstream_contract_violations(value).get(view,[])

    def test_strict_both_sides_flags_and_source_binding(self):
        base=report();self.assertFalse(self.blocked(base))
        flags={'research_observation_projection':True,'affects_formal':False,'is_executable':False,
               'eligible_for_l1_v0':False,'formal_actions_allowed':False}
        for side in ('raw','projection'):
            for field,expected in flags.items():
                for value in (None,not expected,int(expected),str(expected).lower()):
                    with self.subTest(side=side,field=field,value=value):
                        changed=copy.deepcopy(base)
                        row=changed['observation_watchlist'][0] if side=='raw' else changed['workspace']['views']['observation_top5'][0]
                        row[field]=value
                        self.assertTrue(self.blocked(changed))
        self.assertFalse(self.blocked(base))

    def test_reference_original_identity_and_wrong_fields_rejected(self):
        base=report()
        for side in ('raw','projection'):
            for field,value in (('source_channel','formal'),('view','main'),('tier','candidate'),
                ('minute30_input_status','missing'),('minute30_confirmation_status','confirmed'),
                ('reason_code','buy'),('reason_code',[]),('observation_status','confirmed'),('identity_key','stock|SH|002176'),
                ('exchange','SH'),('asset_type','index'),('final_display_state','candidate')):
                with self.subTest(side=side,field=field):
                    changed=copy.deepcopy(base)
                    row=changed['observation_watchlist'][0] if side=='raw' else changed['workspace']['views']['observation_top5'][0]
                    row[field]=value
                    self.assertTrue(self.blocked(changed))
        for field,value in (('pool','picks_pure'),('code','300890')):
            changed=copy.deepcopy(base);changed['workspace']['views']['observation_top5'][0]['ref'][field]=value
            self.assertTrue(self.blocked(changed))
        changed=copy.deepcopy(base);changed['observation_watchlist']=[]
        self.assertTrue(self.blocked(changed))

    def test_same_duplicate_preserved_conflicting_duplicate_rejected(self):
        base=report();base['observation_watchlist'].append(copy.deepcopy(base['observation_watchlist'][0]))
        self.assertFalse(self.blocked(base))
        for field,value in (('is_executable',True),('source_channel','formal'),('name','不同来源')):
            changed=copy.deepcopy(base);changed['observation_watchlist'][1][field]=value
            self.assertTrue(self.blocked(changed))

    def test_missing_minutes_and_valid_pending_contracts_both_allowed(self):
        for reason,status,inputs,confirmation in (
            ('missing_30m_data','minute_data_insufficient','missing','not_evaluated'),
            ('waiting_30m_confirm','pending_confirmation','verified','pending'),
            ('alignment_without_confirmation','pending_confirmation','verified','pending')):
            changed=report();changed['observation_watchlist'][0].update(reason_code=reason,
                observation_status=status,minute30_input_status=inputs,minute30_confirmation_status=confirmation)
            changed['workspace']=build_workspace(changed)
            self.assertFalse(self.blocked(changed))

    def test_b_projection_cannot_bypass_other_views(self):
        for view in ('main','h4_t3','highlights','acceleration','luojie','confirming','growth_quality'):
            with self.subTest(view=view):
                changed=report();row=copy.deepcopy(changed['workspace']['views']['observation_top5'][0])
                changed['workspace']['views'][view]=[row]
                self.assertTrue(self.blocked(changed,view))

    def test_b_contract_cannot_borrow_old_limit_or_pure_exceptions(self):
        for kind in ('limit_up','pure'):
            with self.subTest(kind=kind):
                changed=report();row=changed['workspace']['views']['observation_top5'][0]
                row['is_executable']=True
                if kind=='limit_up':row['price_limit_state']='limit_up'
                else:changed['picks_pure']=[{'code':'002176'}]
                self.assertTrue(self.blocked(changed))

    def test_non_b_legacy_limit_and_pure_exceptions_still_work(self):
        for kind in ('limit_up','pure'):
            with self.subTest(kind=kind):
                changed=report()
                for item in (changed['observation_watchlist'][0],changed['workspace']['views']['observation_top5'][0]):
                    item['research_observation_projection']=False
                if kind=='limit_up':changed['workspace']['views']['observation_top5'][0]['price_limit_state']='limit_up'
                else:changed['picks_pure']=[{'code':'002176'}]
                self.assertFalse(self.blocked(changed))

    def test_frozen_real_report_top5_order_and_protected_surfaces(self):
        path=Path(__file__).resolve().parents[1]/'docs/data/2026-09-30.json'
        raw_bytes=path.read_bytes();value=json.loads(raw_bytes);value['workspace']=build_workspace(value)
        expected=['300890','300893','002176','000692','002317']
        before=protected_report_digest(value)
        protected_names=('main','h4_t3','acceleration','luojie','confirming')
        protected={name:copy.deepcopy(value['workspace']['views'][name]) for name in protected_names}
        expected_health=copy.deepcopy(value['selection_input_health'])
        expected_health['by_view'].pop('observation_top5')
        scorecards=dict(schema_version=2,thresholds={},formal=[],baselines=[],research=[],gates=[],classification_failures=[])
        result,diagnostics=rebuild_strategy_scorecard_report(value,report_date='2026-09-30',
            scorecards=scorecards,review_diagnostics={'status':'ok'})
        self.assertEqual([r['code'] for r in result['workspace']['views']['observation_top5']],expected)
        self.assertEqual(protected_report_digest(result),before)
        self.assertEqual({name:result['workspace']['views'][name] for name in protected_names},protected)
        self.assertEqual(path.read_bytes(),raw_bytes)
        self.assertNotIn('observation_top5',diagnostics.get('upstream_contract_blocked_views',[]))
        self.assertEqual(result['selection_input_health'],expected_health)
        self.assertEqual(result['workspace']['view_meta']['observation_top5']['availability']['state'],'available')

    def test_stored_closed_workspace_restores_only_proven_observation_marker(self):
        value=self.real_report(False)
        self.assertEqual(value['workspace']['views']['observation_top5'],[])
        expected=copy.deepcopy(value['selection_input_health']);expected['by_view'].pop('observation_top5')
        result,diagnostics=self.rebuild(value)
        self.assertEqual([r['code'] for r in result['workspace']['views']['observation_top5']],
            ['300890','300893','002176','000692','002317'])
        self.assertEqual(result['selection_input_health'],expected)
        self.assertEqual(diagnostics['restored_observation_views'],['observation_top5'])
        self.assertEqual(protected_report_digest(result),protected_report_digest(value))

    def test_other_or_tampered_view_health_is_preserved(self):
        for field,value in (('blocking_reason','minute_input_unavailable'),('required_date','2026-09-29'),
            ('invalid_count',3.0),('output_hidden',1),('invalid_codes',['002176']),('extra_reason','real_missing_input')):
            with self.subTest(field=field):
                source=self.real_report();source['selection_input_health']['by_view']['observation_top5'][field]=value
                marker=copy.deepcopy(source['selection_input_health']['by_view']['observation_top5'])
                result,diagnostics=self.rebuild(source)
                self.assertEqual(result['selection_input_health']['by_view']['observation_top5'],marker)
                self.assertEqual(diagnostics['restored_observation_views'],[])

    def test_invalid_or_empty_b_does_not_clear_old_health(self):
        for kind in ('unsafe','no_b'):
            with self.subTest(kind=kind):
                source=self.real_report()
                if kind=='unsafe':
                    next(r for r in source['observation_watchlist'] if r['code']=='002176')['is_executable']=True
                else:
                    source['observation_watchlist']=[]
                result,diagnostics=self.rebuild(source)
                self.assertIn('observation_top5',result['selection_input_health']['by_view'])
                self.assertEqual(diagnostics['restored_observation_views'],[])

    def test_stored_empty_view_needs_matching_closing_receipt(self):
        from scripts.repair_strategy_scorecard_snapshot import _has_legacy_observation_upstream_marker
        source=self.real_report(False);rebuilt=build_workspace(source)
        self.assertTrue(_has_legacy_observation_upstream_marker(source,'2026-09-30',rebuilt))
        for section in ('upstream_contract','availability'):
            changed=copy.deepcopy(source);changed['workspace']['view_meta']['observation_top5'].pop(section)
            self.assertFalse(_has_legacy_observation_upstream_marker(changed,'2026-09-30',rebuilt))
        changed=copy.deepcopy(source);changed['workspace']['diagnostics']['upstream_contract_incidents']=[]
        self.assertFalse(_has_legacy_observation_upstream_marker(changed,'2026-09-30',rebuilt))

    def test_nonempty_top5_membership_and_order_stay_protected_when_clearing_health(self):
        for kind in ('reverse','subset'):
            with self.subTest(kind=kind):
                value=self.real_report()
                if kind=='reverse':value['workspace']['views']['observation_top5'].reverse()
                else:value['workspace']['views']['observation_top5'].pop()
                with self.assertRaisesRegex(RuntimeError,'workspace membership or ordering changed'):
                    self.rebuild(value)


if __name__=='__main__':unittest.main()
