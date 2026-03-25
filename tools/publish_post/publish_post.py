"""publish_post — deliver due queue entries to their platforms.

Reads the scheduling queue, selects entries whose slot <= now, calls a platform
adapter for each, writes the result back to the queue store, and drives the
approval state machine from scheduled → posted or scheduled → failed.

Adapter injection is a library-only concern. The public JSON input schema has no
adapter field — a callable cannot round-trip through JSON. The CLI always uses
the built-in _stub_adapter.

Usage (CLI):
    echo '{...}' | python -m tools.publish_post.publish_post
    # exits 0 on success, 1 on system error

Usage (library):
    from tools.publish_post import publish_post

    def my_adapter(entry):
        ...
        return {"success": True, "platform_post_id": "id", "platform_response": None}

    result = publish_post(data, _adapter=my_adapter)
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

from tools.approval_state_manager import manage_approval_state

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_QUEUE_STORE_PATH = "data/queue.json"
DEFAULT_APPROVAL_STORE_PATH = "data/approval_states.json"

# ---------------------------------------------------------------------------
# Default adapter (stub — no real delivery; always reports success)
# ---------------------------------------------------------------------------

def _stub_adapter(entry: dict) -> dict:
    """No-op adapter used by the CLI and when no adapter is injected."""
    return {"success": True, "platform_post_id": None, "platform_response": None}


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _read_store(path: str) -> dict:
    """Load JSON store from disk. Returns {} if file does not exist."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"Store file '{path}' is not valid JSON: {exc}") from exc


def _write_store(path: str, data: dict) -> None:
    """Write the JSON store atomically via temp-file + os.replace."""
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


def _entry_status(entry: dict) -> str:
    """Return canonical status. Absent or unrecognised values → 'pending'."""
    status = entry.get("status")
    if status in ("posted", "failed"):
        return status
    return "pending"


