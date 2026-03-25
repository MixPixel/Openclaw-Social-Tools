"""Tests for tools/schedule_post/schedule_post.py

Run from repo root:
    python -m unittest tests.test_schedule_post
"""

import json
import os
import tempfile
import unittest

from tools.approval_state_manager import manage_approval_state
from tools.find_next_slot import find_next_slot
from tools.schedule_post import schedule_post

# ---------------------------------------------------------------------------
# Fixed timestamps — keeps all tests deterministic
# ---------------------------------------------------------------------------

NOW       = "2026-03-24T12:00:00+00:00"   # "current time" injected into calls
SLOT      = "2026-03-25T09:15:00+00:00"   # a valid future slot (Tuesday, 09:15 UTC)
SLOT2     = "2026-03-25T11:00:00+00:00"   # another valid future slot, 1h45m after SLOT
CREATED   = "2026-03-24T12:00:00+00:00"   # injected created_at

# ---------------------------------------------------------------------------
# Minimal valid schedule_config (UTC timezone, Mon–Fri 08:00–18:00)
# ---------------------------------------------------------------------------

SCHED = {
    "timezone": "UTC",
    "allowed_windows": [
        {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "08:00", "end": "18:00"},
    ],
    "min_gap_minutes": 60,
    "slot_resolution_minutes": 15,
}


# ---------------------------------------------------------------------------
# Base fixture
# ---------------------------------------------------------------------------

class _Base(unittest.TestCase):
    """Provides fresh temp stores and an approved post for each test."""

    POST_ID = "post_001"

    def setUp(self):
        # Approval store
        fd, self.approval_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.approval_path)

        # Queue store
        fd, self.queue_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.queue_path)

        # Create post and walk it to 'approved'
        self._asm({"action": "create",      "post_id": self.POST_ID, "actor": "author", "timestamp": "2026-03-24T09:00:00+00:00"})
        self._asm({"action": "transition",  "post_id": self.POST_ID, "actor": "author", "current_state": "draft",            "target_state": "pending_approval", "timestamp": "2026-03-24T09:01:00+00:00"})
        self._asm({"action": "transition",  "post_id": self.POST_ID, "actor": "approver", "current_state": "pending_approval", "target_state": "approved",         "timestamp": "2026-03-24T09:02:00+00:00"})

    def tearDown(self):
        for path in (self.approval_path, self.queue_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _asm(self, extra: dict) -> dict:
        return manage_approval_state({**extra, "store_path": self.approval_path})

    def _schedule(self, **kw) -> dict:
        """Call schedule_post with defaults filled in."""
        base = {
            "post_id":             self.POST_ID,
            "platform":            "twitter",
            "content":             "Hello world! Sign up now.",
            "actor":               "scheduler",
            "schedule_config":     SCHED,
            "slot":                SLOT,
            "now":                 NOW,
            "timestamp":           CREATED,
            "queue_id":            "q_test0001",
            "approval_store_path": self.approval_path,
            "queue_store_path":    self.queue_path,
        }
        base.update(kw)
        return schedule_post(base)

    def _read_queue(self) -> dict:
        try:
            with open(self.queue_path) as fh:
                return json.load(fh)
        except FileNotFoundError:
            return {}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestSuccessProvided(unittest.TestCase):
    """schedule_post succeeds with a caller-supplied slot."""

    POST_ID = "post_002"

    def setUp(self):
        fd, self.approval_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.approval_path)
        fd, self.queue_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.queue_path)
        for step in [
            {"action": "create",     "post_id": self.POST_ID, "actor": "a", "timestamp": "2026-03-24T09:00:00+00:00"},
            {"action": "transition", "post_id": self.POST_ID, "actor": "a", "current_state": "draft",            "target_state": "pending_approval", "timestamp": "2026-03-24T09:01:00+00:00"},
            {"action": "transition", "post_id": self.POST_ID, "actor": "a", "current_state": "pending_approval", "target_state": "approved",         "timestamp": "2026-03-24T09:02:00+00:00"},
        ]:
            manage_approval_state({**step, "store_path": self.approval_path})

    def tearDown(self):
        for p in (self.approval_path, self.queue_path):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass

    def _go(self, **kw) -> dict:
        base = {
            "post_id": self.POST_ID, "platform": "twitter",
            "content": "Hello world! Sign up now.",
            "actor": "sched", "schedule_config": SCHED,
            "slot": SLOT, "now": NOW, "timestamp": CREATED,
            "queue_id": "q_test0002",
            "approval_store_path": self.approval_path,
            "queue_store_path": self.queue_path,
        }
        base.update(kw)
        return schedule_post(base)

    def test_returns_success(self):
        r = self._go()
        self.assertTrue(r["success"], r)

    def test_response_fields(self):
        r = self._go()
        self.assertEqual(r["queue_id"],    "q_test0002")
        self.assertEqual(r["post_id"],     self.POST_ID)
        self.assertEqual(r["platform"],    "twitter")
        self.assertEqual(r["slot_source"], "provided")
        self.assertEqual(r["actor"],       "sched")
        self.assertEqual(r["created_at"],  CREATED)
        self.assertEqual(r["warnings"],    [])

    def test_queue_record_written(self):
        self._go()
        with open(self.queue_path) as fh:
            q = json.load(fh)
        self.assertIn("q_test0002", q)
        rec = q["q_test0002"]
        self.assertEqual(rec["post_id"],  self.POST_ID)
        self.assertEqual(rec["platform"], "twitter")
        self.assertEqual(rec["actor"],    "sched")

    def test_state_transitions_to_scheduled(self):
        self._go()
        state = manage_approval_state({
            "action": "get_state", "post_id": self.POST_ID,
            "store_path": self.approval_path,
        })
        self.assertEqual(state["current_state"], "scheduled")

    def test_platform_alias_normalised(self):
        r = self._go(platform="x")
        self.assertTrue(r["success"], r)
        self.assertEqual(r["platform"], "twitter")

    def test_no_alt_text_warning(self):
        r = self._go(media=[{"type": "image", "url_or_path": "/img/a.jpg"}])
        self.assertTrue(r["success"], r)
        self.assertIn("NO_ALT_TEXT", r["warnings"])

    def test_alt_text_present_no_warning(self):
        r = self._go(media=[{"type": "image", "url_or_path": "/img/a.jpg", "alt_text": "banner"}])
        self.assertTrue(r["success"], r)
        self.assertNotIn("NO_ALT_TEXT", r["warnings"])


