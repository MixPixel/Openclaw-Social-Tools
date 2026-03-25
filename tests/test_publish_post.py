"""Tests for tools/publish_post/publish_post.py

Run from repo root:
    python -m unittest tests.test_publish_post
"""

import json
import os
import tempfile
import unittest

from tools.approval_state_manager import manage_approval_state
from tools.publish_post import publish_post

# ---------------------------------------------------------------------------
# Fixed timestamps
# ---------------------------------------------------------------------------

NOW        = "2026-03-25T10:00:00+00:00"   # injected "current time"
SLOT_DUE   = "2026-03-25T09:00:00+00:00"   # slot in the past → due
SLOT_DUE2  = "2026-03-25T09:30:00+00:00"   # a second due slot
SLOT_FUTURE = "2026-03-25T11:00:00+00:00"  # slot in the future → not due
CREATED    = "2026-03-25T08:00:00+00:00"   # created_at for queue entries


# ---------------------------------------------------------------------------
# Adapter stubs
# ---------------------------------------------------------------------------

def _ok_adapter(entry: dict) -> dict:
    """Always succeeds; returns a fixed platform_post_id."""
    return {"success": True, "platform_post_id": "pid_ok", "platform_response": None}


def _fail_adapter(entry: dict) -> dict:
    """Always fails with a predictable error."""
    return {"success": False, "error_code": "ADAPTER_ERROR", "message": "down"}


def _raising_adapter(entry: dict) -> dict:
    """Always raises an exception."""
    raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Base fixture
# ---------------------------------------------------------------------------

