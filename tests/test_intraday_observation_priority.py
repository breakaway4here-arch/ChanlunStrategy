"""Read-only prior-report priority and unchanged acquisition contracts."""

from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from chanlun import intraday_observation_data as observation
from chanlun.market_history_store import MarketHistoryStore
import intraday_observation_run as runner
from tests import test_intraday_observation_reliability as fixtures


DAY = "2026-10-13"
PREVIOUS = "2026-10-12"
CUTOFF = datetime.fromisoformat(DAY + "T14:45:00+08:00")


def formal_report():
    return {
        "date": PREVIOUS,
        "data_quality": {
            "report_date": PREVIOUS, "is_official": True, "is_trading_day": True,
            "bar_state": "closed", "generated_at": PREVIOUS + "T15:05:00+08:00",
            "as_of": PREVIOUS + "T15:05:00+08:00",
        },
        "selection_input_health": {
            "required_date": PREVIOUS,
            "formal": {"status": "verified", "formal_actions_allowed": True},
            "sublevels": {"30m": {
                "required_date": PREVIOUS, "interval": "30m", "requested_count": 5,
                "verified_count": 3, "missing_count": 2,
                "verified_codes": ["600002", "000001", "600001"],
                "missing_codes": ["000002", "000999"],
            }},
        },
    }


def git(root, *args):
    return subprocess.check_output(["/usr/bin/git", "-C", str(root), *args], timeout=3, text=True).strip()


def published_docs(root, report):
    git(root, "init", "-q")
    git(root, "config", "user.name", "Priority Test")
    git(root, "config", "user.email", "priority@example.invalid")
    archive = root / "docs" / "data" / (PREVIOUS + ".json")
    archive.parent.mkdir(parents=True)
    archive.write_text(json.dumps(report))
    git(root, "add", "--", "docs")
    git(root, "commit", "-qm", "fixture")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root / "docs"


