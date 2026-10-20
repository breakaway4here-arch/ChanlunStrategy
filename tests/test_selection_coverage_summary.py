"""Coverage projections keep collection, evaluation, and recommendation scopes apart."""
import copy
import json
from pathlib import Path
import unittest

from chanlun.decision_workbench import _coverage, build_decision_workbench


STATUSES = ('not_requested', 'request_failed', 'price_basis_unverified',
            'risk_rejected', 'valid_no_confirmation', 'passed')


def recorded_report():
    """Synthetic producer contract: two buy points belong to one stock."""
    rows = {
        '600001': {'status': 'price_basis_unverified', 'buy_points': [
            {'status': 'price_basis_unverified'}, {'status': 'price_basis_unverified'}]},
        '600002': {'status': 'valid_no_confirmation', 'buy_points': [
            {'status': 'valid_no_confirmation'}]},
        '600003': {'status': 'passed', 'buy_points': [{'status': 'passed'}]},
    }
    counts = dict.fromkeys(STATUSES, 0)
    for row in rows.values():
        counts[row['status']] += 1
    return {
        'date': '2026-10-19',
        'data_quality': {
            'as_of': '2026-10-19T15:05:00+08:00', 'is_official': True,
            'bar_state': 'closed', 'market_status': 'verified',
            'universe_builder': {'eligibility': {
                'instrument_count': 100, 'eligible_count': 60,
                'excluded': {'nonfinal_bars': 4, 'stale_latest_bar': 2,
                             'listed_days': 9},
                'listing_age_evidence': {'unknown': 8, 'below_minimum': 1},
            }},
        },
        'selection_input_health': {'formal': {
            'formal_actions_allowed': True, 'status': 'verified'}},
        'diagnostics': {
            'candidate_funnel': {'stage_counts': {'full_a': 100, 'eligible': 60, 'retrieval': 40},
                                 'first_failure_counts': {'retrieval': 20}},
            'daily_scan': {'total': 42},
            'sublevel_upgrade_pure': {'evaluation_by_code': rows,
                                      'evaluation_stock_counts': counts,
                                      'evaluation_buy_point_counts': dict(counts,
                                          price_basis_unverified=2)},
            # Fusion reuses pure confirmation; it is not another three stocks.
            'sublevel_upgrade_fusion': {'evaluation_stock_counts': counts},
        },
    }


