# Tool Spec: schedule-post

## Purpose

Writes an approved post to the scheduling queue at a specified slot, verifying all
preconditions before claiming the slot. Returns a queue ID and confirmation, or a
structured error if any precondition fails.

---

## Why It Exists

Scheduling is a write operation with real consequences — it claims a slot and commits
a post to delivery. Separating it from slot-finding (`find-next-slot`) means:

- Slot previewing has no side effects
- The write step has one clear responsibility with a defined precondition checklist
- Errors at write time (slot taken, post not approved) are caught before anything is
  sent to the platform

This tool is the last gate before platform delivery. It should be conservative and
explicit about failures.

---

## Inputs

| Field | Type | Required | Description |
|---|---|---|---|
| `post_id` | string | yes | ID of the post to schedule (must be in `approved` state) |
| `content` | string | yes | Final post body text |
| `platform` | enum | yes | Target platform: `twitter`, `linkedin`, `instagram`, `facebook`, `mastodon` (aliases accepted) |
| `actor` | string | yes | Who or what is scheduling this post |
| `schedule_config` | object | yes | Same config schema as `find-next-slot`; used to validate the slot and, when `slot` is omitted, to find the next available one |
| `slot` | string (ISO 8601) | **no** | Datetime to schedule at. If omitted, `find-next-slot` is called internally to find the next available slot |
| `media` | list[object] | no | Attached media: `{ type, url_or_path, alt_text? }` |
| `approval_store_path` | string | no | Path to approval state store. Defaults to `data/approval_states.json` |
| `queue_store_path` | string | no | Path to the queue store. Defaults to `data/queue.json` |
| `now` | string (ISO 8601) | no | Inject current time (for testing). Defaults to `datetime.now(UTC)` |
| `timestamp` | string (ISO 8601) | no | Inject `created_at` for the queue record (for testing). Defaults to `now` |
| `queue_id` | string | no | Inject a specific queue ID (for testing). If omitted, generated from `sha256(post_id:slot)[:8]` |

---

## Precondition Checks (in order)

Before writing to the queue, the tool verifies:

1. **Required fields present** — `post_id`, `content`, `platform`, `actor`, `schedule_config`
2. **Platform recognised** — platform alias resolves to a known canonical platform
3. **Post exists** — `post_id` resolves to a known post in the approval store
4. **Post is approved** — `approval-state-manager` confirms state is `approved`
5. **Slot determination:**
   - If `slot` provided:
     - **a. Slot is in the future** — `slot` is strictly after `now`
     - **b. Slot is within an allowed window** — falls inside a `schedule_config` allowed window
     - **c. Slot is not a blackout date** — slot date is not in `blackout_dates`
     - **d. Slot is not already taken** — no other post is queued within `min_gap_minutes` of `slot`
   - If `slot` omitted:
     - **e. Call `find-next-slot`** — if it returns `available: false`, fail with `NO_SLOT_AVAILABLE`
6. **Content passes validation** — re-runs `validate-post` on `(content, platform, media)`
7. **Media items resolvable** — each media item has a non-empty `url_or_path`

If any check fails, the tool returns immediately with the relevant error code. It does
not proceed to subsequent checks after the first failure.

Conflict threshold: `abs(slot − existing_slot) < min_gap_minutes` (strictly less than;
consistent with `find-next-slot`'s own gap check so a slot returned by that tool is
always valid here).

---

## Outputs

### Success

```json
{
  "success": true,
  "queue_id": "q_a1b2c3d4",
  "post_id": "post_abc123",
  "platform": "linkedin",
  "slot": "2026-03-25T09:15:00+00:00",
  "slot_source": "provided",
  "actor": "scheduler@example.com",
  "created_at": "2026-03-24T15:00:00+00:00",
  "warnings": []
}
```

`slot_source` is `"provided"` when the caller supplied the slot, `"auto"` when
`find-next-slot` was called internally.

`warnings` is always present. Current warning codes:

| Code | Description |
|---|---|
| `NO_ALT_TEXT` | An image media item has no `alt_text`. Scheduling proceeds. |

### Failure

```json
{
  "success": false,
  "post_id": "post_abc123",
  "error_code": "SLOT_CONFLICT",
  "message": "Slot 2026-03-25T09:15:00Z conflicts with post q_z9y8x7w6 scheduled at 2026-03-25T09:00:00Z (gap: 15 min, minimum: 120 min).",
  "conflicting_queue_id": "q_z9y8x7w6"
}
```

