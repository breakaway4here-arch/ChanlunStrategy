"""One raw report produces full and light representations of the same facts."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chanlun import report_generator as generator
from scripts import repair_strategy_scorecard_snapshot as repair
from tests.test_report_generator import make_pick, _make_minimal_report_data


def raw_report():
    raw = _make_minimal_report_data()
    for index,code in enumerate(('600519','600036')):
        pick=make_pick(with_30min=False)
        pick['code']=code
        point=dict(pick['best_buy_point'],index=59,date=pick['dates'][-1],price=50.+index)
        pick['best_buy_point']=point
        pick['buy_points']=[copy.deepcopy(point),dict(point,index=5,date=pick['dates'][5],price=53.)]
        raw['picks_pure'].append(pick)
    return raw


class ReportProjectionConsistencyTests(unittest.TestCase):
    def test_normal_full_and_aggregate_writers_agree_without_losing_points_silently(self):
        raw=raw_report()
        with tempfile.TemporaryDirectory() as temporary:
            generator.generate_report(raw,output_dir=temporary,comparison_db_path='')
            full=json.loads((Path(temporary)/'data'/('2026-05-26.json')).read_text())
            generator.update_data_json(raw,output_dir=temporary)
            aggregate=json.loads((Path(temporary)/'data.json').read_text())['reports']['2026-05-26']
        self.assertTrue(repair._aggregate_matches_source(aggregate,full))
        for source,light in zip(full['picks_pure'],aggregate['picks_pure']):
            self.assertEqual(source['code'],light['code'])
            self.assertEqual(source['best_buy_point']['index'],light['best_buy_point']['index'])
            self.assertEqual(len(source['buy_points']),len(light['buy_points']))

    def test_explicit_full_helper_preserves_scores_order_and_does_not_reclip_or_rescore(self):
        self.assertTrue(hasattr(generator,'build_aggregate_day_projection_from_full'))
        full=generator.build_full_daily_projection(raw_report())
        full['picks_pure'].reverse()
        for i,row in enumerate(full['picks_pure']):
            row.update(opportunity_score=7+i,watch_score=19+i,view_rank=8-i)
        before=copy.deepcopy(full)
        with patch.object(generator,'build_workspace',side_effect=AssertionError('no repeated scoring')), \
             patch.object(generator,'_serialize_picks',side_effect=AssertionError('no repeated full serialization')):
            aggregate=generator.build_aggregate_day_projection_from_full(full)
        self.assertEqual(full,before)
        for source,light in zip(full['picks_pure'],aggregate['picks_pure']):
            for key in ('code','score','opportunity_score','watch_score','view_rank','decision_engine_v1'):
                self.assertEqual(source.get(key),light.get(key))
            self.assertEqual(source['best_buy_point']['index'],light['best_buy_point']['index'])

    def test_same_generation_changed_selection_facts_still_fail(self):
        self.assertTrue(hasattr(generator,'build_aggregate_day_projection_from_full'))
        full=generator.build_full_daily_projection(raw_report())
        aggregate=generator.build_aggregate_day_projection_from_full(full)
        for mutate in (
                lambda x:x['picks_pure'][0]['best_buy_point'].update(price=123.),
                lambda x:x['picks_pure'][0].update(score=123.),
                lambda x:x['picks_pure'][0].update(code='600888'),
                lambda x:x['picks_pure'].reverse(),
                lambda x:x['picks_pure'][0]['best_buy_point'].update(index=999),
                lambda x:x['picks_pure'][0]['buy_points'].append(dict(x['picks_pure'][0]['buy_points'][0])),
                lambda x:x['selection_input_health']['formal'].update(formal_actions_allowed=False)):
            candidate=copy.deepcopy(aggregate);mutate(candidate)
            self.assertFalse(repair._aggregate_matches_source(candidate,full))

    def test_update_does_not_borrow_an_old_daily_with_same_generation(self):
        raw=raw_report()
        full=generator.build_full_daily_projection(raw)
        stale=copy.deepcopy(full);stale['picks_pure'][0]['best_buy_point']['price']=999.
        with tempfile.TemporaryDirectory() as temporary:
            data=Path(temporary)/'data';data.mkdir()
            path=data/'2026-05-26.json';path.write_text(json.dumps(stale))
            before=path.read_bytes()
            generator.update_data_json(raw,output_dir=temporary)
            aggregate=json.loads((Path(temporary)/'data.json').read_text())['reports']['2026-05-26']
            self.assertEqual(path.read_bytes(),before)
        self.assertTrue(repair._aggregate_matches_source(aggregate,full))
        self.assertFalse(repair._aggregate_matches_source(aggregate,stale))


if __name__=='__main__':
    unittest.main()
