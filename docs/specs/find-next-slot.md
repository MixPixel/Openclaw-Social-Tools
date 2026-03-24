# Tool Spec: find-next-slot

## Purpose

Given a schedule configuration and a reference datetime, returns the next available posting slot for a given platform. Read-only — it does not claim or reserve the slot.

---

## Why It Exists

Deciding *when* to post involves rules (frequency limits, time windows, platform-specific best-times) that are entirely deterministic once the config is defined. There is no creative judgement involved. Putting this logic in a standalone tool means:

- It can be called to *preview* available slots without side effects
- It can be tested exhaustively without an LLM
- `schedule-post` can call it to find a slot and then claim it in one atomic step

---

## Inputs

| Field | Type | Required | Description |
|---|---|---|---|
| `platform` | enum | yes | Target platform: `twitter`, `linkedin`, `instagram`, `facebook`, `mastodon` |
| `after` | string (ISO 8601) | yes | Find the next slot strictly after this datetime |
| `schedule_config` | object | yes | See schedule config schema below |
| `existing_queue` | list[string] | no | List of already-claimed slot datetimes (ISO 8601). Used to avoid conflicts |

### Schedule Config Schema

```json
{
  "timezone": "Europe/London",
  "allowed_windows": [
    { "days": ["mon", "tue", "wed", "thu", "fri"], "start": "09:00", "end": "12:00" },
    { "days": ["mon", "wed", "fri"], "start": "17:00", "end": "19:00" }
  ],
  "min_gap_minutes": 120,
  "max_per_day": 2,
  "blackout_dates": ["2026-12-25", "2026-01-01"],
  "slot_resolution_minutes": 15
}
```

| Config Field | Type | Description |
|---|---|---|
| `timezone` | string (IANA) | All window times are interpreted in this timezone |
| `allowed_windows` | list[object] | Time windows in which posting is permitted |
| `min_gap_minutes` | integer | Minimum minutes between any two posts on this platform |
| `max_per_day` | integer | Maximum posts per calendar day (in `timezone`) |
| `blackout_dates` | list[string] | Dates on which no posts should be scheduled (YYYY-MM-DD) |
| `slot_resolution_minutes` | integer | Slots are rounded to this interval (e.g. 15 = slots at :00, :15, :30, :45) |

---

## Outputs

### Slot found

```json
{
  "available": true,
  "slot": "2026-03-25T09:15:00+00:00",
  "platform": "linkedin",
  "timezone": "Europe/London",
  "local_time": "2026-03-25T09:15:00+00:00"
}
```

### No slot available

```json
{
  "available": false,
  "platform": "linkedin",
  "reason_code": "NO_WINDOW_IN_RANGE",
  "message": "No allowed posting window found within the next 7 days.",
  "search_range_end": "2026-03-31T23:59:59Z"
}
```

---

## Reason Codes (when `available: false`)

| Code | Description |
|---|---|
| `NO_WINDOW_IN_RANGE` | No allowed time window exists in the lookahead period |
| `BLACKOUT_COVERS_RANGE` | All available windows are blocked by blackout dates |
| `DAILY_LIMIT_REACHED` | `max_per_day` is already reached for every day with available windows |
| `GAP_CONSTRAINT_UNMET` | Existing queue posts are too close together to fit a new slot |
| `INVALID_CONFIG` | Schedule config is malformed (details in `message`) |

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| `after` is in the middle of an allowed window | Returns the next slot at or after `after` within that window, rounded up to `slot_resolution_minutes` |
| `after` is in a timezone with DST transition | Uses IANA timezone database; handles DST correctly |
| `existing_queue` has slots outside allowed windows | These are respected for gap calculation but do not cause errors |
| `allowed_windows` is empty | Return `INVALID_CONFIG` |
| `min_gap_minutes` is larger than any window duration | Return `INVALID_CONFIG` with explanation |
| `blackout_dates` covers all days in the lookahead | Return `BLACKOUT_COVERS_RANGE` |
| Overlapping `allowed_windows` | Merge overlapping windows before slot search; do not return duplicate slots |
| `slot_resolution_minutes` is 0 or negative | Return `INVALID_CONFIG` |
| Multiple platforms in one call | Not supported; call once per platform |

---

## Lookahead Limit

The tool searches forward up to **14 days** from `after` by default. If no slot is found within that range, it returns `available: false`. This limit prevents infinite loops when config is very restrictive.

---

## Where It Fits in the Workflow

**Position: Step 5 — after approval, before scheduling.**

```
[approval-state-manager: approved]  →  [find-next-slot]  →  [schedule-post]
```

`find-next-slot` is read-only. It does not mark any slot as taken. The slot only becomes claimed when `schedule-post` writes to the queue. For concurrent workflows, `schedule-post` should call `find-next-slot` internally and handle the case where the slot was taken between the two calls.
