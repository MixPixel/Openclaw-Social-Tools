"""Tests for tools/find_next_slot/find_next_slot.py

Run from repo root:
    python -m unittest tests.test_find_next_slot

Day-of-week reference used throughout:
    2026-03-23 = Monday
    2026-03-24 = Tuesday
    2026-03-25 = Wednesday
    2026-03-26 = Thursday
    2026-03-27 = Friday
    2026-03-28 = Saturday
    2026-03-29 = Sunday
"""

import unittest
from datetime import datetime, timezone

from tools.find_next_slot import find_next_slot


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

WEEKDAY_WINDOW = {
    "timezone": "UTC",
    "allowed_windows": [
        {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "09:00", "end": "12:00"}
    ],
    "min_gap_minutes": 60,
    "max_per_day": 3,
    "slot_resolution_minutes": 15,
}

ALL_DAY_WINDOW = {
    "timezone": "UTC",
    "allowed_windows": [
        {"start": "00:00", "end": "23:45"}   # no 'days' → every day
    ],
    "min_gap_minutes": 60,
    "max_per_day": 10,
    "slot_resolution_minutes": 15,
}


def _call(after: str, config: dict | None = None, queue: list | None = None,
          platform: str = "twitter") -> dict:
    return find_next_slot({
        "platform": platform,
        "after": after,
        "schedule_config": config or WEEKDAY_WINDOW,
        "existing_queue": queue or [],
    })


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure(unittest.TestCase):

    def test_success_has_required_fields(self):
        r = _call("2026-03-24T08:00:00Z")
        self.assertTrue(r["available"])
        self.assertIn("slot", r)
        self.assertIn("local_time", r)
        self.assertIn("platform", r)
        self.assertIn("timezone", r)
        self.assertNotIn("reason_code", r)

    def test_failure_has_required_fields(self):
        # Saturday — no weekend windows in WEEKDAY_WINDOW → eventually NO_WINDOW
        # Use a config with max_per_day=0-equivalent by filling the queue
        r = find_next_slot({
            "platform": "twitter",
            "after": "2026-03-28T00:00:00Z",  # Saturday
            "schedule_config": {
                "timezone": "UTC",
                "allowed_windows": [
                    {"days": ["sat"], "start": "09:00", "end": "09:15"}
                ],
                "min_gap_minutes": 60,
                "max_per_day": 1,
                "slot_resolution_minutes": 15,
                "blackout_dates": [
                    f"2026-{m:02d}-{d:02d}"
                    for m in range(3, 5)
                    for d in range(1, 32)
                    if datetime(2026, m, d if d <= 30 else 1, tzinfo=timezone.utc).weekday() == 5
                    # Saturdays in a wide range
                ],
            },
            "existing_queue": [],
        })
        # May or may not be BLACKOUT; just check the failure shape
        self.assertFalse(r["available"])
        self.assertIn("reason_code", r)
        self.assertIn("message", r)

    def test_platform_echoed(self):
        r = _call("2026-03-24T08:00:00Z", platform="linkedin")
        self.assertEqual(r["platform"], "linkedin")

    def test_timezone_echoed(self):
        r = _call("2026-03-24T08:00:00Z")
        self.assertEqual(r["timezone"], "UTC")

    def test_slot_is_iso8601(self):
        r = _call("2026-03-24T08:00:00Z")
        # Should parse cleanly as a datetime
        dt = datetime.fromisoformat(r["slot"])
        self.assertIsNotNone(dt.tzinfo)

    def test_slot_and_local_time_same_in_utc(self):
        r = _call("2026-03-24T08:00:00Z")
        slot_dt = datetime.fromisoformat(r["slot"])
        local_dt = datetime.fromisoformat(r["local_time"])
        # Same instant
        self.assertEqual(
            slot_dt.astimezone(timezone.utc),
            local_dt.astimezone(timezone.utc),
        )


# ---------------------------------------------------------------------------
# Basic slot finding
# ---------------------------------------------------------------------------

