#!/usr/bin/env python3
"""Refresh one optional KPL supplement in an existing official report.

The default entry never invokes Git, selection, databases, or notifications.
Only four public files may change, and their other JSON/HTML bytes are guarded.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if os.fspath(ROOT_DIR) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT_DIR))

from chanlun.identity import normalize_identity
from chanlun.kaipanla import fetch_themes, parse_themes
from chanlun.report_generator import _escape_inline_json, _render_kaipanla_context
from scripts import enable_shadow_evaluation_snapshot as atomic

BOOTSTRAP = re.compile(r'window\.CHANLUN_BOOTSTRAP\s*=\s*')
DECODER = json.JSONDecoder()
CONTEXT_KEY = 'kaipanla_context'


def public_targets(report_date):
    return ('data/'+report_date+'.json', 'data.json', 'index.html', report_date+'/index.html')


def _parse_date(value):
    parsed = date.fromisoformat(str(value))
    if parsed.isoformat() != value:
        raise ValueError('report_date must be YYYY-MM-DD')
    return parsed


def _space(text, position):
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _member_location(text, path, start=0):
    """Locate a JSON member value without rewriting sibling bytes."""
    start = _space(text, start)
    if text[start:start+1] != '{':
        raise ValueError('expected JSON object at '+'.'.join(path))
    position = _space(text, start+1)
    members = 0
    found = None
    while text[position:position+1] != '}':
        key, key_end = DECODER.raw_decode(text, position)
        if not isinstance(key, str):
            raise ValueError('invalid JSON object key')
        colon = _space(text, key_end)
        if text[colon:colon+1] != ':':
            raise ValueError('invalid JSON object member')
        value_start = _space(text, colon+1)
        _, value_end = DECODER.raw_decode(text, value_start)
        if key == path[0]:
            if found is not None:
                raise ValueError('duplicate JSON member '+key)
            found = (value_start, value_end)
        members += 1
        position = _space(text, value_end)
        if text[position:position+1] == ',':
            position = _space(text, position+1)
        elif text[position:position+1] != '}':
            raise ValueError('invalid JSON object terminator')
    if found is None:
        if len(path) != 1:
            raise ValueError('missing JSON member '+path[0])
        return position, position, members > 0
    if len(path) > 1:
        return _member_location(text, path[1:], found[0])
    return found[0], found[1], None


def _replace_member(text, path, replacement):
    start, end, insert = _member_location(text, path)
    if insert is not None:
        replacement = (',' if insert else '') + json.dumps(path[-1]) + ':' + replacement
    return text[:start]+replacement+text[end:]


class _CardParser(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=False)
        self.text = text
        self.line_offsets = [0]
        for match in re.finditer('\n', text):
            self.line_offsets.append(match.end())
        self.start = None
        self.depth = 0
        self.span = None
        self.body_end = None

    def absolute_offset(self):
        line, column = self.getpos()
        return self.line_offsets[line-1]+column

    def handle_starttag(self, tag, attrs):
        if tag == 'body' and self.body_end is None:
            self.body_end = self.absolute_offset()+len(self.get_starttag_text())
        if dict(attrs).get('id') == 'kaipanla-context':
            if self.start is not None or self.span is not None or tag != 'details':
                raise ValueError('invalid or duplicate kaipanla-context card')
            self.start = self.absolute_offset()
            self.depth = 1
        elif self.start is not None and tag == 'details':
            self.depth += 1

    def handle_endtag(self, tag):
        if self.start is not None and tag == 'details':
            self.depth -= 1
            if self.depth == 0:
                match = re.match(r'</\s*details\s*>', self.text[self.absolute_offset():], re.I)
                if not match:
                    raise ValueError('invalid kaipanla-context close tag')
                self.span = (self.start, self.absolute_offset()+match.end())
                self.start = None


def _card_parser(text):
    parser = _CardParser(text)
    parser.feed(text)
    parser.close()
    if parser.start is not None:
        raise ValueError('unclosed kaipanla-context card')
    return parser


def card_span(text):
    return _card_parser(text).span


def _replace_card(text, context):
    parser = _card_parser(text)
    # Git core.autocrlf=input normalizes actual HTML line endings on staging.
    # Normalize only this replaceable card; source JSON strings keep their CRLF.
    rendered = _render_kaipanla_context(context).replace('\r\n','\n')
    if parser.span:
        start, end = parser.span
    elif parser.body_end is not None:
        start = end = parser.body_end
    else:
        raise ValueError('missing HTML body')
    return text[:start]+rendered+text[end:]


def _bootstrap_location(text):
    candidates = []
    for match in BOOTSTRAP.finditer(text):
        start = match.end()
        try:
            value, end = DECODER.raw_decode(text,start)
        except ValueError:
            continue
        if isinstance(value,dict) and isinstance(value.get('inlineReportData'),dict):
            candidates.append((start,end,value))
    if len(candidates) != 1:
        raise ValueError('missing or ambiguous report bootstrap')
    return candidates[0]


def _json_path(relative, report_date):
    return ['reports', report_date, CONTEXT_KEY] if relative == 'data.json' else [CONTEXT_KEY]


def protected_bytes(content, relative, report_date):
    """Canonical guard retaining every byte outside the allowed two fragments."""
    text = content.decode('utf-8')
    if relative.endswith('.html'):
        span = card_span(text)
        if span:
            text = text[:span[0]]+text[span[1]:]
        start, end, _ = _bootstrap_location(text)
        inner = _replace_member(text[start:end], ['inlineReportData', CONTEXT_KEY], 'null')
        text = text[:start]+inner+text[end:]
    else:
        text = _replace_member(text, _json_path(relative, report_date), 'null')
    return text.encode('utf-8')


def _require_official(report, report_date, aggregate=False):
    quality = report.get('data_quality') or {}
    if ((not aggregate and report.get('date') != report_date)
            or (aggregate and report.get('date') not in (None,report_date))
            or quality.get('report_date') != report_date):
        raise ValueError('report date mismatch')
    if quality.get('is_official') is not True:
        raise ValueError('refresh requires an official report')
    if quality.get('is_trading_day') is not True or quality.get('bar_state') != 'closed':
        raise ValueError('refresh requires an existing closed trading-day report')
    if quality.get('sources_trusted') is not True or quality.get('market_status') != 'verified':
        raise ValueError('refresh requires verified report sources')


def _read_baseline(docs_dir, report_date):
    _parse_date(report_date)
    originals = {}
    planes = {}
    for relative in public_targets(report_date):
        path = docs_dir/relative
        if path.is_symlink() or not path.is_file():
            raise ValueError('missing or symlink public target: '+relative)
        content = path.read_bytes()
        originals[relative] = content
        if relative.endswith('.html'):
            _, _, envelope = _bootstrap_location(content.decode('utf-8'))
            if (envelope.get('pageDate') != report_date
                    or envelope.get('date') not in (None,report_date)):
                raise ValueError('HTML report mapping date mismatch')
            planes[relative] = envelope['inlineReportData']
        else:
            payload = json.loads(content)
            planes[relative] = payload.get('reports', {}).get(report_date) if relative == 'data.json' else payload
        if not isinstance(planes[relative], dict):
            raise ValueError('missing report: '+relative)
        _require_official(planes[relative], report_date, aggregate=relative=='data.json')
    day_report = planes['data/'+report_date+'.json']
    for relative, payload in planes.items():
        if payload.get(CONTEXT_KEY) != day_report.get(CONTEXT_KEY):
            raise ValueError('four-plane context baseline mismatch: '+relative)
        if relative.endswith('.html') and payload != day_report:
            raise ValueError('HTML report mapping baseline mismatch: '+relative)
    return originals, planes


def _validate_context(context, report_date):
    if not isinstance(context, dict):
        return False
    if (context.get('status') != 'available' or context.get('source') != 'kaipanla'
            or context.get('affects_formal') is not False
            or context.get('data_date') != report_date or context.get('report_date') != report_date
            or context.get('coverage') != 'returned_sample'):
        return False
    try:
        stamp = datetime.fromisoformat(context.get('fetched_at'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return False
    except (TypeError,ValueError):
        return False
    groups = context.get('groups')
    if not isinstance(groups, list) or not groups:
        return False
    try:
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get('name'), str):
                return False
            stocks = group.get('stocks')
            if not isinstance(stocks, list) or not stocks:
                return False
            for stock in stocks:
                if not isinstance(stock, dict):
                    return False
                identity = normalize_identity(stock.get('code'), asset_type='stock')
                if identity.code != stock.get('code') or not identity.code.startswith(('00','30','60','68','43','83','87','88','92')):
                    return False
                if not all(isinstance(stock.get(key), str) for key in ('name', 'reason')):
                    return False
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _same_content(left, right):
    def without_fetch(value):
        return {key:item for key,item in value.items() if key != 'fetched_at'} if isinstance(value,dict) else value
    return without_fetch(left) == without_fetch(right)


def _prepare_plan(originals, context, report_date):
    plan = {}
    for relative, content in originals.items():
        text = content.decode('utf-8')
        if relative.endswith('.html'):
            start, end, _ = _bootstrap_location(text)
            envelope = _replace_member(text[start:end], ['inlineReportData', CONTEXT_KEY], _escape_inline_json(context))
            text = _replace_card(text[:start]+envelope+text[end:], context)
        else:
            text = _replace_member(text, _json_path(relative, report_date), json.dumps(context, ensure_ascii=False))
        candidate = text.encode('utf-8')
        if protected_bytes(content,relative,report_date) != protected_bytes(candidate,relative,report_date):
            raise RuntimeError('non-context byte drift: '+relative)
        plan[relative] = candidate
    return plan


@contextmanager
def _publication_lock(docs_dir, lock_timeout=20):
    lock_path = atomic.docs_publish_lock_path(docs_dir)
    # The dedicated outer wrapper passes both the exact path and live lock FD.
    inherited = None
    if (os.environ.get('CHANLUN_DOCS_PUBLISH_LOCK_HELD') == '1'
            and os.environ.get(atomic.LOCK_PATH_ENV) == str(lock_path)):
        try:
            candidate = int(os.environ['CHANLUN_KPL_PUBLISH_LOCK_FD'])
            held = os.fstat(candidate)
            target = lock_path.stat()
            if (held.st_dev,held.st_ino) == (target.st_dev,target.st_ino):
                inherited = candidate
        except (KeyError,ValueError,OSError):
            pass
    if inherited is not None:
        yield lock_path, inherited
        return
    lock_path.parent.mkdir(parents=True,exist_ok=True)
    descriptor = os.open(lock_path,os.O_RDWR|os.O_CREAT,0o600)
    deadline = time.monotonic()+max(0,float(lock_timeout))
    try:
        while True:
            try:
                fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('docs publication lock timeout: '+str(lock_path))
                time.sleep(min(0.05,remaining))
        yield lock_path, descriptor
    finally:
        os.close(descriptor)


def _recover_state(docs_dir, report_date, dry_run, lock_timeout):
    with _publication_lock(docs_dir,lock_timeout):
        journal = atomic.transaction_journal_path(docs_dir)
        if dry_run:
            if journal.exists():
                raise RuntimeError('publication recovery is required before dry-run')
            return
        atomic._recover_incomplete_transaction(docs_dir)
        atomic._cleanup_stale_publication_artifacts(docs_dir,report_date)


def apply_plan(docs_dir, originals, plan, *, report_date, asset_originals, lock_timeout=20):
    """Use the durable publisher; assets are staged with exactly their old bytes.

    The shared transaction protects six physical files against interrupted writes.
    Only the four supplement files have changed bytes or enter the Git commit.
    """
    with _publication_lock(docs_dir,lock_timeout):
        for relative, content in {**originals,**asset_originals}.items():
            path = docs_dir/relative
            if path.is_symlink() or path.read_bytes() != content:
                raise RuntimeError('public target changed before apply: '+relative)
        transaction_id = uuid.uuid4().hex
        stage = atomic._create_controlled_stage_root(docs_dir,transaction_id)
        try:
            staged_docs = stage/'docs'
            staged_docs.mkdir()
            for relative, content in {**plan,**asset_originals}.items():
                path = staged_docs/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(content)
            # Required only as an ownership fingerprint for interrupted-stage cleanup.
            (staged_docs/'data/index.json').write_bytes((docs_dir/'data/index.json').read_bytes())
            hashes = {relative:hashlib.sha256(content).hexdigest()
                      for relative,content in {**originals,**asset_originals}.items()}
            atomic._atomic_replace_targets(staged_docs,docs_dir,report_date,
                    expected_original_hashes=hashes,transaction_id=transaction_id)
        finally:
            if stage.exists():
                atomic._remove_controlled_stage_root(stage,docs_dir,assume_owned=True)


def refresh_context(docs_dir, report_date, *, context=None, input_path=None,
                    cache_dir=None, dry_run=False, lock_timeout=20):
    docs_dir = Path(docs_dir).resolve()
    _parse_date(report_date)
    _recover_state(docs_dir,report_date,dry_run,lock_timeout)
    originals, planes = _read_baseline(docs_dir,report_date)
    asset_originals = {}
    for relative in ('assets/report-v2.js','assets/report-v2.css'):
        path = docs_dir/relative
        if path.is_symlink() or not path.is_file(): raise ValueError('missing or symlink asset: '+relative)
        asset_originals[relative] = path.read_bytes()
    if context is not None and input_path is not None:
        raise ValueError('use context or frozen input, not both')
    if input_path is not None:
        payload = json.loads(Path(input_path).read_text(encoding='utf-8'))
        context = parse_themes(payload,report_date) if isinstance(payload,dict) and 'errcode' in payload else payload
    elif context is None:
        context = fetch_themes(report_date,cache_dir=cache_dir,force_refresh=True)
    if not _validate_context(context,report_date):
        return {'status':'skipped','report_date':report_date,'reason':'today_context_not_ready'}
    context = copy.deepcopy(context)
    if all(_same_content(payload.get(CONTEXT_KEY),context) for payload in planes.values()):
        # Retain the first attested collection timestamp for identical content.
        context = copy.deepcopy(planes['data/'+report_date+'.json'][CONTEXT_KEY])
        expected_card = _render_kaipanla_context(context).replace('\r\n','\n')
        cards_match = True
        for relative in ('index.html',report_date+'/index.html'):
            text = originals[relative].decode('utf-8')
            span = card_span(text)
            if span is None or text[span[0]:span[1]] != expected_card:
                cards_match = False
        if cards_match:
            return {'status':'no_changes','report_date':report_date}
    plan = _prepare_plan(originals,context,report_date)
    # Validate the staged semantic identity independently from the byte guard.
    for relative, content in plan.items():
        if relative.endswith('.html'):
            _,_,envelope = _bootstrap_location(content.decode('utf-8'))
            staged = envelope['inlineReportData']
        else:
            staged = json.loads(content)
            if relative == 'data.json': staged = staged['reports'][report_date]
        expected = copy.deepcopy(planes[relative]); expected[CONTEXT_KEY] = context
        if staged != expected:
            raise RuntimeError('staged report drift: '+relative)
    if not dry_run:
        apply_plan(docs_dir,originals,plan,report_date=report_date,asset_originals=asset_originals,lock_timeout=lock_timeout)
    return {'status':'dry_run' if dry_run else 'updated','report_date':report_date,
            'targets':list(public_targets(report_date)),
            'target_sha256':{relative:hashlib.sha256(content).hexdigest() for relative,content in plan.items()},
            'groups':len(context['groups']),
            'stock_records':sum(len(group['stocks']) for group in context['groups'])}


def rollback_uncommitted_refresh(docs_dir, report_date, receipt_path, source_head, *, lock_timeout=20):
    """CAS recovery for this optional batch when a later Git step rejects it."""
    docs_dir = Path(docs_dir).resolve()
    repo_dir = docs_dir.parent
    _parse_date(report_date)
    if not re.fullmatch(r'[0-9a-f]{40}',str(source_head or '')):
        raise ValueError('rollback source_head must be a full commit SHA')
    receipt = json.loads(Path(receipt_path).read_bytes())
    targets = list(public_targets(report_date))
    if (receipt.get('status') != 'updated' or receipt.get('report_date') != report_date
            or receipt.get('source_head') != source_head
            or set(receipt.get('targets',[])) != set(targets)
            or set(receipt.get('target_sha256',{})) != set(targets)):
        raise ValueError('rollback receipt identity mismatch')

    def git_bytes(*arguments):
        completed = subprocess.run(['git',*arguments],cwd=repo_dir,capture_output=True)
        if completed.returncode:
            raise RuntimeError('rollback Git read failed: '+completed.stderr.decode('utf-8',errors='replace'))
        return completed.stdout

    with _publication_lock(docs_dir,lock_timeout) as (lock_path,descriptor):
        if git_bytes('rev-parse','HEAD').decode().strip() != source_head:
            return {'status':'preserved_head_changed','receipt':str(receipt_path)}
        current = {}
        original = {}
        for relative in targets:
            path = docs_dir/relative
            if path.is_symlink():
                return {'status':'preserved_concurrent_target','target':relative,'receipt':str(receipt_path)}
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != receipt['target_sha256'][relative]:
                return {'status':'preserved_concurrent_target','target':relative,'receipt':str(receipt_path)}
            current[relative] = content
            original[relative] = git_bytes('show',source_head+':docs/'+relative)
            index_content = git_bytes('show',':docs/'+relative)
            if index_content not in (content,original[relative]):
                return {'status':'preserved_concurrent_index','target':relative,'receipt':str(receipt_path)}
        if git_bytes('rev-parse','HEAD').decode().strip() != source_head:
            return {'status':'preserved_head_changed','receipt':str(receipt_path)}
        # Restore only this batch's index paths. Other staged entries stay intact.
        git_bytes('restore','--staged','--source='+source_head,'--',*['docs/'+relative for relative in targets])
        if git_bytes('rev-parse','HEAD').decode().strip() != source_head:
            return {'status':'preserved_head_changed','receipt':str(receipt_path)}
        assets = {relative:(docs_dir/relative).read_bytes()
                  for relative in ('assets/report-v2.js','assets/report-v2.css')}
        # Reuse the same crash-safe transaction while the outer shared lock is held.
        environment = {key:os.environ.get(key) for key in (
            'CHANLUN_DOCS_PUBLISH_LOCK_HELD',atomic.LOCK_PATH_ENV,'CHANLUN_KPL_PUBLISH_LOCK_FD')}
        try:
            os.environ['CHANLUN_DOCS_PUBLISH_LOCK_HELD'] = '1'
            os.environ[atomic.LOCK_PATH_ENV] = str(lock_path)
            os.environ['CHANLUN_KPL_PUBLISH_LOCK_FD'] = str(descriptor)
            apply_plan(docs_dir,current,original,report_date=report_date,asset_originals=assets,lock_timeout=lock_timeout)
        finally:
            for key,value in environment.items():
                if value is None: os.environ.pop(key,None)
                else: os.environ[key] = value
        return {'status':'restored_uncommitted','source_head':source_head,'targets':targets}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docs-dir',type=Path,default=ROOT_DIR/'docs')
    parser.add_argument('--report-date')
    parser.add_argument('--lock-timeout',type=float,default=20)
    parser.add_argument('--with-lock',nargs=argparse.REMAINDER)
    parser.add_argument('--input',dest='input_path',type=Path)
    parser.add_argument('--cache-dir',type=Path,default=ROOT_DIR/'.cache/chanlun/kaipanla')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--check-ready',action='store_true')
    parser.add_argument('--rollback-receipt',type=Path)
    parser.add_argument('--source-head')
    args = parser.parse_args(argv)
    try:
        if args.with_lock is not None:
            command = list(args.with_lock)
            if command and command[0] == '--': command.pop(0)
            if not command: parser.error('--with-lock requires a command')
            with _publication_lock(args.docs_dir.resolve(),args.lock_timeout) as (path,descriptor):
                os.set_inheritable(descriptor,True)
                environment = dict(os.environ)
                environment['CHANLUN_DOCS_PUBLISH_LOCK_HELD'] = '1'
                environment[atomic.LOCK_PATH_ENV] = str(path)
                environment['CHANLUN_KPL_PUBLISH_LOCK_FD'] = str(descriptor)
                os.execvpe(command[0],command,environment)
        if not args.report_date: parser.error('--report-date is required')
        if args.rollback_receipt:
            result = rollback_uncommitted_refresh(args.docs_dir,args.report_date,args.rollback_receipt,args.source_head,lock_timeout=args.lock_timeout)
            print(json.dumps(result,ensure_ascii=False))
            return 0 if result['status']=='restored_uncommitted' else 1
        if args.check_ready:
            _parse_date(args.report_date)
            _recover_state(args.docs_dir.resolve(),args.report_date,False,args.lock_timeout)
            _read_baseline(args.docs_dir.resolve(),args.report_date)
            result = {'status':'ready','report_date':args.report_date}
        else:
            result = refresh_context(args.docs_dir,args.report_date,input_path=args.input_path,
                                     cache_dir=args.cache_dir,dry_run=args.dry_run,lock_timeout=args.lock_timeout)
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (OSError,ValueError,RuntimeError) as exc:
        print('KPL refresh stopped: '+str(exc),file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
