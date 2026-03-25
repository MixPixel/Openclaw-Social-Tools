# Tool Spec: publish-post

## Purpose

Reads the scheduling queue, selects entries whose slot is due, delivers each post via
a platform adapter boundary, records the result back into the queue store, and advances
the approval state machine from `scheduled` → `posted` or `scheduled` → `failed`.

---

## Why It Exists

`schedule_post` commits a post to the queue but performs no delivery. `publish_post`
closes the loop: it is the only tool that writes delivery results and advances posts
to a terminal outcome (`posted` or `failed`). Keeping delivery separate from scheduling
means scheduling decisions are always reversible until this tool runs.

---

## Inputs

### Public JSON schema

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `queue_store_path` | string | no | `data/queue.json` | Path to queue store |
| `approval_store_path` | string | no | `data/approval_states.json` | Path to approval store |
| `now` | string (ISO 8601) | no | `datetime.now(UTC)` | Injectable current time for testing |
| `timestamp` | string (ISO 8601) | no | same as `now` | Injectable `posted_at`/`failed_at` |
| `dry_run` | bool | no | `false` | Select due entries but skip delivery and writes |
| `queue_ids` | list[string] | no | `null` | Manual override — see **Candidate Selection** |
| `retry_failed` | bool | no | `false` | Re-attempt entries whose `status` is `"failed"` |

`adapter` is intentionally absent from this schema. The public contract is
JSON-serialisable and deterministic. An adapter callable cannot round-trip through JSON.

### Adapter injection (library use only)

For library and test callers, `publish_post` accepts a `_adapter` keyword argument:

```python
from tools.publish_post import publish_post

result = publish_post(data, _adapter=my_platform_adapter)
```

The CLI always uses the built-in `_stub_adapter` (see below). No real platform APIs
are called without an explicit library-side adapter injection.

---

## Platform Adapter Interface

```python
def adapter(entry: dict) -> dict:
    """
    Receives the full queue entry dict.

    Returns on success:
        {"success": True, "platform_post_id": str | None, "platform_response": dict | None}

    Returns on failure:
        {"success": False, "error_code": str, "message": str, "platform_response": dict | None}
    """
```

### Default stub (CLI and uninjected library use)

```python
def _stub_adapter(entry: dict) -> dict:
    return {"success": True, "platform_post_id": None, "platform_response": None}
```

### Exception safety

If the adapter raises any exception, `publish_post` catches it and treats the delivery
as failed with `error_code: "ADAPTER_EXCEPTION"` and the exception message stored in
`error_message`.

---

## Queue Entry Statuses

Canonical values:

| Status | Meaning |
|---|---|
| `"pending"` | Awaiting delivery |
| `"posted"` | Successfully delivered |
| `"failed"` | Delivery attempted and failed |

**Backward-compatibility rule:** entries written by `schedule_post` have no `status`
field. Any entry whose `status` is absent or is not `"posted"` or `"failed"` is treated
as `"pending"`. No migration is required.

---

## Candidate Selection

### Default mode (no `queue_ids`)

All queue entries where `slot <= now` and effective `status` is `"pending"` are
selected, in store insertion order.

### `queue_ids` mode (manual override)

When `queue_ids` is provided:
- Entries are processed in the order given by `queue_ids`, regardless of `slot` value.
- The slot-time filter is **not applied**. This is an intentional operator override
  (e.g. replaying a specific entry, testing against a real platform).
- Entries absent from the store yield `outcome: "not_found"`.
- Idempotency and `retry_failed` logic still applies to found entries.

`queue_ids` mode and default slot-filtering are mutually exclusive.

---

## Processing Order (per call)

1. Parse `now` and `timestamp`.
2. Read queue store → `QUEUE_STORE_ERROR` on invalid JSON.
3. Determine candidates (default or `queue_ids` mode).
4. For each candidate in order:
   - `status == "posted"` → `already_posted`; skip.
   - `status == "failed"` and `retry_failed == false` → `already_failed`; skip.
   - `dry_run == true` → `dry_run`; skip.
   - Call adapter; catch any exception.
   - **Write queue entry atomically (step 1 of side effects).**
   - **Attempt approval state transition (step 2 of side effects).**
   - Append per-entry result.
5. Return top-level summary.

---

## Outputs

### Top-level success

```json
{
  "success": true,
  "now": "2026-03-25T09:30:00+00:00",
  "dry_run": false,
  "processed": 2,
  "posted": 1,
  "failed": 1,
  "already_posted": 0,
  "already_failed": 0,
  "results": [...]
}
```

`processed` is the total number of entries in `results` (including `not_found` and
`dry_run` outcomes). `posted`, `failed`, `already_posted`, `already_failed` are
sub-counts.

### Per-entry result — posted

