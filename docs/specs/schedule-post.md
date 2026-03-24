# Tool Spec: schedule-post

## Purpose

Writes an approved post to the scheduling queue at a specified slot, verifying all preconditions before claiming the slot. Returns a queue ID and confirmation, or a structured error if any precondition fails.

---

## Why It Exists

Scheduling is a write operation with real consequences — it claims a slot and commits a post to delivery. Separating it from slot-finding (`find-next-slot`) means:

- Slot previewing has no side effects
- The write step has one clear responsibility with a defined precondition checklist
- Errors at write time (slot taken, post not approved) are caught before anything is sent to the platform

This tool is the last gate before platform delivery. It should be conservative and explicit about failures.

---

## Inputs

| Field | Type | Required | Description |
|---|---|---|---|
| `post_id` | string | yes | ID of the post to schedule (must be in `approved` state) |
| `content` | string | yes | Final post body text |
| `platform` | enum | yes | Target platform: `twitter`, `linkedin`, `instagram`, `facebook`, `mastodon` |
| `slot` | string (ISO 8601) | yes | The datetime to schedule the post at |
| `media` | list[object] | no | Attached media: `{ type, url_or_path, alt_text? }` |
| `schedule_config` | object | yes | Same config schema as `find-next-slot`; used to validate the slot |
| `actor` | string | yes | Who or what is scheduling this post |

---

## Precondition Checks (in order)

Before writing to the queue, the tool verifies:

1. **Post exists** — `post_id` resolves to a known post
2. **Post is approved** — `approval-state-manager` confirms state is `approved`
3. **Slot is in the future** — `slot` is strictly after the current UTC time
4. **Slot is within an allowed window** — `slot` falls inside a `schedule_config` allowed window
5. **Slot is not a blackout date** — `slot` date is not in `blackout_dates`
6. **Slot is not already taken** — no other post is queued within `min_gap_minutes` of `slot`
7. **Content passes validation** — re-runs `validate-post` as a final check (uses cached result if available within 5 minutes)

If any check fails, the tool returns immediately with the relevant error code. It does not proceed to subsequent checks after the first failure.

---

## Outputs

### Success

```json
{
  "success": true,
  "queue_id": "q_a1b2c3d4",
  "post_id": "post_abc123",
  "platform": "linkedin",
  "scheduled_at": "2026-03-25T09:15:00+00:00",
  "actor": "scheduler@example.com",
  "confirmation_timestamp": "2026-03-24T15:00:00Z"
}
```

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

| Code | Description |
|---|---|
| `POST_NOT_FOUND` | No post found with the given `post_id` |
| `POST_NOT_APPROVED` | Post is not in `approved` state |
| `SLOT_IN_PAST` | The requested slot datetime has already passed |
| `SLOT_OUTSIDE_WINDOW` | Slot does not fall within any allowed posting window |
| `SLOT_ON_BLACKOUT_DATE` | Slot date is listed in `blackout_dates` |
| `SLOT_CONFLICT` | Another post is queued too close to this slot |
| `VALIDATION_FAILED` | Re-validation of content failed; includes `errors` sub-array |
| `PLATFORM_NOT_SUPPORTED` | Platform value is not recognised |
| `MEDIA_UNAVAILABLE` | A media attachment URL or path cannot be resolved |

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| Slot taken between `find-next-slot` and `schedule-post` (race condition) | Returns `SLOT_CONFLICT`; caller should call `find-next-slot` again to get a fresh slot |
| `actor` is a system identifier rather than a user | Accepted; stored in queue record and audit log as-is |
| Same post scheduled twice | Second call returns `POST_NOT_APPROVED` — after first scheduling, `approval-state-manager` transitions state to `scheduled` |
| `content` in input differs from stored post content | Tool uses the `content` field as provided; a warning is logged if it differs from the stored draft, but it is not blocked |
| Slot at exactly `min_gap_minutes` from another | Treat as conflict (gap must be strictly greater than `min_gap_minutes`) |
| Media alt text omitted for image | Allowed; a `NO_ALT_TEXT` warning is added to the response but does not block scheduling |
| Platform delivery system is unavailable | Tool writes to queue only; delivery errors are out of scope |

---

## Side Effects

On success, this tool:

1. Writes a queue record with `queue_id`, `post_id`, `content`, `platform`, `slot`, `media`, `actor`, and `confirmation_timestamp`
2. Calls `approval-state-manager` to transition the post from `approved` → `scheduled`

On failure, no write occurs and no state is changed.

---

## Where It Fits in the Workflow

**Position: Step 6 — final step before platform delivery.**

```
[find-next-slot]  →  [schedule-post]  →  (queue)  →  (platform delivery)
```

This is the last tool in the deterministic pipeline. After a post is scheduled, it is picked up by the delivery layer (outside the scope of this toolset) at the appointed time.