class _Base(unittest.TestCase):
    """Fresh temp stores per test, helpers for queue and approval setup."""

    POST_ID  = "post_001"
    QUEUE_ID = "q_001"

    def setUp(self):
        fd, self.approval_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.approval_path)

        fd, self.queue_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.queue_path)

    def tearDown(self):
        for path in (self.approval_path, self.queue_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    # --- queue helpers ---

    def _make_entry(
        self,
        queue_id=None,
        post_id=None,
        slot=SLOT_DUE,
        status=None,
        platform="twitter",
        **kw,
    ) -> dict:
        entry = {
            "queue_id":   queue_id or self.QUEUE_ID,
            "post_id":    post_id  or self.POST_ID,
            "platform":   platform,
            "content":    "Hello world! Sign up now.",
            "slot":       slot,
            "media":      [],
            "actor":      "scheduler",
            "created_at": CREATED,
        }
        if status is not None:
            entry["status"] = status
        entry.update(kw)
        return entry

    def _write_queue(self, entries: dict) -> None:
        with open(self.queue_path, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)

    def _read_queue(self) -> dict:
        try:
            with open(self.queue_path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return {}

    # --- approval helpers ---

    def _asm(self, extra: dict) -> dict:
        return manage_approval_state({**extra, "store_path": self.approval_path})

    def _setup_scheduled_post(self, post_id=None, queue_id=None, slot=SLOT_DUE):
        """Walk a post to 'scheduled' state and write a matching queue entry."""
        pid = post_id or self.POST_ID
        qid = queue_id or self.QUEUE_ID
        for step in [
            {"action": "create",     "post_id": pid, "actor": "a",
             "timestamp": "2026-03-25T08:00:00+00:00"},
            {"action": "transition", "post_id": pid, "actor": "a",
             "current_state": "draft",            "target_state": "pending_approval",
             "timestamp": "2026-03-25T08:01:00+00:00"},
            {"action": "transition", "post_id": pid, "actor": "a",
             "current_state": "pending_approval", "target_state": "approved",
             "timestamp": "2026-03-25T08:02:00+00:00"},
            {"action": "transition", "post_id": pid, "actor": "a",
             "current_state": "approved",         "target_state": "scheduled",
             "timestamp": "2026-03-25T08:03:00+00:00"},
        ]:
            self._asm(step)
        self._write_queue({qid: self._make_entry(queue_id=qid, post_id=pid, slot=slot)})

    # --- publish helper ---

    def _publish(self, _adapter=_ok_adapter, **kw) -> dict:
        data = {
            "now":                 NOW,
            "timestamp":           NOW,
            "queue_store_path":    self.queue_path,
            "approval_store_path": self.approval_path,
        }
        data.update(kw)
        return publish_post(data, _adapter=_adapter)


# ---------------------------------------------------------------------------
# TestEmptyAndNoOp
# ---------------------------------------------------------------------------

class TestEmptyAndNoOp(_Base):

    def test_empty_queue_returns_success(self):
        r = self._publish()
        self.assertTrue(r["success"])
        self.assertEqual(r["processed"],  0)
        self.assertEqual(r["posted"],     0)
        self.assertEqual(r["results"],    [])

    def test_no_due_entries_returns_zero_processed(self):
        self._write_queue({"q_001": self._make_entry(slot=SLOT_FUTURE)})
        r = self._publish()
        self.assertTrue(r["success"])
        self.assertEqual(r["processed"], 0)
        self.assertEqual(r["results"],   [])

    def test_now_echoed_in_response(self):
        r = self._publish()
        self.assertIn("now", r)
        self.assertTrue(r["now"].startswith("2026-03-25T10:00:00"))


# ---------------------------------------------------------------------------
# TestHappyPath
# ---------------------------------------------------------------------------

class TestHappyPath(_Base):

    def test_due_entry_outcome_posted(self):
        self._setup_scheduled_post()
        r = self._publish()
        self.assertTrue(r["success"])
        self.assertEqual(r["posted"],    1)
        self.assertEqual(r["processed"], 1)
        res = r["results"][0]
        self.assertEqual(res["outcome"],  "posted")
        self.assertEqual(res["queue_id"], self.QUEUE_ID)
        self.assertEqual(res["post_id"],  self.POST_ID)

    def test_queue_status_written_to_posted(self):
        self._setup_scheduled_post()
        self._publish()
        q = self._read_queue()
        self.assertEqual(q[self.QUEUE_ID]["status"],    "posted")
        self.assertEqual(q[self.QUEUE_ID]["posted_at"], NOW)

    def test_platform_post_id_stored_in_queue(self):
        self._setup_scheduled_post()
        self._publish()
        q = self._read_queue()
        self.assertEqual(q[self.QUEUE_ID]["platform_post_id"], "pid_ok")

    def test_approval_state_transitions_to_posted(self):
        self._setup_scheduled_post()
        self._publish()
        state = self._asm({"action": "get_state", "post_id": self.POST_ID})
        self.assertEqual(state["current_state"], "posted")

    def test_posted_at_in_per_entry_result(self):
        self._setup_scheduled_post()
        r = self._publish()
        self.assertEqual(r["results"][0]["posted_at"], NOW)

    def test_legacy_entry_no_status_treated_as_pending(self):
        """Entry written by schedule_post has no status field; must be delivered."""
        self._setup_scheduled_post()
        # Verify entry has no status field
        q = self._read_queue()
        self.assertNotIn("status", q[self.QUEUE_ID])
        # Should still be delivered
        r = self._publish()
        self.assertEqual(r["results"][0]["outcome"], "posted")

    def test_multiple_due_entries_all_processed(self):
        self._setup_scheduled_post(post_id="post_a", queue_id="q_a", slot=SLOT_DUE)
        # Add second post
        self._asm({"action": "create",     "post_id": "post_b", "actor": "a", "timestamp": "2026-03-25T08:00:00+00:00"})
        self._asm({"action": "transition", "post_id": "post_b", "actor": "a", "current_state": "draft",            "target_state": "pending_approval", "timestamp": "2026-03-25T08:01:00+00:00"})
        self._asm({"action": "transition", "post_id": "post_b", "actor": "a", "current_state": "pending_approval", "target_state": "approved",         "timestamp": "2026-03-25T08:02:00+00:00"})
        self._asm({"action": "transition", "post_id": "post_b", "actor": "a", "current_state": "approved",         "target_state": "scheduled",        "timestamp": "2026-03-25T08:03:00+00:00"})
        q = self._read_queue()
        q["q_b"] = self._make_entry(queue_id="q_b", post_id="post_b", slot=SLOT_DUE2)
        self._write_queue(q)

        r = self._publish()
        self.assertEqual(r["posted"],    2)
        self.assertEqual(r["processed"], 2)
        outcomes = {res["queue_id"]: res["outcome"] for res in r["results"]}
        self.assertEqual(outcomes["q_a"], "posted")
        self.assertEqual(outcomes["q_b"], "posted")


# ---------------------------------------------------------------------------
# TestIdempotency
# ---------------------------------------------------------------------------

class TestIdempotency(_Base):

    def test_already_posted_skipped(self):
        entry = self._make_entry(status="posted", posted_at=CREATED)
        self._write_queue({self.QUEUE_ID: entry})
        calls = []
        def _tracking_adapter(e):
            calls.append(e)
            return {"success": True, "platform_post_id": None, "platform_response": None}
        r = self._publish(_adapter=_tracking_adapter)
        self.assertEqual(r["already_posted"], 1)
        self.assertEqual(r["posted"],         0)
        self.assertEqual(r["results"][0]["outcome"], "already_posted")
        self.assertEqual(len(calls), 0)  # adapter must not be called

    def test_already_posted_result_includes_posted_at(self):
        entry = self._make_entry(status="posted", posted_at=CREATED)
        self._write_queue({self.QUEUE_ID: entry})
        r = self._publish()
        self.assertEqual(r["results"][0]["posted_at"], CREATED)

    def test_already_failed_skipped_when_retry_false(self):
        self._write_queue({self.QUEUE_ID: self._make_entry(status="failed")})
        r = self._publish(_adapter=_fail_adapter, retry_failed=False)
        self.assertEqual(r["already_failed"], 1)
        self.assertEqual(r["failed"],         0)
        self.assertEqual(r["results"][0]["outcome"], "already_failed")

    def test_second_call_after_success_is_already_posted(self):
        self._setup_scheduled_post()
        self._publish()  # first call → posted
        r = self._publish()  # second call → already_posted
        self.assertEqual(r["results"][0]["outcome"], "already_posted")
        self.assertEqual(r["already_posted"], 1)
        self.assertEqual(r["posted"],         0)


# ---------------------------------------------------------------------------
# TestAdapterFailure
# ---------------------------------------------------------------------------

class TestAdapterFailure(_Base):

    def test_adapter_failure_outcome_failed(self):
        self._setup_scheduled_post()
        r = self._publish(_adapter=_fail_adapter)
        self.assertTrue(r["success"])
        self.assertEqual(r["failed"],    1)
        self.assertEqual(r["posted"],    0)
        res = r["results"][0]
        self.assertEqual(res["outcome"],    "failed")
        self.assertEqual(res["error_code"], "ADAPTER_ERROR")
        self.assertEqual(res["message"],    "down")

    def test_adapter_failure_queue_status_written(self):
        self._setup_scheduled_post()
        self._publish(_adapter=_fail_adapter)
        q = self._read_queue()
        entry = q[self.QUEUE_ID]
        self.assertEqual(entry["status"],        "failed")
        self.assertEqual(entry["failed_at"],     NOW)
        self.assertEqual(entry["error_code"],    "ADAPTER_ERROR")
        self.assertEqual(entry["error_message"], "down")

    def test_adapter_failure_approval_state_transitions_to_failed(self):
        self._setup_scheduled_post()
        self._publish(_adapter=_fail_adapter)
        state = self._asm({"action": "get_state", "post_id": self.POST_ID})
        self.assertEqual(state["current_state"], "failed")

    def test_adapter_exception_recorded_as_failed(self):
        self._setup_scheduled_post()
        r = self._publish(_adapter=_raising_adapter)
        self.assertTrue(r["success"])
        res = r["results"][0]
        self.assertEqual(res["outcome"],    "failed")
        self.assertEqual(res["error_code"], "ADAPTER_EXCEPTION")
        self.assertIn("boom",               res["message"])

    def test_adapter_exception_written_to_queue(self):
        self._setup_scheduled_post()
        self._publish(_adapter=_raising_adapter)
        q = self._read_queue()
        entry = q[self.QUEUE_ID]
        self.assertEqual(entry["status"],     "failed")
        self.assertEqual(entry["error_code"], "ADAPTER_EXCEPTION")
        self.assertIn("boom", entry["error_message"])


# ---------------------------------------------------------------------------
# TestNotYetDue
# ---------------------------------------------------------------------------

class TestNotYetDue(_Base):

    def test_future_slot_not_selected(self):
        self._write_queue({"q_001": self._make_entry(slot=SLOT_FUTURE)})
        r = self._publish()
        self.assertEqual(r["processed"], 0)
        self.assertEqual(r["results"],   [])

    def test_mixed_due_and_future_only_due_processed(self):
        q = {
            "q_due":    self._make_entry(queue_id="q_due",    slot=SLOT_DUE),
            "q_future": self._make_entry(queue_id="q_future", slot=SLOT_FUTURE),
        }
        self._write_queue(q)
        r = self._publish()
        self.assertEqual(r["processed"], 1)
        self.assertEqual(r["results"][0]["queue_id"], "q_due")

    def test_slot_exactly_equal_to_now_is_due(self):
        # slot == now → due (slot <= now)
        self._write_queue({"q_001": self._make_entry(slot=NOW)})
        r = self._publish()
        self.assertEqual(r["processed"], 1)


# ---------------------------------------------------------------------------
# TestQueueIdsFilter
# ---------------------------------------------------------------------------

class TestQueueIdsFilter(_Base):

    def test_queue_ids_processes_only_named_entries(self):
        q = {
            "q_a": self._make_entry(queue_id="q_a", slot=SLOT_DUE),
            "q_b": self._make_entry(queue_id="q_b", slot=SLOT_DUE),
        }
        self._write_queue(q)
        r = self._publish(queue_ids=["q_a"])
        self.assertEqual(r["processed"], 1)
        self.assertEqual(r["results"][0]["queue_id"], "q_a")

    def test_queue_ids_missing_entry_returns_not_found(self):
        self._write_queue({"q_001": self._make_entry()})
        r = self._publish(queue_ids=["q_001", "q_missing"])
        outcomes = {res["queue_id"]: res["outcome"] for res in r["results"]}
        self.assertEqual(outcomes["q_001"],    "posted")
        self.assertEqual(outcomes["q_missing"], "not_found")

    def test_queue_ids_bypasses_slot_filter(self):
        """A future-slot entry is processed when explicitly named."""
        self._write_queue({"q_future": self._make_entry(queue_id="q_future", slot=SLOT_FUTURE)})
        r = self._publish(queue_ids=["q_future"])
        self.assertEqual(r["processed"], 1)
        self.assertEqual(r["results"][0]["outcome"], "posted")

    def test_queue_ids_respects_idempotency(self):
        entry = self._make_entry(status="posted", posted_at=CREATED)
        self._write_queue({self.QUEUE_ID: entry})
        r = self._publish(queue_ids=[self.QUEUE_ID])
        self.assertEqual(r["results"][0]["outcome"], "already_posted")

    def test_queue_ids_order_preserved_in_results(self):
        q = {
            "q_a": self._make_entry(queue_id="q_a"),
            "q_b": self._make_entry(queue_id="q_b"),
            "q_c": self._make_entry(queue_id="q_c"),
        }
        self._write_queue(q)
        r = self._publish(queue_ids=["q_c", "q_a"])
        self.assertEqual(r["results"][0]["queue_id"], "q_c")
        self.assertEqual(r["results"][1]["queue_id"], "q_a")


# ---------------------------------------------------------------------------
# TestDryRun
# ---------------------------------------------------------------------------

class TestDryRun(_Base):

    def test_dry_run_outcome_is_dry_run(self):
        self._write_queue({"q_001": self._make_entry()})
        r = self._publish(dry_run=True)
        self.assertTrue(r["success"])
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["results"][0]["outcome"], "dry_run")

    def test_dry_run_does_not_write_queue(self):
        self._write_queue({"q_001": self._make_entry()})
        self._publish(dry_run=True)
        q = self._read_queue()
        self.assertNotIn("status", q["q_001"])

    def test_dry_run_does_not_change_approval_state(self):
        self._setup_scheduled_post()
        self._publish(dry_run=True)
        state = self._asm({"action": "get_state", "post_id": self.POST_ID})
        self.assertEqual(state["current_state"], "scheduled")

    def test_dry_run_already_posted_still_returns_already_posted(self):
        """Idempotency check runs before the dry_run branch."""
        entry = self._make_entry(status="posted", posted_at=CREATED)
        self._write_queue({self.QUEUE_ID: entry})
        r = self._publish(dry_run=True)
        self.assertEqual(r["results"][0]["outcome"], "already_posted")

    def test_dry_run_does_not_count_in_posted_counter(self):
        self._write_queue({"q_001": self._make_entry()})
        r = self._publish(dry_run=True)
        self.assertEqual(r["posted"], 0)
        self.assertEqual(r["failed"], 0)


# ---------------------------------------------------------------------------
# TestRetryFailed
# ---------------------------------------------------------------------------

class TestRetryFailed(_Base):

    def test_retry_false_returns_already_failed(self):
        self._write_queue({self.QUEUE_ID: self._make_entry(status="failed")})
        r = self._publish(_adapter=_ok_adapter, retry_failed=False)
        self.assertEqual(r["results"][0]["outcome"], "already_failed")

    def test_retry_true_attempts_delivery_again(self):
        self._setup_scheduled_post()
        # First: fail
        self._publish(_adapter=_fail_adapter)
        # Confirm failed
        q = self._read_queue()
        self.assertEqual(q[self.QUEUE_ID]["status"], "failed")

        # Second: retry with ok adapter
        r = self._publish(_adapter=_ok_adapter, retry_failed=True)
        self.assertEqual(r["results"][0]["outcome"], "posted")

    def test_retry_true_overwrites_queue_status(self):
        self._setup_scheduled_post()
        self._publish(_adapter=_fail_adapter)
        self._publish(_adapter=_ok_adapter, retry_failed=True)
        q = self._read_queue()
        self.assertEqual(q[self.QUEUE_ID]["status"], "posted")


# ---------------------------------------------------------------------------
# TestStateTransitionWarning
# ---------------------------------------------------------------------------

class TestStateTransitionWarning(_Base):

    def test_warning_when_post_not_in_approval_store(self):
        """Queue entry with a post_id absent from the approval store.

        Queue write must succeed; approval transition fails (POST_NOT_FOUND);
        per-entry result includes state_transition_warning; top-level success=True.
        """
        # No approval store entry — post_id is unknown to manage_approval_state.
        self._write_queue({self.QUEUE_ID: self._make_entry()})
        r = self._publish()
        self.assertTrue(r["success"])
        res = r["results"][0]
        self.assertEqual(res["outcome"], "posted")
        self.assertIn("state_transition_warning", res)

    def test_queue_written_despite_transition_failure(self):
        self._write_queue({self.QUEUE_ID: self._make_entry()})
        self._publish()
        q = self._read_queue()
        self.assertEqual(q[self.QUEUE_ID]["status"], "posted")

    def test_transition_warning_counted_as_posted_in_summary(self):
        self._write_queue({self.QUEUE_ID: self._make_entry()})
        r = self._publish()
        self.assertEqual(r["posted"], 1)

    def test_warning_on_adapter_failure_and_wrong_approval_state(self):
        """Adapter fails; approval state is not 'scheduled' → transition warning on 'failed'."""
        self._write_queue({self.QUEUE_ID: self._make_entry()})
        r = self._publish(_adapter=_fail_adapter)
        self.assertTrue(r["success"])
        res = r["results"][0]
        self.assertEqual(res["outcome"], "failed")
        self.assertIn("state_transition_warning", res)


# ---------------------------------------------------------------------------
# TestSystemErrors
# ---------------------------------------------------------------------------

class TestSystemErrors(_Base):

    def test_corrupt_queue_store_returns_system_error(self):
        with open(self.queue_path, "w") as fh:
            fh.write("not valid json {{{")
        r = self._publish()
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "QUEUE_STORE_ERROR")
        self.assertIn("message", r)

    def test_missing_queue_store_treated_as_empty(self):
        # File does not exist → _read_store returns {}
        r = self._publish()
        self.assertTrue(r["success"])
        self.assertEqual(r["processed"], 0)


if __name__ == "__main__":
    unittest.main()