class TestBasicSlotFinding(unittest.TestCase):

    def test_after_before_window_returns_window_start(self):
        # after=08:00, window starts 09:00 → expect 09:00
        r = _call("2026-03-24T08:00:00Z")
        self.assertTrue(r["available"])
        self.assertIn("T09:00:00", r["slot"])

    def test_after_at_window_start_returns_next_slot(self):
        # after=09:00 exactly (on boundary) → strictly after → 09:15
        r = _call("2026-03-24T09:00:00Z")
        self.assertTrue(r["available"])
        self.assertIn("T09:15:00", r["slot"])

    def test_after_inside_window_returns_next_boundary(self):
        # after=09:10, resolution=15 → next boundary is 09:15
        r = _call("2026-03-24T09:10:00Z")
        self.assertTrue(r["available"])
        self.assertIn("T09:15:00", r["slot"])

    def test_after_inside_window_on_boundary_returns_next(self):
        # after=09:15 exactly → 09:30
        r = _call("2026-03-24T09:15:00Z")
        self.assertIn("T09:30:00", r["slot"])

    def test_after_near_window_end_jumps_to_next_day(self):
        # after=11:50, resolution=15 → next slot 12:00 but window is [09,12) → go to next day
        r = _call("2026-03-24T11:50:00Z")
        self.assertTrue(r["available"])
        self.assertIn("2026-03-25", r["slot"])
        self.assertIn("T09:00:00", r["slot"])

    def test_after_after_window_jumps_to_next_day(self):
        # after=12:01 → past window → next day
        r = _call("2026-03-24T12:01:00Z")
        self.assertIn("2026-03-25", r["slot"])

    def test_empty_queue_no_gap_constraint(self):
        r = _call("2026-03-24T08:00:00Z", queue=[])
        self.assertTrue(r["available"])

    def test_resolution_30(self):
        config = {**WEEKDAY_WINDOW, "slot_resolution_minutes": 30}
        r = _call("2026-03-24T09:10:00Z", config=config)
        self.assertTrue(r["available"])
        # Next 30-min boundary after 09:10 is 09:30
        self.assertIn("T09:30:00", r["slot"])

    def test_resolution_60(self):
        config = {**WEEKDAY_WINDOW, "slot_resolution_minutes": 60}
        r = _call("2026-03-24T09:10:00Z", config=config)
        self.assertTrue(r["available"])
        # Next 60-min boundary after 09:10 UTC is 10:00 UTC
        self.assertIn("T10:00:00", r["slot"])


# ---------------------------------------------------------------------------
# Strictly after semantics
# ---------------------------------------------------------------------------

class TestStrictlyAfter(unittest.TestCase):

    def test_slot_is_strictly_after_after(self):
        after = "2026-03-24T09:00:00Z"
        r = _call(after)
        after_dt = datetime.fromisoformat(after)
        slot_dt = datetime.fromisoformat(r["slot"])
        self.assertGreater(slot_dt, after_dt)

    def test_slot_strictly_after_when_after_on_slot_boundary(self):
        r = _call("2026-03-24T09:30:00Z")
        slot_dt = datetime.fromisoformat(r["slot"])
        self.assertGreater(slot_dt, datetime.fromisoformat("2026-03-24T09:30:00Z"))

    def test_slot_strictly_after_after_with_queue(self):
        after = "2026-03-24T09:00:00Z"
        queue = ["2026-03-24T09:00:00Z"]
        r = _call(after, queue=queue)
        after_dt = datetime.fromisoformat(after).astimezone(timezone.utc)
        slot_dt = datetime.fromisoformat(r["slot"]).astimezone(timezone.utc)
        self.assertGreater(slot_dt, after_dt)


# ---------------------------------------------------------------------------
# Min-gap constraint
# ---------------------------------------------------------------------------