```json
{
  "queue_id":          "q_abc12345",
  "post_id":           "post_001",
  "platform":          "twitter",
  "slot":              "2026-03-25T09:00:00+00:00",
  "outcome":           "posted",
  "posted_at":         "2026-03-25T09:30:00+00:00",
  "platform_post_id":  "tweet_789",
  "platform_response": null
}
```

### Per-entry result — failed

```json
{
  "queue_id":   "q_def67890",
  "post_id":    "post_002",
  "platform":   "linkedin",
  "slot":       "2026-03-25T09:15:00+00:00",
  "outcome":    "failed",
  "failed_at":  "2026-03-25T09:30:00+00:00",
  "error_code": "ADAPTER_ERROR",
  "message":    "Connection refused"
}
```

### Per-entry result — already posted

```json
{
  "queue_id":  "q_abc12345",
  "post_id":   "post_001",
  "platform":  "twitter",
  "slot":      "2026-03-25T09:00:00+00:00",
  "outcome":   "already_posted",
  "posted_at": "2026-03-25T09:30:00+00:00"
}
```

### Per-entry result — dry run

```json
{
  "queue_id": "q_abc12345",
  "post_id":  "post_001",
  "platform": "twitter",
  "slot":     "2026-03-25T09:00:00+00:00",
  "outcome":  "dry_run"
}
```

### Per-entry result — not found

```json
{ "queue_id": "q_missing", "outcome": "not_found" }
```

### Top-level failure (system error)

```json
{
  "success":    false,
  "error_code": "QUEUE_STORE_ERROR",
  "message":    "Store file 'data/queue.json' is not valid JSON: ..."
}
```

---

## Error Codes

### Top-level

| Code | Trigger |
|---|---|
| `QUEUE_STORE_ERROR` | Queue store file unreadable or invalid JSON |

### Per-entry `error_code` (within `outcome: "failed"` results)

| Code | Source |
|---|---|
| Any string | Passed through from the adapter's `error_code` field |
| `ADAPTER_EXCEPTION` | Adapter raised an exception; message is the exception string |

---

## Side Effects

For each entry that reaches the delivery step, in fixed order:

**Step 1 — write queue entry atomically.**
The entry's `status` and result fields are written to the queue store via temp-file
+ `os.replace` before the state transition is attempted.

**Step 2 — attempt approval state transition.**
`manage_approval_state` is called to advance the post:
- Adapter success → `scheduled → posted`
- Adapter failure → `scheduled → failed`

### Transition failure handling

If step 2 fails after step 1 completes:
- The queue write is **not rolled back**.
- The per-entry result includes `"state_transition_warning": "<message>"`.
- The entry is still counted as `posted`/`failed` in the summary.
- The top-level `success` remains `true`.

`dry_run=True` skips both steps.

### Queue store fields written on success

```json
{
  "status":            "posted",
  "posted_at":         "<timestamp>",
  "platform_post_id":  "<id or null>",
  "platform_response": "<dict or null>"
}
```

### Queue store fields written on failure

```json
{
  "status":        "failed",
  "failed_at":     "<timestamp>",
  "error_code":    "<from adapter or ADAPTER_EXCEPTION>",
  "error_message": "<from adapter or exception str>"
}
```

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| Entry has no `status` field (legacy from `schedule_post`) | Treated as `"pending"`; eligible for delivery |
| Adapter raises an exception | Caught; entry recorded as `failed` with `error_code: ADAPTER_EXCEPTION` |
| State is not `scheduled` when transition is attempted (race) | Queue write stands; `state_transition_warning` added to per-entry result |
| `queue_ids` entry has `slot > now` | Processed (override mode bypasses slot check) |
| Same entry run twice after success | Second call returns `already_posted`; adapter not called |
| `retry_failed=true` on a failed entry | Adapter is called again; outcome depends on adapter result |
| Queue store file does not exist | Treated as empty queue; returns `success: true`, 0 processed |
| Entry has unparseable `slot` in default mode | Entry is silently skipped (slot comparison impossible) |

---

## Where It Fits in the Workflow

**Position: Step 7 — final step; drives posts from queue to platform.**

```
[schedule-post]  →  (queue)  →  [publish-post]  →  scheduled → posted / failed
```

---

## Usage

### CLI (stub adapter — no real delivery)

```bash
echo '{
  "queue_store_path": "data/queue.json",
  "approval_store_path": "data/approval_states.json"
}' | python -m tools.publish_post.publish_post
# exits 0 on success, 1 on system error
```

### Library (inject a real or mock adapter)

```python
from tools.publish_post import publish_post

def my_twitter_adapter(entry):
    # post to Twitter, return result dict
    return {"success": True, "platform_post_id": "tweet_123", "platform_response": None}

result = publish_post(
    {
        "queue_store_path": "data/queue.json",
        "approval_store_path": "data/approval_states.json",
    },
    _adapter=my_twitter_adapter,
)
```
