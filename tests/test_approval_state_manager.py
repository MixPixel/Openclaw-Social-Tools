"""Tests for tools/approval_state_manager/approval_state_manager.py

Run from repo root:
    python -m unittest tests.test_approval_state_manager
"""

import os
import tempfile
import unittest

from tools.approval_state_manager import manage_approval_state

# Fixed timestamps used throughout to keep tests deterministic
T1 = "2026-03-24T10:00:00+00:00"
T2 = "2026-03-24T11:00:00+00:00"
T3 = "2026-03-24T12:00:00+00:00"
T4 = "2026-03-24T13:00:00+00:00"
T5 = "2026-03-24T14:00:00+00:00"


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

class _Base(unittest.TestCase):
    """Provides a fresh temp store file for each test."""

    def setUp(self):
        fd, self.store_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.store_path)  # start with no file

    def tearDown(self):
        try:
            os.unlink(self.store_path)
        except FileNotFoundError:
            pass

    # --- convenience wrappers ---

    def _call(self, data: dict) -> dict:
        return manage_approval_state({**data, "store_path": self.store_path})

    def _create(self, post_id="post_001", actor="author", timestamp=T1, **kw) -> dict:
        return self._call({
            "action": "create", "post_id": post_id,
            "actor": actor, "timestamp": timestamp, **kw,
        })

    def _transition(self, post_id, frm, to, actor="system", timestamp=T2, **kw) -> dict:
        return self._call({
            "action": "transition", "post_id": post_id,
            "current_state": frm, "target_state": to,
            "actor": actor, "timestamp": timestamp, **kw,
        })

    def _get_state(self, post_id) -> dict:
        return self._call({"action": "get_state", "post_id": post_id})

    def _get_history(self, post_id) -> dict:
        return self._call({"action": "get_history", "post_id": post_id})

    def _walk(self, post_id, *steps):
        """Run a chain of transitions.  steps = [(from, to, actor, timestamp), ...]"""
        for frm, to, actor, ts in steps:
            r = self._transition(post_id, frm, to, actor=actor, timestamp=ts)
            self.assertTrue(r["success"], f"transition {frm}→{to} failed: {r}")


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure(_Base):

    def test_all_responses_have_success(self):
        self._create()
        for r in [
            self._create(post_id="p2"),
            self._transition("p2", "draft", "pending_approval"),
            self._get_state("p2"),
            self._get_history("p2"),
        ]:
            self.assertIn("success", r, f"'success' missing in {r}")

    def test_success_true_on_create(self):
        r = self._create()
        self.assertTrue(r["success"])

    def test_success_false_on_error_has_error_code_and_message(self):
        r = self._call({"action": "get_state", "post_id": "nonexistent"})
        self.assertFalse(r["success"])
        self.assertIn("error_code", r)
        self.assertIn("message", r)

    def test_error_response_has_post_id(self):
        r = self._call({"action": "get_state", "post_id": "missing_post"})
        self.assertEqual(r["post_id"], "missing_post")

    def test_success_response_has_no_error_code(self):
        r = self._create()
        self.assertNotIn("error_code", r)
        self.assertNotIn("message", r)


# ---------------------------------------------------------------------------
# create action
# ---------------------------------------------------------------------------