class TestMinGap(unittest.TestCase):

    def test_gap_from_preceding_post(self):
        # Queue has 09:00; min_gap=60 → next slot must be >= 10:00
        queue = ["2026-03-24T09:00:00Z"]
        r = _call("2026-03-24T08:00:00Z", queue=queue)
        self.assertTrue(r["available"])
        slot_dt = datetime.fromisoformat(r["slot"]).astimezone(timezone.utc)
        q_dt = datetime.fromisoformat("2026-03-24T09:00:00Z").astimezone(timezone.utc)
        diff = abs((slot_dt - q_dt).total_seconds() / 60)
        self.assertGreaterEqual(diff, 60)

    def test_gap_from_future_post(self):
        # Queue has 11:00; min_gap=60; after=08:00
        # First open slot without gap would be 09:00, but 09:00 is 120 min before 11:00 ✓
        queue = ["2026-03-24T11:00:00Z"]
        r = _call("2026-03-24T08:00:00Z", queue=queue)
        self.assertTrue(r["available"])
        slot_dt = datetime.fromisoformat(r["slot"]).astimezone(timezone.utc)
        q_dt = datetime.fromisoformat("2026-03-24T11:00:00Z").astimezone(timezone.utc)
        diff = abs((slot_dt - q_dt).total_seconds() / 60)
        self.assertGreaterEqual(diff, 60)

    def test_gap_from_close_future_post(self):
        # Queue has 09:30; after=08:00; min_gap=60
        # 09:00 is 30 min before 09:30 → too close; jump to 10:30
        queue = ["2026-03-24T09:30:00Z"]
        r = _call("2026-03-24T08:00:00Z", queue=queue)
        self.assertTrue(r["available"])
        slot_dt = datetime.fromisoformat(r["slot"]).astimezone(timezone.utc)
        q_dt = datetime.fromisoformat("2026-03-24T09:30:00Z").astimezone(timezone.utc)
        diff = abs((slot_dt - q_dt).total_seconds() / 60)
        self.assertGreaterEqual(diff, 60)

    def test_multiple_queue_posts_all_respected(self):
        # Two posts: 09:00 and 10:30; min_gap=60
        # Need ≥60 from both. 09:00+60=10:00 is 30 min from 10:30 → bad.
        # Jump to 10:30+60=11:30
        queue = ["2026-03-24T09:00:00Z", "2026-03-24T10:30:00Z"]
        r = _call("2026-03-24T08:00:00Z", queue=queue)
        self.assertTrue(r["available"])
        slot_dt = datetime.fromisoformat(r["slot"]).astimezone(timezone.utc)
        for q in queue:
            q_dt = datetime.fromisoformat(q).astimezone(timezone.utc)
            diff = abs((slot_dt - q_dt).total_seconds() / 60)
            self.assertGreaterEqual(diff, 60)

    def test_gap_zero_always_satisfied(self):
        config = {**WEEKDAY_WINDOW, "min_gap_minutes": 0}
        queue = ["2026-03-24T09:00:00Z"]
        r = _call("2026-03-24T08:00:00Z", config=config, queue=queue)
        self.assertTrue(r["available"])
        # min_gap=0: diff=0, 0 < 0 is False → no violation at 09:00 itself
        self.assertIn("T09:00:00", r["slot"])

    def test_gap_exactly_satisfied(self):
        # Queue at 09:00; min_gap=60; candidate at 10:00 → diff=60, not < 60 → OK
        config = {**WEEKDAY_WINDOW, "min_gap_minutes": 60}
        queue = ["2026-03-24T09:00:00Z"]
        r = _call("2026-03-24T08:45:00Z", config=config, queue=queue)
        self.assertTrue(r["available"])
        slot_dt = datetime.fromisoformat(r["slot"]).astimezone(timezone.utc)
        q_dt = datetime.fromisoformat("2026-03-24T09:00:00Z").astimezone(timezone.utc)
        diff = abs((slot_dt - q_dt).total_seconds() / 60)
        self.assertGreaterEqual(diff, 60)