# ---------------------------------------------------------------------------
# Happy path — auto slot (no slot provided)
# ---------------------------------------------------------------------------

class TestSuccessAutoSlot(_Base):

    def test_auto_slot_success(self):
        r = self._schedule(slot=None)
        self.assertTrue(r["success"], r)
        self.assertEqual(r["slot_source"], "auto")
        self.assertIn("slot", r)

    def test_auto_slot_state_scheduled(self):
        self._schedule(slot=None)
        state = self._asm({"action": "get_state", "post_id": self.POST_ID})
        self.assertEqual(state["current_state"], "scheduled")

    def test_auto_slot_queue_written(self):
        self._schedule(slot=None)
        q = self._read_queue()
        self.assertEqual(len(q), 1)


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------

class TestMissingFields(_Base):

    def test_missing_post_id(self):
        r = self._schedule(post_id="")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")

    def test_missing_content(self):
        r = self._schedule(content="")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")

    def test_missing_platform(self):
        r = self._schedule(platform="")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")

    def test_missing_actor(self):
        r = self._schedule(actor="")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")

    def test_missing_schedule_config(self):
        r = self._schedule(schedule_config=None)
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "MISSING_REQUIRED_FIELD")


# ---------------------------------------------------------------------------
# Platform errors
# ---------------------------------------------------------------------------

class TestPlatformErrors(_Base):

    def test_unknown_platform(self):
        r = self._schedule(platform="myspace")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "PLATFORM_NOT_SUPPORTED")


