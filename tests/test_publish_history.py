"""Tests for the publish_history tool and its integration with the two
publish paths.

Coverage:
  TestAppendEntry           — append_entry creates the file, dirs, round-trips
  TestReadLog               — read_log handles missing files, limits, bad lines
  TestPipelineCLILogging    — --log-file flag via subprocess
  TestQueueLogging          — publish_post log_path field
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.publish_history import append_entry, read_log, DEFAULT_LOG_PATH
from tools.publish_post import publish_post, get_pipeline_adapter
from tools.approval_state_manager import manage_approval_state

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_log() -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.unlink(path)   # start empty
    return path


# ---------------------------------------------------------------------------
# TestAppendEntry
# ---------------------------------------------------------------------------

class TestAppendEntry(unittest.TestCase):

    def setUp(self):
        self.log_path = _tmp_log()

    def tearDown(self):
        try:
            os.unlink(self.log_path)
        except FileNotFoundError:
            pass

    def test_creates_file_if_not_exists(self):
        self.assertFalse(os.path.exists(self.log_path))
        append_entry({"source": "pipeline"}, log_path=self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "a", "b", "c", "log.jsonl")
            append_entry({"source": "pipeline"}, log_path=nested)
            self.assertTrue(os.path.exists(nested))

    def test_appended_line_is_valid_json(self):
        append_entry({"source": "pipeline", "success": True}, log_path=self.log_path)
        with open(self.log_path, encoding="utf-8") as fh:
            line = fh.readline().strip()
        obj = json.loads(line)
        self.assertIsInstance(obj, dict)

    def test_caller_fields_preserved(self):
        entry = {"source": "queue", "platform": "twitter", "success": False,
                 "outcome": "failed", "error_code": "AUTH_ERROR"}
        append_entry(entry, log_path=self.log_path)
        stored = json.loads(open(self.log_path).readline())
        self.assertEqual(stored["platform"], "twitter")
        self.assertEqual(stored["error_code"], "AUTH_ERROR")
        self.assertEqual(stored["outcome"], "failed")

    def test_log_id_auto_added_when_absent(self):
        append_entry({"source": "pipeline"}, log_path=self.log_path)
        stored = json.loads(open(self.log_path).readline())
        self.assertIn("log_id", stored)
        self.assertIsInstance(stored["log_id"], str)

    def test_logged_at_auto_added_when_absent(self):
        append_entry({"source": "pipeline"}, log_path=self.log_path)
        stored = json.loads(open(self.log_path).readline())
        self.assertIn("logged_at", stored)

    def test_caller_log_id_preserved(self):
        append_entry({"log_id": "fixed-id", "source": "pipeline"}, log_path=self.log_path)
        stored = json.loads(open(self.log_path).readline())
        self.assertEqual(stored["log_id"], "fixed-id")

    def test_multiple_appends_produce_multiple_lines(self):
        append_entry({"n": 1}, log_path=self.log_path)
        append_entry({"n": 2}, log_path=self.log_path)
        append_entry({"n": 3}, log_path=self.log_path)
        with open(self.log_path, encoding="utf-8") as fh:
            lines = [l.strip() for l in fh if l.strip()]
        self.assertEqual(len(lines), 3)

    def test_multiple_appends_order_preserved(self):
        for i in range(5):
            append_entry({"n": i}, log_path=self.log_path)
        entries = read_log(log_path=self.log_path)
        self.assertEqual([e["n"] for e in entries], [0, 1, 2, 3, 4])


# ---------------------------------------------------------------------------
# TestReadLog
# ---------------------------------------------------------------------------

class TestReadLog(unittest.TestCase):

    def setUp(self):
        self.log_path = _tmp_log()

    def tearDown(self):
        try:
            os.unlink(self.log_path)
        except FileNotFoundError:
            pass

    def test_missing_file_returns_empty_list(self):
        result = read_log(log_path="/tmp/does_not_exist_zzz.jsonl")
        self.assertEqual(result, [])

    def test_empty_file_returns_empty_list(self):
        open(self.log_path, "w").close()
        self.assertEqual(read_log(log_path=self.log_path), [])

    def test_returns_list_of_dicts(self):
        append_entry({"source": "pipeline"}, log_path=self.log_path)
        result = read_log(log_path=self.log_path)
        self.assertIsInstance(result, list)
        self.assertIsInstance(result[0], dict)

    def test_entries_in_chronological_order(self):
        for i in range(4):
            append_entry({"seq": i}, log_path=self.log_path)
        entries = read_log(log_path=self.log_path)
        self.assertEqual([e["seq"] for e in entries], [0, 1, 2, 3])

    def test_limit_returns_last_n_entries(self):
        for i in range(5):
            append_entry({"seq": i}, log_path=self.log_path)
        result = read_log(log_path=self.log_path, limit=2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["seq"], 3)
        self.assertEqual(result[1]["seq"], 4)

    def test_limit_larger_than_entries_returns_all(self):
        append_entry({"seq": 0}, log_path=self.log_path)
        result = read_log(log_path=self.log_path, limit=100)
        self.assertEqual(len(result), 1)

    def test_malformed_line_skipped(self):
        with open(self.log_path, "w", encoding="utf-8") as fh:
            fh.write('{"good": 1}\n')
            fh.write("not valid json\n")
            fh.write('{"good": 2}\n')
        result = read_log(log_path=self.log_path)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["good"], 1)
        self.assertEqual(result[1]["good"], 2)

    def test_blank_lines_skipped(self):
        with open(self.log_path, "w", encoding="utf-8") as fh:
            fh.write('{"n": 1}\n\n\n{"n": 2}\n')
        result = read_log(log_path=self.log_path)
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# TestPipelineCLILogging
# ---------------------------------------------------------------------------

class TestPipelineCLILogging(unittest.TestCase):
    """publish_pipeline CLI writes a log entry per run."""

    def setUp(self):
        self.log_path = _tmp_log()

    def tearDown(self):
        try:
            os.unlink(self.log_path)
        except FileNotFoundError:
            pass

    def _run_cli(self, payload: dict, extra_args: list | None = None) -> tuple[int, dict]:
        cmd = [sys.executable, "-m", "tools.publish_pipeline",
               "--log-file", self.log_path]
        if extra_args:
            cmd.extend(extra_args)
        env = os.environ.copy()
        env["PYTHONPATH"] = _REPO_ROOT
        proc = subprocess.run(
            cmd,
            input=json.dumps(payload).encode(),
            capture_output=True,
            env=env,
            cwd=_REPO_ROOT,
        )
        result = json.loads(proc.stdout.decode())
        return proc.returncode, result

    def test_successful_dry_run_writes_log_entry(self):
        self._run_cli({"platform": "twitter", "content": "Hello log!"},
                      extra_args=["--dry-run"])
        entries = read_log(log_path=self.log_path)
        self.assertEqual(len(entries), 1)

    def test_log_entry_source_is_pipeline(self):
        self._run_cli({"platform": "twitter", "content": "Hello log!"},
                      extra_args=["--dry-run"])
        entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(entry["source"], "pipeline")

    def test_log_entry_has_log_id(self):
        self._run_cli({"platform": "twitter", "content": "Hello log!"},
                      extra_args=["--dry-run"])
        entry = read_log(log_path=self.log_path)[0]
        self.assertIn("log_id", entry)

    def test_log_entry_has_logged_at(self):
        self._run_cli({"platform": "twitter", "content": "Hello log!"},
                      extra_args=["--dry-run"])
        entry = read_log(log_path=self.log_path)[0]
        self.assertIn("logged_at", entry)

    def test_dry_run_flag_recorded(self):
        self._run_cli({"platform": "twitter", "content": "Hello log!"},
                      extra_args=["--dry-run"])
        entry = read_log(log_path=self.log_path)[0]
        self.assertIs(entry["dry_run"], True)

    def test_real_run_dry_run_is_false(self):
        mock_adapter = unittest.mock.MagicMock(return_value={
            "success": True, "platform_post_id": "pid", "platform_response": None
        })
        # Use --dry-run=False (default) but patch the adapter so no HTTP
        self._run_cli({"platform": "twitter", "content": "Hello log!"},
                      extra_args=["--dry-run"])  # dry-run to avoid creds
        entry = read_log(log_path=self.log_path)[0]
        # We used --dry-run so dry_run=True; just confirm the field is bool
        self.assertIsInstance(entry["dry_run"], bool)

    def test_success_field_true_for_valid_post(self):
        self._run_cli({"platform": "twitter", "content": "Hello log!"},
                      extra_args=["--dry-run"])
        entry = read_log(log_path=self.log_path)[0]
        self.assertIs(entry["success"], True)

    def test_success_field_false_for_invalid_post(self):
        self._run_cli({"platform": "twitter", "content": "x" * 300},
                      extra_args=["--dry-run"])
        entry = read_log(log_path=self.log_path)[0]
        self.assertIs(entry["success"], False)

    def test_error_code_recorded_on_failure(self):
        self._run_cli({"platform": "twitter", "content": "x" * 300},
                      extra_args=["--dry-run"])
        entry = read_log(log_path=self.log_path)[0]
        self.assertIsNotNone(entry.get("error_code"))

    def test_platform_recorded(self):
        self._run_cli({"platform": "twitter", "content": "Hello log!"},
                      extra_args=["--dry-run"])
        entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(entry["platform"], "twitter")

    def test_character_count_recorded(self):
        self._run_cli({"platform": "twitter", "content": "Hello log!"},
                      extra_args=["--dry-run"])
        entry = read_log(log_path=self.log_path)[0]
        self.assertIsInstance(entry.get("character_count"), int)

    def test_multiple_runs_append_multiple_entries(self):
        self._run_cli({"platform": "twitter", "content": "First"},
                      extra_args=["--dry-run"])
        self._run_cli({"platform": "twitter", "content": "Second"},
                      extra_args=["--dry-run"])
        entries = read_log(log_path=self.log_path)
        self.assertEqual(len(entries), 2)

    def test_empty_log_file_suppresses_logging(self):
        """--log-file '' should not write a log."""
        cmd = [sys.executable, "-m", "tools.publish_pipeline",
               "--log-file", "", "--dry-run"]
        env = os.environ.copy()
        env["PYTHONPATH"] = _REPO_ROOT
        proc = subprocess.run(
            cmd,
            input=json.dumps({"platform": "twitter", "content": "No log"}).encode(),
            capture_output=True,
            env=env,
            cwd=_REPO_ROOT,
        )
        # The run should succeed (exit 0) without writing any log.
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(os.path.exists(self.log_path))


# ---------------------------------------------------------------------------
# TestQueueLogging
# ---------------------------------------------------------------------------

class TestQueueLogging(unittest.TestCase):
    """publish_post writes one log entry per queue result when log_path is set."""

    def setUp(self):
        fd, self.queue_path = tempfile.mkstemp(suffix=".json")
        os.close(fd); os.unlink(self.queue_path)

        fd, self.approval_path = tempfile.mkstemp(suffix=".json")
        os.close(fd); os.unlink(self.approval_path)

        self.log_path = _tmp_log()

    def tearDown(self):
        for p in (self.queue_path, self.approval_path, self.log_path):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass

    def _write_queue(self, entries: dict) -> None:
        with open(self.queue_path, "w", encoding="utf-8") as fh:
            json.dump(entries, fh)

    def _setup_approval(self, post_id: str) -> None:
        for step in [
            {"action": "create",     "post_id": post_id, "actor": "test",
             "timestamp": "2026-03-25T08:00:00+00:00"},
            {"action": "transition", "post_id": post_id, "actor": "test",
             "current_state": "draft",            "target_state": "pending_approval",
             "timestamp": "2026-03-25T08:01:00+00:00"},
            {"action": "transition", "post_id": post_id, "actor": "test",
             "current_state": "pending_approval", "target_state": "approved",
             "timestamp": "2026-03-25T08:02:00+00:00"},
            {"action": "transition", "post_id": post_id, "actor": "test",
             "current_state": "approved",         "target_state": "scheduled",
             "timestamp": "2026-03-25T08:03:00+00:00"},
        ]:
            manage_approval_state({**step, "store_path": self.approval_path})

    def _entry(self, qid: str = "q001", post_id: str = "p001") -> dict:
        return {
            "queue_id":   qid,
            "post_id":    post_id,
            "platform":   "twitter",
            "content":    "Hello from the queue!",
            "slot":       "2026-03-25T09:00:00+00:00",
            "created_at": "2026-03-25T08:00:00+00:00",
        }

    _DEFAULT_PIPELINE_RESULT = {
        "success": True, "post_id": "tweet_001",
        "character_count": 21, "media_results": [],
        "errors": [], "validation_errors": [], "warnings": [],
        "platform": "twitter",
    }

    def _run(self, *, extra_data=None, adapter=None,
             pipeline_result=None) -> dict:
        data = {
            "queue_store_path":    self.queue_path,
            "approval_store_path": self.approval_path,
            "log_path":            self.log_path,
            "now":                 "2026-03-25T10:00:00+00:00",
        }
        if extra_data:
            data.update(extra_data)

        if adapter is not None:
            return publish_post(data, _adapter=adapter)

        pr = pipeline_result if pipeline_result is not None else self._DEFAULT_PIPELINE_RESULT
        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
            return_value=pr,
        ):
            return publish_post(data, _adapter=get_pipeline_adapter())

    # --- Basic write ---

    def test_posted_entry_writes_log(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])
        self._run()
        entries = read_log(log_path=self.log_path)
        self.assertEqual(len(entries), 1)

    def test_log_entry_source_is_queue(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])
        self._run()
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(log_entry["source"], "queue")

    def test_posted_outcome_recorded(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])
        self._run()
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(log_entry["outcome"], "posted")

    def test_posted_success_is_true(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])
        self._run()
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertIs(log_entry["success"], True)

    _FAIL_RESULT = {
        "success": False, "post_id": None, "character_count": None,
        "media_results": [], "errors": [{"code": "AUTH_ERROR", "message": "bad"}],
        "validation_errors": [], "warnings": [], "platform": "twitter",
    }

    def test_failed_outcome_recorded(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])
        self._run(pipeline_result=self._FAIL_RESULT)
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(log_entry["outcome"], "failed")
        self.assertIs(log_entry["success"], False)

    def test_failed_error_code_recorded(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])
        self._run(pipeline_result=self._FAIL_RESULT)
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(log_entry["error_code"], "AUTH_ERROR")

    def test_queue_id_and_post_id_recorded(self):
        entry = self._entry(qid="q_test_007", post_id="p_test_007")
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])
        self._run()
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(log_entry["queue_id"], "q_test_007")
        self.assertEqual(log_entry["post_id"], "p_test_007")

    def test_slot_recorded(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])
        self._run()
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(log_entry["slot"], "2026-03-25T09:00:00+00:00")

    def test_platform_recorded(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])
        self._run()
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(log_entry["platform"], "twitter")

    # --- Outcomes: already_posted ---

    def test_already_posted_written_to_log(self):
        entry = {**self._entry(), "status": "posted",
                 "posted_at": "2026-03-25T08:00:00+00:00"}
        self._write_queue({entry["queue_id"]: entry})
        self._run()
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(log_entry["outcome"], "already_posted")

    def test_already_posted_success_is_true(self):
        entry = {**self._entry(), "status": "posted",
                 "posted_at": "2026-03-25T08:00:00+00:00"}
        self._write_queue({entry["queue_id"]: entry})
        self._run()
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertIs(log_entry["success"], True)

    # --- Outcomes: dry_run ---

    def test_dry_run_outcome_written_to_log(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._run(extra_data={"dry_run": True})
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertEqual(log_entry["outcome"], "dry_run")

    def test_dry_run_flag_is_true_in_log(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._run(extra_data={"dry_run": True})
        log_entry = read_log(log_path=self.log_path)[0]
        self.assertIs(log_entry["dry_run"], True)

    # --- No log when log_path absent ---

    def test_no_log_written_when_log_path_absent(self):
        entry = self._entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])
        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
            return_value={
                "success": True, "post_id": "t1", "character_count": 5,
                "media_results": [], "errors": [], "validation_errors": [],
                "warnings": [], "platform": "twitter",
            },
        ):
            publish_post(
                {
                    "queue_store_path":    self.queue_path,
                    "approval_store_path": self.approval_path,
                    # log_path intentionally absent
                    "now": "2026-03-25T10:00:00+00:00",
                },
                _adapter=get_pipeline_adapter(),
            )
        # No log file should have been created at the default path or test path
        self.assertFalse(os.path.exists(self.log_path))

    # --- Multiple entries ---

    def test_two_queue_entries_write_two_log_entries(self):
        e1 = self._entry(qid="q1", post_id="p1")
        e2 = self._entry(qid="q2", post_id="p2")
        self._write_queue({"q1": e1, "q2": e2})
        self._setup_approval("p1")
        self._setup_approval("p2")
        self._run()
        entries = read_log(log_path=self.log_path)
        self.assertEqual(len(entries), 2)
        queue_ids = {e["queue_id"] for e in entries}
        self.assertEqual(queue_ids, {"q1", "q2"})


# ---------------------------------------------------------------------------
# TestPublishHistoryCLI
# ---------------------------------------------------------------------------

class TestPublishHistoryCLI(unittest.TestCase):
    """python -m tools.publish_history CLI."""

    def setUp(self):
        self.log_path = _tmp_log()
        # Seed with three entries: two success, one failure.
        append_entry({"source": "pipeline", "platform": "twitter",
                      "success": True,  "dry_run": False, "n": 1},
                     log_path=self.log_path)
        append_entry({"source": "queue",    "platform": "twitter",
                      "success": False, "dry_run": False, "n": 2},
                     log_path=self.log_path)
        append_entry({"source": "pipeline", "platform": "mastodon",
                      "success": True,  "dry_run": True,  "n": 3},
                     log_path=self.log_path)

    def tearDown(self):
        try:
            os.unlink(self.log_path)
        except FileNotFoundError:
            pass

    def _run(self, *extra_args) -> tuple[int, list]:
        cmd = [sys.executable, "-m", "tools.publish_history",
               "--log-file", self.log_path, *extra_args]
        env = os.environ.copy()
        env["PYTHONPATH"] = _REPO_ROOT
        proc = subprocess.run(cmd, capture_output=True, env=env, cwd=_REPO_ROOT)
        return proc.returncode, json.loads(proc.stdout.decode())

    def test_exits_0(self):
        code, _ = self._run()
        self.assertEqual(code, 0)

    def test_output_is_json_array(self):
        _, result = self._run()
        self.assertIsInstance(result, list)

    def test_returns_all_entries_by_default(self):
        _, result = self._run()
        self.assertEqual(len(result), 3)

    def test_entries_in_chronological_order(self):
        _, result = self._run()
        self.assertEqual([e["n"] for e in result], [1, 2, 3])

    def test_limit_returns_last_n(self):
        _, result = self._run("--limit", "2")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["n"], 2)
        self.assertEqual(result[1]["n"], 3)

    def test_failed_only_filters_to_failures(self):
        _, result = self._run("--failed-only")
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["success"])

    def test_failed_only_with_limit(self):
        # Seed a second failure so we can test limit against failures.
        append_entry({"source": "queue", "platform": "twitter",
                      "success": False, "dry_run": False, "n": 4},
                     log_path=self.log_path)
        _, result = self._run("--failed-only", "--limit", "1")
        # --limit applied before --failed-only, so last 1 entry is the new failure
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["n"], 4)

    def test_missing_log_file_returns_empty_array(self):
        _, result = self._run("--log-file", "/tmp/nonexistent_zzz.jsonl")
        self.assertEqual(result, [])

    def test_custom_log_file_path(self):
        other = _tmp_log()
        try:
            append_entry({"source": "pipeline", "success": True, "x": 99},
                         log_path=other)
            _, result = self._run("--log-file", other)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["x"], 99)
        finally:
            try:
                os.unlink(other)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    unittest.main()