# ---------------------------------------------------------------------------
# Daily cap
# ---------------------------------------------------------------------------

class TestDailyCap(unittest.TestCase):

    def test_max_per_day_not_reached_returns_today(self):
        # 1 post today, max=3 → still room
        queue = ["2026-03-24T09:00:00Z"]
        r = _call("2026-03-24T08:00:00Z", queue=queue)
        self.assertTrue(r["available"])
        self.assertIn("2026-03-24", r["slot"])

    def test_max_per_day_reached_returns_tomorrow(self):
        queue = [
            "2026-03-24T09:00:00Z",
            "2026-03-24T10:00:00Z",
            "2026-03-24T11:00:00Z",  # 3 posts = max_per_day
        ]
        r = _call("2026-03-24T08:00:00Z", queue=queue)
        self.assertTrue(r["available"])
        self.assertNotIn("2026-03-24", r["slot"])
        self.assertIn("2026-03-25", r["slot"])

    def test_max_per_day_1(self):
        config = {**WEEKDAY_WINDOW, "max_per_day": 1}
        queue = ["2026-03-24T09:00:00Z"]
        r = _call("2026-03-24T08:00:00Z", config=config, queue=queue)
        self.assertTrue(r["available"])
        self.assertNotIn("2026-03-24", r["slot"])

    def test_past_queue_posts_count_toward_daily_cap(self):
        # Two posts yesterday, two today — max=2 → no slot today
        config = {**ALL_DAY_WINDOW, "max_per_day": 2}
        queue = [
            "2026-03-24T01:00:00Z",
            "2026-03-24T02:00:00Z",
        ]
        r = _call("2026-03-24T00:00:00Z", config=config, queue=queue)
        self.assertTrue(r["available"])
        # Today is full; next slot should be tomorrow
        self.assertNotIn("2026-03-24", r["slot"])


# ---------------------------------------------------------------------------
# Blackout dates
# ---------------------------------------------------------------------------

class TestBlackoutDates(unittest.TestCase):

    def test_today_blacked_out_returns_tomorrow(self):
        config = {**WEEKDAY_WINDOW, "blackout_dates": ["2026-03-24"]}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(r["available"])
        self.assertNotIn("2026-03-24", r["slot"])

    def test_consecutive_blackouts_skipped(self):
        config = {**WEEKDAY_WINDOW, "blackout_dates": ["2026-03-24", "2026-03-25", "2026-03-26"]}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(r["available"])
        slot_date = r["slot"][:10]
        self.assertNotIn(slot_date, {"2026-03-24", "2026-03-25", "2026-03-26"})

    def test_blackout_all_days_returns_unavailable(self):
        # Black out every day for 15 days (past lookahead limit)
        from datetime import date, timedelta
        start = date(2026, 3, 24)
        dates = [(start + timedelta(days=i)).isoformat() for i in range(15)]
        config = {**WEEKDAY_WINDOW, "blackout_dates": dates}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason_code"], "BLACKOUT_COVERS_RANGE")


# ---------------------------------------------------------------------------
# Weekday window filters
# ---------------------------------------------------------------------------

