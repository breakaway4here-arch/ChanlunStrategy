import io
import json
from pathlib import Path
import tempfile
import unittest

import opening_limitup_run
from tests.test_opening_limitup import evidence


class OpeningRunTests(unittest.TestCase):
    def test_offline_default_preview_never_calls_collector_or_sender(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"input.json"; p.write_text(json.dumps(evidence()))
            output = io.StringIO()
            def forbidden(*a, **k): raise AssertionError("no network")
            code = opening_limitup_run.main(["--input", str(p)], collector=forbidden, stdout=output)
            r = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(r["delivery_status"], "dry_run")
            self.assertTrue(r["offline_replay"])
            self.assertEqual(r["result"]["status"], "candidate")

    def test_send_from_offline_input_is_blocked_without_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"input.json"; p.write_text(json.dumps(evidence()))
            output = io.StringIO()
            code = opening_limitup_run.main(["--input", str(p), "--send"], stdout=output)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["delivery_status"], "blocked_offline_input")

    def test_preview_output_does_not_allow_formal_data_directory(self):
        output = io.StringIO()
        code = opening_limitup_run.main(["--output-dir", "docs/data"], stdout=output)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["delivery_status"], "blocked_preview_directory")

    def test_collector_failure_renders_data_insufficient_without_traceback(self):
        output = io.StringIO()
        def failed(*a, **k): raise TimeoutError("secret detail")
        code = opening_limitup_run.main(["--date", "2026-11-03"], collector=failed, stdout=output)
        r = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(r["result"]["status"], "unavailable")
        self.assertIn("数据不足", r["message"])
        self.assertNotIn("secret detail", output.getvalue())

    def test_each_preview_leaf_replaces_symlink_without_following_target(self):
        for leaf in ("evidence.json", "result.json", "message.txt"):
            with self.subTest(leaf=leaf), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); p=root/"input.json";p.write_text(json.dumps(evidence()))
                preview=root/"opening-limitup-preview";preview.mkdir()
                target=root/"formal-db-standin.sqlite";target.write_bytes(b"UNCHANGED_STANDIN")
                (preview/leaf).symlink_to(target)
                code=opening_limitup_run.main(["--input",str(p),"--output-dir",str(preview)],stdout=io.StringIO())
                self.assertEqual(target.read_bytes(),b"UNCHANGED_STANDIN")
                self.assertEqual(code,0)
                self.assertFalse((preview/leaf).is_symlink())

    def test_regular_preview_can_be_exported_again_without_temporary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"input.json";preview=root/"opening-limitup-preview"
            e=evidence();p.write_text(json.dumps(e))
            args=["--input",str(p),"--output-dir",str(preview)]
            self.assertEqual(opening_limitup_run.main(args,stdout=io.StringIO()),0)
            e["index"]["sessions"][-1]["open"]="9";p.write_text(json.dumps(e))
            self.assertEqual(opening_limitup_run.main(args,stdout=io.StringIO()),0)
            self.assertEqual(json.loads((preview/"result.json").read_text())["result"]["status"],"no_trade")
            self.assertEqual(sorted(p.name for p in preview.iterdir()),["evidence.json","message.txt","result.json"])


if __name__ == "__main__": unittest.main()
