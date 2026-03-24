# Tool Spec: approval-state-manager

## Purpose

Manages the lifecycle state of a post through the approval workflow. Enforces a strict state machine — only valid transitions are allowed — and records every change with a timestamp and actor for auditability.

---

## Why It Exists

Without explicit state tracking it becomes easy to schedule unapproved posts, lose track of what is pending review, or approve something that has already been rejected and revised. A state machine with an audit log eliminates these failure modes without needing an LLM or a human to remember what happened.

State management is also the coordination point between human reviewers and the automated pipeline — the tool holds the post in `pending_approval` until a human (or automated rule) makes a decision.

---

## Implementation

`tools/approval_state_manager/approval_state_manager.py` — stdlib only. State is persisted to a JSON file on disk. Writes are atomic (temp file + `os.replace`).

---

## States

```
draft ──→ pending_approval ──→ approved ──→ scheduled ──→ posted
  │              │                 │             │
  │              ▼                 ▼             └──→ failed
  │          rejected          archived
  │              │
  └──→ archived  └──→ draft (revision cycle)

scheduled ──→ archived  (cancel after scheduling)
```

| State | Meaning |
|---|---|
| `draft` | Post has been created/revised but not yet submitted for approval |
| `pending_approval` | Submitted for review; awaiting decision |
| `approved` | Approved and ready to be scheduled |
| `rejected` | Rejected; returned to draft for revision |
| `scheduled` | Slot assigned and post written to queue |
| `posted` | Post has been successfully published |
| `failed` | Publishing attempt failed |
| `archived` | Permanently removed from the active workflow (terminal) |

`archived` is the only terminal state. `posted` and `failed` have no outgoing transitions currently defined but are not marked terminal — transitions from them can be added to `VALID_TRANSITIONS` as the workflow evolves.

---

## Valid Transitions

| From | To | Trigger |
|---|---|---|
| `draft` | `pending_approval` | Author submits for review |
| `pending_approval` | `approved` | Reviewer approves |
| `pending_approval` | `rejected` | Reviewer rejects |
| `rejected` | `draft` | Author acknowledges and begins revision |
| `approved` | `scheduled` | `schedule-post` tool writes to queue |
| `approved` | `archived` | Author or admin withdraws post |
| `draft` | `archived` | Author or admin withdraws post |
| `pending_approval` | `archived` | Admin withdraws post during review |
| `scheduled` | `archived` | Post cancelled after scheduling |
| `scheduled` | `posted` | Publisher confirms successful publish |
| `scheduled` | `failed` | Publisher reports publishing failure |

Any pair not in this table is invalid and will be rejected with `INVALID_TRANSITION`.

---

## Inputs

All operations share a single input structure dispatched by `action`.

### Common fields

| Field | Type | Required | Description |
|---|---|---|---|
| `action` | string | yes | `create`, `transition`, `get_state`, or `get_history` |
| `post_id` | string | yes | Unique identifier of the post |
| `store_path` | string | no | Path to the JSON store file. Default: `data/approval_states.json` |
| `timestamp` | string (ISO 8601) | no | Timestamp to record. Default: `now(UTC)`. Inject for determinism in tests |

### Per-action additional fields

| Action | Additional required | Optional |
|---|---|---|
| `create` | `actor` | `note` |
| `transition` | `actor`, `current_state`, `target_state` | `note` |
| `get_state` | — | — |
| `get_history` | — | — |

`current_state` in `transition` is an **optimistic lock** — if the stored state differs from the caller's value, the transition is rejected with `STATE_MISMATCH`. This ensures first-writer-wins under concurrent access.

---

## Outputs

Every response includes `success: true/false`. On failure, `error_code` and `message` are always present.

### `create` — success

```json
{
  "success":      true,
  "post_id":      "post_abc123",
  "state":        "draft",
  "actor":        "author@example.com",
  "timestamp":    "2026-03-24T10:00:00+00:00",
  "log_entry_id": "log_0001"
}
```

### `transition` — success

```json
{
  "success":        true,
  "post_id":        "post_abc123",
  "previous_state": "pending_approval",
  "new_state":      "approved",
  "actor":          "reviewer@example.com",
  "timestamp":      "2026-03-24T14:30:00+00:00",
  "log_entry_id":   "log_0003"
}
```

### Any action — failure

```json
{
  "success":    false,
  "post_id":    "post_abc123",
  "error_code": "STATE_MISMATCH",
  "message":    "Expected state 'draft' but post is in 'pending_approval'."
}
```

`post_id` is omitted from the failure response only when `post_id` itself was not supplied (e.g. `MISSING_REQUIRED_FIELD` for the `post_id` field).

### `get_state`

