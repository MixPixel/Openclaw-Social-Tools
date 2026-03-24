"""find_next_slot — find the next available posting slot given a schedule config.

Usage (CLI):
    echo '{...}' | python -m tools.find_next_slot.find_next_slot
    # exits 0 when a slot is found, 1 when none found or error

Usage (library):
    from tools.find_next_slot import find_next_slot
    result = find_next_slot({...})
"""

import json
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOOKAHEAD_DAYS = 14

# Short day name → Python weekday() (0 = Monday, 6 = Sunday)
_DAY_MAP: dict[str, int] = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ceil_slot(dt: datetime, resolution_minutes: int) -> datetime:
    """Return the nearest UTC slot at or after dt.

    Slots are aligned to resolution_minutes intervals from the Unix epoch.
    """
    res_sec = resolution_minutes * 60
    ts = dt.timestamp()
    return datetime.fromtimestamp(
        math.ceil(ts / res_sec) * res_sec, tz=timezone.utc
    )


def _next_slot(dt: datetime, resolution_minutes: int) -> datetime:
    """Return the first UTC slot strictly after dt."""
    res_sec = resolution_minutes * 60
    ts = dt.timestamp()
    return datetime.fromtimestamp(
        (math.floor(ts / res_sec) + 1) * res_sec, tz=timezone.utc
    )


def _make_local_dt(d: date, t: time, tz: ZoneInfo) -> datetime:
    """Construct a timezone-aware datetime from a local date + time."""
    return datetime(d.year, d.month, d.day, t.hour, t.minute, 0, tzinfo=tz)


def _midnight(d: date, tz: ZoneInfo) -> datetime:
    """Return midnight at the start of date d in tz."""
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)


def _parse_time_str(s: str) -> time:
    """Parse 'HH:MM' into a time object."""
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]))


def _merge_windows(
    windows_raw: list[dict],
) -> dict[int, list[tuple[time, time]]]:
    """Build {weekday_int: [(start, end), ...]} with overlapping intervals merged.

    Weekdays use Python's weekday() convention: 0=Mon, 6=Sun.
    Omitting 'days' in a window entry means every day of the week.
    """
    per_day: dict[int, list[tuple[time, time]]] = {i: [] for i in range(7)}

    for w in windows_raw:
        days_raw = w.get("days")
        if days_raw is None:
            day_ints = list(range(7))
        else:
            day_ints = [_DAY_MAP[d.lower()] for d in days_raw]

        start = _parse_time_str(w["start"])
        end = _parse_time_str(w["end"])
        if end <= start:
            raise ValueError(
                f"Window end '{w['end']}' must be after start '{w['start']}'."
            )
        for d in day_ints:
            per_day[d].append((start, end))

    # Sort and merge overlapping intervals per day
    for d in range(7):
        intervals = sorted(per_day[d])
        merged: list[tuple[time, time]] = []
        for s, e in intervals:
            if merged and s <= merged[-1][1]:
                prev_s, prev_e = merged[-1]
                merged[-1] = (prev_s, max(prev_e, e))
            else:
                merged.append((s, e))
        per_day[d] = merged

    return per_day


def _invalid_config(platform: str, message: str) -> dict:
    return {
        "available": False,
        "platform": platform,
        "reason_code": "INVALID_CONFIG",
        "message": message,
    }