class TestCreate(_Base):

    def test_creates_post_in_draft(self):
        r = self._create()
        self.assertTrue(r["success"])
        self.assertEqual(r["state"], "draft")

    def test_returns_post_id(self):
        r = self._create(post_id="abc")
        self.assertEqual(r["post_id"], "abc")

    def test_returns_actor(self):
        r = self._create(actor="alice")
        self.assertEqual(r["actor"], "alice")

    def test_returns_injected_timestamp(self):
        r = self._create(timestamp=T1)
        self.assertEqual(r["timestamp"], T1)

    def test_log_entry_id_is_log_0001(self):
        r = self._create()
        self.assertEqual(r["log_entry_id"], "log_0001")

    def test_get_state_after_create(self):
        self._create(post_id="p1")
        r = self._get_state("p1")
        self.assertEqual(r["current_state"], "draft")
        self.assertEqual(r["last_actor"], "author")
        self.assertEqual(r["last_updated"], T1)

    def test_history_has_one_entry_after_create(self):
        self._create(post_id="p1")
        r = self._get_history("p1")
        self.assertEqual(len(r["history"]), 1)
        entry = r["history"][0]
        self.assertIsNone(entry["from"])
        self.assertEqual(entry["to"], "draft")
        self.assertEqual(entry["actor"], "author")
        self.assertEqual(entry["log_entry_id"], "log_0001")

    def test_note_recorded_in_history(self):
        self._create(post_id="p1", note="Initial draft for Q2 campaign")
        r = self._get_history("p1")
        self.assertEqual(r["history"][0]["note"], "Initial draft for Q2 campaign")

    def test_note_none_when_omitted(self):
        self._create(post_id="p1")
        r = self._get_history("p1")
        self.assertIsNone(r["history"][0]["note"])

    def test_duplicate_post_id_returns_post_already_exists(self):
        self._create(post_id="p1")
        r = self._create(post_id="p1")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "POST_ALREADY_EXISTS")

    def test_duplicate_includes_current_state_in_message(self):
        self._create(post_id="p1")
        r = self._create(post_id="p1")
        self.assertIn("draft", r["message"])

    def test_missing_actor_returns_missing_required_field(self):
        r = self._call({"action": "create", "post_id": "p1"})
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")

    def test_store_file_created_on_first_write(self):
        self.assertFalse(os.path.exists(self.store_path))
        self._create()
        self.assertTrue(os.path.exists(self.store_path))

    def test_multiple_posts_coexist_in_store(self):
        self._create(post_id="p1")
        self._create(post_id="p2", actor="bob")
        self.assertTrue(self._get_state("p1")["success"])
        self.assertTrue(self._get_state("p2")["success"])


# ---------------------------------------------------------------------------
# transition action
# ---------------------------------------------------------------------------

class TestTransition(_Base):

    def setUp(self):
        super().setUp()
        self._create(post_id="p1", timestamp=T1)

    def test_valid_transition_succeeds(self):
        r = self._transition("p1", "draft", "pending_approval")
        self.assertTrue(r["success"])

    def test_returns_previous_and_new_state(self):
        r = self._transition("p1", "draft", "pending_approval")
        self.assertEqual(r["previous_state"], "draft")
        self.assertEqual(r["new_state"], "pending_approval")

    def test_returns_actor_and_timestamp(self):
        r = self._transition("p1", "draft", "pending_approval", actor="alice", timestamp=T2)
        self.assertEqual(r["actor"], "alice")
        self.assertEqual(r["timestamp"], T2)

    def test_log_entry_id_increments(self):
        r1 = self._transition("p1", "draft", "pending_approval", timestamp=T2)
        self.assertEqual(r1["log_entry_id"], "log_0002")
        r2 = self._transition("p1", "pending_approval", "approved", timestamp=T3)
        self.assertEqual(r2["log_entry_id"], "log_0003")

    def test_note_recorded(self):
        r = self._transition("p1", "draft", "pending_approval", note="Ready for review")
        self.assertTrue(r["success"])
        hist = self._get_history("p1")["history"]
        self.assertEqual(hist[-1]["note"], "Ready for review")

    def test_get_state_reflects_new_state(self):
        self._transition("p1", "draft", "pending_approval", timestamp=T2, actor="alice")
        s = self._get_state("p1")
        self.assertEqual(s["current_state"], "pending_approval")
        self.assertEqual(s["last_actor"], "alice")
        self.assertEqual(s["last_updated"], T2)

    def test_state_mismatch_rejected(self):
        # actual state is draft; caller claims pending_approval
        r = self._transition("p1", "pending_approval", "approved")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "STATE_MISMATCH")

    def test_state_mismatch_message_includes_actual_state(self):
        r = self._transition("p1", "pending_approval", "approved")
        self.assertIn("draft", r["message"])

    def test_state_mismatch_does_not_modify_state(self):
        self._transition("p1", "pending_approval", "approved")
        self.assertEqual(self._get_state("p1")["current_state"], "draft")

    def test_invalid_transition(self):
        r = self._transition("p1", "draft", "approved")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "INVALID_TRANSITION")

    def test_invalid_transition_message_includes_both_states(self):
        r = self._transition("p1", "draft", "approved")
        self.assertIn("draft", r["message"])
        self.assertIn("approved", r["message"])

    def test_post_not_found(self):
        r = self._transition("no_such_post", "draft", "pending_approval")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "POST_NOT_FOUND")

    def test_invalid_current_state_name(self):
        r = self._transition("p1", "limbo", "draft")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "INVALID_STATE")

    def test_invalid_target_state_name(self):
        r = self._transition("p1", "draft", "gondola")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "INVALID_STATE")

    def test_missing_actor(self):
        r = self._call({
            "action": "transition", "post_id": "p1",
            "current_state": "draft", "target_state": "pending_approval",
        })
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")

    def test_missing_current_state(self):
        r = self._call({
            "action": "transition", "post_id": "p1",
            "target_state": "pending_approval", "actor": "x",
        })
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")

    def test_missing_target_state(self):
        r = self._call({
            "action": "transition", "post_id": "p1",
            "current_state": "draft", "actor": "x",
        })
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")


