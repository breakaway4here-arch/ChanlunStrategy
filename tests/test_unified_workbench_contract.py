import copy
import json
import unittest

from chanlun.decision_workbench import build_decision_workbench


DAY = '2026-09-07'


def inputs():
    report = {
        'date': DAY,
        'data_quality': {'as_of': DAY + 'T15:05:00+08:00', 'is_official': True,
                         'bar_state': 'closed', 'market_status': 'verified'},
        'selection_input_health': {'formal': {'status': 'verified', 'formal_actions_allowed': True}},
        'price_basis': {'adjustment': 'qfq', 'factor_vs_raw': 1.0},
        'strategy_version': 'v1',
    }
    row = {'code': '600001', 'name': '样本', 'view_rank': 1,
           'action_semantics': 'formal', 'opportunity_score': 99,
           'price_basis': {'adjustment': 'qfq', 'factor_vs_raw': 1.0},
           'decision_engine_v1': {'total_score': 62},
           'ref': {'pool': 'picks_fusion', 'code': '600001'},
           'data_status': {'daily': 'verified', 'latest_date': DAY, 'stale': False, 'is_final': True},
           'formal_decision_contract': {'action': '可上车', 'action_reason': '结构确认',
                                        'reference_price': 10, 'invalidation_price': 9,
                                        'intended_horizon': 3, 'position_band': 0.2}}
    workspace = {'views': {'main': [row]}, 'view_meta': {
        'main': {'role': 'formal', 'action_semantics': 'formal', 'availability': {'state': 'available'}},
        'h4_t3': {'role': 'formal', 'action_semantics': 'formal', 'availability': {'state': 'verified_empty'}},
    }}
    evidence = {'report_date': DAY, 'views': {'main': [{
        'code': '600001', 'summary': {'status': 'available', 'as_of': DAY},
        'daily_structure': {'status': 'available', 'as_of': DAY, 'is_final': True},
        'sublevel_30m': {'status': 'available', 'as_of': DAY},
        'price_evidence': {'status': 'available', 'as_of': DAY},
        'risk_and_next': {'status': 'available', 'as_of': DAY,
                          'next_confirmation': ['突破位保持'], 'cancel_conditions': ['跌破9元']},
    }]}}
    return report, workspace, evidence