# ---------------------------------------------------------------------------
# Post state errors
# ---------------------------------------------------------------------------

class TestPostStateErrors(_Base):

    def test_post_not_found(self):
        r = self._schedule(post_id="does_not_exist")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "POST_NOT_FOUND")

    def test_post_not_approved_draft(self):
        # Create a second post, leave it in draft
        self._asm({"action": "create", "post_id": "post_draft", "actor": "a",
                   "timestamp": "2026-03-24T09:00:00+00:00"})
        r = self._schedule(post_id="post_draft")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "POST_NOT_APPROVED")
        self.assertEqual(r["actual_state"], "draft")

    def test_double_schedule_returns_not_approved(self):
        # Schedule once successfully
        self._schedule()
        # Create a new approved post with same ID is not possible; the state
        # is now 'scheduled', so a second call must fail with POST_NOT_APPROVED.
        r = self._schedule(queue_id="q_second")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "POST_NOT_APPROVED")
        self.assertEqual(r["actual_state"], "scheduled")


# ---------------------------------------------------------------------------
# Slot validation errors (slot provided)
# ---------------------------------------------------------------------------

class TestSlotErrors(_Base):

    def test_slot_in_past(self):
        r = self._schedule(slot="2026-03-23T09:00:00+00:00")  # before NOW
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "SLOT_IN_PAST")

    def test_slot_outside_window(self):
        # 02:00 UTC on a Tuesday is outside Mon–Fri 08:00–18:00
        r = self._schedule(slot="2026-03-25T02:00:00+00:00")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "SLOT_OUTSIDE_WINDOW")

    def test_slot_on_weekend(self):
        # 2026-03-28 is a Saturday
        r = self._schedule(slot="2026-03-28T09:00:00+00:00")
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "SLOT_OUTSIDE_WINDOW")

    def test_slot_on_blackout_date(self):
        config = {**SCHED, "blackout_dates": ["2026-03-25"]}
        r = self._schedule(schedule_config=config)
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "SLOT_ON_BLACKOUT_DATE")

    def test_slot_conflict(self):
        # Write a queue entry at the same slot manually
        with open(self.queue_path, "w") as fh:
            json.dump({
                "q_existing": {
                    "queue_id": "q_existing",
                    "post_id": "post_other",
                    "platform": "twitter",
                    "content": "other",
                    "slot": SLOT,  # exact same slot
                    "media": [],
                    "actor": "other",
                    "created_at": CREATED,
                }
            }, fh)
        r = self._schedule()
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "SLOT_CONFLICT")
        self.assertEqual(r["conflicting_queue_id"], "q_existing")

    def test_slot_conflict_within_min_gap(self):
        # Entry at SLOT - 30 min; min_gap is 60 min → should conflict
        near_slot = "2026-03-25T08:45:00+00:00"
        with open(self.queue_path, "w") as fh:
            json.dump({
                "q_near": {
                    "queue_id": "q_near",
                    "post_id": "post_other",
                    "platform": "twitter",
                    "content": "other",
                    "slot": near_slot,
                    "media": [],
                    "actor": "other",
                    "created_at": CREATED,
                }
            }, fh)
        r = self._schedule()
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "SLOT_CONFLICT")

    def test_slot_exactly_min_gap_away_is_allowed(self):
        # Entry at SLOT - 60 min exactly; gap == min_gap → NOT a conflict (strictly <)
        exactly_min_gap_away = "2026-03-25T08:15:00+00:00"
        with open(self.queue_path, "w") as fh:
            json.dump({
                "q_edge": {
                    "queue_id": "q_edge",
                    "post_id": "post_other",
                    "platform": "twitter",
                    "content": "other",
                    "slot": exactly_min_gap_away,
                    "media": [],
                    "actor": "other",
                    "created_at": CREATED,
                }
            }, fh)
        r = self._schedule()
        self.assertTrue(r["success"], r)


# ---------------------------------------------------------------------------
# NO_SLOT_AVAILABLE (auto slot, no windows configured)
# ---------------------------------------------------------------------------