---

## Error Codes

| Code | Description | Extra fields |
|---|---|---|
| `MISSING_REQUIRED_FIELD` | A required input field is absent | — |
| `PLATFORM_NOT_SUPPORTED` | Platform value is not recognised | — |
| `POST_NOT_FOUND` | No post found with the given `post_id` | — |
| `POST_NOT_APPROVED` | Post is not in `approved` state | `actual_state` |
| `SLOT_IN_PAST` | The requested slot datetime has already passed | — |
| `SLOT_OUTSIDE_WINDOW` | Slot does not fall within any allowed posting window | — |
| `SLOT_ON_BLACKOUT_DATE` | Slot date is listed in `blackout_dates` | — |
| `SLOT_CONFLICT` | Another post is queued too close to this slot | `conflicting_queue_id` |
| `NO_SLOT_AVAILABLE` | `slot` was omitted and `find-next-slot` found no available slot | `find_next_slot_reason` |
| `VALIDATION_FAILED` | Re-validation of content failed | `validation_errors` |
| `MEDIA_UNAVAILABLE` | A media item has a missing or empty `url_or_path` | — |
| `STATE_TRANSITION_FAILED` | Queue write succeeded but state transition failed (rare race) | `queue_id` |

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| Slot taken between `find-next-slot` and `schedule-post` (race condition) | Returns `SLOT_CONFLICT`; caller should call `find-next-slot` again |
| Same post scheduled twice | Second call returns `POST_NOT_APPROVED` — after first scheduling, state is `scheduled` |
| `actor` is a system identifier | Accepted and stored as-is |
| `content` in input differs from any stored draft | No check performed; tool uses the provided `content` field |
| Slot at exactly `min_gap_minutes` from another | **Allowed** (`< min_gap`, not `<=`); consistent with `find-next-slot` |
| Media alt text omitted for image | `NO_ALT_TEXT` warning added to response; scheduling proceeds |
| Platform delivery system unavailable | Tool writes to queue only; delivery is out of scope |
| `slot` omitted, no windows configured | `find-next-slot` returns `INVALID_CONFIG`; this tool returns `NO_SLOT_AVAILABLE` |

---

## Side Effects

On success, this tool:

1. Writes a queue record to `queue_store_path` with `queue_id`, `post_id`, `content`,
   `platform`, `slot`, `media`, `actor`, and `created_at`
2. Calls `approval-state-manager` to transition the post from `approved` → `scheduled`

On failure, no write occurs and no state is changed, **except** for `STATE_TRANSITION_FAILED`
where the queue record has been written but the state transition failed. The `queue_id` is
included in the error so the caller can investigate or clean up.

---

## Queue Store Format

```json
{
  "q_a1b2c3d4": {
    "queue_id":   "q_a1b2c3d4",
    "post_id":    "post_abc123",
    "platform":   "linkedin",
    "content":    "Hello world! Sign up now.",
    "slot":       "2026-03-25T09:15:00+00:00",
    "media":      [],
    "actor":      "scheduler@example.com",
    "created_at": "2026-03-24T15:00:00+00:00"
  }
}
```

Keyed by `queue_id`. Written atomically via temp-file + `os.replace`.

---

## Where It Fits in the Workflow

**Position: Step 6 — final step before platform delivery.**

```
[find-next-slot]  →  [schedule-post]  →  (queue)  →  (platform delivery)
```

This is the last tool in the deterministic pipeline. After a post is scheduled, it is
picked up by the delivery layer (outside the scope of this toolset) at the appointed time.

---

## Usage

### Library

```python
from tools.schedule_post import schedule_post

result = schedule_post({
    "post_id":   "post_abc123",
    "platform":  "linkedin",
    "content":   "Hello world! Sign up now.",
    "actor":     "scheduler@example.com",
    "slot":      "2026-03-25T09:15:00Z",
    "schedule_config": {
        "timezone": "Europe/London",
        "allowed_windows": [
            {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "09:00", "end": "17:00"}
        ],
        "min_gap_minutes": 60,
    },
})
```

### CLI

```bash
echo '{
  "post_id": "post_abc123",
  "platform": "linkedin",
  "content": "Hello world!",
  "actor": "scheduler@example.com",
  "slot": "2026-03-25T09:15:00Z",
  "schedule_config": { ... }
}' | python -m tools.schedule_post.schedule_post
# exits 0 on success, 1 on failure
```
