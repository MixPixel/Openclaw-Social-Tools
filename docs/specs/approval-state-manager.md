# Tool Spec: approval-state-manager

## Purpose

Manages the lifecycle state of a post through the approval workflow. Enforces a strict state machine — only valid transitions are allowed — and records every change with a timestamp and actor for auditability.

---

## Why It Exists

Without explicit state tracking it becomes easy to schedule unapproved posts, lose track of what is pending review, or approve something that has already been rejected and revised. A state machine with an audit log eliminates these failure modes without needing an LLM or a human to remember what happened.

State management is also the coordination point between human reviewers and the automated pipeline — the tool holds the post in `pending_approval` until a human (or automated rule) makes a decision.

---

## States

```
draft  ──→  pending_approval  ──→  approved  ──→  scheduled
                │                      │
                ▼                      ▼
            rejected               archived
                │
                ▼
             draft  (revised and resubmitted)
```

| State | Meaning |
|---|---|
| `draft` | Post has been created/revised but not yet submitted for approval |
| `pending_approval` | Submitted for review; awaiting decision |
| `approved` | Approved and ready to be scheduled |
| `rejected` | Rejected; returned to draft for revision |
| `scheduled` | Slot assigned and post written to queue |
| `archived` | Permanently removed from the active workflow |

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
| `scheduled` | `archived` | Post cancelled after scheduling (triggers queue removal) |

Any transition not in this table is invalid and will be rejected.

---

## Inputs

### `transition` (primary action)

| Field | Type | Required | Description |
|---|---|---|---|
| `post_id` | string | yes | Unique identifier of the post |
| `current_state` | enum | yes | The state the caller believes the post is in |
| `target_state` | enum | yes | The state to transition to |
| `actor` | string | yes | Who or what is making this transition (user ID, system name) |
| `note` | string | no | Optional reason or comment to attach to the log entry |

### `get_state` (read-only query)

| Field | Type | Required | Description |
|---|---|---|---|
| `post_id` | string | yes | Unique identifier of the post |

### `get_history` (read-only query)

| Field | Type | Required | Description |
|---|---|---|---|
| `post_id` | string | yes | Unique identifier of the post |

---

## Outputs

### `transition` — success

```json
{
  "success": true,
  "post_id": "post_abc123",
  "previous_state": "pending_approval",
  "new_state": "approved",
  "actor": "reviewer@example.com",
  "timestamp": "2026-03-24T14:30:00Z",
  "log_entry_id": "log_xyz789"
}
```

### `transition` — failure

```json
{
  "success": false,
  "post_id": "post_abc123",
  "error_code": "INVALID_TRANSITION",
  "message": "Cannot transition from 'approved' to 'pending_approval'.",
  "current_state": "approved"
}
```

### `get_state`

```json
{
  "post_id": "post_abc123",
  "current_state": "approved",
  "last_updated": "2026-03-24T14:30:00Z",
  "last_actor": "reviewer@example.com"
}
```

### `get_history`

```json
{
  "post_id": "post_abc123",
  "history": [
    { "from": null, "to": "draft", "actor": "author@example.com", "timestamp": "2026-03-24T10:00:00Z", "note": null },
    { "from": "draft", "to": "pending_approval", "actor": "author@example.com", "timestamp": "2026-03-24T11:00:00Z", "note": null },
    { "from": "pending_approval", "to": "approved", "actor": "reviewer@example.com", "timestamp": "2026-03-24T14:30:00Z", "note": "Looks good." }
  ]
}
```

---

## Error Codes

| Code | Description |
|---|---|
| `INVALID_TRANSITION` | The requested state change is not permitted by the state machine |
| `STATE_MISMATCH` | `current_state` supplied by caller does not match the stored state |
| `POST_NOT_FOUND` | No post exists with the given `post_id` |
| `MISSING_REQUIRED_FIELD` | A required input field was omitted |

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| Caller supplies wrong `current_state` | Return `STATE_MISMATCH` — do not apply transition. Forces caller to re-read state before retrying |
| Two callers attempt simultaneous transitions | First write wins; second receives `STATE_MISMATCH` |
| Post does not exist | Return `POST_NOT_FOUND`; do not create implicitly |
| `approved` → `scheduled` without a queue write | Only `schedule-post` tool should trigger this transition; the tool calls it internally |
| Re-approval after rejection | Valid path: `rejected` → `draft` → `pending_approval` → `approved` — full history preserved |
| Archiving a scheduled post | Valid; implementation should trigger queue removal as a side effect |

---

## Where It Fits in the Workflow

**Position: Step 4 — after validation, before scheduling.**

```
[validate-post]  →  [approval-state-manager]  →  [find-next-slot]  →  [schedule-post]
                       (human review happens
                        while in pending_approval)
```

The tool is also queried by `schedule-post` to confirm a post is in `approved` state before writing to the queue.