class TestNoSlotAvailable(_Base):

    def test_no_windows_returns_no_slot_available(self):
        config = {**SCHED, "allowed_windows": []}
        r = self._schedule(slot=None, schedule_config=config)
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "NO_SLOT_AVAILABLE")
        self.assertIn("find_next_slot_reason", r)


# ---------------------------------------------------------------------------
# Validation failure
# ---------------------------------------------------------------------------

class TestValidationFailed(_Base):

    def test_content_too_long_fails(self):
        # Twitter limit is 280 chars
        long_content = "x" * 281
        r = self._schedule(content=long_content)
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "VALIDATION_FAILED")
        self.assertIn("validation_errors", r)
        self.assertIsInstance(r["validation_errors"], list)
        self.assertTrue(len(r["validation_errors"]) > 0)


# ---------------------------------------------------------------------------
# Media errors
# ---------------------------------------------------------------------------

class TestMediaErrors(_Base):

    def test_media_missing_url(self):
        r = self._schedule(media=[{"type": "image", "url_or_path": ""}])
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "MEDIA_UNAVAILABLE")

    def test_media_absent_url_key(self):
        r = self._schedule(media=[{"type": "image"}])
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "MEDIA_UNAVAILABLE")


# ---------------------------------------------------------------------------
# Queue ID generation
# ---------------------------------------------------------------------------

class TestQueueIdGeneration(_Base):

    def test_deterministic_queue_id_without_injection(self):
        import hashlib
        expected_qid = "q_" + hashlib.sha256(
            f"{self.POST_ID}:{SLOT}".encode()
        ).hexdigest()[:8]
        # Don't inject queue_id
        r = self._schedule(queue_id=None)
        self.assertTrue(r["success"], r)
        self.assertEqual(r["queue_id"], expected_qid)

    def test_injected_queue_id_used(self):
        r = self._schedule(queue_id="q_custom_abc")
        self.assertTrue(r["success"], r)
        self.assertEqual(r["queue_id"], "q_custom_abc")


# ---------------------------------------------------------------------------
# No side effects on failure
# ---------------------------------------------------------------------------

class TestNoSideEffectsOnFailure(_Base):

    def test_queue_not_written_on_slot_in_past(self):
        self._schedule(slot="2026-03-23T09:00:00+00:00")
        self.assertEqual(self._read_queue(), {})

    def test_state_unchanged_on_slot_in_past(self):
        self._schedule(slot="2026-03-23T09:00:00+00:00")
        state = self._asm({"action": "get_state", "post_id": self.POST_ID})
        self.assertEqual(state["current_state"], "approved")

    def test_queue_not_written_on_validation_failure(self):
        self._schedule(content="x" * 300)
        self.assertEqual(self._read_queue(), {})

    def test_state_unchanged_on_validation_failure(self):
        self._schedule(content="x" * 300)
        state = self._asm({"action": "get_state", "post_id": self.POST_ID})
        self.assertEqual(state["current_state"], "approved")


# ---------------------------------------------------------------------------
# Alignment guard tests
# ---------------------------------------------------------------------------