class UnifiedWorkbenchContracts(unittest.TestCase):
    def build(self, values=None, **kwargs):
        return build_decision_workbench(*(values or inputs()), **kwargs)

    def test_complete_formal_does_not_require_unpromised_pressure_target(self):
        row = self.build()['items'][0]
        self.assertEqual(row.get('page_status'), 'formal_ready')
        self.assertTrue(row['is_executable'])
        self.assertEqual(row.get('score'), 62)

    def test_research_never_vetoes_or_overwrites_formal_contract(self):
        r, w, e = inputs()
        w['views']['highlights'] = [{'code': '600001', 'name': '样本', 'action_semantics': 'watch_only',
                                     'page_action': '仅观察', 'decision_engine_v1': {'total_score': 98}}]
        row = self.build((r, w, e))['items'][0]
        self.assertEqual(row.get('formal_action'), '可上车')
        self.assertEqual(row.get('page_status'), 'formal_ready')
        self.assertEqual(len(row.get('strategy_results', [])), 2)

    def test_formal_reject_is_a_conflict_even_if_not_executable(self):
        r, w, e = inputs()
        other = copy.deepcopy(w['views']['main'][0])
        other['formal_decision_contract']['action'] = '不推荐'
        w['views']['h4_t3'] = [other]
        e['views']['h4_t3'] = copy.deepcopy(e['views']['main'])
        row = self.build((r, w, e))['items'][0]
        self.assertEqual(row.get('page_status'), 'strategy_disagreement')
        self.assertFalse(row['is_executable'])

    def test_candidate_conflict_blocks_even_with_globally_good_health(self):
        r, w, e = inputs()
        e['views']['main'][0]['daily_structure']['status'] = 'conflict'
        row = self.build((r, w, e))['items'][0]
        self.assertEqual(row.get('page_status'), 'evidence_blocked')
        self.assertFalse(row['is_executable'])

    def test_price_evidence_conflict_blocks_positive_contract_numbers(self):
        r, w, e = inputs()
        e['views']['main'][0]['price_evidence']['status'] = 'conflict'
        self.assertFalse(self.build((r, w, e))['items'][0]['is_executable'])

    def test_invalid_formal_contract_declaration_blocks_execution(self):
        r, w, e = inputs()
        w['views']['main'][0]['formal_decision_contract_diagnostics'] = {'intended_horizon': 'conflict'}
        self.assertFalse(self.build((r, w, e))['items'][0]['is_executable'])

    def test_partial_global_permission_does_not_enable_blocked_strategy(self):
        r, w, e = inputs()
        r['selection_input_health']['formal']['blocked_strategies'] = ['daily_fusion']
        self.assertFalse(self.build((r, w, e))['items'][0]['is_executable'])

    def test_partial_quantity_coverage_keeps_valid_peer_and_is_visible(self):
        r, w, e = inputs()
        quantity = {
            'status': 'partial', 'required_count': 10,
            'available_count': 9, 'coverage': 0.9,
            'minimum_coverage': 0.9, 'pending_codes': ['300009'],
        }
        r['selection_input_health'] = {
            'schema_version': 2,
            'status': 'partial',
            'formal': {
                'status': 'verified', 'formal_actions_allowed': True,
                'all_formal_actions_allowed': True,
                'blocked_strategies': [],
            },
            'by_strategy': {
                'daily_fusion': {
                    'status': 'verified', 'formal_actions_allowed': True,
                    'quantity': quantity,
                },
                'h4_t3': {
                    'status': 'verified', 'formal_actions_allowed': True,
                    'quantity': quantity,
                },
            },
        }

        result = self.build((r, w, e))

        self.assertEqual(result['items'][0]['page_status'], 'formal_ready')
        self.assertEqual(result['summary']['coverage']['quantity'], {
            'status': 'partial', 'required': 10, 'available': 9,
            'pending': 1, 'coverage': 0.9, 'minimum_coverage': 0.9,
        })
        self.assertIn(
            'quantity_coverage_partial',
            result['summary']['coverage']['reasons'],
        )

    def test_declared_bad_input_status_cannot_be_overridden_by_true_flag(self):
        r, w, e = inputs()
        r['selection_input_health']['formal']['status'] = 'unavailable'
        self.assertFalse(self.build((r, w, e))['items'][0]['is_executable'])

    def test_missing_candidate_evidence_is_not_execution_permission(self):
        r, w, e = inputs()
        e['views'] = {}
        self.assertFalse(self.build((r, w, e))['items'][0]['is_executable'])

    def test_nonfinal_and_wrong_date_evidence_block(self):
        for change in ({'is_final': False}, {'as_of': '2026-09-04'}):
            with self.subTest(change=change):
                r, w, e = inputs()
                e['views']['main'][0]['daily_structure'].update(change)
                self.assertFalse(self.build((r, w, e))['items'][0]['is_executable'])

    def test_price_missing_retains_formal_action_and_names_missing_field(self):
        r, w, e = inputs()
        del w['views']['main'][0]['formal_decision_contract']['invalidation_price']
        row = self.build((r, w, e))['items'][0]
        self.assertEqual(row.get('formal_action'), '可上车')
        self.assertEqual(row.get('page_status'), 'formal_incomplete')
        self.assertFalse(row['is_executable'])

    def test_invalid_prices_never_execute(self):
        for price in (True, False, 0, -1, float('nan'), float('inf'), '', 'NaN', None):
            with self.subTest(price=price):
                r, w, e = inputs()
                w['views']['main'][0]['formal_decision_contract']['invalidation_price'] = price
                self.assertFalse(self.build((r, w, e))['items'][0]['is_executable'])

    def test_research_does_not_get_formal_price_blockers_or_featured_padding(self):
        r, w, e = inputs()
        row = w['views'].pop('main')[0]
        row.pop('formal_decision_contract')
        row.update(action_semantics='watch_only', primary_reason='涨停后观察')
        w['views']['confirming'] = [row]
        e['views']['confirming'] = e['views'].pop('main')
        e['views']['confirming'][0]['risk_and_next'] = {'status': 'partial'}
        p = self.build((r, w, e)); row = p['items'][0]
        self.assertEqual(row.get('page_status'), 'watch_only')
        self.assertIsNone(row.get('formal_action'))
        self.assertIsNone(row.get('score'))
        self.assertEqual(p['featured_ids'], [])
        self.assertNotIn('missing_pressure_price', row['blocked_reasons'])

    def test_h4_is_formal_even_when_main_is_empty(self):
        r, w, e = inputs()
        w['views']['h4_t3'] = w['views'].pop('main')
        e['views']['h4_t3'] = e['views'].pop('main')
        p = self.build((r, w, e))
        self.assertEqual(p['summary'].get('h4_t3', {}).get('count'), 1)
        self.assertEqual(p['items'][0].get('page_status'), 'formal_ready')

    def test_unavailable_h4_is_not_presented_as_a_normal_zero_count(self):
        r, w, e = inputs()
        w['view_meta']['h4_t3']['availability']['state'] = 'unavailable'
        title = self.build((r, w, e))['summary']['title']
        self.assertIn('H4', title)
        self.assertIn('待核验', title)

    def test_generic_reference_price_does_not_make_research_conditions_complete(self):
        r, w, e = inputs()
        row = w['views'].pop('main')[0]
        row.pop('formal_decision_contract')
        row.update(
            action_semantics='watch_only', reference_price=10,
            price_basis={'adjustment': 'qfq', 'factor_vs_raw': 1.02},
            primary_reason='等待回踩',
        )
        w['views']['confirming'] = [row]
        e['views']['confirming'] = e['views'].pop('main')
        p = self.build((r, w, e))
        self.assertEqual(p['items'][0]['page_status'], 'watch_only')
        self.assertEqual(p['featured_ids'], [])
        row['watch_anchor'] = {
            'value': 9.5,
            'source': 'test.breakout',
            'reference_date': DAY,
            'price_basis': {'adjustment': 'qfq', 'factor_vs_raw': 1.02},
            'purpose': '观察回踩',
        }
        p = self.build((r, w, e))
        self.assertEqual(p['items'][0]['page_status'], 'waiting_trigger')

    def test_score_never_falls_back_to_pool_rank(self):
        r, w, e = inputs()
        w['views']['main'][0].pop('decision_engine_v1')
        self.assertIsNone(self.build((r, w, e))['items'][0].get('score'))

    def test_priority_preserves_pool_order_instead_of_cross_pool_scores(self):
        r, w, e = inputs()
        second = copy.deepcopy(w['views']['main'][0]); second.update(code='600002', view_rank=2, opportunity_score=999)
        w['views']['main'].append(second)
        evidence2 = copy.deepcopy(e['views']['main'][0]); evidence2['code'] = '600002'
        e['views']['main'].append(evidence2)
        p = self.build((r, w, e))
        self.assertEqual([x['code'] for x in p['items']], ['600001', '600002'])

    def test_prior_day_comparison_requires_compatible_valid_facts(self):
        r, w, e = inputs(); previous = self.build((r, w, e))
        r['date'] = '2026-09-08'; r['data_quality']['as_of'] = '2026-09-08T15:05:00+08:00'
        w['views']['main'][0]['data_status']['latest_date'] = '2026-09-08'
        e['report_date'] = '2026-09-08'
        for block in e['views']['main'][0].values():
            if isinstance(block, dict) and 'as_of' in block: block['as_of'] = '2026-09-08'
        self.assertEqual(self.build((r, w, e), previous=previous)['changes']['status'], 'available')
        r['price_basis'] = 'raw'
        self.assertEqual(self.build((r, w, e), previous=previous)['changes']['status'], 'partial')
        self.assertEqual(
            self.build((r, w, e), previous=previous)['changes']['value_comparison_status'],
            'unavailable_price_basis_missing',
        )

    def test_does_not_mutate_inputs_and_has_stable_snapshot_identity(self):
        args = inputs(); before = copy.deepcopy(args)
        a = self.build(args); b = self.build(args)
        self.assertEqual(args, before)
        self.assertEqual(a, b)
        self.assertTrue(a['snapshot_id'])
        self.assertIn('2026-09-07', a['items'][0].get('id', ''))
        json.dumps(a, allow_nan=False)

    def test_observation_reason_is_not_a_conflicting_structure_fact(self):
        from chanlun.recommendation_evidence import _project_daily_structure
        raw = {'best_buy_point': {'type': '启动', 'reason': '低位放量涨停'}}
        row = {'primary_reason': '涨停当日不追，等待次日回踩确认', 'action_semantics': 'watch_only'}
        result = _project_daily_structure(row, raw, copy.deepcopy(raw), {}, DAY)
        self.assertNotIn('summary', result.get('audit_reasons', {}))
        other = copy.deepcopy(raw)
        other['best_buy_point']['reason'] = '相反的结构事实'
        result = _project_daily_structure(row, raw, other, {}, DAY)
        self.assertEqual(result['audit_reasons']['summary'], 'conflict')