class ObservationPriorityTests(unittest.TestCase):
    def test_source_is_the_exact_published_date_and_untouched_by_local_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = published_docs(root, formal_report())
            (docs / "data" / (PREVIOUS + ".json")).write_text("unpublished")
            (docs / "data" / (DAY + ".json")).write_text(json.dumps(formal_report()))
            priorities, commit = observation._previous_report_priority(docs, PREVIOUS, CUTOFF, 2)
            self.assertEqual(priorities, {"stock|SZ|000001", "stock|SZ|000002", "stock|SZ|000999",
                                          "stock|SH|600001", "stock|SH|600002"})
            self.assertEqual(commit, git(root, "rev-parse", "refs/remotes/origin/main"))
            self.assertIsNone(observation._previous_report_priority(docs, DAY, CUTOFF, 2))
            self.assertIsNone(observation._previous_report_priority(docs, "2026-10-09", CUTOFF, 2))

    def test_unproved_sources_fall_back_to_the_original_order(self):
        variants = (
            (("date",), DAY),
            (("data_quality", "report_date"), DAY),
            (("data_quality", "is_official"), False),
            (("data_quality", "is_trading_day"), 1),
            (("data_quality", "bar_state"), "intraday"),
            (("data_quality", "generated_at"), DAY + "T15:05:00+08:00"),
            (("data_quality", "generated_at"), PREVIOUS + "T15:05:00"),
            (("data_quality", "as_of"), PREVIOUS + "T14:45:00+08:00"),
            (("selection_input_health", "formal", "formal_actions_allowed"), False),
            (("selection_input_health", "required_date"), DAY),
            (("selection_input_health", "sublevels", "30m", "required_date"), DAY),
            (("selection_input_health", "sublevels", "30m", "interval"), "15m"),
            (("selection_input_health", "sublevels", "30m", "requested_count"), 4),
            (("selection_input_health", "sublevels", "30m", "verified_count"), True),
            (("selection_input_health", "sublevels", "30m", "missing_codes"), ["600001", "000999"]),
            (("selection_input_health", "sublevels", "30m", "missing_codes"), [" 000002", "000999"]),
            (("selection_input_health", "sublevels", "30m", "missing_codes"), ["399001.x", "000999"]),
        )
        for keys, value in variants:
            with self.subTest(keys=keys), tempfile.TemporaryDirectory() as directory:
                document = formal_report()
                leaf = document
                for key in keys[:-1]:
                    leaf = leaf[key]
                leaf[keys[-1]] = value
                docs = published_docs(Path(directory), document)
                self.assertIsNone(observation._previous_report_priority(docs, PREVIOUS, CUTOFF, 2))
        with tempfile.TemporaryDirectory() as directory:
            docs = published_docs(Path(directory), formal_report())
            with patch.object(observation, "_PRIORITY_BLOB_LIMIT", 1):
                self.assertIsNone(observation._previous_report_priority(docs, PREVIOUS, CUTOFF, 2))
            with patch.object(observation.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 1)):
                self.assertIsNone(observation._previous_report_priority(docs, PREVIOUS, CUTOFF, 2))

    def test_dispatch_only_prioritizes_eligible_stocks_and_keeps_budget_and_payload(self):
        request_order = []
        http_requests = []

        class Session:
            def get(self, url, **kwargs):
                params = kwargs["params"]
                http_requests.append((params["secid"], params["klt"], params["fqt"]))
                if params["klt"] == "15" and params["fqt"] == "0":
                    request_order.append(params["secid"])
                return fixtures.FakeResponse(params)

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = published_docs(root, formal_report())
            db = fixtures.CaptureReliabilityTests.make_market_db(None, directory)
            with MarketHistoryStore(db) as store:
                for code, exchange in (("000001", "SZ"), ("000002", "SZ"), ("300001", "SZ"), ("600002", "SH")):
                    instrument = store.upsert_instrument("stock", exchange, code)
                    store.upsert_stock_meta(instrument, PREVIOUS, dict(name=code, listed_days=500,
                        is_st=False, delisting_risk=False, risk_status="verified", risk_source="eastmoney",
                        risk_as_of=PREVIOUS, code=code, exchange=exchange, asset_type="stock"))
            before = db.read_bytes()
            outcomes = []
            for name, config in (("off", ""), ("on", str(docs)), ("invalid", str(root / "missing" / "docs"))):
                request_order.clear()
                http_requests.clear()
                source = root / name
                timings = {}
                with patch.dict("os.environ", {"CHANLUN_OBSERVATION_FORMAL_DOCS_DIR": config}), \
                        patch("requests.Session", Session), \
                        patch.object(observation, "INDEX_NAMES", {"上证指数": "000001"}):
                    payload = runner._live_acquire(db, DAY, deadline=fixtures.DEADLINE, snapshot_dir=source,
                        max_workers=1, clock=lambda: fixtures.NOW, timings=timings)
                budget = (source / "_requests" / "primary.json").read_bytes()
                self.assertEqual(len(http_requests), 28)
                self.assertEqual(len(set(http_requests)), 28)
                outcomes.append((list(request_order), payload, budget, timings, set(http_requests)))
            old, new, fallback = outcomes
            self.assertEqual(old[:3], fallback[:3])
            self.assertEqual(old[0], [
                "1.000001", "1.600000", "1.600001", "1.600002", "0.000001", "0.000002", "0.300001",
            ])
            self.assertEqual(new[0], [
                "1.000001", "1.600001", "0.000001", "1.600002", "0.000002", "1.600000", "0.300001",
            ])
            self.assertEqual(old[1:3], new[1:3])
            self.assertEqual(old[4], new[4])
            self.assertEqual(new[1]["collection_health"]["acquired"], 6)
            self.assertEqual(new[3]["dispatch_priority"]["priority_count"], 4)
            self.assertNotIn("dispatch_priority", new[1]["collection_health"])
            self.assertEqual(db.read_bytes(), before)

    def test_exhausted_time_does_not_add_network_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = published_docs(root, formal_report())
            db = fixtures.CaptureReliabilityTests.make_market_db(None, directory)
            calls = []
            with patch.dict("os.environ", {"CHANLUN_OBSERVATION_FORMAL_DOCS_DIR": str(docs)}), \
                    patch("requests.Session", side_effect=lambda: calls.append("session")):
                payload = runner._live_acquire(db, DAY, deadline=fixtures.NOW - timedelta(milliseconds=1),
                    snapshot_dir=root / "expired", max_workers=1, clock=lambda: fixtures.NOW)
            self.assertEqual(calls, [])
            self.assertEqual(payload["collection_health"]["status"], "failed")
            self.assertGreater(payload["collection_health"]["timed_out"], 0)

    def test_published_symlink_is_not_a_formal_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = published_docs(root, formal_report())
            archive = docs / "data" / (PREVIOUS + ".json")
            target = archive.with_name("another-report.json")
            archive.rename(target)
            archive.symlink_to(target.name)
            git(root, "add", "--", "docs")
            git(root, "commit", "-qm", "symlink fixture")
            git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
            self.assertIsNone(observation._previous_report_priority(docs, PREVIOUS, CUTOFF, 2))

    def test_parent_passes_only_the_docs_setting_to_the_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            env_file = root / "preclose.env"
            env_file.write_text(
                f"CHANLUN_OBSERVATION_FORMAL_DOCS_DIR={docs}\nWXPUSHER_APP_TOKEN=file-token\n"
                "WECOM_BOT_WEBHOOK=file-webhook\nUNRELATED_PRIVATE_FIELD=file-secret\n"
            )
            env_file.chmod(0o600)
            actual_popen = subprocess.Popen
            children = []

            def inspect_worker(command, **kwargs):
                # Use a real finite child to check exactly what the parent passed.
                self.assertIn("--compute-worker", command)
                self.assertNotIn("--env-file", command)
                self.assertNotIn(str(env_file), command)
                check = (
                    "import os,sys;"
                    "assert os.environ.get('CHANLUN_OBSERVATION_FORMAL_DOCS_DIR','') == sys.argv[1];"
                    "assert not {'WXPUSHER_APP_TOKEN','WECOM_BOT_WEBHOOK','OPENAI_API_KEY',"
                    "'UNRELATED_PRIVATE_FIELD'}.intersection(os.environ)"
                )
                child = actual_popen([sys.executable, "-B", "-c", check, str(expected)], **kwargs)
                children.append(child)
                return child

            args = SimpleNamespace(root=directory, formal_market_db=root / "formal.sqlite",
                                   input=None, env_file=str(env_file))
            for mode, expected in ((0o600, docs), (0o644, "")):
                env_file.chmod(mode)
                batch = root / str(mode)
                batch.mkdir()
                with patch.dict("os.environ", {"WXPUSHER_APP_TOKEN": "ambient-token",
                        "OPENAI_API_KEY": "ambient-key", "CHANLUN_OBSERVATION_FORMAL_DOCS_DIR": ""}), \
                        patch.object(runner.subprocess, "Popen", side_effect=inspect_worker), \
                        patch.object(runner, "_now", return_value=fixtures.NOW):
                    runner._run_worker(args, batch, DAY, fixtures.NOW + timedelta(seconds=2))
            self.assertEqual([child.poll() for child in children], [0, 0])
