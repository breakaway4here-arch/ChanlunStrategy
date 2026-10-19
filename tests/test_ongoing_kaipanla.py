"""Real ongoing/KPL shells and local Git; business jobs/provider remain frozen."""
import copy
import fcntl
import hashlib
import json
import os
import signal
import shutil
import subprocess
import time
import unittest
from pathlib import Path

from tests import test_refresh_kaipanla_context as fixture


ROOT = Path(__file__).resolve().parents[1]
PYTHON = '/usr/bin/python3'


class OngoingKaipanlaTests(unittest.TestCase):
    _git = fixture.ScheduleGitIntegrationTests._git
    schedule = fixture.ScheduleGitIntegrationTests.schedule
    install_git_failure = fixture.ScheduleGitIntegrationTests.install_git_failure
    pending_fixture = fixture.ScheduleGitIntegrationTests.pending_fixture

    def setUp(self):
        fixture.ScheduleGitIntegrationTests.setUp(self)
        self.events = self.base/'events.jsonl'
        router = self.base/'business-python'
        router.write_text(r'''#!/usr/bin/python3
import json,os,pathlib,shutil,sys
args=sys.argv[1:]
name=pathlib.Path(args[0]).name
if name in ('run_with_docs_publish_lock.py','run_daily_git_network.py','formal_publish_guard.py'):
    os.execv('/usr/bin/python3',['/usr/bin/python3']+args)
repo=pathlib.Path(os.environ['ONGOING_TEST_REPO'])
with open(os.environ['ONGOING_TEST_EVENTS'],'a') as handle:
    handle.write(json.dumps({'job':name,'args':args,'receipts':list(str(p) for p in (repo/'.cache/chanlun/kaipanla').glob('publication-*.json'))})+'\n')
if name=='validate_today_report.py' and '--needs-sublevel-retry' in args:
    raise SystemExit(0 if os.environ.get('ONGOING_TEST_SUBLEVEL_RETRY')=='1' else 1)
if name=='-c':
    frozen=os.environ.get('ONGOING_TEST_GENERATED_DOCS')
    if frozen: shutil.copytree(frozen,repo/'docs',dirs_exist_ok=True)
    with open(os.environ['KPL_TEST_CALL_LOG'],'a') as handle: handle.write('run.main source\n')
raise SystemExit(0)
''')
        router.chmod(0o700)
        script=(ROOT/'daily_run.sh').read_text().replace('source ~/.zshrc 2>/dev/null || true',':')
        (self.repo/'daily_run.sh').write_text(script.replace(PYTHON,str(router)))
        for name in ('run_with_docs_publish_lock.py','formal_publish_guard.py'):
            shutil.copy2(ROOT/'scripts'/name,self.repo/'scripts'/name)
        self._git('add','daily_run.sh','scripts')
        self._git('commit','-m','test: isolated ongoing entry')
        self._git('push')
        self.old_head=self._git('rev-parse','HEAD').strip()
        self.env.update(ONGOING_TEST_REPO=str(self.repo),ONGOING_TEST_EVENTS=str(self.events),
                        CHANLUN_DAILY_GIT_RETRY_DELAY_SECONDS='0')
        self.env.pop('CHANLUN_DOCS_PUBLISH_LOCK_FD',None)

    def ongoing(self,**environment):
        return subprocess.run(['/bin/zsh',str(self.repo/'daily_run.sh')],cwd=self.repo,
            env=dict(self.env,**environment),capture_output=True,text=True,timeout=30)

    def jobs(self):
        return [json.loads(row) for row in self.events.read_text().splitlines()] if self.events.exists() else []

    def calls(self):
        return self.call_log.read_text().splitlines() if self.call_log.exists() else []

    def docs_bytes(self):
        return {str(p.relative_to(self.repo/'docs')):p.read_bytes() for p in (self.repo/'docs').rglob('*') if p.is_file()}

    def assert_no_formal_side_effects(self):
        jobs=[row['job'] for row in self.jobs()]
        for name in ('-c','finalize_recommendation_ledger.py','repair_strategy_scorecard_snapshot.py','nextday_research_hook.py'):
            self.assertNotIn(name,jobs)

    def assert_context(self,expected):
        planes=fixture.atomic._load_public_planes(self.repo/'docs',self.today)
        for plane in planes.values(): self.assertEqual(plane['kaipanla_context'],expected)

    def test_published_fast_exit_refreshes_available_again_and_four_rounds_are_bounded(self):
        original=self.docs_bytes()
        for attempt in range(4):
            source=json.loads(self.input.read_text())
            if attempt==1:
                source['groups'][0]['stocks'].append({'code':'600001','name':'新增','reason':'稍后补充'})
                self.input.write_text(json.dumps(source))
            before=self._git('rev-parse','HEAD')
            result=self.ongoing()
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(len(self.calls()),attempt+1)
            self.assert_context(source)
            self.assertEqual(self._git('rev-parse','HEAD'),self._git('rev-parse','origin/main'))
            if attempt>=2: self.assertEqual(before,self._git('rev-parse','HEAD'))
        self.assertEqual(self._git('rev-list','--count',self.old_head+'..HEAD').strip(),'2')
        for relative,content in self.docs_bytes().items():
            if relative in fixture.refresh.public_targets(self.today):
                self.assertEqual(fixture.refresh.protected_bytes(original[relative],relative,self.today),
                                 fixture.refresh.protected_bytes(content,relative,self.today))
            else: self.assertEqual(original[relative],content)
        self.assertEqual(self._git('diff','--name-only').splitlines(),['notes.txt'])
        self.assert_no_formal_side_effects()

    def test_push_only_success_then_refreshes_without_regeneration(self):
        # A formal pending commit remains the generic daily push's responsibility.
        (self.repo/'formal-marker.txt').write_text('already validated formal output')
        self._git('add','formal-marker.txt');self._git('commit','-m','test: formal pending')
        result=self.ongoing()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self.calls(),['source'])
        jobs=[row['job'] for row in self.jobs()]
        self.assertNotIn('-c',jobs)
        self.assertEqual(jobs.count('finalize_recommendation_ledger.py'),1)
        self.assertEqual(jobs.count('repair_strategy_scorecard_snapshot.py'),1)
        self.assert_context(json.loads(self.input.read_text()))
        self.assertEqual(self._git('rev-parse','HEAD'),self._git('rev-parse','origin/main'))

    def test_first_run_already_fetches_once_without_an_immediate_second_hook(self):
        self.assertEqual(self.schedule().returncode,0)
        generated=self.base/'generated-docs';shutil.copytree(self.repo/'docs',generated)
        self._git('rm','docs/data/'+self.today+'.json')
        self._git('commit','-m','test: before first generation');self._git('push')
        self.call_log.unlink()
        result=self.ongoing(ONGOING_TEST_GENERATED_DOCS=str(generated))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self.calls(),['run.main source'])
        self.assertEqual([row['job'] for row in self.jobs()].count('-c'),1)
        self.assert_context(json.loads(self.input.read_text()))

    def test_optional_empty_old_date_and_source_failure_preserve_published_bytes(self):
        self.assertEqual(self.schedule().returncode,0)
        self.call_log.unlink();before=self.docs_bytes();head=self._git('rev-parse','HEAD')
        for source in ({'status':'empty','groups':[]},fixture.context('2026-09-30'),None):
            self.input.write_text(json.dumps(source) if source is not None else 'invalid frozen provider response')
            result=self.ongoing()
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(self.docs_bytes(),before)
            self.assertEqual(self._git('rev-parse','HEAD'),head)
        self.assertEqual(self.calls(),['source']*3)
        self.assert_no_formal_side_effects()

    def test_recover_only_without_receipt_never_checks_readiness_or_fetches(self):
        (self.repo/'docs/data'/ (self.today+'.json')).unlink()
        # Even a missing remote cannot matter to a no-op recovery.
        self._git('remote','set-url','origin',str(self.base/'absent.git'))
        result=subprocess.run(['/bin/zsh',str(self.repo/'scripts/kaipanla_refresh.sh'),'--recover-pending-only'],
            cwd=self.repo,env=self.env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse(self.call_log.exists())
        self.assertNotIn('未就绪',result.stdout+result.stderr)
        self.assertNotIn('ready',result.stdout)

    def test_trusted_pending_is_recovered_before_formal_prepare_and_incremental_record(self):
        pending=self.pending_fixture()
        journal=self.repo/'.cache/chanlun/formal-publish-targets.json'
        journal.write_text(json.dumps({'schema_version':1,'trade_date':self.today,'head_sha':self.old_head,
                                      'generated_targets':{},'excluded_report_entrypoints':[]}))
        result=self.ongoing(ONGOING_TEST_SUBLEVEL_RETRY='1')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self._git('rev-parse','origin/main').strip(),pending)
        recorded=json.loads(journal.read_text())
        self.assertEqual(recorded['head_sha'],pending)
        for relative in fixture.refresh.public_targets(self.today):
            self.assertEqual(recorded['generated_targets']['docs/'+relative],
                             hashlib.sha256((self.repo/'docs'/relative).read_bytes()).hexdigest())
        self.assertEqual(self.calls(),['source','run.main source'])
        self.assertTrue(all(not row['receipts'] for row in self.jobs()))

    def test_remote_accepted_pending_is_cleared_then_new_source_is_checked_once(self):
        self.install_git_failure('push_response_lost')
        self.assertNotEqual(self.schedule().returncode,0)
        self.env['KPL_TEST_GIT_FAILURE']='none'
        self.call_log.unlink()
        result=self.ongoing()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self.calls(),['source'])
        self.assertFalse(list((self.repo/'.cache/chanlun/kaipanla').glob('publication-*.json')))
        self.assert_no_formal_side_effects()

    def test_bad_receipt_with_unready_or_dirty_report_never_reaches_generic_push(self):
        for mode in ('invalid_receipt','unready','dirty','stale_day','dangling_receipt'):
            with self.subTest(mode=mode):
                self._bad_receipt_case(mode)

    def _bad_receipt_case(self,mode):
        # Each case needs a fresh fixture without throwing away prior user work.
        case=OngoingKaipanlaTests(methodName='test_push_only_success_then_refreshes_without_regeneration')
        case.setUp()
        try:
            pending=case.pending_fixture()
            receipt=next((case.repo/'.cache/chanlun/kaipanla').glob('publication-*.json'))
            if mode in ('invalid_receipt','unready'):
                receipt.write_text('{broken receipt')
            if mode=='unready':
                payload=json.loads((case.repo/'docs/data'/ (case.today+'.json')).read_text())
                payload['data_quality']['is_official']=False
                (case.repo/'docs/data'/ (case.today+'.json')).write_text(json.dumps(payload))
                case._git('add','docs');case._git('commit','-m','test: unready report')
            if mode=='dirty': (case.repo/'docs/index.html').write_text('user dirty report')
            if mode=='stale_day': receipt.rename(receipt.with_name('publication-2000-01-01.json'))
            if mode=='dangling_receipt': receipt.unlink();receipt.symlink_to(case.base/'missing-receipt')
            result=case.ongoing()
            self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(case._git('rev-parse','origin/main').strip(),case.old_head)
            self.assertEqual(case.jobs(),[])
            self.assertEqual(case.calls(),['source'])
        finally: case.doCleanups()

    def test_tampered_hash_or_remote_divergence_cannot_become_generic_daily_push(self):
        self.pending_fixture()
        receipt=next((self.repo/'.cache/chanlun/kaipanla').glob('publication-*.json'))
        payload=json.loads(receipt.read_text());payload['target_sha256']['index.html']='0'*64
        receipt.write_text(json.dumps(payload))
        result=self.ongoing()
        self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self._git('rev-parse','origin/main').strip(),self.old_head)
        self.assertEqual(self.jobs(),[])
        self.assertEqual(self.calls(),['source'])

    def test_remote_divergence_blocks_receipted_pending_before_generic_work(self):
        self.pending_fixture()
        peer=self.base/'peer'
        self._git('clone','--branch','main',str(self.remote),str(peer),cwd=self.base)
        self._git('config','user.name','Peer',cwd=peer)
        self._git('config','user.email','peer@example.invalid',cwd=peer)
        (peer/'peer.txt').write_text('concurrent remote work')
        self._git('add','peer.txt',cwd=peer);self._git('commit','-m','test: remote divergence',cwd=peer)
        self._git('push',cwd=peer)
        remote=self._git('rev-parse','HEAD',cwd=peer)
        head=self._git('rev-parse','HEAD')
        result=self.ongoing()
        self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self._git('rev-parse','origin/main'),remote)
        self.assertEqual(self._git('rev-parse','HEAD'),head)
        self.assertEqual(self.jobs(),[])
        self.assertEqual(self.calls(),['source'])

    def test_concurrent_ongoing_waits_for_the_same_lock_and_both_exit_cleanly(self):
        marker=self.base/'source-held';release=self.base/'release-source'
        wrapper=Path(self.env['CHANLUN_KPL_PYTHON'])
        wrapper.write_text(wrapper.read_text().replace('args=sys.argv[1:]','''args=sys.argv[1:]
if "--check-ready" not in args:
    import time
    marker=Path(os.environ["ONGOING_TEST_MARKER"])
    if not marker.exists():
        marker.write_text(str(os.getpid()))
        deadline=time.monotonic()+10
        while not Path(os.environ["ONGOING_TEST_RELEASE"]).exists():
            if time.monotonic()>deadline: raise SystemExit("test provider release timeout")
            time.sleep(0.01)
'''))
        env=dict(self.env,ONGOING_TEST_MARKER=str(marker),ONGOING_TEST_RELEASE=str(release))
        processes=[]
        try:
            first=subprocess.Popen(['/bin/zsh',str(self.repo/'daily_run.sh')],cwd=self.repo,env=env,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            processes.append(first)
            deadline=time.monotonic()+10
            while not marker.exists():
                self.assertIsNone(first.poll())
                self.assertLess(time.monotonic(),deadline,'first refresh never reached frozen provider')
                time.sleep(0.01)
            jobs=self.jobs()
            second=subprocess.Popen(['/bin/zsh',str(self.repo/'daily_run.sh')],cwd=self.repo,env=env,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            processes.append(second)
            time.sleep(0.15)
            self.assertIsNone(second.poll())
            self.assertEqual(self.jobs(),jobs,'second ongoing entered while first held publication lock')
            release.write_text('release')
            for process in processes:
                out,err=process.communicate(timeout=15)
                self.assertEqual(process.returncode,0,out+err)
            self.assertEqual(self.calls(),['source','source'])
            self.assert_no_formal_side_effects()
            lock=self.repo/'.cache/chanlun/docs-publish.lock'
            fd=os.open(lock,os.O_RDWR)
            try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally: os.close(fd)
        finally:
            release.write_text('release')
            for process in processes:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try: process.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL);process.communicate(timeout=3)

    def test_dirty_formal_target_stops_without_refresh_or_mutation(self):
        (self.repo/'docs/index.html').write_text('user content')
        head=self._git('rev-parse','HEAD')
        result=self.ongoing()
        self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual((self.repo/'docs/index.html').read_text(),'user content')
        self.assertEqual(self._git('rev-parse','HEAD'),head)
        self.assertEqual(self.calls(),[])

    def test_unreceipted_kpl_commit_never_falls_through_to_generic_push(self):
        pending=self.pending_fixture()
        next((self.repo/'.cache/chanlun/kaipanla').glob('publication-*.json')).unlink()
        result=self.ongoing()
        self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self._git('rev-parse','origin/main').strip(),self.old_head)
        self.assertEqual(self._git('rev-parse','HEAD').strip(),pending)
        self.assertEqual(self.jobs(),[])
        self.assertEqual(self.calls(),['source'])