class TestAlignmentWithFindNextSlot(_Base):
    """Guard tests: schedule_post and find_next_slot must agree on shared rules.

    These tests call both tools independently with identical inputs and assert
    they reach the same conclusion. They exist to catch drift if either tool's
    inlined logic is updated without updating the other.

    Architecture is unchanged: schedule_post still inlines its slot validation.
    """

    def test_exact_min_gap_allowed_by_both(self):
        """A slot exactly min_gap_minutes from an existing entry is allowed by both tools."""
        existing = "2026-03-25T08:00:00+00:00"
        candidate = "2026-03-25T09:00:00+00:00"  # exactly 60 min later; min_gap = 60

        # find_next_slot: searching from just before 09:00 should land on 09:00
        fns = find_next_slot({
            "platform": "twitter",
            "after": "2026-03-25T08:55:00+00:00",
            "schedule_config": SCHED,
            "existing_queue": [existing],
        })
        self.assertTrue(fns["available"], fns)
        self.assertEqual(fns["slot"], candidate)

        # schedule_post: same slot with the same existing entry in the queue → should succeed
        with open(self.queue_path, "w") as fh:
            json.dump({"q_pre": {
                "queue_id": "q_pre", "post_id": "post_other", "platform": "twitter",
                "content": "other", "slot": existing, "media": [], "actor": "other",
                "created_at": CREATED,
            }}, fh)
        r = self._schedule(slot=candidate, queue_id="q_align_exact")
        self.assertTrue(r["success"], r)

    def test_sub_gap_blocked_by_schedule_skipped_by_fns(self):
        """A slot within min_gap is rejected by schedule_post and skipped by find_next_slot."""
        existing  = "2026-03-25T08:00:00+00:00"
        too_close = "2026-03-25T08:30:00+00:00"  # 30 min later, below min_gap of 60

        # find_next_slot skips 08:30 (conflict) and returns 09:00
        fns = find_next_slot({
            "platform": "twitter",
            "after": "2026-03-25T08:25:00+00:00",
            "schedule_config": SCHED,
            "existing_queue": [existing],
        })
        self.assertTrue(fns["available"], fns)
        self.assertNotEqual(fns["slot"], too_close)

        # schedule_post rejects the same too-close slot
        with open(self.queue_path, "w") as fh:
            json.dump({"q_pre": {
                "queue_id": "q_pre", "post_id": "post_other", "platform": "twitter",
                "content": "other", "slot": existing, "media": [], "actor": "other",
                "created_at": CREATED,
            }}, fh)
        r = self._schedule(slot=too_close)
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "SLOT_CONFLICT")

    def test_blackout_date_blocked_by_both(self):
        """Both tools respect blackout_dates: find_next_slot skips the day, schedule_post rejects."""
        blackout_config = {**SCHED, "blackout_dates": ["2026-03-25"]}

        # find_next_slot: should skip 2026-03-25 and return a slot on 2026-03-26
        fns = find_next_slot({
            "platform": "twitter",
            "after": NOW,
            "schedule_config": blackout_config,
        })
        self.assertTrue(fns["available"], fns)
        from datetime import timezone as _tz
        returned_date = (
            __import__("datetime").datetime.fromisoformat(fns["slot"])
            .astimezone(_tz.utc).date().isoformat()
        )
        self.assertNotEqual(returned_date, "2026-03-25")

        # schedule_post: a slot falling on the blackout date should be rejected
        r = self._schedule(schedule_config=blackout_config)
        self.assertFalse(r["success"])
        self.assertEqual(r["error_code"], "SLOT_ON_BLACKOUT_DATE")

    def test_timezone_window_slot_accepted_by_both(self):
        """Both tools use the config timezone for window checks, not UTC.

        Config: America/New_York, window 09:00-17:00.
        2026-03-24 is a Tuesday. Spring-forward was Mar 8, so EDT = UTC-4.
        NOW is 2026-03-24T12:00Z = 08:00 EDT — before the 09:00 window opens.
        First valid slot is 09:00 EDT on the same day = 13:00 UTC on 2026-03-24.
        """
        ny_config = {
            "timezone": "America/New_York",
            "allowed_windows": [
                {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "09:00", "end": "17:00"},
            ],
            "min_gap_minutes": 60,
            "slot_resolution_minutes": 15,
        }
        expected_slot = "2026-03-24T13:00:00+00:00"  # 09:00 EDT same day as NOW

        # find_next_slot returns 13:00 UTC as the first available slot
        fns = find_next_slot({
            "platform": "twitter",
            "after": NOW,
            "schedule_config": ny_config,
        })
        self.assertTrue(fns["available"], fns)
        self.assertEqual(fns["slot"], expected_slot)

        # schedule_post accepts that same slot (both tools agree on the window boundary)
        r = self._schedule(slot=expected_slot, schedule_config=ny_config, queue_id="q_tz_01")
        self.assertTrue(r["success"], r)


if __name__ == "__main__":
    unittest.main()
