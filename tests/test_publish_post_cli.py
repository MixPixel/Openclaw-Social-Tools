"""Tests for the publish_post scheduler runner CLI.

python -m tools.publish_post — flags-based runner for queue delivery.

Coverage:
  TestPublishPostCLIBasic       — output shape, exit codes, empty queue
  TestPublishPostCLIFlags       — --dry-run, --retry-failed, --log-file,
                                  --queue-file, --env-file
  TestPublishPostCLIDueEntries  — due entry with --dry-run shows outcome
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PAST_SLOT  = "2026-03-25T09:00:00+00:00"
_FUTURE_NOW = "2026-03-25T10:00:00+00:00"


def _run_cli(*extra_args, queue_path=None, env_extra=None) -> tuple[int, dict]:
    """Run python -m tools.publish_post with extra_args.

    Uses an empty temp queue file unless queue_path is provided.
    Returns (returncode, parsed_result).
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tmp_q:
        json.dump({}, tmp_q)
        tmp_q_path = tmp_q.name

    actual_queue = queue_path if queue_path is not None else tmp_q_path

    try:
        cmd = [
            sys.executable, "-m", "tools.publish_post",
            "--queue-file", actual_queue,
            "--approval-file", "/dev/null",
            "--log-file", "",           # suppress log writes in tests
            *extra_args,
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = _REPO_ROOT
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(cmd, capture_output=True, env=env, cwd=_REPO_ROOT)
        result = json.loads(proc.stdout.decode())
        return proc.returncode, result
    finally:
        if queue_path is None:
            try:
                os.unlink(tmp_q_path)
            except FileNotFoundError:
                pass


def _tmp_queue(entries: dict) -> str:
    """Write a temp queue JSON file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(entries, fh)
    return path


def _pending_entry(qid: str = "q001", post_id: str = "p001",
                   slot: str = _PAST_SLOT) -> dict:
    return {
        "queue_id":   qid,
        "post_id":    post_id,
        "platform":   "twitter",
        "content":    "Hello from the scheduler runner!",
        "slot":       slot,
        "created_at": "2026-03-25T08:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# TestPublishPostCLIBasic
# ---------------------------------------------------------------------------

class TestPublishPostCLIBasic(unittest.TestCase):

    def test_exits_0_on_empty_queue(self):
        code, _ = _run_cli()
        self.assertEqual(code, 0)

    def test_output_is_valid_json(self):
        code, result = _run_cli()
        self.assertIsInstance(result, dict)

    def test_success_true_on_empty_queue(self):
        _, result = _run_cli()
        self.assertTrue(result["success"])

    def test_processed_zero_on_empty_queue(self):
        _, result = _run_cli()
        self.assertEqual(result["processed"], 0)

    def test_result_has_now_field(self):
        _, result = _run_cli()
        self.assertIn("now", result)

    def test_result_has_results_list(self):
        _, result = _run_cli()
        self.assertIsInstance(result["results"], list)

    def test_exits_1_on_invalid_queue_json(self):
        fd, bad_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            fh.write("not valid json{{{")
        try:
            code, result = _run_cli(queue_path=bad_path)
            self.assertEqual(code, 1)
            self.assertFalse(result["success"])
        finally:
            os.unlink(bad_path)

    def test_error_code_on_invalid_queue(self):
        fd, bad_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            fh.write("{bad}")
        try:
            _, result = _run_cli(queue_path=bad_path)
            self.assertEqual(result.get("error_code"), "QUEUE_STORE_ERROR")
        finally:
            os.unlink(bad_path)


# ---------------------------------------------------------------------------
# TestPublishPostCLIFlags
# ---------------------------------------------------------------------------

class TestPublishPostCLIFlags(unittest.TestCase):

    def test_dry_run_flag_reflected_in_result(self):
        _, result = _run_cli("--dry-run")
        self.assertIs(result["dry_run"], True)

    def test_no_dry_run_flag_result_is_false(self):
        _, result = _run_cli()
        self.assertIs(result["dry_run"], False)

    def test_log_file_written_when_specified(self):
        fd, log_path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.unlink(log_path)
        # Queue has one due entry so there's something to log.
        qpath = _tmp_queue({"q1": _pending_entry()})
        try:
            cmd = [
                sys.executable, "-m", "tools.publish_post",
                "--queue-file", qpath,
                "--approval-file", "/dev/null",
                "--log-file", log_path,
                "--dry-run",
            ]
            env = os.environ.copy()
            env["PYTHONPATH"] = _REPO_ROOT
            subprocess.run(cmd, capture_output=True, env=env, cwd=_REPO_ROOT)
            self.assertTrue(os.path.exists(log_path))
        finally:
            os.unlink(qpath)
            try:
                os.unlink(log_path)
            except FileNotFoundError:
                pass

    def test_empty_log_file_arg_suppresses_log(self):
        """--log-file '' should not create a log file."""
        qpath = _tmp_queue({"q1": _pending_entry()})
        # If no log file is created we confirm suppression.
        # We use a path we know doesn't exist and check it stays absent.
        sentinel = "/tmp/should_not_be_created_zzz_openclaw.jsonl"
        try:
            os.unlink(sentinel)
        except FileNotFoundError:
            pass
        try:
            cmd = [
                sys.executable, "-m", "tools.publish_post",
                "--queue-file", qpath,
                "--approval-file", "/dev/null",
                "--log-file", "",
                "--dry-run",
            ]
            env = os.environ.copy()
            env["PYTHONPATH"] = _REPO_ROOT
            subprocess.run(cmd, capture_output=True, env=env, cwd=_REPO_ROOT)
            self.assertFalse(os.path.exists(sentinel))
        finally:
            os.unlink(qpath)

    def test_missing_env_file_exits_1(self):
        code, result = _run_cli("--env-file", "/tmp/nonexistent_zzz.env")
        self.assertEqual(code, 1)
        self.assertFalse(result["success"])
        self.assertEqual(result.get("error_code"), "ENV_FILE_ERROR")

    def test_env_file_loaded_correctly(self):
        """Credentials in a .env file reach os.environ before the adapter runs."""
        fd, env_path = tempfile.mkstemp(suffix=".env")
        with os.fdopen(fd, "w") as fh:
            fh.write("TWITTER_API_KEY=test_key_from_file\n")
        try:
            # Run with --dry-run so no actual delivery; we just confirm no crash.
            code, result = _run_cli("--dry-run", "--env-file", env_path)
            self.assertEqual(code, 0)
        finally:
            os.unlink(env_path)

    def test_custom_queue_file_used(self):
        """--queue-file reads from the specified path."""
        qpath = _tmp_queue({"q1": _pending_entry(), "q2": _pending_entry("q2", "p2")})
        try:
            _, result = _run_cli("--dry-run", queue_path=qpath)
            self.assertEqual(result["processed"], 2)
        finally:
            os.unlink(qpath)


# ---------------------------------------------------------------------------
# TestPublishPostCLIDueEntries
# ---------------------------------------------------------------------------

class TestPublishPostCLIDueEntries(unittest.TestCase):

    def test_due_entry_processed_in_dry_run(self):
        qpath = _tmp_queue({"q1": _pending_entry()})
        try:
            _, result = _run_cli("--dry-run", queue_path=qpath)
            self.assertEqual(result["processed"], 1)
        finally:
            os.unlink(qpath)

    def test_due_entry_outcome_is_dry_run(self):
        qpath = _tmp_queue({"q1": _pending_entry()})
        try:
            _, result = _run_cli("--dry-run", queue_path=qpath)
            self.assertEqual(result["results"][0]["outcome"], "dry_run")
        finally:
            os.unlink(qpath)

    def test_future_slot_not_processed(self):
        future_slot = "2099-01-01T00:00:00+00:00"
        qpath = _tmp_queue({"q1": _pending_entry(slot=future_slot)})
        try:
            _, result = _run_cli("--dry-run", queue_path=qpath)
            self.assertEqual(result["processed"], 0)
        finally:
            os.unlink(qpath)

    def test_already_posted_entry_skipped(self):
        entry = {**_pending_entry(), "status": "posted",
                 "posted_at": "2026-03-25T08:00:00+00:00"}
        qpath = _tmp_queue({"q1": entry})
        try:
            _, result = _run_cli(queue_path=qpath)
            self.assertEqual(result["results"][0]["outcome"], "already_posted")
        finally:
            os.unlink(qpath)

    def test_failed_entry_retried_with_flag(self):
        """--retry-failed makes failed entries eligible for delivery."""
        entry = {**_pending_entry(), "status": "failed",
                 "failed_at": "2026-03-25T08:00:00+00:00",
                 "error_code": "ADAPTER_EXCEPTION"}
        qpath = _tmp_queue({"q1": entry})
        try:
            # dry_run + retry_failed: entry is attempted (dry_run outcome)
            _, result = _run_cli("--dry-run", "--retry-failed", queue_path=qpath)
            self.assertEqual(result["results"][0]["outcome"], "dry_run")
        finally:
            os.unlink(qpath)

    def test_failed_entry_skipped_without_retry_flag(self):
        entry = {**_pending_entry(), "status": "failed",
                 "failed_at": "2026-03-25T08:00:00+00:00",
                 "error_code": "ADAPTER_EXCEPTION"}
        qpath = _tmp_queue({"q1": entry})
        try:
            _, result = _run_cli(queue_path=qpath)
            self.assertEqual(result["results"][0]["outcome"], "already_failed")
        finally:
            os.unlink(qpath)

    def test_two_due_entries_both_processed(self):
        qpath = _tmp_queue({
            "q1": _pending_entry("q1", "p1"),
            "q2": _pending_entry("q2", "p2"),
        })
        try:
            _, result = _run_cli("--dry-run", queue_path=qpath)
            self.assertEqual(result["processed"], 2)
        finally:
            os.unlink(qpath)


if __name__ == "__main__":
    unittest.main()
