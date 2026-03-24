# Tool Spec: find-next-slot

## Purpose

Given a schedule configuration and a reference datetime, returns the next available posting slot. Read-only — it does not claim or reserve the slot.

---

## Why It Exists

Deciding *when* to post involves rules (frequency limits, time windows, blackout dates) that are entirely deterministic once the config is defined. There is no creative judgement involved. Putting this logic in a standalone tool means:

- It can be called to *preview* available slots without side effects
- It can be tested exhaustively without an LLM
- `schedule-post` can call it to find a slot and then claim it in one atomic step

---

## Implementation

`tools/find_next_slot/find_next_slot.py` — stdlib only (`zoneinfo`, Python 3.9+).

---

## Inputs

| Field | Type | Required | Description |
|---|---|---|---|
| `platform` | string | yes | Target platform — echoed to output, not used in scheduling logic |
| `after` | string (ISO 8601) | yes | Find the next slot *strictly after* this datetime |
| `schedule_config` | object | yes | See schedule config schema below |
| `existing_queue` | list[string] | no | Already-claimed slot datetimes (ISO 8601). Used for gap and daily-cap checks |

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

| Config Field | Type | Default | Description |
|---|---|---|---|
| `timezone` | string (IANA) | `"UTC"` | All window times and day boundaries are interpreted in this timezone |
| `allowed_windows` | list[object] | — | **Required.** Time windows in which posting is permitted |
| `min_gap_minutes` | integer | `60` | Minimum minutes between any two posts |
| `max_per_day` | integer | `8` | Maximum posts per calendar day (in `timezone`) |
| `blackout_dates` | list[YYYY-MM-DD] | `[]` | Dates on which no posts should be scheduled |
| `slot_resolution_minutes` | integer | `15` | Slots snap to this interval (e.g. 15 → :00, :15, :30, :45) |

#### allowed_windows entries

| Field | Type | Required | Description |
|---|---|---|---|
| `start` | `"HH:MM"` | yes | Window open time (inclusive) |
| `end` | `"HH:MM"` | yes | Window close time (exclusive) |
| `days` | list[string] | no | Weekdays this window applies to. Omit for every day. Values: `"mon"` `"tue"` `"wed"` `"thu"` `"fri"` `"sat"` `"sun"` (case-insensitive) |

---

## Outputs

Both responses are explicit, flat JSON objects.

### Slot found

```json
{
  "available": true,
  "slot":       "2026-03-25T09:15:00+00:00",
  "local_time": "2026-03-25T10:15:00+01:00",
  "platform":   "linkedin",
  "timezone":   "Europe/Berlin"
}
```

`slot` is always in UTC with an explicit `+00:00` offset.
`local_time` is the same instant in the configured timezone (differs from `slot` for non-UTC zones).

### No slot available

```json
{
  "available":        false,
  "platform":         "linkedin",
  "reason_code":      "NO_WINDOW_IN_RANGE",
  "message":          "No allowed posting window found within 14 days.",
  "search_range_end": "2026-04-07T14:00:00+00:00"
}
```

### Naive datetime flag

When `after` has no timezone info, the tool treats it as UTC and adds a flag:

```json
{
  "available":   true,
  "slot":        "2026-03-25T09:15:00+00:00",
  "local_time":  "2026-03-25T09:15:00+00:00",
  "platform":    "twitter",
  "timezone":    "UTC",
  "assumed_utc": true
}
```

This is a warning, not a failure. The tool continues normally.

---

## Reason Codes

### When `available: false`

| Code | Description |
|---|---|
| `NO_WINDOW_IN_RANGE` | No allowed time window found in the lookahead period |
| `BLACKOUT_COVERS_RANGE` | All available days are blocked by blackout dates |
| `DAILY_LIMIT_REACHED` | `max_per_day` already reached for every eligible day |
| `GAP_CONSTRAINT_UNMET` | Existing queue entries leave no gap of `min_gap_minutes` within the lookahead |
| `INVALID_CONFIG` | Schedule config is malformed (details in `message`); `search_range_end` absent |

### INVALID_CONFIG triggers

- `allowed_windows` is missing or empty
- `slot_resolution_minutes` ≤ 0
- `max_per_day` ≤ 0
- `min_gap_minutes` < 0
- `min_gap_minutes` exceeds any individual window's duration
- `timezone` is not a valid IANA key
- A `blackout_dates` entry is not a valid YYYY-MM-DD string
- A window has `end` ≤ `start`
- An `existing_queue` entry cannot be parsed as ISO 8601
- `after` cannot be parsed as ISO 8601

---

## Scheduling Algorithm