class SharedLockInheritanceTests(unittest.TestCase):
    def test_generic_wrapper_exports_a_live_fd_that_kpl_reuses_without_deadlock(self):
        with fixture.tempfile.TemporaryDirectory(prefix='ongoing-kpl-lock-') as tmp:
            lock=Path(tmp)/'.cache/chanlun/docs-publish.lock'
            docs=Path(tmp)/'docs';docs.mkdir()
            code='''import fcntl,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from scripts import refresh_kaipanla_context as refresh
descriptor=int(os.environ['CHANLUN_DOCS_PUBLISH_LOCK_FD'])
with refresh._publication_lock(Path(sys.argv[2]),0.05) as (path,inherited):
    assert inherited==descriptor
    other=os.open(path,os.O_RDWR)
    try:
        fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: pass
    else: raise AssertionError('mutual exclusion lost')
    finally: os.close(other)
'''
            result=subprocess.run([PYTHON,str(ROOT/'scripts/run_with_docs_publish_lock.py'),'--lock-path',str(lock),
                '--',PYTHON,'-c',code,str(ROOT),str(docs)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            fd=os.open(lock,os.O_RDWR)
            try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            finally: os.close(fd)

    def test_unknown_fd_cannot_bypass_another_publisher_lock(self):
        with fixture.tempfile.TemporaryDirectory(prefix='ongoing-kpl-lock-') as tmp:
            docs=Path(tmp)/'docs';docs.mkdir()
            lock=fixture.atomic.docs_publish_lock_path(docs);lock.parent.mkdir(parents=True,exist_ok=True)
            fd=os.open(lock,os.O_RDWR|os.O_CREAT,0o600)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX)
                code='''import sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from scripts import refresh_kaipanla_context as refresh
with refresh._publication_lock(Path(sys.argv[2]),0.03): raise AssertionError('unknown FD bypassed lock')
'''
                env=dict(os.environ,CHANLUN_DOCS_PUBLISH_LOCK_HELD='1',CHANLUN_DOCS_PUBLISH_LOCK_PATH=str(lock),
                         CHANLUN_DOCS_PUBLISH_LOCK_FD='99999',CHANLUN_KPL_PUBLISH_LOCK_FD='99998')
                result=subprocess.run([PYTHON,'-c',code,str(ROOT),str(docs)],env=env,capture_output=True,text=True,timeout=5)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('publication lock timeout',result.stderr)
            finally: os.close(fd)


if __name__=='__main__': unittest.main()