# ---------------------------------------------------------------------------
# get_state action
# ---------------------------------------------------------------------------

class TestGetState(_Base):

    def test_returns_current_state(self):
        self._create(post_id="p1", actor="alice", timestamp=T1)
        r = self._get_state("p1")
        self.assertTrue(r["success"])
        self.assertEqual(r["post_id"], "p1")
        self.assertEqual(r["current_state"], "draft")
        self.assertEqual(r["last_actor"], "alice")
        self.assertEqual(r["last_updated"], T1)

    def test_reflects_state_after_transition(self):
        self._create(post_id="p1")
        self._transition("p1", "draft", "pending_approval", actor="bob", timestamp=T2)
        r = self._get_state("p1")
        self.assertEqual(r["current_state"], "pending_approval")
        self.assertEqual(r["last_actor"], "bob")
        self.assertEqual(r["last_updated"], T2)

    def test_post_not_found(self):
        r = self._get_state("ghost")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "POST_NOT_FOUND")

    def test_success_true_when_found(self):
        self._create()
        self.assertTrue(self._get_state("post_001")["success"])

    def test_does_not_modify_store(self):
        self._create(post_id="p1")
        self._get_state("p1")
        # State unchanged after read
        self.assertEqual(self._get_state("p1")["current_state"], "draft")


# ---------------------------------------------------------------------------
# get_history action
# ---------------------------------------------------------------------------

class TestGetHistory(_Base):

    def test_history_grows_with_each_transition(self):
        self._create(post_id="p1")
        self._transition("p1", "draft", "pending_approval", timestamp=T2)
        self._transition("p1", "pending_approval", "approved", timestamp=T3)
        r = self._get_history("p1")
        self.assertTrue(r["success"])
        self.assertEqual(len(r["history"]), 3)

    def test_first_entry_from_is_null(self):
        self._create(post_id="p1")
        r = self._get_history("p1")
        self.assertIsNone(r["history"][0]["from"])
        self.assertEqual(r["history"][0]["to"], "draft")

    def test_entry_fields_are_complete(self):
        self._create(post_id="p1", actor="alice")
        entry = self._get_history("p1")["history"][0]
        for field in ("log_entry_id", "from", "to", "actor", "timestamp", "note"):
            self.assertIn(field, entry, f"Missing field: {field}")

    def test_log_entry_ids_are_sequential(self):
        self._create(post_id="p1")
        self._transition("p1", "draft", "pending_approval", timestamp=T2)
        self._transition("p1", "pending_approval", "rejected", timestamp=T3)
        ids = [e["log_entry_id"] for e in self._get_history("p1")["history"]]
        self.assertEqual(ids, ["log_0001", "log_0002", "log_0003"])

    def test_actors_recorded_per_entry(self):
        self._create(post_id="p1", actor="author")
        self._transition("p1", "draft", "pending_approval", actor="author", timestamp=T2)
        self._transition("p1", "pending_approval", "approved", actor="reviewer", timestamp=T3)
        actors = [e["actor"] for e in self._get_history("p1")["history"]]
        self.assertEqual(actors, ["author", "author", "reviewer"])

    def test_post_not_found(self):
        r = self._get_history("unknown")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "POST_NOT_FOUND")

    def test_history_is_ordered_chronologically(self):
        self._create(post_id="p1")
        self._transition("p1", "draft", "pending_approval", timestamp=T2)
        hist = self._get_history("p1")["history"]
        timestamps = [e["timestamp"] for e in hist]
        self.assertEqual(timestamps, sorted(timestamps))


# ---------------------------------------------------------------------------
# State machine — valid transition coverage
# ---------------------------------------------------------------------------