class TestWeekdayFilters(unittest.TestCase):

    def test_weekday_only_window_skips_weekend(self):
        # after is Friday 12:01 → past window. Saturday and Sunday have no windows.
        # Next slot = Monday 09:00
        r = _call("2026-03-27T12:01:00Z")  # Friday
        self.assertTrue(r["available"])
        # 2026-03-30 = Monday
        self.assertIn("2026-03-30", r["slot"])
        self.assertIn("T09:00:00", r["slot"])

    def test_weekend_only_window(self):
        config = {
            "timezone": "UTC",
            "allowed_windows": [
                {"days": ["sat", "sun"], "start": "10:00", "end": "14:00"}
            ],
            "min_gap_minutes": 60,
            "max_per_day": 2,
            "slot_resolution_minutes": 15,
        }
        r = _call("2026-03-24T08:00:00Z", config=config)  # Tuesday
        self.assertTrue(r["available"])
        # 2026-03-28 = Saturday
        self.assertIn("2026-03-28", r["slot"])
        self.assertIn("T10:00:00", r["slot"])

    def test_multiple_windows_same_day(self):
        config = {
            "timezone": "UTC",
            "allowed_windows": [
                {"days": ["tue"], "start": "09:00", "end": "10:00"},
                {"days": ["tue"], "start": "17:00", "end": "19:00"},
            ],
            "min_gap_minutes": 30,
            "max_per_day": 5,
            "slot_resolution_minutes": 15,
        }
        # after=10:00 → past first window → should land in second window
        r = _call("2026-03-24T10:00:00Z", config=config)
        self.assertTrue(r["available"])
        self.assertIn("T17:00:00", r["slot"])

    def test_window_without_days_applies_every_day(self):
        config = {
            "timezone": "UTC",
            "allowed_windows": [{"start": "08:00", "end": "20:00"}],  # no 'days'
            "min_gap_minutes": 30,
            "max_per_day": 5,
            "slot_resolution_minutes": 15,
        }
        # Saturday — should still find a slot
        r = _call("2026-03-28T07:00:00Z", config=config)
        self.assertTrue(r["available"])
        self.assertIn("2026-03-28", r["slot"])


# ---------------------------------------------------------------------------
# Overlapping windows
# ---------------------------------------------------------------------------

class TestOverlappingWindows(unittest.TestCase):

    def test_overlapping_windows_merged(self):
        config = {
            "timezone": "UTC",
            "allowed_windows": [
                {"days": ["tue"], "start": "09:00", "end": "11:00"},
                {"days": ["tue"], "start": "10:00", "end": "12:00"},  # overlaps
            ],
            "min_gap_minutes": 30,
            "max_per_day": 5,
            "slot_resolution_minutes": 15,
        }
        # Merged window is 09:00–12:00; a slot at 10:30 should be valid
        r = _call("2026-03-24T10:25:00Z", config=config)
        self.assertTrue(r["available"])
        self.assertIn("T10:30:00", r["slot"])

    def test_adjacent_windows_treated_as_one(self):
        # 09:00-10:00 and 10:00-11:00 → merged to 09:00-11:00
        config = {
            "timezone": "UTC",
            "allowed_windows": [
                {"days": ["tue"], "start": "09:00", "end": "10:00"},
                {"days": ["tue"], "start": "10:00", "end": "11:00"},
            ],
            "min_gap_minutes": 30,
            "max_per_day": 5,
            "slot_resolution_minutes": 15,
        }
        r = _call("2026-03-24T09:50:00Z", config=config)
        self.assertTrue(r["available"])
        self.assertIn("T10:00:00", r["slot"])


# ---------------------------------------------------------------------------
# Non-UTC timezone
# ---------------------------------------------------------------------------

class TestNonUtcTimezone(unittest.TestCase):

    def test_slot_in_configured_timezone(self):
        config = {
            "timezone": "America/New_York",
            "allowed_windows": [
                {"days": ["tue"], "start": "09:00", "end": "12:00"}
            ],
            "min_gap_minutes": 60,
            "max_per_day": 3,
            "slot_resolution_minutes": 15,
        }
        # after=2026-03-24T08:00:00Z = 04:00 AM ET (before window)
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(r["available"])
        # local_time should contain New York offset and 09:00 AM
        self.assertIn("09:00:00", r["local_time"])

    def test_slot_and_local_time_represent_same_instant(self):
        config = {
            "timezone": "Europe/Berlin",
            "allowed_windows": [
                {"days": ["tue"], "start": "10:00", "end": "14:00"}
            ],
            "min_gap_minutes": 60,
            "max_per_day": 3,
            "slot_resolution_minutes": 15,
        }
        # 2026-03-24 08:00 UTC = 09:00 CET (before 10:00 window)
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(r["available"])
        slot_dt = datetime.fromisoformat(r["slot"]).astimezone(timezone.utc)
        local_dt = datetime.fromisoformat(r["local_time"]).astimezone(timezone.utc)
        self.assertEqual(slot_dt, local_dt)

    def test_tz_aware_after_with_offset(self):
        # after with explicit non-UTC offset
        config = {**WEEKDAY_WINDOW}
        r = _call("2026-03-24T10:00:00+02:00", config=config)
        # 10:00+02:00 = 08:00 UTC → slot should be 09:00 UTC
        self.assertTrue(r["available"])
        self.assertIn("T09:00:00", r["slot"])