```json
{
  "success":       true,
  "post_id":       "post_abc123",
  "current_state": "approved",
  "last_updated":  "2026-03-24T14:30:00+00:00",
  "last_actor":    "reviewer@example.com"
}
```

### `get_history`

```json
{
  "success":  true,
  "post_id":  "post_abc123",
  "history": [
    {"log_entry_id": "log_0001", "from": null,              "to": "draft",            "actor": "author",   "timestamp": "2026-03-24T10:00:00+00:00", "note": null},
    {"log_entry_id": "log_0002", "from": "draft",           "to": "pending_approval", "actor": "author",   "timestamp": "2026-03-24T11:00:00+00:00", "note": null},
    {"log_entry_id": "log_0003", "from": "pending_approval","to": "approved",          "actor": "reviewer", "timestamp": "2026-03-24T14:30:00+00:00", "note": "Looks good."}
  ]
}
```

`log_entry_id` is sequential within a post: `log_0001`, `log_0002`, … The first entry always has `from: null`.

---

## Error Codes

| Code | Trigger |
|---|---|
| `MISSING_REQUIRED_FIELD` | A required field for the requested action is absent or empty |
| `INVALID_ACTION` | `action` is not one of the four valid values |
| `INVALID_STATE` | `current_state` or `target_state` is not a recognised state name |
| `INVALID_TRANSITION` | The `(current_state, target_state)` pair is not in the valid transition table |
| `STATE_MISMATCH` | Caller's `current_state` does not match the stored state |
| `POST_NOT_FOUND` | No post exists with the given `post_id` (for `transition`, `get_state`, `get_history`) |
| `POST_ALREADY_EXISTS` | `create` called with a `post_id` that is already in the store |

---

## Storage

State is persisted in a single JSON file (`store_path`). The file contains a dict keyed by `post_id`:

```json
{
  "post_abc123": {
    "current_state": "approved",
    "last_updated":  "2026-03-24T14:30:00+00:00",
    "last_actor":    "reviewer@example.com",
    "history": [ ... ]
  }
}
```

The file is written atomically: data is written to a sibling `.tmp` file, then renamed over the target path via `os.replace()`. The parent directory is created on first write.

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| Caller supplies wrong `current_state` | `STATE_MISMATCH` — transition not applied; caller must re-read before retrying |
| Two callers attempt simultaneous transitions | First write wins; second receives `STATE_MISMATCH` |
| Post does not exist | `POST_NOT_FOUND`; posts are never created implicitly |
| `create` called twice with same `post_id` | `POST_ALREADY_EXISTS`; existing post is not modified |
| `timestamp` not provided | Defaults to `datetime.now(UTC)` |
| `timestamp` provided | Used exactly as supplied — enables deterministic tests |
| `archived` → anything | `INVALID_TRANSITION`; `archived` is terminal |
| `posted` / `failed` → anything | `INVALID_TRANSITION` (no outgoing transitions defined yet) |
| `scheduled` → `posted` or `failed` | Valid; records outcome of the publish attempt |
| Re-approval after rejection | Valid path: `rejected → draft → pending_approval → approved`; full history preserved |
| `note` omitted | Stored as `null` in the log entry |

---

## CLI Usage

```bash
# Create a post
echo '{"action": "create", "post_id": "post_001", "actor": "author@example.com"}' \
  | python -m tools.approval_state_manager.approval_state_manager

# Transition state
echo '{
  "action": "transition",
  "post_id": "post_001",
  "current_state": "draft",
  "target_state": "pending_approval",
  "actor": "author@example.com",
  "note": "Ready for review"
}' | python -m tools.approval_state_manager.approval_state_manager

# Exits 0 on success, 1 on failure
```

## Library Usage

```python
from tools.approval_state_manager import manage_approval_state

# Create
result = manage_approval_state({
    "action": "create",
    "post_id": "post_001",
    "actor": "author@example.com",
    "store_path": "data/approval_states.json",
})

# Transition
result = manage_approval_state({
    "action": "transition",
    "post_id": "post_001",
    "current_state": "draft",
    "target_state": "pending_approval",
    "actor": "author@example.com",
})

if result["success"]:
    print(f"Now in state: {result['new_state']}")
else:
    print(f"Error: {result['error_code']} — {result['message']}")
```

---

## Where It Fits in the Workflow

**Position: Step 4 — after validation, before scheduling.**

```
[validate-post]  →  [approval-state-manager]  →  [find-next-slot]  →  [schedule-post]
                       (human review happens
                        while in pending_approval)
```

After `schedule-post` writes to the queue, it calls `approval-state-manager` to transition the post from `approved` → `scheduled`. After the post is published, the publisher transitions `scheduled` → `posted` or `scheduled` → `failed`.