class TestStateMachine(_Base):

    def _assert_transition_valid(self, setup_states, frm, to):
        """Helper: walk to frm, then assert frm→to succeeds."""
        post_id = f"test_{frm}_{to}"
        self._create(post_id=post_id, timestamp=T1)
        ts = T2
        for s_frm, s_to in setup_states:
            ts = str(int(ts[:4]) + 0) + ts[4:]  # same year, just reuse
            r = self._transition(post_id, s_frm, s_to, timestamp=ts)
            self.assertTrue(r["success"], f"Setup step {s_frm}→{s_to} failed: {r}")
        r = self._transition(post_id, frm, to, timestamp=T5)
        self.assertTrue(r["success"], f"Expected {frm}→{to} to succeed but got: {r}")

    def test_draft_to_pending(self):
        self._assert_transition_valid([], "draft", "pending_approval")

    def test_pending_to_approved(self):
        self._assert_transition_valid(
            [("draft", "pending_approval")],
            "pending_approval", "approved",
        )

    def test_pending_to_rejected(self):
        self._assert_transition_valid(
            [("draft", "pending_approval")],
            "pending_approval", "rejected",
        )

    def test_rejected_to_draft(self):
        self._assert_transition_valid(
            [("draft", "pending_approval"), ("pending_approval", "rejected")],
            "rejected", "draft",
        )

    def test_approved_to_scheduled(self):
        self._assert_transition_valid(
            [("draft", "pending_approval"), ("pending_approval", "approved")],
            "approved", "scheduled",
        )

    def test_approved_to_archived(self):
        self._assert_transition_valid(
            [("draft", "pending_approval"), ("pending_approval", "approved")],
            "approved", "archived",
        )

    def test_draft_to_archived(self):
        self._assert_transition_valid([], "draft", "archived")

    def test_pending_to_archived(self):
        self._assert_transition_valid(
            [("draft", "pending_approval")],
            "pending_approval", "archived",
        )

    def test_scheduled_to_archived(self):
        self._assert_transition_valid(
            [("draft", "pending_approval"),
             ("pending_approval", "approved"),
             ("approved", "scheduled")],
            "scheduled", "archived",
        )

    def test_scheduled_to_posted(self):
        self._assert_transition_valid(
            [("draft", "pending_approval"),
             ("pending_approval", "approved"),
             ("approved", "scheduled")],
            "scheduled", "posted",
        )

    def test_scheduled_to_failed(self):
        self._assert_transition_valid(
            [("draft", "pending_approval"),
             ("pending_approval", "approved"),
             ("approved", "scheduled")],
            "scheduled", "failed",
        )

    def test_archived_has_no_outgoing_transitions(self):
        self._create(post_id="p1")
        self._transition("p1", "draft", "archived", timestamp=T2)
        for target in ("draft", "pending_approval", "approved", "scheduled",
                       "rejected", "posted", "failed"):
            r = self._transition("p1", "archived", target, timestamp=T3)
            self.assertFalse(r["success"])
            self.assertEqual(r["error_code"], "INVALID_TRANSITION",
                             f"Expected INVALID_TRANSITION for archived→{target}")

    def test_posted_has_no_outgoing_transitions(self):
        self._create(post_id="p1")
        self._walk("p1",
            ("draft", "pending_approval", "author", T2),
            ("pending_approval", "approved", "reviewer", T3),
            ("approved", "scheduled", "scheduler", T4),
            ("scheduled", "posted", "publisher", T5),
        )
        for target in ("draft", "scheduled", "archived"):
            r = self._transition("p1", "posted", target, timestamp=T5)
            self.assertFalse(r["success"])
            self.assertEqual(r["error_code"], "INVALID_TRANSITION")

    def test_failed_has_no_outgoing_transitions(self):
        self._create(post_id="p1")
        self._walk("p1",
            ("draft", "pending_approval", "author", T2),
            ("pending_approval", "approved", "reviewer", T3),
            ("approved", "scheduled", "scheduler", T4),
            ("scheduled", "failed", "publisher", T5),
        )
        r = self._transition("p1", "failed", "draft", timestamp=T5)
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "INVALID_TRANSITION")


# ---------------------------------------------------------------------------
# Full workflow scenarios
# ---------------------------------------------------------------------------

