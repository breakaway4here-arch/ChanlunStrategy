#!/usr/bin/env python3
"""Prepare a private launchd update candidate; installation/reload stays explicit.

Example: /usr/bin/python3 scripts/update_daily_report_launchd.py --output /private/tmp/daily-report.plist
The installed plist is never modified. Review/backup it before installing the candidate.
launchd calendar triggers use the host timezone, so TZ in the child alone is insufficient.
"""
import argparse
import copy
import os
from pathlib import Path
import plistlib

LABEL = "com.chanlun.daily-report"
RUNTIME = "/Users/yangfan/yf_source/ChanlunStrategy/.worktrees/production-runtime"


def validate_identity(data):
    if (data.get("Label") != LABEL or data.get("WorkingDirectory") != RUNTIME
            or data.get("ProgramArguments") != ["/bin/zsh", "-l", "-c", RUNTIME + "/daily_run.sh"]):
        raise ValueError("daily-report label or production runtime identity mismatch")
    if data.get("RunAtLoad") is not False or data.get("KeepAlive", False) or "StartInterval" in data:
        raise ValueError("daily-report must use only finite calendar triggers")


def prepare_update(template, installed, *, host_timezone):
    if host_timezone != "Asia/Shanghai":
        raise ValueError("launchd host timezone must be Asia/Shanghai")
    validate_identity(template)
    validate_identity(installed)
    rows = template.get("StartCalendarInterval", [])
    expected = {(day, 15, minute) for day in range(1, 6) for minute in (5, 20, 35, 50)}
    if (len(rows) != len(expected)
            or {(r.get("Weekday"), r.get("Hour"), r.get("Minute")) for r in rows} != expected
            or any(set(row) != {"Weekday", "Hour", "Minute"} for row in rows)):
        raise ValueError("daily-report template schedule must contain exactly 20 weekday triggers")
    candidate = copy.deepcopy(installed)
    candidate["StartCalendarInterval"] = copy.deepcopy(rows)
    candidate.setdefault("EnvironmentVariables", {})["TZ"] = "Asia/Shanghai"
    return candidate


def host_timezone():
    parts = Path("/etc/localtime").resolve().parts
    return "/".join(parts[-2:])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", type=Path,
                        default=Path.home() / "Library/LaunchAgents" / (LABEL + ".plist"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.resolve() == args.installed.resolve():
            raise ValueError("candidate output must differ from the installed plist")
        template_path = Path(__file__).resolve().parents[1] / "launchd" / (LABEL + ".plist")
        with template_path.open("rb") as source:
            template = plistlib.load(source)
        with args.installed.open("rb") as source:
            installed = plistlib.load(source)
        candidate = prepare_update(template, installed, host_timezone=host_timezone())
        payload = plistlib.dumps(candidate, sort_keys=False)
        descriptor = os.open(str(args.output), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
        print("Private daily-report candidate ready: {}; installation/reload remains separate".format(args.output))
        return 0
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException) as error:
        # Do not print plist values or inherited environment.
        print("Cannot prepare daily-report candidate: {}".format(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