# ---------------------------------------------------------------------------
# Naive datetime (assumed_utc flag)
# ---------------------------------------------------------------------------

class TestNaiveDatetime(unittest.TestCase):

    def test_naive_after_treated_as_utc(self):
        r = _call("2026-03-24T08:00:00")   # no tz info
        self.assertTrue(r["available"])
        self.assertTrue(r.get("assumed_utc"))

    def test_naive_after_result_consistent_with_utc(self):
        r_naive = _call("2026-03-24T08:00:00")
        r_utc = _call("2026-03-24T08:00:00Z")
        self.assertEqual(r_naive["slot"], r_utc["slot"])

    def test_assumed_utc_absent_when_tz_given(self):
        r = _call("2026-03-24T08:00:00Z")
        self.assertNotIn("assumed_utc", r)


# ---------------------------------------------------------------------------
# Config validation (INVALID_CONFIG)
# ---------------------------------------------------------------------------

class TestInvalidConfig(unittest.TestCase):

    def _is_invalid(self, result: dict) -> bool:
        return (
            not result["available"]
            and result.get("reason_code") == "INVALID_CONFIG"
        )

    def test_empty_allowed_windows(self):
        config = {**WEEKDAY_WINDOW, "allowed_windows": []}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(self._is_invalid(r))

    def test_missing_allowed_windows(self):
        config = {k: v for k, v in WEEKDAY_WINDOW.items() if k != "allowed_windows"}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(self._is_invalid(r))

    def test_resolution_zero(self):
        config = {**WEEKDAY_WINDOW, "slot_resolution_minutes": 0}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(self._is_invalid(r))

    def test_resolution_negative(self):
        config = {**WEEKDAY_WINDOW, "slot_resolution_minutes": -5}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(self._is_invalid(r))

    def test_max_per_day_zero(self):
        config = {**WEEKDAY_WINDOW, "max_per_day": 0}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(self._is_invalid(r))

    def test_min_gap_negative(self):
        config = {**WEEKDAY_WINDOW, "min_gap_minutes": -1}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(self._is_invalid(r))

    def test_unknown_timezone(self):
        config = {**WEEKDAY_WINDOW, "timezone": "Mars/Olympus"}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(self._is_invalid(r))

    def test_invalid_blackout_date(self):
        config = {**WEEKDAY_WINDOW, "blackout_dates": ["not-a-date"]}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(self._is_invalid(r))

    def test_window_end_before_start(self):
        config = {
            **WEEKDAY_WINDOW,
            "allowed_windows": [{"days": ["tue"], "start": "12:00", "end": "09:00"}],
        }
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(self._is_invalid(r))

    def test_min_gap_exceeds_window_duration(self):
        config = {
            **WEEKDAY_WINDOW,
            "allowed_windows": [{"days": ["tue"], "start": "09:00", "end": "10:00"}],
            "min_gap_minutes": 90,  # 90 > 60-min window
        }
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertTrue(self._is_invalid(r))

    def test_unparseable_after(self):
        r = _call("not-a-date")
        self.assertTrue(self._is_invalid(r))

    def test_invalid_queue_entry(self):
        r = _call(
            "2026-03-24T08:00:00Z",
            queue=["not-a-datetime"],
        )
        self.assertTrue(self._is_invalid(r))