class TestWorkflows(_Base):

    def test_approval_workflow_draft_to_posted(self):
        """Happy path: draft → pending → approved → scheduled → posted."""
        self._create(post_id="p1", actor="author", timestamp=T1)
        self._walk("p1",
            ("draft",            "pending_approval", "author",    T2),
            ("pending_approval", "approved",         "reviewer",  T3),
            ("approved",         "scheduled",        "scheduler", T4),
            ("scheduled",        "posted",           "publisher", T5),
        )
        s = self._get_state("p1")
        self.assertEqual(s["current_state"], "posted")
        self.assertEqual(len(self._get_history("p1")["history"]), 5)

    def test_rejection_and_revision_cycle(self):
        """Reject, revise, resubmit, approve."""
        self._create(post_id="p1", actor="author", timestamp=T1)
        self._walk("p1",
            ("draft",            "pending_approval", "author",   T2),
            ("pending_approval", "rejected",         "reviewer", T3),
            ("rejected",         "draft",            "author",   T4),
            ("draft",            "pending_approval", "author",   T5),
        )
        self.assertEqual(self._get_state("p1")["current_state"], "pending_approval")
        self.assertEqual(len(self._get_history("p1")["history"]), 5)

    def test_archive_after_scheduling(self):
        """Scheduled post is cancelled."""
        self._create(post_id="p1", timestamp=T1)
        self._walk("p1",
            ("draft",            "pending_approval", "author",    T2),
            ("pending_approval", "approved",         "reviewer",  T3),
            ("approved",         "scheduled",        "scheduler", T4),
            ("scheduled",        "archived",         "admin",     T5),
        )
        self.assertEqual(self._get_state("p1")["current_state"], "archived")

    def test_scheduled_to_failed_records_history(self):
        self._create(post_id="p1", timestamp=T1)
        self._walk("p1",
            ("draft",            "pending_approval", "author",    T2),
            ("pending_approval", "approved",         "reviewer",  T3),
            ("approved",         "scheduled",        "scheduler", T4),
        )
        r = self._transition("p1", "scheduled", "failed",
                             actor="publisher", timestamp=T5, note="API timeout")
        self.assertTrue(r["success"])
        hist = self._get_history("p1")["history"]
        last = hist[-1]
        self.assertEqual(last["to"], "failed")
        self.assertEqual(last["note"], "API timeout")

    def test_concurrent_write_simulation(self):
        """Second caller gets STATE_MISMATCH after first succeeds."""
        self._create(post_id="p1", timestamp=T1)
        # First caller transitions draft → pending_approval
        r1 = self._transition("p1", "draft", "pending_approval", timestamp=T2)
        self.assertTrue(r1["success"])
        # Second caller also thinks state is draft
        r2 = self._transition("p1", "draft", "pending_approval", timestamp=T3)
        self.assertFalse(r2["success"])
        self.assertEqual(r2["error_code"], "STATE_MISMATCH")

    def test_history_preserved_across_full_rejection_cycle(self):
        """Full cycle with two reviewers; all entries logged."""
        self._create(post_id="p1", actor="author", timestamp=T1)
        self._walk("p1",
            ("draft",            "pending_approval", "author",    T2),
            ("pending_approval", "rejected",         "reviewer1", T3),
            ("rejected",         "draft",            "author",    T4),
            ("draft",            "pending_approval", "author",    T5),
        )
        hist = self._get_history("p1")["history"]
        actors = [e["actor"] for e in hist]
        self.assertIn("reviewer1", actors)
        self.assertEqual(len(hist), 5)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestInputValidation(_Base):

    def test_missing_action(self):
        r = self._call({"post_id": "p1"})
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")

    def test_invalid_action(self):
        r = self._call({"action": "destroy", "post_id": "p1"})
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "INVALID_ACTION")

    def test_missing_post_id(self):
        r = self._call({"action": "get_state"})
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")

    def test_timestamp_injection_used_in_create(self):
        ts = "2025-01-15T09:30:00+00:00"
        r = self._create(timestamp=ts)
        self.assertEqual(r["timestamp"], ts)
        self.assertEqual(self._get_state("post_001")["last_updated"], ts)

    def test_timestamp_injection_used_in_transition(self):
        self._create(post_id="p1")
        ts = "2025-06-01T15:00:00+00:00"
        r = self._transition("p1", "draft", "pending_approval", timestamp=ts)
        self.assertEqual(r["timestamp"], ts)

    def test_no_timestamp_defaults_to_now(self):
        # Without injection, timestamp should be a non-empty string
        r = self._call({"action": "create", "post_id": "p1", "actor": "author"})
        self.assertTrue(r["success"])
        self.assertIsInstance(r["timestamp"], str)
        self.assertTrue(len(r["timestamp"]) > 0)


if __name__ == "__main__":
    unittest.main()
