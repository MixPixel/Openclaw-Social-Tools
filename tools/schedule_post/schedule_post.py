"""schedule_post — write an approved post to the scheduling queue.

Preconditions (checked in order):
  1. Required fields present
  2. Platform recognised
  3. Post exists in the approval store
  4. Post is in 'approved' state
  5a. (slot provided) Slot is in the future, within a window, not on a blackout
      date, not in conflict with existing queue entries
  5e. (slot omitted) find-next-slot is called; fails with NO_SLOT_AVAILABLE if
      no slot is found
  6. Content passes validate-post
  7. Each media item has a non-empty url_or_path

On success:
  - Writes a queue record atomically to the queue store
  - Transitions the post from 'approved' → 'scheduled' via approval-state-manager

Usage (CLI):
    echo '{...}' | python -m tools.schedule_post.schedule_post
    # exits 0 on success, 1 on failure

Usage (library):
    from tools.schedule_post import schedule_post
    result = schedule_post({...})
"""

import hashlib
import json
import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tools.approval_state_manager import manage_approval_state
from tools.find_next_slot import find_next_slot
from tools.validate_post import validate_post
from tools.validate_post.validate_post import PLATFORM_ALIASES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_APPROVAL_STORE_PATH = "data/approval_states.json"
DEFAULT_QUEUE_STORE_PATH = "data/queue.json"

# ---------------------------------------------------------------------------
# Storage helpers (mirrors approval_state_manager pattern)
# ---------------------------------------------------------------------------

def _read_store(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"Store file '{path}' is not valid JSON: {exc}") from exc


def _write_store(path: str, data: dict) -> None:
    abs_path = os.path.abspath(path)
    dir_ = os.path.dirname(abs_path)
    os.makedirs(dir_, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, abs_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw: str) -> datetime:
    """Parse an ISO 8601 string to a timezone-aware UTC datetime."""
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_time_str(s: str) -> time:
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]))


def _make_queue_id(post_id: str, slot: str) -> str:
    digest = hashlib.sha256(f"{post_id}:{slot}".encode()).hexdigest()[:8]
    return f"q_{digest}"


def _err(post_id: str, error_code: str, message: str, **extra) -> dict:
    result: dict = {"success": False}
    if post_id:
        result["post_id"] = post_id
    result["error_code"] = error_code
    result["message"] = message
    result.update(extra)
    return result


# ---------------------------------------------------------------------------
# Slot validation helpers (inlined to keep schedule_post self-contained)
# ---------------------------------------------------------------------------

def _slot_in_window(slot_local: datetime, windows_raw: list[dict]) -> bool:
    """Return True if slot_local's time falls within any allowed window for its weekday."""
    _DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    weekday = slot_local.weekday()
    local_time = slot_local.time().replace(second=0, microsecond=0)

    for w in windows_raw:
        days_raw = w.get("days")
        if days_raw is None:
            day_ints = list(range(7))
        else:
            day_ints = [_DAY_MAP[d.lower()] for d in days_raw]
        if weekday not in day_ints:
            continue
        start = _parse_time_str(w["start"])
        end = _parse_time_str(w["end"])
        if start <= local_time < end:
            return True
    return False


def _slot_on_blackout(slot_local: datetime, blackout_raw: list[str]) -> bool:
    """Return True if slot_local's date is in blackout_dates."""
    slot_date = slot_local.date()
    for d in blackout_raw:
        if date.fromisoformat(d) == slot_date:
            return True
    return False


