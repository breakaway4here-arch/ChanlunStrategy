#!/usr/bin/env python3
"""Bounded GitHub transport retries for finite daily and supplement jobs."""
import argparse
import os
import signal
import subprocess
import time

PROXIES = ("http://127.0.0.1:17891", "http://127.0.0.1:7897")


def bounded_number(kind, minimum, maximum):
    def parse(value):
        number = kind(value)
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError("must be between {} and {}".format(minimum, maximum))
        return number
    return parse


def stop_process_group(process):
    """Reap git and stop any transport helpers it spawned, including on signals."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # Git may exit on TERM before one of its helpers; kill the whole group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_attempt(command, timeout_seconds):
    process = subprocess.Popen(command, start_new_session=True,
                               env=dict(os.environ, GIT_TERMINAL_PROMPT="0",
                                        GIT_ASKPASS="/usr/bin/false",
                                        SSH_ASKPASS="/usr/bin/false",
                                        GCM_INTERACTIVE="never"))
    previous_handler = signal.getsignal(signal.SIGTERM)

    def terminate(_signum, _frame):
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, terminate)
    try:
        return process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        print("Git transport deadline exceeded; terminating this attempt", flush=True)
        stop_process_group(process)
        return 124
    except BaseException:
        stop_process_group(process)
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("fetch", "push"))
    parser.add_argument("--push-ref", help="explicit origin push ref; omitted preserves daily push defaults")
    parser.add_argument("--rounds", type=bounded_number(int, 1, 3), default=3)
    parser.add_argument("--timeout-seconds", type=bounded_number(float, 0.1, 120), default=60)
    parser.add_argument("--retry-delay-seconds", type=bounded_number(float, 0, 30), default=5)
    args = parser.parse_args(argv)
    if args.push_ref and (args.operation != "push" or args.push_ref.startswith("-")):
        parser.error("--push-ref requires push and a non-option ref")
    last_status = 1
    for round_index in range(args.rounds):
        for proxy in PROXIES:
            print("Git {} attempt round {}/{} via {}".format(
                args.operation, round_index + 1, args.rounds, proxy), flush=True)
            command = ["git", "-c", "http.https://github.com.proxy=" + proxy,
                       "-c", "https.https://github.com.proxy=" + proxy]
            command += (["fetch", "origin", "main"] if args.operation == "fetch" else
                        ["push", "origin", args.push_ref] if args.push_ref else ["push"])
            last_status = run_attempt(command, args.timeout_seconds)
            if last_status == 0:
                return 0
        if round_index + 1 < args.rounds:
            time.sleep(args.retry_delay_seconds)
    print("Git {} failed after {} bounded attempts; keep local state for the next scheduled run".format(
        args.operation, args.rounds * len(PROXIES)), flush=True)
    return last_status if 0 < last_status < 256 else 1


if __name__ == "__main__":
    raise SystemExit(main())