class SelectionCoverageSummaryTests(unittest.TestCase):
    def test_scanned_quota_and_classic_evaluation_are_distinct_scopes(self):
        report = recorded_report()
        original = copy.deepcopy(report)
        coverage = _coverage(report)
        self.assertEqual(coverage['retrieval'].get('quota_excluded'), 20)
        self.assertEqual(coverage['daily_scan']['scanned'], 42)
        evaluation = coverage['classic_minute30_evaluation']
        self.assertEqual(evaluation['status'], 'recorded')
        self.assertEqual(evaluation['input_count'], 3)
        self.assertEqual(evaluation['stock_counts']['price_basis_unverified'], 1)
        self.assertEqual(evaluation['stock_counts']['valid_no_confirmation'], 1)
        self.assertEqual(evaluation['stock_counts']['passed'], 1)
        self.assertEqual(report, original)

    def test_real_legacy_report_keeps_new_reason_counts_unrecorded(self):
        report = json.loads((Path(__file__).resolve().parents[1]
                            / 'docs/data/2026-10-19.json').read_text())
        coverage = _coverage(report)
        self.assertEqual(coverage['eligibility']['eligible_count'], 3465)
        self.assertEqual(coverage['retrieval'].get('quota_excluded'), 2265)
        self.assertEqual(coverage['daily_scan']['scanned'], 1205)
        self.assertEqual(coverage['classic_minute30_evaluation']['status'], 'unknown')
        self.assertIsNone(coverage['classic_minute30_evaluation']['stock_counts']
                          ['valid_no_confirmation'])
        self.assertIsNone(coverage['eligibility']['listing_age_evidence']['unknown'])

    def test_missing_listing_age_is_separate_from_known_below_minimum(self):
        coverage = _coverage(recorded_report())
        self.assertEqual(coverage['eligibility'].get('listing_age_evidence'),
                         {'unknown': 8, 'below_minimum': 1})

    def test_conflicting_evaluation_counts_do_not_publish_false_totals(self):
        report = recorded_report()
        report['diagnostics']['sublevel_upgrade_pure']['evaluation_stock_counts']\
            ['price_basis_unverified'] = 2
        result = _coverage(report).get('classic_minute30_evaluation', {})
        self.assertEqual(result.get('status'), 'conflict')
        self.assertIsNone(result['stock_counts']['price_basis_unverified'])

    def test_empty_recorded_classic_input_is_true_zero_but_absent_is_unknown(self):
        report = recorded_report()
        report['diagnostics']['sublevel_upgrade_pure'] = {
            'evaluation_by_code': {}, 'evaluation_stock_counts': dict.fromkeys(STATUSES, 0)}
        result = _coverage(report).get('classic_minute30_evaluation', {})
        self.assertEqual(result.get('input_count'), 0)
        self.assertEqual(result['stock_counts']['valid_no_confirmation'], 0)
        self.assertIsNone(_coverage({})['daily_scan']['scanned'])

    def test_quota_count_conflict_does_not_hide_a_collection_mismatch(self):
        report = recorded_report()
        report['diagnostics']['candidate_funnel']['first_failure_counts']['retrieval'] = 19
        result = _coverage(report)
        self.assertIsNone(result['retrieval']['quota_excluded'])
        self.assertIn('retrieval_coverage_conflict', result['reasons'])

    def test_universe_fallback_retrieval_is_not_subtracted_from_funnel_eligibility(self):
        report = recorded_report()
        del report['diagnostics']['candidate_funnel']['stage_counts']['retrieval']
        report['diagnostics']['candidate_funnel']['first_failure_counts'] = {}
        report['data_quality']['universe_builder']['final_count'] = 65
        result = _coverage(report)
        self.assertEqual(result['retrieval']['retrieval'], 65)
        self.assertIsNone(result['retrieval']['quota_excluded'])
        self.assertNotIn('retrieval_coverage_conflict', result['reasons'])

    def test_known_listing_age_rejection_is_not_a_historical_data_hole(self):
        report = recorded_report()
        eligibility = report['data_quality']['universe_builder']['eligibility']
        eligibility['excluded'].update(nonfinal_bars=0, stale_latest_bar=0)
        eligibility['listing_age_evidence'] = {'unknown': 0, 'below_minimum': 9}
        self.assertNotIn('historical_window_exclusions', _coverage(report)['reasons'])

    def test_coverage_pending_does_not_remove_existing_workbench_items(self):
        report = json.loads((Path(__file__).resolve().parents[1]
                            / 'docs/data/2026-10-19.json').read_text())
        before = build_decision_workbench(report, report['workspace'], {})
        report['diagnostics']['sublevel_upgrade_pure'].update(
            recorded_report()['diagnostics']['sublevel_upgrade_pure'])
        after = build_decision_workbench(report, report['workspace'], {})
        self.assertEqual(before['items'], after['items'])
        self.assertEqual(before['summary']['main'], after['summary']['main'])

    def test_verified_empty_main_explains_evaluated_scope_without_promotion(self):
        report = recorded_report()
        workspace = {'views': {'main': [], 'h4_t3': []}, 'view_meta': {
            key: {'availability': {'state': 'verified_empty'}}
            for key in ('main', 'h4_t3')}}
        result = build_decision_workbench(report, workspace, {})
        self.assertIn('已评估范围内暂无正式推荐', result['summary']['title'])
        self.assertIn('覆盖', result['summary']['reason'])
        self.assertEqual(result['summary']['coverage']['formal']['recommendation_count'], 0)
        self.assertEqual(result['items'], [])


if __name__ == '__main__':
    unittest.main()
