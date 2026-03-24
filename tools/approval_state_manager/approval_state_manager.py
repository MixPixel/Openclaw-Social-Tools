"""approval_state_manager — post approval lifecycle state machine.

Supports four actions dispatched by the 'action' field:
  create     — initialise a new post in 'draft' state
  transition — advance a post to the next state
  get_state  — read the current state of a post
  get_history — read the full audit log for a post

State machine:

  draft ──→ pending_approval ──→ approved ──→ scheduled ──→ posted
    │              │                 │             │
    │              ▼                 ▼             └──→ failed
    │          rejected          archived          └──→ archived
    │              │
    └──→ archived  └──→ draft (revision cycle)

archived is the only terminal state; posted and failed have no
outgoing transitions defined (extend via VALID_TRANSITIONS as needed).

Usage (CLI):
    echo '{...}' | python -m tools.approval_state_manager.approval_state_manager
    # exits 0 on success, 1 on failure

Usage (library):
    from tools.approval_state_manager import manage_approval_state
    result = manage_approval_state({...})
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_STORE_PATH = "data/approval_states.json"

VALID_STATES: frozenset[str] = frozenset({
    "draft",
    "pending_approval",
    "approved",
    "rejected",
    "scheduled",
    "posted",
    "failed",
    "archived",
})

# (from_state, to_state) pairs that are permitted
VALID_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("draft",            "pending_approval"),
    ("pending_approval", "approved"),
    ("pending_approval", "rejected"),
    ("rejected",         "draft"),
    ("approved",         "scheduled"),
    ("approved",         "archived"),
    ("draft",            "archived"),
    ("pending_approval", "archived"),
    ("scheduled",        "archived"),
    ("scheduled",        "posted"),
    ("scheduled",        "failed"),
})

VALID_ACTIONS: frozenset[str] = frozenset({
    "create", "transition", "get_state", "get_history",
})

# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _read_store(path: str) -> dict:
    """Load the JSON store from disk. Returns {} if file does not exist."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise ValueError(f"Store file '{path}' is not valid JSON: {exc}") from exc


def _write_store(path: str, data: dict) -> None:
    """Write the JSON store atomically via a temp-file + os.replace."""
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

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_ts(data: dict) -> str:
    """Return the injected timestamp if provided, otherwise now()."""
    ts = data.get("timestamp")
    return str(ts) if ts else _now_iso()


def _make_log_id(history_len: int) -> str:
    """Sequential log entry id: log_0001, log_0002, …"""
    return f"log_{history_len + 1:04d}"


def _err(post_id: str, error_code: str, message: str) -> dict:
    """Build a consistent failure response."""
    result: dict = {"success": False}
    if post_id:
        result["post_id"] = post_id
    result["error_code"] = error_code
    result["message"] = message
    return result


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _do_create(data: dict, post_id: str, store: dict, store_path: str) -> dict:
    actor: str = str(data.get("actor") or "")
    if not actor:
        return _err(post_id, "MISSING_REQUIRED_FIELD",
                    "Field 'actor' is required for action 'create'.")

    if post_id in store:
        existing = store[post_id]["current_state"]
        return _err(post_id, "POST_ALREADY_EXISTS",
                    f"Post '{post_id}' already exists in state '{existing}'.")

    ts = _resolve_ts(data)
    note = data.get("note") or None
    log_id = _make_log_id(0)

    entry = {
        "log_entry_id": log_id,
        "from": None,
        "to": "draft",
        "actor": actor,
        "timestamp": ts,
        "note": note,
    }
    store[post_id] = {
        "current_state": "draft",
        "last_updated": ts,
        "last_actor": actor,
        "history": [entry],
    }
    _write_store(store_path, store)

    return {
        "success": True,
        "post_id": post_id,
        "state": "draft",
        "actor": actor,
        "timestamp": ts,
        "log_entry_id": log_id,
    }


