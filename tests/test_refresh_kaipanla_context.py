"""Isolated fixed-input checks; never read/write the runtime docs or cache."""
import copy
import fcntl
import importlib.util
import json
import os
import plistlib
import shutil
import signal
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from chanlun.report_generator import _build_report_v2_html, _escape_inline_json
from scripts import enable_shadow_evaluation_snapshot as atomic

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.find_spec('scripts.refresh_kaipanla_context')
if SPEC:
    from scripts import refresh_kaipanla_context as refresh
else:
    refresh = None
DAY = '2026-10-08'


def context(day=DAY):
    return {'source': 'kaipanla', 'status': 'available', 'affects_formal': False,
            'data_date': day, 'report_date': DAY, 'coverage': 'returned_sample',
            'fetched_at': DAY + 'T17:20:00+08:00',
            'groups': [{'code': '801001', 'name': '芯片', 'stocks': [
                {'code': '600000', 'name': '样本', 'reason': '已返回样本 <正文>'}]}]}


def report():
    old = context('2026-09-30')
    old['status'] = 'previous_day'
    return {'date': DAY, 'picks_fusion': [{'code': '000001', 'score': 0}],
            'market': {'index': 0}, 'shadow_evaluations': {'status': 'collecting'},
            'data_quality': {'report_date': DAY, 'is_official': True,
                             'is_trading_day': True, 'bar_state': 'closed',
                             'sources_trusted': True, 'market_status': 'verified'},
            'kaipanla_context': old}


class RefreshContextTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(refresh, 'independent refresh entry is not implemented')
        self.temp = tempfile.TemporaryDirectory(prefix='kpl_refresh_test_')
        self.addCleanup(self.temp.cleanup)
        self.docs = (Path(self.temp.name) / 'docs').resolve()
        (self.docs / 'data').mkdir(parents=True)
        (self.docs / DAY).mkdir()
        (self.docs / 'assets').mkdir()
        payload = report()
        (self.docs / 'data' / (DAY+'.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        (self.docs / 'data.json').write_text(json.dumps({'dates': [DAY, '2026-09-30'],
             'extra': 'aggregate envelope untouched', 'reports': {DAY: payload,
             '2026-09-30': {'date': '2026-09-30', 'kept': [0, None]}}}, ensure_ascii=False, indent=2))
        bootstrap = {'pageDate': DAY, 'futureEnvelope': {'retain': True}, 'inlineReportData': payload}
        for relative, prefix in [('index.html', ''), (DAY+'/index.html', '../')]:
            html = _build_report_v2_html(DAY, _escape_inline_json(bootstrap), prefix, 'old-query')
            html = html.replace('</body>', '<aside id="unrelated-widget"><details>retain</details></aside></body>')
            (self.docs / relative).write_text(html)
        for relative in ['assets/report-v2.js', 'assets/report-v2.css', 'data/index.json', 'data/comparison-index.json']:
            (self.docs / relative).write_text('retain original bytes\n')
        self.before = self.bytes()

    def bytes(self):
        return {str(p.relative_to(self.docs)): p.read_bytes() for p in self.docs.rglob('*') if p.is_file()}

    def run_refresh(self, source=None, **kwargs):
        return refresh.refresh_context(self.docs, DAY, context=source if source is not None else context(), **kwargs)

    def test_only_context_bytes_change_in_four_planes(self):
        result = self.run_refresh()
        self.assertEqual(result['status'], 'updated')
        after = self.bytes()
        targets = set(refresh.public_targets(DAY))
        self.assertEqual({p for p in after if after[p] != self.before[p]}, targets)
        for path in targets:
            self.assertEqual(refresh.protected_bytes(self.before[path], path, DAY),
                             refresh.protected_bytes(after[path], path, DAY))
        planes = atomic._load_public_planes(self.docs, DAY)
        for payload in planes.values():
            self.assertEqual(payload['kaipanla_context'], context())
            self.assertEqual({k:v for k,v in payload.items() if k!='kaipanla_context'},
                             {k:v for k,v in report().items() if k!='kaipanla_context'})
        for relative in ['index.html', DAY+'/index.html']:
            self.assertIn('old-query', (self.docs/relative).read_text())
            self.assertIn('unrelated-widget', (self.docs/relative).read_text())
            self.assertEqual(atomic._read_bootstrap_envelope(self.docs/relative)['futureEnvelope'], {'retain': True})
            self.assertIn('id="kaipanla-context"', (self.docs/relative).read_text())
            self.assertIn('资料日期 '+DAY, (self.docs/relative).read_text())

    def test_parser_partial_and_confirmed_empty_groups_refresh_all_four_planes(self):
        from chanlun.kaipanla import parse_themes
        stock = ['600001', '甲'] + [''] * 15 + ['开盘啦原文']
        raw = {'errcode': '0', 'date': DAY, '_fetched_at': DAY+'T17:20:00+08:00',
               'list': [
                   {'ZSCode': 'A', 'ZSName': 'AI 应用', 'StockList': [stock]},
                   {'ZSCode': 'B', 'ZSName': '股票明细未取得', 'StockList': 3},
                   {'ZSCode': 'C', 'ZSName': '确证空题材', 'StockList': []},
               ]}
        parsed = parse_themes(raw, DAY)
        self.assertEqual(parsed['status'], 'partial')
        invalid = copy.deepcopy(parsed)
        invalid['groups'][0]['stocks'][0]['code'] = '200001'
        self.assertEqual(self.run_refresh(invalid)['status'], 'skipped')
        stale_raw = dict(raw, date='2026-10-07')
        previous = parse_themes(stale_raw, DAY)
        self.assertEqual(previous['status'], 'previous_day')
        self.assertEqual(self.run_refresh(previous)['status'], 'skipped')
        self.assertEqual(self.bytes(), self.before)
        self.assertEqual(self.run_refresh(parsed)['status'], 'updated')
        after = self.bytes()
        self.assertEqual({p for p in after if after[p] != self.before[p]},
                         set(refresh.public_targets(DAY)))
        for relative in refresh.public_targets(DAY):
            self.assertEqual(refresh.protected_bytes(self.before[relative], relative, DAY),
                             refresh.protected_bytes(after[relative], relative, DAY))
        planes = atomic._load_public_planes(self.docs, DAY)
        for payload in planes.values():
            self.assertEqual(payload['kaipanla_context'], parsed)
        self.assertEqual([(g['name'], g['stock_list_status']) for g in parsed['groups']],
                         [('AI 应用', 'available'), ('股票明细未取得', 'unavailable'),
                          ('确证空题材', 'available')])
        raw['list'] = [{'ZSCode': 'C', 'ZSName': '确证空题材', 'StockList': []}]
        empty = parse_themes(raw, DAY)
        self.assertEqual(empty['status'], 'available')
        self.assertEqual(self.run_refresh(empty)['status'], 'updated')
        for payload in atomic._load_public_planes(self.docs, DAY).values():
            self.assertEqual(payload['kaipanla_context'], empty)

    def test_later_partial_missing_details_keeps_earlier_verified_source_version(self):
        from chanlun.kaipanla import parse_themes
        stock = ['600001', '甲'] + [''] * 15 + ['17:30 题材原因']
        raw = {'errcode': '0', 'date': DAY, '_fetched_at': DAY+'T17:30:00+08:00',
               'list': [{'ZSCode': 'A', 'ZSName': 'AI 应用', 'StockList': [stock]}]}
        complete = parse_themes(raw, DAY)
        self.assertEqual(self.run_refresh(complete)['status'], 'updated')
        prior = self.bytes()
        raw['_fetched_at'] = DAY+'T18:00:00+08:00'
        raw['list'][0]['StockList'] = 3
        partial = parse_themes(raw, DAY)
        self.assertEqual(partial['status'], 'partial')
        self.assertEqual(partial['groups'][0]['stocks'], [])
        result = self.run_refresh(partial)
        self.assertEqual(result, {'status': 'skipped', 'report_date': DAY,
                                  'reason': 'would_discard_verified_theme_details'})
        self.assertEqual(self.bytes(), prior)
        for payload in atomic._load_public_planes(self.docs, DAY).values():
            self.assertEqual(payload['kaipanla_context'], complete)
            self.assertEqual(payload['kaipanla_context']['fetched_at'],
                             DAY+'T17:30:00+08:00')
        raw['list'][0]['StockList'] = []
        confirmed_empty = parse_themes(raw, DAY)
        self.assertEqual(confirmed_empty['status'], 'available')
        self.assertEqual(self.run_refresh(confirmed_empty)['status'], 'updated')
        for payload in atomic._load_public_planes(self.docs, DAY).values():
            self.assertEqual(payload['kaipanla_context'], confirmed_empty)
        raw['_fetched_at'] = DAY+'T18:30:00+08:00'
        raw['list'][0]['StockList'] = [stock]
        complete_new = parse_themes(raw, DAY)
        self.assertEqual(self.run_refresh(complete_new)['status'], 'updated')
        for payload in atomic._load_public_planes(self.docs, DAY).values():
            self.assertEqual(payload['kaipanla_context'], complete_new)

    def test_partial_omitting_existing_verified_group_is_skipped(self):
        from chanlun.kaipanla import parse_themes
        stock = ['600001', '甲'] + [''] * 15 + ['原文']
        raw = {'errcode': '0', 'date': DAY, '_fetched_at': DAY+'T17:30:00+08:00',
               'list': [{'ZSCode': 'A', 'ZSName': 'AI 应用', 'StockList': [stock]}]}
        self.assertEqual(self.run_refresh(parse_themes(raw, DAY))['status'], 'updated')
        prior = self.bytes()
        raw['_fetched_at'] = DAY+'T18:00:00+08:00'
        raw['list'] = [{'ZSCode': 'B', 'ZSName': '未知组', 'StockList': 3}]
        incoming = parse_themes(raw, DAY)
        self.assertEqual(incoming['status'], 'partial')
        self.assertEqual(self.run_refresh(incoming)['reason'],
                         'would_discard_verified_theme_details')
        self.assertEqual(self.bytes(), prior)

    def test_partial_blank_theme_name_keeps_earlier_verified_name(self):
        from chanlun.kaipanla import parse_themes
        stock = ['600001', '甲'] + [''] * 15 + ['原文']
        raw = {'errcode': '0', 'date': DAY, '_fetched_at': DAY+'T17:30:00+08:00',
               'list': [{'ZSCode': 'A', 'ZSName': 'AI 应用', 'StockList': [stock]}]}
        original = parse_themes(raw, DAY)
        self.assertEqual(self.run_refresh(original)['status'], 'updated')
        prior = self.bytes()
        raw['_fetched_at'] = DAY+'T18:00:00+08:00'
        raw['list'][0]['ZSName'] = ''
        raw['list'].append({'ZSCode': 'B', 'ZSName': '坏明细', 'StockList': 3})
        partial = parse_themes(raw, DAY)
        self.assertEqual(partial['status'], 'partial')
        self.assertEqual(partial['groups'][0]['name'], '')
        self.assertEqual([s['code'] for s in partial['groups'][0]['stocks']], ['600001'])
        self.assertEqual(self.run_refresh(partial),
                         {'status': 'skipped', 'report_date': DAY,
                          'reason': 'would_discard_verified_theme_details'})
        self.assertEqual(self.bytes(), prior)
        for payload in atomic._load_public_planes(self.docs, DAY).values():
            self.assertEqual(payload['kaipanla_context'], original)


    def test_baseline_context_and_html_report_mismatch_are_rejected(self):
        for relative in ['data.json','index.html']:
            with self.subTest(relative=relative):
                path=self.docs/relative
                text=path.read_bytes().decode()
                if relative=='data.json':
                    changed=refresh._replace_member(text,['reports',DAY,'kaipanla_context','fetched_at'],json.dumps('different'))
                else:
                    start,end,_=refresh._bootstrap_location(text)
                    inner=refresh._replace_member(text[start:end],['inlineReportData','market'],json.dumps({'index':999}))
                    changed=text[:start]+inner+text[end:]
                path.write_bytes(changed.encode())
                baseline=self.bytes()
                with self.assertRaisesRegex(ValueError,'baseline|mapping'):
                    self.run_refresh()
                self.assertEqual(self.bytes(),baseline)
                path.write_bytes(self.before[relative])

    def test_aggregate_projection_without_date_is_supported(self):
        path=self.docs/'data.json'; obj=json.loads(path.read_bytes())
        obj['reports'][DAY].pop('date')
        obj['reports'][DAY]['picks_fusion']=[]
        path.write_text(json.dumps(obj,ensure_ascii=False))
        before=path.read_bytes()
        self.assertEqual(self.run_refresh()['status'],'updated')
        self.assertEqual(refresh.protected_bytes(before,'data.json',DAY),refresh.protected_bytes(path.read_bytes(),'data.json',DAY))

    def test_unattested_or_timezone_missing_fetched_at_is_rejected(self):
        for stamp in [None,'invalid',DAY+'T15:20:00']:
            item=context(); item['fetched_at']=stamp
            self.assertEqual(self.run_refresh(item)['status'],'skipped')
            self.assertEqual(self.bytes(),self.before)

    def test_abrupt_subprocess_exit_recovers_before_loading_mixed_baseline(self):
        input_path=Path(self.temp.name)/'frozen.json';input_path.write_text(json.dumps(context()))
        code="""import os, signal, sys
from pathlib import Path
from scripts import refresh_kaipanla_context as r
original=r.atomic.os.replace
def abrupt(src,dst):
    result=original(src,dst)
    if Path(dst)==Path(sys.argv[1])/'index.html':
        os.kill(os.getpid(),signal.SIGKILL)
    return result
r.atomic.os.replace=abrupt
r.refresh_context(Path(sys.argv[1]),sys.argv[2],input_path=Path(sys.argv[3]))
"""
        proc=subprocess.run(['/usr/bin/python3','-c',code,str(self.docs),DAY,str(input_path)],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(proc.returncode,-9,proc.stderr)
        self.assertTrue(atomic.transaction_journal_path(self.docs).exists())
        mixed=self.bytes()
        self.assertNotEqual(mixed,self.before)
        with self.assertRaisesRegex(RuntimeError,'recovery'):
            self.run_refresh(dry_run=True)
        self.assertEqual(self.bytes(),mixed)
        unavailable=context();unavailable['groups']=[]
        self.assertEqual(self.run_refresh(unavailable)['status'],'skipped')
        self.assertEqual(self.bytes(),self.before)
        self.assertFalse(atomic.transaction_journal_path(self.docs).exists())
        self.assertFalse(list(self.docs.parent.glob('.chanlun-shadow-stage-*')))

    def test_dry_run_is_read_only(self):
        self.assertEqual(self.run_refresh(dry_run=True)['status'], 'dry_run')
        self.assertEqual(self.bytes(), self.before)

    def test_unavailable_empty_old_future_wrong_report_and_formal_inputs_do_not_write(self):
        variants=[]
        for key, value in [('status','unavailable'), ('groups',[]), ('data_date','2026-09-30'),
                           ('data_date','2026-10-09'), ('report_date','2026-09-30'),
                           ('affects_formal',True), ('source','other')]:
            item=context(); item[key]=value; variants.append(item)
        item=context(); item['groups'][0]['stocks']=[]; variants.append(item)
        item=context(); item['groups'][0]['stocks'][0]['code']='200001'; variants.append(item)
        for value in variants:
            with self.subTest(value=value):
                self.assertEqual(self.run_refresh(value)['status'], 'skipped')
                self.assertEqual(self.bytes(), self.before)

    def test_repeat_data_ignores_new_fetch_timestamp(self):
        self.run_refresh()
        first = self.bytes()
        later=context(); later['fetched_at']=DAY+'T17:30:00+08:00'
        self.assertEqual(self.run_refresh(later)['status'], 'no_changes')
        self.assertEqual(self.bytes(), first)

    def test_existing_current_context_with_missing_static_card_is_repaired(self):
        self.run_refresh()
        path=self.docs/'index.html';text=path.read_bytes().decode();span=refresh.card_span(text)
        path.write_bytes((text[:span[0]]+text[span[1]:]).encode())
        first=json.loads((self.docs/'data'/(DAY+'.json')).read_bytes())['kaipanla_context']
        later=context();later['fetched_at']=DAY+'T18:00:00+08:00'
        self.assertEqual(self.run_refresh(later)['status'],'updated')
        self.assertIsNotNone(refresh.card_span(path.read_bytes().decode()))
        self.assertEqual(json.loads((self.docs/'data'/(DAY+'.json')).read_bytes())['kaipanla_context'],first)

    def test_reason_can_quote_bootstrap_assignment_without_hiding_valid_report(self):
        source=context();source['groups'][0]['stocks'][0]['reason']='window.CHANLUN_BOOTSTRAP = informational text'
        self.assertEqual(self.run_refresh(source)['status'],'updated')
        self.assertEqual(self.run_refresh(source)['status'],'no_changes')

    def test_missing_card_is_inserted_without_rebuilding_html(self):
        for relative in ['index.html', DAY+'/index.html']:
            path=self.docs/relative; text=path.read_text(); span=refresh.card_span(text)
            path.write_text(text[:span[0]]+text[span[1]:])
        baseline=self.bytes()
        self.run_refresh()
        for relative in ['index.html', DAY+'/index.html']:
            self.assertEqual(refresh.protected_bytes(baseline[relative],relative,DAY),
                             refresh.protected_bytes(self.bytes()[relative],relative,DAY))

    def test_concurrent_change_is_not_overwritten(self):
        original=refresh.apply_plan
        path=self.docs/'index.html'
        newer=None
        def conflict(*args, **kwargs):
            nonlocal newer
            newer=path.read_bytes()+b'<!-- concurrent update -->'
            path.write_bytes(newer)
            return original(*args, **kwargs)
        with mock.patch.object(refresh,'apply_plan',side_effect=conflict):
            with self.assertRaisesRegex(RuntimeError,'changed'):
                self.run_refresh()
        self.assertEqual(path.read_bytes(),newer)
        for relative in refresh.public_targets(DAY):
            if relative!='index.html': self.assertEqual((self.docs/relative).read_bytes(),self.before[relative])

    def test_mid_apply_error_restores_all_four_files_and_releases_lock(self):
        actual_replace=os.replace; calls=0
        def fail_once(src,dst):
            nonlocal calls
            if str(dst).startswith(str(self.docs)):
                calls+=1
                if calls==3: raise OSError('injected third replace failure')
            return actual_replace(src,dst)
        with mock.patch.object(refresh.os,'replace',side_effect=fail_once):
            with self.assertRaisesRegex(OSError,'injected'):
                self.run_refresh()
        self.assertEqual(self.bytes(),self.before)
        self.assertFalse(list(self.docs.parent.glob('.chanlun-kpl-stage-*')))
        self.assertEqual(self.run_refresh()['status'],'updated')

    def test_identity_gate_precedes_network_and_rejects_nonofficial_reports(self):
        path=self.docs/'data'/(DAY+'.json'); payload=json.loads(path.read_text())
        payload['data_quality']['is_official']=False; path.write_text(json.dumps(payload))
        before=self.bytes()
        with mock.patch.object(refresh,'fetch_themes') as fetch:
            with self.assertRaisesRegex(ValueError,'official'):
                refresh.refresh_context(self.docs,DAY,cache_dir=Path(self.temp.name)/'cache')
            fetch.assert_not_called()
        self.assertEqual(self.bytes(),before)

    def test_network_is_one_force_refresh_with_explicit_cache(self):
        cache=Path(self.temp.name)/'cache'
        with mock.patch.object(refresh,'fetch_themes',return_value=context()) as fetch:
            self.assertEqual(refresh.refresh_context(self.docs,DAY,cache_dir=cache)['status'],'updated')
        fetch.assert_called_once_with(DAY,cache_dir=cache,force_refresh=True)

    def test_lock_timeout_preserves_files_and_release_allows_retry(self):
        lock_path=atomic.docs_publish_lock_path(self.docs)
        lock_path.parent.mkdir(parents=True,exist_ok=True)
        descriptor=os.open(lock_path,os.O_RDWR|os.O_CREAT,0o600)
        try:
            fcntl.flock(descriptor,fcntl.LOCK_EX)
            with self.assertRaisesRegex(TimeoutError,'lock'):
                self.run_refresh(lock_timeout=0.02)
            self.assertEqual(self.bytes(),self.before)
        finally:
            os.close(descriptor)
        self.assertEqual(self.run_refresh()['status'],'updated')

    def test_crlf_reason_script_text_and_nested_details_preserve_protected_bytes(self):
        source=context(); source['groups'][0]['stocks'][0]['reason']='line1\r\n}; </script><details>line2'
        self.assertEqual(self.run_refresh(source)['status'],'updated')
        for relative in refresh.public_targets(DAY):
            self.assertEqual(refresh.protected_bytes(self.before[relative],relative,DAY),
                             refresh.protected_bytes(self.bytes()[relative],relative,DAY))
        text=(self.docs/'index.html').read_bytes().decode()
        _,_,envelope=refresh._bootstrap_location(text)
        self.assertEqual(envelope['inlineReportData']['kaipanla_context'],source)
        self.assertIn('\\u003c/script\\u003e',text)

    def test_outer_wrapper_inherits_exact_live_lock_and_releases_at_exit(self):
        code="""import fcntl,os,sys
from pathlib import Path
path=Path(os.environ['CHANLUN_DOCS_PUBLISH_LOCK_PATH'])
assert int(os.environ['CHANLUN_KPL_PUBLISH_LOCK_FD'])>=3
other=os.open(path,os.O_RDWR)
try:
    fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:
    pass
else:
    raise AssertionError('outer command has no live shared lock')
os.close(other)
"""
        proc=subprocess.run(['/usr/bin/python3',str(ROOT/'scripts/refresh_kaipanla_context.py'),
            '--docs-dir',str(self.docs),'--with-lock','/usr/bin/python3','-c',code],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        descriptor=os.open(atomic.docs_publish_lock_path(self.docs),os.O_RDWR)
        try: fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally: os.close(descriptor)

    def test_cli_frozen_input_dry_run_and_default_has_no_git(self):
        input_path=Path(self.temp.name)/'frozen.json'; input_path.write_text(json.dumps(context()))
        completed=subprocess.run(['/usr/bin/python3',str(ROOT/'scripts/refresh_kaipanla_context.py'),
            '--docs-dir',str(self.docs),'--report-date',DAY,'--input',str(input_path),'--dry-run'],capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['status'],'dry_run')
        self.assertEqual(self.bytes(),self.before)


class ScheduleTests(unittest.TestCase):
    def test_schedule_is_once_late_weekdays_and_runtime_paths_are_exact(self):
        path=ROOT/'launchd/com.breakaway4here.chanlun-kaipanla-refresh.plist'
        self.assertTrue(path.exists(), 'late refresh schedule is not implemented')
        obj=plistlib.loads(path.read_bytes())
        root='/Users/yangfan/yf_source/ChanlunStrategy/.worktrees/production-runtime'
        self.assertEqual(obj['WorkingDirectory'],root)
        self.assertEqual(obj['ProgramArguments'],['/bin/zsh',root+'/scripts/kaipanla_refresh.sh'])
        self.assertFalse(obj['RunAtLoad'])
        self.assertNotIn('KeepAlive',obj)
        self.assertEqual(obj['StartCalendarInterval'],[{'Weekday':day,'Hour':17,'Minute':30} for day in range(1,6)])

    def test_shell_gates_synchronizes_and_stages_only_four_files(self):
        path=ROOT/'scripts/kaipanla_refresh.sh'
        self.assertTrue(path.exists(), 'refresh shell is not implemented')
        text=path.read_text()
        self.assertIn('--with-lock',text)
        self.assertIn('TZ=Asia/Shanghai',text)
        self.assertIn('--check-ready',text)
        self.assertIn('git merge --ff-only origin/main',text)
        self.assertIn('git merge-base --is-ancestor origin/main HEAD',text)
        self.assertIn('git add -- "${TARGETS[@]}"',text)
        self.assertIn('git diff --cached --quiet',text)
        self.assertIn('timeout=30',text)
        self.assertIn('git status --porcelain=v1 --untracked-files=all -- "${TARGETS[@]}"',text)
        for forbidden in ['daily_run','import run','notify','git add -A','git add .','reset --hard','stash']:
            self.assertNotIn(forbidden,text)
        subprocess.run(['/bin/zsh','-n',str(path)],check=True)


class ScheduleGitIntegrationTests(unittest.TestCase):
    def setUp(self):
        today=datetime.now(timezone(timedelta(hours=8))).date()
        if today.weekday()>=5: self.skipTest('late weekday job does not run on weekends')
        self.today=today.isoformat()
        self.temp=tempfile.TemporaryDirectory(prefix='kpl_schedule_git_test_')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve()
        self.repo=self.base/'repo';self.repo.mkdir()
        self.remote=self.base/'remote.git'
        self._git('init','--bare',str(self.remote),cwd=self.base)
        self._git('init','-b','main')
        self._git('config','user.email','test@example.invalid')
        self._git('config','user.name','KPL Test')
        (self.repo/'scripts').mkdir();(self.repo/'docs/data').mkdir(parents=True)
        (self.repo/('docs/'+self.today)).mkdir();(self.repo/'docs/assets').mkdir()
        for name in ['refresh_kaipanla_context.py','kaipanla_refresh.sh']:
            shutil.copy2(ROOT/'scripts'/name,self.repo/'scripts'/name)
        (self.repo/'scripts/enable_shadow_evaluation_snapshot.py').symlink_to(ROOT/'scripts/enable_shadow_evaluation_snapshot.py')
        (self.repo/'chanlun').symlink_to(ROOT/'chanlun',target_is_directory=True)
        (self.repo/'config.py').symlink_to(ROOT/'config.py')
        (self.repo/'.gitignore').write_text('chanlun\nconfig.py\nscripts/enable_shadow_evaluation_snapshot.py\n.cache/\n')
        payload=json.loads(json.dumps(report()).replace(DAY,self.today))
        (self.repo/('docs/data/'+self.today+'.json')).write_text(json.dumps(payload))
        projected=copy.deepcopy(payload);projected.pop('date')
        (self.repo/'docs/data.json').write_text(json.dumps({'dates':[self.today],'reports':{self.today:projected}}))
        bootstrap={'pageDate':self.today,'inlineReportData':payload}
        for path in ['docs/index.html','docs/'+self.today+'/index.html']:
            (self.repo/path).write_text(_build_report_v2_html(self.today,_escape_inline_json(bootstrap),asset_version='kept'))
        for path in ['docs/assets/report-v2.js','docs/assets/report-v2.css','docs/data/index.json']:
            (self.repo/path).write_text('preserved')
        (self.repo/'notes.txt').write_text('other task original')
        self._git('add','.')
        self._git('commit','-m','chore: isolated schedule fixture')
        self._git('remote','add','origin',str(self.remote))
        self._git('push','-u','origin','main')
        self.old_head=self._git('rev-parse','HEAD').strip()
        (self.repo/'notes.txt').write_text('other task unfinished')
        source=json.loads(json.dumps(context()).replace(DAY,self.today))
        self.input=self.base/'source.json';self.input.write_text(json.dumps(source))
        self.call_log=self.base/'source-calls.txt'
        wrapper=self.base/'mock-python'
        wrapper.write_text('#!/usr/bin/python3\nimport os,sys\nfrom pathlib import Path\nargs=sys.argv[1:]\nif "--check-ready" not in args:\n    p=Path(os.environ["KPL_TEST_CALL_LOG"]);p.write_text(p.read_text()+"source\\n" if p.exists() else "source\\n")\n    args += ["--input",os.environ["KPL_TEST_INPUT"]]\nos.execv("/usr/bin/python3",["/usr/bin/python3"]+args)\n')
        wrapper.chmod(0o700)
        (self.base/'tmp').mkdir()
        self.env=dict(os.environ,CHANLUN_KPL_PYTHON=str(wrapper),KPL_TEST_INPUT=str(self.input),KPL_TEST_CALL_LOG=str(self.call_log),TMPDIR=str(self.base/'tmp'))
        for key in ['CHANLUN_DOCS_PUBLISH_LOCK_HELD','CHANLUN_DOCS_PUBLISH_LOCK_PATH','CHANLUN_KPL_PUBLISH_LOCK_FD']:
            self.env.pop(key,None)

    def _git(self,*args,cwd=None):
        proc=subprocess.run(['git',*args],cwd=cwd or self.repo,capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        return proc.stdout

    def schedule(self):
        return subprocess.run(['/bin/zsh',str(self.repo/'scripts/kaipanla_refresh.sh')],cwd=self.repo,env=self.env,capture_output=True,text=True,timeout=30)

    def test_real_local_git_publishes_exact_four_files_and_keeps_unrelated_dirty(self):
        proc=self.schedule()
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        changed=self._git('diff-tree','--no-commit-id','--name-only','-r','HEAD').splitlines()
        self.assertEqual(set(changed),{'docs/'+path for path in refresh.public_targets(self.today)})
        self.assertEqual(self._git('rev-parse','HEAD').strip(),self._git('rev-parse','origin/main').strip())
        self.assertEqual((self.repo/'notes.txt').read_text(),'other task unfinished')
        self.assertEqual(self._git('diff','--name-only').splitlines(),['notes.txt'])
        first_head=self._git('rev-parse','HEAD')
        proc=self.schedule()
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assertEqual(self._git('rev-parse','HEAD'),first_head)
        self.assertIn('no_changes',proc.stdout)
        self.assertEqual(self.call_log.read_text().splitlines(),['source','source'])

    def install_git_failure(self, mode):
        self.before_docs={str(p.relative_to(self.repo/'docs')):p.read_bytes() for p in (self.repo/'docs').rglob('*') if p.is_file()}
        tool_dir=self.base/'bin';tool_dir.mkdir(exist_ok=True)
        wrapper=tool_dir/'git'
        wrapper.write_text("""#!/usr/bin/python3
import os,sys
from pathlib import Path
real=os.environ['KPL_TEST_REAL_GIT']
args=sys.argv[1:]
command=list(args)
while command and command[0]=='-c': command=command[2:]
mode=os.environ['KPL_TEST_GIT_FAILURE']
if command and command[0]=='fetch':
    marker=Path(os.environ['KPL_TEST_FETCH_COUNT'])
    count=int(marker.read_text())+1 if marker.exists() else 1
    marker.write_text(str(count))
    if count==2 and mode=='remote_advanced':
        import subprocess
        subprocess.run([real,'--git-dir',os.environ['KPL_TEST_REMOTE'],'update-ref','refs/heads/main',os.environ['KPL_TEST_FUTURE_SHA']],check=True)
    if count==2 and mode=='concurrent_target':
        path=Path.cwd()/'docs/index.html';path.write_bytes(path.read_bytes()+b'<!-- other task concurrent -->')
    if count==2 and mode=='other_staged':
        import subprocess
        subprocess.run([real,'add','notes.txt'],check=True)
if command and command[0]=='commit' and mode=='concurrent_index':
    import subprocess
    path=Path.cwd()/'docs/index.html';saved=path.read_bytes()
    path.write_bytes(saved+b'<!-- other task index -->')
    subprocess.run([real,'add','docs/index.html'],check=True)
    path.write_bytes(saved)
    print('injected concurrent index rejection',file=sys.stderr);raise SystemExit(1)
if command and command[0]=='commit' and mode=='commit_failed':
    print('injected commit rejection',file=sys.stderr);raise SystemExit(1)
if command and command[0]=='push' and mode=='push_failed':
    print('injected push rejection',file=sys.stderr);raise SystemExit(1)
os.execv(real,[real]+args)
""")
        wrapper.chmod(0o700)
        self.env.update(PATH=str(tool_dir)+os.pathsep+os.environ['PATH'],KPL_TEST_REAL_GIT=shutil.which('git'),
                        KPL_TEST_GIT_FAILURE=mode,KPL_TEST_FETCH_COUNT=str(self.base/'fetch-count'),KPL_TEST_REMOTE=str(self.remote))
        if mode=='remote_advanced':
            future=self.base/'future';self._git('clone',str(self.remote),str(future),cwd=self.base)
            self._git('checkout','main',cwd=future)
            self._git('config','user.email','test@example.invalid',cwd=future)
            self._git('config','user.name','KPL Test',cwd=future)
            (future/'future.txt').write_text('new remote work')
            self._git('add','future.txt',cwd=future);self._git('commit','-m','chore: later remote commit',cwd=future)
            self._git('push','origin','HEAD:refs/heads/future-test',cwd=future)
            self.env['KPL_TEST_FUTURE_SHA']=self._git('rev-parse','HEAD',cwd=future).strip()

    def assert_docs_restored(self):
        after={str(p.relative_to(self.repo/'docs')):p.read_bytes() for p in (self.repo/'docs').rglob('*') if p.is_file()}
        self.assertEqual(after,self.before_docs)
        self.assertEqual(self._git('rev-parse','HEAD').strip(),self.old_head)

    def test_commit_failure_restores_only_own_targets_and_index(self):
        self.install_git_failure('commit_failed')
        proc=self.schedule();self.assertNotEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assert_docs_restored()
        self.assertEqual(self._git('diff','--cached','--name-only').splitlines(),[])
        self.assertEqual(self._git('diff','--name-only').splitlines(),['notes.txt'])
        self.assertIn('restored_uncommitted',proc.stderr)

    def test_remote_advance_after_refresh_restores_own_targets(self):
        self.install_git_failure('remote_advanced')
        proc=self.schedule();self.assertNotEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assert_docs_restored()
        self.assertEqual(self._git('diff','--cached','--name-only').splitlines(),[])
        self.assertEqual(self._git('rev-parse','origin/main').strip(),self.env['KPL_TEST_FUTURE_SHA'])

    def test_other_index_change_is_preserved_while_own_targets_restore(self):
        self.install_git_failure('other_staged')
        proc=self.schedule();self.assertNotEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assert_docs_restored()
        self.assertEqual(self._git('diff','--cached','--name-only').splitlines(),['notes.txt'])
        self.assertEqual((self.repo/'notes.txt').read_text(),'other task unfinished')

    def test_concurrent_target_blocks_rollback_and_keeps_receipt(self):
        self.install_git_failure('concurrent_target')
        proc=self.schedule();self.assertNotEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assertIn('preserved_concurrent_target',proc.stderr)
        self.assertIn('补更receipt',proc.stderr)
        self.assertTrue((self.repo/'docs/index.html').read_bytes().endswith(b'<!-- other task concurrent -->'))
        self.assertTrue(list((self.base/'tmp').glob('chanlun-kpl-result.*')))
        self.assertEqual(self._git('rev-parse','HEAD').strip(),self.old_head)

    def test_concurrent_target_index_blocks_rollback_without_unstaging_other_bytes(self):
        self.install_git_failure('concurrent_index')
        proc=self.schedule();self.assertNotEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assertIn('preserved_concurrent_index',proc.stderr)
        self.assertTrue(self._git('show',':docs/index.html').endswith('<!-- other task index -->'))
        self.assertTrue(list((self.base/'tmp').glob('chanlun-kpl-result.*')))
        self.assertEqual(self._git('rev-parse','HEAD').strip(),self.old_head)

    def test_push_failure_keeps_commit_and_prints_pending_sha(self):
        self.install_git_failure('push_failed')
        proc=self.schedule();self.assertNotEqual(proc.returncode,0,proc.stdout+proc.stderr)
        current=self._git('rev-parse','HEAD').strip()
        self.assertNotEqual(current,self.old_head)
        self.assertEqual(self._git('rev-parse','origin/main').strip(),self.old_head)
        self.assertEqual(self._git('diff','--cached','--name-only').splitlines(),[])
        self.assertEqual(self._git('diff','--name-only').splitlines(),['notes.txt'])
        self.assertIn(current,proc.stderr)
        self.assertIn('HEAD:main',proc.stderr)

    def test_shared_cache_symlink_uses_canonical_lock_without_wrapper_loop(self):
        shared=self.base/'shared-cache';shared.mkdir()
        (self.repo/'.cache').mkdir()
        (self.repo/'.cache/chanlun').symlink_to(shared,target_is_directory=True)
        process=subprocess.Popen(['/bin/zsh',str(self.repo/'scripts/kaipanla_refresh.sh')],
            cwd=self.repo,env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,start_new_session=True)
        timed_out=False
        try:
            stdout,stderr=process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            timed_out=True
            os.killpg(process.pid,signal.SIGTERM)
            try:
                stdout,stderr=process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL)
                stdout,stderr=process.communicate()
        self.assertFalse(timed_out,'shared-cache symlink caused repeated lock wrapper execution')
        self.assertEqual(process.returncode,0,stdout+stderr)
        self.assertTrue((shared/'docs-publish.lock').is_file())
        self.assertEqual(self.call_log.read_text().splitlines(),['source'])
        self.assertEqual(self._git('rev-parse','HEAD').strip(),self._git('rev-parse','origin/main').strip())

    def test_autocrlf_input_with_provider_crlf_reason_publishes_without_json_loss(self):
        self._git('config','core.autocrlf','input')
        source=json.loads(self.input.read_bytes())
        source['groups'][0]['stocks'][0]['reason']='provider line one\r\nprovider line two'
        self.input.write_text(json.dumps(source))
        before={relative:(self.repo/'docs'/relative).read_bytes() for relative in refresh.public_targets(self.today)}
        proc=self.schedule()
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        for relative,original in before.items():
            after=(self.repo/'docs'/relative).read_bytes()
            self.assertEqual(refresh.protected_bytes(original,relative,self.today),refresh.protected_bytes(after,relative,self.today))
            staged=subprocess.check_output(['git','show','HEAD:docs/'+relative],cwd=self.repo)
            self.assertEqual(after,staged)
        daily=json.loads((self.repo/('docs/data/'+self.today+'.json')).read_bytes())
        self.assertEqual(daily['kaipanla_context']['groups'][0]['stocks'][0]['reason'],source['groups'][0]['stocks'][0]['reason'])
        for relative in ['index.html',self.today+'/index.html']:
            text=(self.repo/'docs'/relative).read_bytes().decode()
            span=refresh.card_span(text)
            self.assertNotIn('\r\n',text[span[0]:span[1]])

    def test_existing_dirty_target_stops_before_source_and_preserves_all_work(self):
        path=self.repo/'docs/index.html';path.write_bytes(path.read_bytes()+b'<!-- another task -->')
        before=path.read_bytes()
        proc=self.schedule()
        self.assertNotEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assertIn('目标已有改动',proc.stderr)
        self.assertFalse(self.call_log.exists())
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self._git('rev-parse','HEAD').strip(),self.old_head)


if __name__=='__main__': unittest.main()
