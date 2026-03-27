# Spec: publish-history

## Purpose

`publish_history` records a minimal structured history of every publish
attempt so a user can inspect what ran, when it ran, whether it was a
dry-run or real delivery, and whether it succeeded or failed.

---

## Problem It Solves

Before this tool:
- `publish_to_platform` and `publish_post` returned rich result dicts
  but wrote no durable record of what happened.
- Restarting a process or closing a terminal lost all run history.
- No way to audit how many posts were sent, to which platform, or which
  failed.

After this tool:
- Every CLI invocation of `publish_to_platform` appends one JSON line to
  `data/publish_log.jsonl`.
- Every queue entry processed by `publish_post` appends one JSON line.
- `read_log()` reads entries back for inspection or scripting.

---

## File Structure

```
tools/publish_history/
    __init__.py          public exports
    publish_history.py   append_entry, read_log
```

---

## Public API

### `append_entry(entry, *, log_path=DEFAULT_LOG_PATH) -> None`

Append one log entry dict to the JSONL file.  Creates the file and any
missing parent directories.  Adds `log_id` (uuid4) and `logged_at`
(ISO 8601 UTC) to the written record if the caller did not supply them.

### `read_log(*, log_path=DEFAULT_LOG_PATH, limit=None) -> list[dict]`

Return log entries in chronological order (oldest first).  Returns `[]`
if the file does not exist.  Silently skips malformed lines.

Pass `limit=N` to return only the last N entries.

### `DEFAULT_LOG_PATH`

`"data/publish_log.jsonl"` — used by both callers and `read_log` when no
explicit path is supplied.

---

## Log File Format

Newline-delimited JSON (JSONL).  Each line is one complete JSON object.
The file is append-only; no line is ever modified or deleted.

---

## Log Entry Shapes

### Common fields (all sources)

| Field       | Type         | Description                              |
|-------------|--------------|------------------------------------------|
| `log_id`    | str (uuid4)  | Unique per entry; auto-generated         |
| `logged_at` | str (ISO UTC)| When the entry was written               |
| `source`    | str          | `"pipeline"` or `"queue"`               |
| `dry_run`   | bool         | True when no network delivery was made   |
| `platform`  | str          | Canonical platform id, e.g. `"twitter"` |
| `success`   | bool         | True for posted / already_posted         |

### source == "pipeline"  (from `publish_to_platform` via CLI)

| Field             | Type         | Description                            |
|-------------------|--------------|----------------------------------------|
| `post_id`         | str \| null  | Platform post ID; null on failure/dry  |
| `character_count` | int \| null  | From content validation                |
| `media_count`     | int          | Number of media items in the post      |
| `error_code`      | str \| null  | First error code on failure            |

### source == "queue"  (from `publish_post`)

| Field              | Type         | Description                           |
|--------------------|--------------|---------------------------------------|
| `queue_id`         | str          | Queue entry identifier                |
| `post_id`          | str          | Content post identifier               |
| `slot`             | str (ISO)    | Scheduled slot datetime               |
| `outcome`          | str          | `"posted"`, `"failed"`, `"dry_run"`, `"already_posted"`, `"already_failed"`, `"not_found"` |
| `platform_post_id` | str \| null  | Returned by the platform adapter      |
| `error_code`       | str \| null  | First error code on failure           |

---

## Wiring

### `publish_pipeline` CLI

`__main__.py` writes one log entry after every `publish_to_platform` call
(whether the result is success or failure).

`--log-file PATH` controls the log path (default: `data/publish_log.jsonl`).
Pass an empty string (`--log-file ""`) to suppress logging.

### `publish_post`

`publish_post()` writes one log entry per queue result (all outcomes
including `dry_run` and `already_posted`) when the `log_path` field is
present in the `data` dict.

Library callers set `log_path` in the data dict to opt into logging.
The `publish_post` CLI sets `log_path` to `data/publish_log.jsonl` by
default.

---

## Failure Handling

Log write failures are non-blocking.  If `append_entry` raises (e.g.
disk full, permission denied):

- The `publish_pipeline` CLI prints a warning to stderr but does not
  change the exit code.
- `publish_post` silently swallows the exception; the publish run result
  is unaffected.

---

## Example Output

```jsonl
{"log_id":"a1b2c3","logged_at":"2026-03-25T10:01:00+00:00","source":"pipeline","dry_run":false,"platform":"twitter","success":true,"post_id":"1234567890","character_count":20,"media_count":0,"error_code":null}
{"log_id":"d4e5f6","logged_at":"2026-03-25T10:02:00+00:00","source":"queue","dry_run":false,"platform":"twitter","success":true,"outcome":"posted","queue_id":"q_abc","post_id":"post_001","slot":"2026-03-25T09:00:00+00:00","platform_post_id":"1234567891","error_code":null}
```

Reading with `read_log`:

```python
from tools.publish_history import read_log

# All entries
entries = read_log()

# Last 10
entries = read_log(limit=10)

# Custom path
entries = read_log(log_path="logs/staging.jsonl")
```

---

## What Is Not in This Contract

- Log rotation or archival — the file grows indefinitely.
- Log levels or severity — every attempt is written at the same level.
- Structured querying — use standard shell tools (`grep`, `jq`) or read
  into Python for filtering.
- Remote logging — local file only.