def _find_conflict(
    slot_utc: datetime,
    queue: dict,
    min_gap: int,
) -> str | None:
    """Return queue_id of the first conflicting entry, or None if no conflict.

    Conflict: abs(slot_utc - existing_slot_utc) < min_gap_minutes (strictly less).
    """
    for qid, entry in queue.items():
        existing_utc = _parse_dt(entry["slot"])
        diff_min = abs((slot_utc - existing_utc).total_seconds() / 60)
        if diff_min < min_gap:
            return qid
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def schedule_post(data: dict) -> dict:
    """Schedule an approved post.

    Args:
        data: dict with keys:
            post_id             (str, required)
            content             (str, required)
            platform            (str, required)
            actor               (str, required)
            schedule_config     (dict, required)
            slot                (str, optional)  ISO 8601; if omitted find-next-slot is called
            media               (list, optional) [{ type, url_or_path, alt_text? }]
            approval_store_path (str, optional)  default: data/approval_states.json
            queue_store_path    (str, optional)  default: data/queue.json
            now                 (str, optional)  injectable current time (ISO 8601)
            timestamp           (str, optional)  injectable created_at (ISO 8601)
            queue_id            (str, optional)  injectable queue ID for testing

    Returns:
        dict always containing 'success' (bool) plus either result fields
        or 'error_code' and 'message' on failure.
    """
    post_id: str = str(data.get("post_id") or "")
    content: str = str(data.get("content") or "")
    platform_raw: str = str(data.get("platform") or "")
    actor: str = str(data.get("actor") or "")
    config: dict = data.get("schedule_config") or {}
    slot_raw: str = str(data.get("slot") or "")
    media: list = data.get("media") or []
    approval_store_path: str = str(
        data.get("approval_store_path") or DEFAULT_APPROVAL_STORE_PATH
    )
    queue_store_path: str = str(
        data.get("queue_store_path") or DEFAULT_QUEUE_STORE_PATH
    )

    # --- 1. Required fields ---
    for field, value in [
        ("post_id", post_id),
        ("content", content),
        ("platform", platform_raw),
        ("actor", actor),
    ]:
        if not value:
            return _err("", "MISSING_REQUIRED_FIELD",
                        f"Field '{field}' is required.")
    if not config:
        return _err(post_id, "MISSING_REQUIRED_FIELD",
                    "Field 'schedule_config' is required.")

    # --- 2. Platform ---
    platform = PLATFORM_ALIASES.get(platform_raw.strip().lower())
    if platform is None:
        supported = ", ".join(sorted(PLATFORM_ALIASES.keys()))
        return _err(post_id, "PLATFORM_NOT_SUPPORTED",
                    f"Platform '{platform_raw}' is not recognised. "
                    f"Supported: {supported}.")

    # --- Resolve 'now' ---
    now_raw: str = str(data.get("now") or "")
    try:
        now_utc: datetime = _parse_dt(now_raw) if now_raw else _now_utc()
    except ValueError as exc:
        return _err(post_id, "MISSING_REQUIRED_FIELD",
                    f"Could not parse 'now': {exc}")

    # --- 3 & 4. Post state ---
    state_result = manage_approval_state({
        "action": "get_state",
        "post_id": post_id,
        "store_path": approval_store_path,
    })
    if not state_result.get("success"):
        code = state_result.get("error_code", "POST_NOT_FOUND")
        return _err(post_id, code, state_result.get("message", "Post not found."))

    actual_state = state_result["current_state"]
    if actual_state != "approved":
        return _err(post_id, "POST_NOT_APPROVED",
                    f"Post '{post_id}' is in state '{actual_state}', not 'approved'.",
                    actual_state=actual_state)

    # --- Config fields used for slot validation ---
    tz_name: str = config.get("timezone", "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return _err(post_id, "MISSING_REQUIRED_FIELD",
                    f"Unknown timezone '{tz_name}' in schedule_config.")

    min_gap: int = config.get("min_gap_minutes", 60)
    blackout_raw: list = config.get("blackout_dates") or []
    windows_raw: list = config.get("allowed_windows") or []

    # --- Read queue store ---
    queue: dict = _read_store(queue_store_path)

    # --- 5. Determine and validate slot ---
    slot_source: str
    slot_utc: datetime

    if slot_raw:
        # Caller provided a slot — validate it directly.
        try:
            slot_utc = _parse_dt(slot_raw)
        except ValueError as exc:
            return _err(post_id, "MISSING_REQUIRED_FIELD",
                        f"Could not parse 'slot': {exc}")

        # 5a. In the future
        if slot_utc <= now_utc:
            return _err(post_id, "SLOT_IN_PAST",
                        f"Slot {slot_utc.isoformat()} is not in the future "
                        f"(now: {now_utc.isoformat()}).")

        slot_local = slot_utc.astimezone(tz)

        # 5b. Within an allowed window
        if windows_raw and not _slot_in_window(slot_local, windows_raw):
            return _err(post_id, "SLOT_OUTSIDE_WINDOW",
                        f"Slot {slot_utc.isoformat()} does not fall within any "
                        f"allowed posting window.")

        # 5c. Not a blackout date
        if _slot_on_blackout(slot_local, blackout_raw):
            return _err(post_id, "SLOT_ON_BLACKOUT_DATE",
                        f"Slot date {slot_local.date().isoformat()} is a blackout date.")

        # 5d. No conflict
        conflict_id = _find_conflict(slot_utc, queue, min_gap)
        if conflict_id is not None:
            existing_slot = queue[conflict_id]["slot"]
            existing_utc = _parse_dt(existing_slot)
            gap_min = int(abs((slot_utc - existing_utc).total_seconds() / 60))
            return _err(
                post_id, "SLOT_CONFLICT",
                f"Slot {slot_utc.isoformat()} conflicts with existing entry "
                f"{conflict_id} at {existing_utc.isoformat()} "
                f"(gap: {gap_min} min, minimum: {min_gap} min).",
                conflicting_queue_id=conflict_id,
            )

        slot_source = "provided"

    else:
        # No slot — call find-next-slot to find one.
        existing_queue_slots = [entry["slot"] for entry in queue.values()]
        fns_result = find_next_slot({
            "platform": platform,
            "after": now_utc.isoformat(),
            "schedule_config": config,
            "existing_queue": existing_queue_slots,
        })
        if not fns_result.get("available"):
            return _err(
                post_id, "NO_SLOT_AVAILABLE",
                fns_result.get("message", "No slot available within the lookahead window."),
                find_next_slot_reason=fns_result.get("reason_code"),
            )
        slot_utc = _parse_dt(fns_result["slot"])
        slot_source = "auto"

    slot_iso = slot_utc.isoformat()

    # --- 6. Re-validate content ---
    val_result = validate_post({
        "content": content,
        "platform": platform,
        "media": media,
    })
    if not val_result.get("valid"):
        return _err(
            post_id, "VALIDATION_FAILED",
            "Content failed validation.",
            validation_errors=val_result.get("errors", []),
        )

    # --- 7. Media items resolvable ---
    for item in media:
        if not str(item.get("url_or_path") or "").strip():
            return _err(post_id, "MEDIA_UNAVAILABLE",
                        "A media item has a missing or empty 'url_or_path'.")

    # --- Collect warnings ---
    warnings: list[str] = []
    for item in media:
        if item.get("type") == "image" and not str(item.get("alt_text") or "").strip():
            warnings.append("NO_ALT_TEXT")
            break  # one warning per scheduling call is enough

    # --- Generate queue_id ---
    injected_qid: str = str(data.get("queue_id") or "")
    queue_id = injected_qid if injected_qid else _make_queue_id(post_id, slot_iso)

    # --- Resolve created_at ---
    ts_raw: str = str(data.get("timestamp") or "")
    try:
        created_at_utc = _parse_dt(ts_raw) if ts_raw else now_utc
    except ValueError as exc:
        return _err(post_id, "MISSING_REQUIRED_FIELD",
                    f"Could not parse 'timestamp': {exc}")
    created_at_iso = created_at_utc.isoformat()

    # --- Write queue record ---
    queue[queue_id] = {
        "queue_id":   queue_id,
        "post_id":    post_id,
        "platform":   platform,
        "content":    content,
        "slot":       slot_iso,
        "media":      media,
        "actor":      actor,
        "created_at": created_at_iso,
    }
    _write_store(queue_store_path, queue)

    # --- Transition state: approved → scheduled ---
    transition_result = manage_approval_state({
        "action":        "transition",
        "post_id":       post_id,
        "current_state": "approved",
        "target_state":  "scheduled",
        "actor":         actor,
        "store_path":    approval_store_path,
        "timestamp":     created_at_iso,
    })
    if not transition_result.get("success"):
        return _err(
            post_id, "STATE_TRANSITION_FAILED",
            f"Queue record written (queue_id: {queue_id}) but state transition failed: "
            f"{transition_result.get('message', 'unknown error')}",
            queue_id=queue_id,
        )

    return {
        "success":     True,
        "queue_id":    queue_id,
        "post_id":     post_id,
        "platform":    platform,
        "slot":        slot_iso,
        "slot_source": slot_source,
        "actor":       actor,
        "created_at":  created_at_iso,
        "warnings":    warnings,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        result = {
            "success":    False,
            "error_code": "INVALID_INPUT",
            "message":    f"Invalid JSON: {exc}",
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)

    result = schedule_post(data)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    _main()