def _no_slot(
    platform: str,
    reason_code: str,
    lookahead_days: int,
    search_range_end_utc: datetime,
    assumed_utc: bool,
) -> dict:
    messages = {
        "NO_WINDOW_IN_RANGE": (
            f"No allowed posting window found within {lookahead_days} days."
        ),
        "BLACKOUT_COVERS_RANGE": (
            f"All days within {lookahead_days} days are blocked by blackout dates."
        ),
        "DAILY_LIMIT_REACHED": (
            f"max_per_day already reached for every eligible day within {lookahead_days} days."
        ),
        "GAP_CONSTRAINT_UNMET": (
            f"Existing queue entries leave no gap of min_gap_minutes "
            f"within {lookahead_days} days."
        ),
    }
    result: dict = {
        "available": False,
        "platform": platform,
        "reason_code": reason_code,
        "message": messages.get(reason_code, f"No slot found within {lookahead_days} days."),
        "search_range_end": search_range_end_utc.isoformat(),
    }
    if assumed_utc:
        result["assumed_utc"] = True
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_next_slot(data: dict) -> dict:
    """Find the next available posting slot.

    Args:
        data: dict with keys:
            platform       (str, required)   — echoed to output
            after          (str, required)   — ISO 8601; find slot strictly after this
            schedule_config (dict, required) — see spec for schema
            existing_queue (list[str], opt)  — already-claimed ISO 8601 datetimes

    Returns:
        On success: {available, slot, local_time, platform, timezone[, assumed_utc]}
        On failure: {available, platform, reason_code, message, search_range_end[, assumed_utc]}
        On bad config: {available, platform, reason_code, message}
    """
    platform: str = data.get("platform") or ""
    after_raw: str = data.get("after") or ""
    config: dict = data.get("schedule_config") or {}
    existing_queue_raw: list = data.get("existing_queue") or []

    # --- Validate and extract config ---
    tz_name: str = config.get("timezone", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return _invalid_config(platform, f"Unknown timezone '{tz_name}'.")

    min_gap: int = config.get("min_gap_minutes", 60)
    max_per_day_val: int = config.get("max_per_day", 8)
    blackout_raw: list = config.get("blackout_dates") or []
    resolution: int = config.get("slot_resolution_minutes", 15)
    windows_raw: list = config.get("allowed_windows") or []

    if not windows_raw:
        return _invalid_config(
            platform, "'allowed_windows' is required and must not be empty."
        )
    if not isinstance(resolution, int) or resolution <= 0:
        return _invalid_config(
            platform, "'slot_resolution_minutes' must be a positive integer."
        )
    if not isinstance(max_per_day_val, int) or max_per_day_val <= 0:
        return _invalid_config(platform, "'max_per_day' must be a positive integer.")
    if not isinstance(min_gap, int) or min_gap < 0:
        return _invalid_config(
            platform, "'min_gap_minutes' must be a non-negative integer."
        )
    if not after_raw:
        return _invalid_config(platform, "'after' is required.")

    # Parse blackout dates
    try:
        blackout_dates: set[date] = {date.fromisoformat(d) for d in blackout_raw}
    except ValueError as exc:
        return _invalid_config(platform, f"Invalid blackout_dates entry: {exc}")

    # Build per-weekday merged window map
    try:
        windows_by_day = _merge_windows(windows_raw)
    except (KeyError, ValueError) as exc:
        return _invalid_config(platform, f"Invalid window configuration: {exc}")

    # Validate min_gap does not exceed any individual window's duration
    for day_idx, intervals in windows_by_day.items():
        for ws, we in intervals:
            dur_min = (we.hour * 60 + we.minute) - (ws.hour * 60 + ws.minute)
            if 0 < dur_min < min_gap:
                day_name = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][day_idx]
                return _invalid_config(
                    platform,
                    f"'min_gap_minutes' ({min_gap}) exceeds the window duration "
                    f"({dur_min} min) on {day_name} "
                    f"{ws.strftime('%H:%M')}–{we.strftime('%H:%M')}.",
                )

    # Parse 'after'
    assumed_utc = False
    try:
        after_dt = datetime.fromisoformat(after_raw)
    except ValueError as exc:
        return _invalid_config(platform, f"Could not parse 'after': {exc}")

    if after_dt.tzinfo is None:
        # Treat as UTC; flag it, but do not fail
        after_dt = after_dt.replace(tzinfo=timezone.utc)
        assumed_utc = True

    # Parse existing_queue
    try:
        queue_utc: list[datetime] = []
        for s in existing_queue_raw:
            qt = datetime.fromisoformat(s)
            if qt.tzinfo is None:
                qt = qt.replace(tzinfo=timezone.utc)
            queue_utc.append(qt.astimezone(timezone.utc))
    except (ValueError, TypeError) as exc:
        return _invalid_config(platform, f"Invalid existing_queue entry: {exc}")

    # --- Search ---
    after_utc = after_dt.astimezone(timezone.utc)
    lookahead_end_utc = after_utc + timedelta(days=_LOOKAHEAD_DAYS)

    candidate_utc = _next_slot(after_utc, resolution)

    last_reason_code = "NO_WINDOW_IN_RANGE"

    # Safety cap: at most one iteration per resolution unit in the lookahead window
    max_iterations = (_LOOKAHEAD_DAYS * 24 * 60 // resolution) + resolution + 10

    for _ in range(max_iterations):
        if candidate_utc > lookahead_end_utc:
            break

        candidate_local = candidate_utc.astimezone(tz)
        local_date = candidate_local.date()
        local_time_val = candidate_local.time()  # naive time in local timezone

        # 1. Blackout check
        if local_date in blackout_dates:
            last_reason_code = "BLACKOUT_COVERS_RANGE"
            next_day = local_date + timedelta(days=1)
            candidate_utc = _ceil_slot(_midnight(next_day, tz), resolution)
            continue

        # 2. Window check: find which window (if any) contains the candidate time
        weekday = candidate_local.weekday()
        day_windows = windows_by_day[weekday]

        window_found: tuple[time, time] | None = None
        next_window_open: time | None = None

        for ws, we in day_windows:
            if ws <= local_time_val < we:
                window_found = (ws, we)
                break
            if local_time_val < ws:
                # Candidate is before this window; remember it as the next open time
                next_window_open = ws
                break

        if window_found is None:
            last_reason_code = "NO_WINDOW_IN_RANGE"
            if next_window_open is not None:
                target = _make_local_dt(local_date, next_window_open, tz)
                candidate_utc = _ceil_slot(target, resolution)
            else:
                # Past all windows today — jump to next day
                next_day = local_date + timedelta(days=1)
                candidate_utc = _ceil_slot(_midnight(next_day, tz), resolution)
            continue

        # 3. Daily cap check
        posts_on_day = sum(
            1 for qt in queue_utc
            if qt.astimezone(tz).date() == local_date
        )
        if posts_on_day >= max_per_day_val:
            last_reason_code = "DAILY_LIMIT_REACHED"
            next_day = local_date + timedelta(days=1)
            candidate_utc = _ceil_slot(_midnight(next_day, tz), resolution)
            continue

        # 4. Min-gap check: find the farthest jump required across all violations
        jump_target_utc: datetime | None = None
        for qt in queue_utc:
            diff_min = abs((candidate_utc - qt).total_seconds() / 60)
            if diff_min < min_gap:
                last_reason_code = "GAP_CONSTRAINT_UNMET"
                j = qt + timedelta(minutes=min_gap)
                if jump_target_utc is None or j > jump_target_utc:
                    jump_target_utc = j

        if jump_target_utc is not None:
            candidate_utc = _ceil_slot(jump_target_utc, resolution)
            continue

        # All checks passed — return this slot
        result: dict = {
            "available": True,
            "slot": candidate_utc.isoformat(),
            "local_time": candidate_local.isoformat(),
            "platform": platform,
            "timezone": tz_name,
        }
        if assumed_utc:
            result["assumed_utc"] = True
        return result

    # No slot found within lookahead
    return _no_slot(platform, last_reason_code, _LOOKAHEAD_DAYS, lookahead_end_utc, assumed_utc)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        result = {
            "available": False,
            "platform": "",
            "reason_code": "INVALID_INPUT",
            "message": f"Invalid JSON: {exc}",
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)

    result = find_next_slot(data)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("available") else 1)


if __name__ == "__main__":
    _main()