def _sys_err(error_code: str, message: str) -> dict:
    return {"success": False, "error_code": error_code, "message": message}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def publish_post(data: dict, *, _adapter=None) -> dict:
    """Deliver due queue entries to their platforms.

    Args:
        data: dict with public JSON keys:
            queue_store_path    (str, optional)  default: data/queue.json
            approval_store_path (str, optional)  default: data/approval_states.json
            now                 (str, optional)  ISO 8601; injectable current time
            timestamp           (str, optional)  ISO 8601; injectable posted_at/failed_at
            dry_run             (bool, optional) default: False
            queue_ids           (list[str], opt) manual override: process exactly these IDs
            retry_failed        (bool, optional) default: False

        _adapter: callable (keyword-only, library use only). Signature:
            (entry: dict) -> {"success": bool, ...}
            Defaults to _stub_adapter when None.

    Returns:
        dict always containing 'success' (bool) plus either summary fields
        and 'results' list, or 'error_code' and 'message' on system failure.
    """
    queue_store_path: str = str(data.get("queue_store_path") or DEFAULT_QUEUE_STORE_PATH)
    approval_store_path: str = str(data.get("approval_store_path") or DEFAULT_APPROVAL_STORE_PATH)
    dry_run: bool = bool(data.get("dry_run", False))
    retry_failed: bool = bool(data.get("retry_failed", False))
    queue_ids_raw = data.get("queue_ids")  # None or list[str]

    # --- Resolve now ---
    now_raw: str = str(data.get("now") or "")
    try:
        now_utc: datetime = _parse_dt(now_raw) if now_raw else _now_utc()
    except ValueError as exc:
        return _sys_err("INVALID_INPUT", f"Could not parse 'now': {exc}")

    # --- Resolve timestamp (posted_at / failed_at) ---
    ts_raw: str = str(data.get("timestamp") or "")
    try:
        timestamp_utc: datetime = _parse_dt(ts_raw) if ts_raw else now_utc
    except ValueError as exc:
        return _sys_err("INVALID_INPUT", f"Could not parse 'timestamp': {exc}")
    timestamp_iso: str = timestamp_utc.isoformat()

    # --- Adapter ---
    adapter = _adapter if _adapter is not None else _stub_adapter

    # --- Read queue store ---
    try:
        queue: dict = _read_store(queue_store_path)
    except ValueError as exc:
        return _sys_err("QUEUE_STORE_ERROR", str(exc))

    # --- Determine work items ---
    # Each item is (queue_id, entry_or_None).
    # None signals a not_found result for queue_ids mode.
    if queue_ids_raw is not None:
        # Manual override: process exactly these IDs, regardless of slot.
        work_items: list[tuple[str, dict | None]] = [
            (qid, queue.get(qid)) for qid in queue_ids_raw
        ]
    else:
        # Default: all entries with slot <= now.
        now_ts = now_utc.timestamp()
        work_items = []
        for qid, entry in queue.items():
            try:
                slot_ts = _parse_dt(entry.get("slot", "")).timestamp()
                if slot_ts <= now_ts:
                    work_items.append((qid, entry))
            except (ValueError, TypeError):
                # Skip entries with unparseable or absent slots.
                pass

    # --- Process candidates ---
    results: list[dict] = []
    counters: dict[str, int] = {
        "posted": 0,
        "failed": 0,
        "already_posted": 0,
        "already_failed": 0,
    }

    for qid, entry in work_items:
        # --- Not found ---
        if entry is None:
            results.append({"queue_id": qid, "outcome": "not_found"})
            continue

        base: dict = {
            "queue_id": qid,
            "post_id":  entry.get("post_id", ""),
            "platform": entry.get("platform", ""),
            "slot":     entry.get("slot", ""),
        }

        status = _entry_status(entry)

        # --- Idempotency: already posted ---
        if status == "posted":
            r: dict = {**base, "outcome": "already_posted"}
            if entry.get("posted_at"):
                r["posted_at"] = entry["posted_at"]
            results.append(r)
            counters["already_posted"] += 1
            continue

        # --- Idempotency: already failed (no retry) ---
        if status == "failed" and not retry_failed:
            results.append({**base, "outcome": "already_failed"})
            counters["already_failed"] += 1
            continue

        # --- Dry run ---
        if dry_run:
            results.append({**base, "outcome": "dry_run"})
            continue

        # --- Call adapter (catch any exception) ---
        try:
            adapter_result: dict = adapter(entry)
        except Exception as exc:
            adapter_result = {
                "success":          False,
                "error_code":       "ADAPTER_EXCEPTION",
                "message":          str(exc),
                "platform_response": None,
            }

        if adapter_result.get("success"):
            # Step 1: write queue entry atomically.
            entry["status"]            = "posted"
            entry["posted_at"]         = timestamp_iso
            entry["platform_post_id"]  = adapter_result.get("platform_post_id")
            entry["platform_response"] = adapter_result.get("platform_response")
            _write_store(queue_store_path, queue)

            r = {
                **base,
                "outcome":           "posted",
                "posted_at":         timestamp_iso,
                "platform_post_id":  adapter_result.get("platform_post_id"),
                "platform_response": adapter_result.get("platform_response"),
            }

            # Step 2: attempt approval state transition.
            tr = manage_approval_state({
                "action":        "transition",
                "post_id":       base["post_id"],
                "current_state": "scheduled",
                "target_state":  "posted",
                "actor":         "publish_post",
                "store_path":    approval_store_path,
                "timestamp":     timestamp_iso,
            })
            if not tr.get("success"):
                r["state_transition_warning"] = tr.get(
                    "message", "State transition to 'posted' failed."
                )

            results.append(r)
            counters["posted"] += 1

        else:
            error_code: str = str(adapter_result.get("error_code") or "ADAPTER_ERROR")
            message: str    = str(adapter_result.get("message") or "")

            # Step 1: write queue entry atomically.
            entry["status"]        = "failed"
            entry["failed_at"]     = timestamp_iso
            entry["error_code"]    = error_code
            entry["error_message"] = message
            _write_store(queue_store_path, queue)

            r = {
                **base,
                "outcome":    "failed",
                "failed_at":  timestamp_iso,
                "error_code": error_code,
                "message":    message,
            }

            # Step 2: attempt approval state transition.
            tr = manage_approval_state({
                "action":        "transition",
                "post_id":       base["post_id"],
                "current_state": "scheduled",
                "target_state":  "failed",
                "actor":         "publish_post",
                "store_path":    approval_store_path,
                "timestamp":     timestamp_iso,
            })
            if not tr.get("success"):
                r["state_transition_warning"] = tr.get(
                    "message", "State transition to 'failed' failed."
                )

            results.append(r)
            counters["failed"] += 1

    return {
        "success":        True,
        "now":            now_utc.isoformat(),
        "dry_run":        dry_run,
        "processed":      len(results),
        "posted":         counters["posted"],
        "failed":         counters["failed"],
        "already_posted": counters["already_posted"],
        "already_failed": counters["already_failed"],
        "results":        results,
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

    # CLI always uses _stub_adapter; no adapter injection from JSON payload.
    result = publish_post(data)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    _main()