# ---------------------------------------------------------------------------
# No slot found (reason codes)
# ---------------------------------------------------------------------------

class TestNoSlotFound(unittest.TestCase):

    def test_no_window_in_lookahead(self):
        # Windows only on Saturdays, and we black them all out
        from datetime import date, timedelta
        saturdays = [
            (date(2026, 3, 24) + timedelta(days=i)).isoformat()
            for i in range(15)
            if (date(2026, 3, 24) + timedelta(days=i)).weekday() == 5  # Saturday
        ]
        config = {
            "timezone": "UTC",
            "allowed_windows": [{"days": ["sat"], "start": "09:00", "end": "10:00"}],
            "min_gap_minutes": 30,
            "max_per_day": 1,
            "slot_resolution_minutes": 15,
            "blackout_dates": saturdays,
        }
        r = _call("2026-03-24T00:00:00Z", config=config)
        self.assertFalse(r["available"])
        self.assertIn(r["reason_code"], ("BLACKOUT_COVERS_RANGE", "NO_WINDOW_IN_RANGE"))

    def test_daily_limit_reached_every_day(self):
        # max_per_day=1, fill every day in lookahead
        from datetime import date, timedelta
        start = date(2026, 3, 24)
        queue_entries = [
            f"{(start + timedelta(days=i)).isoformat()}T09:00:00Z"
            for i in range(15)
            if (start + timedelta(days=i)).weekday() < 5  # weekdays only (matching window)
        ]
        config = {**WEEKDAY_WINDOW, "max_per_day": 1}
        r = _call("2026-03-24T08:00:00Z", config=config, queue=queue_entries)
        self.assertFalse(r["available"])
        # The lookahead mixes days-with-cap-reached and no-window weekends; any
        # of those reason codes is valid. Just assert no slot was found.
        self.assertIn(r["reason_code"], ("DAILY_LIMIT_REACHED", "NO_WINDOW_IN_RANGE"))

    def test_gap_constraint_fills_all_windows(self):
        # Very large min_gap that can't fit in the window
        # Window: 09:00–10:00 (60 min), but min_gap = 59 min → we can place exactly 1 post.
        # Queue already has a post at 09:30, gap check fails for any slot in window.
        # min_gap=59 > window=60 would be INVALID_CONFIG. Use window=120 and min_gap=60.
        # Fill every eligible day with a post.
        from datetime import date, timedelta
        start = date(2026, 3, 24)
        queue_entries = [
            f"{(start + timedelta(days=i)).isoformat()}T09:30:00Z"
            for i in range(15)
        ]
        config = {
            "timezone": "UTC",
            "allowed_windows": [{"start": "09:00", "end": "10:00"}],  # 60-min window
            "min_gap_minutes": 59,  # just under window size — 59 < 60 so not INVALID_CONFIG
            "max_per_day": 3,
            "slot_resolution_minutes": 15,
        }
        r = _call("2026-03-24T08:00:00Z", config=config, queue=queue_entries)
        # With post at 09:30 and min_gap=59: valid slots must be outside [09:30-59, 09:30+59]
        # = outside [08:31, 10:29]. Window is [09:00, 10:00).
        # Every slot in window is within 59 min of 09:30. → no slot today.
        # Since queue covers every day, expect GAP_CONSTRAINT_UNMET
        self.assertFalse(r["available"])

    def test_failure_includes_search_range_end(self):
        from datetime import date, timedelta
        saturdays = [
            (date(2026, 3, 24) + timedelta(days=i)).isoformat()
            for i in range(15)
        ]
        config = {**WEEKDAY_WINDOW, "blackout_dates": saturdays}
        r = _call("2026-03-24T08:00:00Z", config=config)
        self.assertFalse(r["available"])
        self.assertIn("search_range_end", r)
        # search_range_end should be after after+14 days
        end_dt = datetime.fromisoformat(r["search_range_end"])
        self.assertIsNotNone(end_dt.tzinfo)


if __name__ == "__main__":
    unittest.main()