def _do_transition(data: dict, post_id: str, store: dict, store_path: str) -> dict:
    actor: str = str(data.get("actor") or "")
    current_state: str = str(data.get("current_state") or "")
    target_state: str = str(data.get("target_state") or "")

    if not actor:
        return _err(post_id, "MISSING_REQUIRED_FIELD",
                    "Field 'actor' is required for action 'transition'.")
    if not current_state:
        return _err(post_id, "MISSING_REQUIRED_FIELD",
                    "Field 'current_state' is required for action 'transition'.")
    if not target_state:
        return _err(post_id, "MISSING_REQUIRED_FIELD",
                    "Field 'target_state' is required for action 'transition'.")

    valid_list = ", ".join(sorted(VALID_STATES))
    if current_state not in VALID_STATES:
        return _err(post_id, "INVALID_STATE",
                    f"'{current_state}' is not a recognised state. Valid states: {valid_list}.")
    if target_state not in VALID_STATES:
        return _err(post_id, "INVALID_STATE",
                    f"'{target_state}' is not a recognised state. Valid states: {valid_list}.")

    if post_id not in store:
        return _err(post_id, "POST_NOT_FOUND",
                    f"No post found with id '{post_id}'.")

    post = store[post_id]
    stored = post["current_state"]

    if stored != current_state:
        return _err(post_id, "STATE_MISMATCH",
                    f"Expected state '{current_state}' but post is in '{stored}'.")

    if (current_state, target_state) not in VALID_TRANSITIONS:
        return _err(post_id, "INVALID_TRANSITION",
                    f"Cannot transition from '{current_state}' to '{target_state}'.")

    ts = _resolve_ts(data)
    note = data.get("note") or None
    log_id = _make_log_id(len(post["history"]))

    post["history"].append({
        "log_entry_id": log_id,
        "from": current_state,
        "to": target_state,
        "actor": actor,
        "timestamp": ts,
        "note": note,
    })
    post["current_state"] = target_state
    post["last_updated"] = ts
    post["last_actor"] = actor

    _write_store(store_path, store)

    return {
        "success": True,
        "post_id": post_id,
        "previous_state": current_state,
        "new_state": target_state,
        "actor": actor,
        "timestamp": ts,
        "log_entry_id": log_id,
    }


def _do_get_state(post_id: str, store: dict) -> dict:
    if post_id not in store:
        return _err(post_id, "POST_NOT_FOUND",
                    f"No post found with id '{post_id}'.")

    post = store[post_id]
    return {
        "success": True,
        "post_id": post_id,
        "current_state": post["current_state"],
        "last_updated": post["last_updated"],
        "last_actor": post["last_actor"],
    }


def _do_get_history(post_id: str, store: dict) -> dict:
    if post_id not in store:
        return _err(post_id, "POST_NOT_FOUND",
                    f"No post found with id '{post_id}'.")

    return {
        "success": True,
        "post_id": post_id,
        "history": store[post_id]["history"],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def manage_approval_state(data: dict) -> dict:
    """Manage post approval state.

    Args:
        data: dict with keys:
            action      (str, required)  — 'create', 'transition', 'get_state', 'get_history'
            post_id     (str, required)  — unique post identifier
            store_path  (str, optional)  — path to the JSON store file
            timestamp   (str, optional)  — ISO 8601; defaults to now(UTC)
            actor       (str)            — required for create and transition
            current_state (str)         — required for transition (optimistic lock)
            target_state  (str)         — required for transition
            note          (str)         — optional, attached to the log entry

    Returns:
        dict always containing 'success' (bool) plus either result fields
        or 'error_code' and 'message' on failure.
    """
    post_id: str = str(data.get("post_id") or "")
    action: str = str(data.get("action") or "")
    store_path: str = str(data.get("store_path") or DEFAULT_STORE_PATH)

    if not action:
        return _err(post_id, "MISSING_REQUIRED_FIELD", "Field 'action' is required.")
    if action not in VALID_ACTIONS:
        supported = ", ".join(sorted(VALID_ACTIONS))
        return _err(post_id, "INVALID_ACTION",
                    f"Unknown action '{action}'. Valid actions: {supported}.")
    if not post_id:
        return _err("", "MISSING_REQUIRED_FIELD", "Field 'post_id' is required.")

    store = _read_store(store_path)

    if action == "create":
        return _do_create(data, post_id, store, store_path)
    if action == "transition":
        return _do_transition(data, post_id, store, store_path)
    if action == "get_state":
        return _do_get_state(post_id, store)
    # action == "get_history"
    return _do_get_history(post_id, store)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        result = {
            "success": False,
            "error_code": "INVALID_INPUT",
            "message": f"Invalid JSON: {exc}",
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)

    result = manage_approval_state(data)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    _main()