1. Parse `after` → timezone-aware datetime (naive input assumed UTC, sets `assumed_utc: true`).
2. Compute first candidate: next `slot_resolution_minutes` boundary **strictly after** `after`.
3. Merge overlapping `allowed_windows` entries per weekday.
4. Search forward up to **14 days**, advancing the candidate at each step:

   | Check | On failure | Reason code set |
   |---|---|---|
   | Date is a blackout date | Jump to midnight of next day | `BLACKOUT_COVERS_RANGE` |
   | Local time is outside all windows for that weekday | Jump to next window open, or next day if none remain | `NO_WINDOW_IN_RANGE` |
   | Day has `max_per_day` posts in `existing_queue` | Jump to midnight of next day | `DAILY_LIMIT_REACHED` |
   | Candidate is within `min_gap_minutes` of any queue entry | Jump past the farthest violating entry + `min_gap_minutes`, round up to next slot | `GAP_CONSTRAINT_UNMET` |

5. First candidate that passes all four checks is returned as `slot`.
6. If no candidate found within 14 days, return `available: false`.

The gap check uses absolute distance: `|candidate − queued_post| < min_gap_minutes`. This prevents inserting a post too close to one in either direction.

Slots are aligned to `slot_resolution_minutes` boundaries from the Unix epoch (UTC midnight on 1970-01-01). For common resolutions (15, 30, 60 min) and common IANA timezone offsets (multiples of 15 min), local window start times will naturally fall on slot boundaries.

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| `after` is in the middle of an allowed window | Returns the next slot boundary strictly after `after` within that window |
| `after` falls exactly on a slot boundary | Advances to the *next* boundary (slot is always strictly after `after`) |
| `after` is outside all windows | Advances to the start of the next window |
| `after` has no timezone info | Treated as UTC; `assumed_utc: true` added to output |
| DST "spring forward" gap hour | `zoneinfo` handles correctly; no slot is generated in the missing hour |
| DST "fall back" ambiguous hour | `zoneinfo` uses first occurrence (`fold=0`); tool continues without error |
| Overlapping `allowed_windows` entries | Merged before search; continuous slot range returned |
| `allowed_windows` entry with no `days` | Applied to every day of the week |
| `existing_queue` entries outside windows | Still respected for gap and daily-cap calculations |
| `min_gap_minutes = 0` | Gap constraint always passes; posts may be immediately adjacent |
| `min_gap_minutes` ≥ window duration | `INVALID_CONFIG` — no post can ever satisfy both constraints |
| Two queue entries leave a gap < `min_gap_minutes * 2` | No third post fits between them; search advances past both |
| `blackout_dates` covers all days in lookahead | `available: false` with `BLACKOUT_COVERS_RANGE` |
| Multiple constraints fail on different days | `reason_code` reflects the last constraint that blocked a candidate |
| Multiple platforms | Not supported in a single call; call once per platform |

---

## Lookahead Limit

The tool searches forward up to **14 days** from `after`. If no slot is found within that range, it returns `available: false` and `search_range_end` (the UTC datetime at the end of the search window). This prevents infinite loops when config is very restrictive.

---

## CLI Usage

```bash
# Exits 0 when a slot is found, 1 when none found or on error
echo '{
  "platform": "linkedin",
  "after": "2026-03-24T08:00:00Z",
  "schedule_config": {
    "timezone": "Europe/London",
    "allowed_windows": [
      {"days": ["mon","tue","wed","thu","fri"], "start": "09:00", "end": "12:00"}
    ],
    "min_gap_minutes": 120,
    "max_per_day": 2,
    "slot_resolution_minutes": 15
  },
  "existing_queue": ["2026-03-24T09:00:00Z"]
}' | python -m tools.find_next_slot.find_next_slot
```

## Library Usage

```python
from tools.find_next_slot import find_next_slot

result = find_next_slot({
    "platform": "linkedin",
    "after": "2026-03-24T08:00:00Z",
    "schedule_config": {
        "timezone": "Europe/London",
        "allowed_windows": [
            {"days": ["mon","tue","wed","thu","fri"], "start": "09:00", "end": "12:00"}
        ],
        "min_gap_minutes": 120,
        "max_per_day": 2,
        "slot_resolution_minutes": 15,
    },
    "existing_queue": ["2026-03-24T09:00:00Z"],
})

if result["available"]:
    print(f"Post at {result['slot']} ({result['local_time']} local)")
else:
    print(f"No slot: {result['reason_code']} — {result['message']}")
```

---

## Where It Fits in the Workflow

**Position: Step 5 — after approval, before scheduling.**

```
[approval-state-manager: approved]  →  [find-next-slot]  →  [schedule-post]
```

`find-next-slot` is read-only. It does not mark any slot as taken. The slot only becomes claimed when `schedule-post` writes to the queue. For concurrent workflows, `schedule-post` should call `find-next-slot` internally and handle the case where the slot was taken between the two calls.
