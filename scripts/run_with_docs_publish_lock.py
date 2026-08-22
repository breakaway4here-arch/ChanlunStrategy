#!/usr/bin/env python3
"""Run one command while holding the shared docs publication lock."""

import argparse
import fcntl
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = ROOT_DIR / ".cache" / "chanlun" / "docs-publish.lock"
LOCK_HELD_ENV = "CHANLUN_DOCS_PUBLISH_LOCK_HELD"
LOCK_PATH_ENV = "CHANLUN_DOCS_PUBLISH_LOCK_PATH"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run a command under the Chanlun docs publication lock"
    )
    parser.add_argument(
        "--lock-path",
        default=os.environ.get(LOCK_PATH_ENV, os.fspath(DEFAULT_LOCK_PATH)),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        parser.error("a command is required after --")

    lock_path = Path(args.lock_path).resolve()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    os.set_inheritable(descriptor, True)
    environment = dict(os.environ)
    environment[LOCK_HELD_ENV] = "1"
    environment[LOCK_PATH_ENV] = os.fspath(lock_path)
    try:
        os.execvpe(command[0], command, environment)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
