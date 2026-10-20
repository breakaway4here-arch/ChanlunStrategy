#!/usr/bin/env python3
"""Prepare/inspect the approved offline pilot; explicit apply is opt-in."""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chanlun.daily_price_repair import build_manifest, build_manifest_96, validate_manifest, apply_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        'Apply only after business tasks are idle. Use the existing publication lock; '
        'a parent holding it may pass the inherited descriptor. No requests or jobs are started.'))
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('build')
    for key in ('scope', 'frozen', 'pilot', 'anchors'):
        build.add_argument('--'+key, required=True)
    build.add_argument('--created-at', default=None)
    build.add_argument('--output', required=True)
    build96 = commands.add_parser('build96', help='explicit separately approved two-row extension')
    for key in ('scope','frozen','pilot','anchors','tail-scope','tail-quotes'):
        build96.add_argument('--'+key,required=True)
    build96.add_argument('--created-at',default=None)
    build96.add_argument('--output',required=True)
    verify = commands.add_parser('validate')
    verify.add_argument('--manifest', required=True)
    verify.add_argument('--expected-sha256', required=True)
    apply = commands.add_parser('apply')
    apply.add_argument('--manifest', required=True)
    apply.add_argument('--db', required=True)
    apply.add_argument('--apply', action='store_true', help='omit for read-only dry-run')
    apply.add_argument('--expected-sha256', required=True)
    apply.add_argument('--backup-dir')
    apply.add_argument('--identity-key', action='append')
    apply.add_argument('--lock-path', default=os.environ.get('CHANLUN_DOCS_PUBLISH_LOCK_PATH'))
    apply.add_argument('--lock-fd', type=int, default=(int(os.environ['CHANLUN_DOCS_PUBLISH_LOCK_FD'])
        if os.environ.get('CHANLUN_DOCS_PUBLISH_LOCK_HELD') == '1'
        and os.environ.get('CHANLUN_DOCS_PUBLISH_LOCK_FD') else None))
    args = parser.parse_args(argv)
    try:
        if args.command in ('build','build96'):
            kwargs = dict(created_at=args.created_at or datetime.now(timezone.utc).isoformat())
            if args.command == 'build96':
                kwargs.update(tail_scope_path=args.tail_scope,tail_quotes_path=args.tail_quotes)
            builder = build_manifest if args.command == 'build' else build_manifest_96
            manifest = builder(args.scope,args.frozen,args.pilot,args.anchors,**kwargs)
            output = Path(args.output)
            with output.open('x') as stream:
                json.dump(manifest,stream,sort_keys=True,indent=2,allow_nan=False)
                stream.write('\n')
            result = dict(status='manifest_prepared',sha256=manifest['sha256'],path=str(output.resolve()))
        else:
            manifest = json.loads(Path(args.manifest).read_text())
            validate_manifest(manifest)
            if manifest['sha256'] != args.expected_sha256:
                raise ValueError('reviewed_manifest_sha256_mismatch')
            if args.command == 'validate':
                result = dict(status='valid',sha256=manifest['sha256'],changes=manifest['total_changes'])
            else:
                result = apply_manifest(args.db,manifest,apply=args.apply,backup_dir=args.backup_dir,
                    identity_keys=args.identity_key,lock_path=args.lock_path,lock_fd=args.lock_fd,
                    expected_sha256=args.expected_sha256)
        print(json.dumps(result,sort_keys=True,indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps(dict(status='rejected',reason=str(exc))),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
