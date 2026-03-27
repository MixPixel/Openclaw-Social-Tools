"""publish_history — append-only publish run log.

Writes one JSON line per publish attempt to a JSONL file and reads
entries back for inspection.  Both the immediate pipeline path and the
queue-based publish_post path call this module.

File format: newline-delimited JSON (JSONL).  Each line is one complete
JSON object.  Lines are written in chronological order.  Malformed lines
produced by incomplete writes are silently skipped on read.

Public API
----------
  append_entry(entry, *, log_path=DEFAULT_LOG_PATH) -> None
      Append one log entry dict to the JSONL file.  Creates the file and
      any parent directories if they do not exist.  Adds 'log_id' (uuid4)
      and 'logged_at' (ISO 8601 UTC) if the caller omits them.

  read_log(*, log_path=DEFAULT_LOG_PATH, limit=None) -> list[dict]
      Return log entries in chronological order (oldest first).
      Returns [] if the file does not exist.  Skips malformed lines.
      Pass limit=N to return only the last N entries.

Log entry shapes
----------------
  Common fields (all sources):
    log_id      str    uuid4
    logged_at   str    ISO 8601 UTC
    source      str    "pipeline" or "queue"
    dry_run     bool
    platform    str    canonical platform id, e.g. "twitter"
    success     bool

  source == "pipeline":
    post_id         str | None
    character_count int | None
    media_count     int
    error_code      str | None

  source == "queue":
    queue_id         str
    post_id          str
    slot             str
    outcome          str   e.g. "posted", "failed", "dry_run"
    platform_post_id str | None
    error_code       str | None
"""

import json
import os
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LOG_PATH = "data/publish_log.jsonl"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_entry(entry: dict, *, log_path: str = DEFAULT_LOG_PATH) -> None:
    """Append one log entry to the JSONL file.

    Creates the log file and any missing parent directories.  Adds
    'log_id' (uuid4) and 'logged_at' (ISO 8601 UTC) to the written
    record if the caller did not supply them.

    Args:
        entry:    Dict of fields to record.  Must be JSON-serialisable.
        log_path: Path to the JSONL file.  Defaults to
                  data/publish_log.jsonl relative to the working directory.
    """
    record = dict(entry)
    if "log_id" not in record:
        record["log_id"] = str(uuid.uuid4())
    if "logged_at" not in record:
        record["logged_at"] = datetime.now(timezone.utc).isoformat()

    abs_path = os.path.abspath(log_path)
    dir_ = os.path.dirname(abs_path)
    if dir_:
        os.makedirs(dir_, exist_ok=True)

    with open(abs_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def read_log(
    *,
    log_path: str = DEFAULT_LOG_PATH,
    limit: int | None = None,
) -> list[dict]:
    """Return log entries in chronological order (oldest first).

    Args:
        log_path: Path to the JSONL file.
        limit:    If given, return only the last N entries.

    Returns:
        List of log entry dicts.  Empty list if the file does not exist.
        Malformed (non-JSON) lines are silently skipped.
    """
    try:
        with open(log_path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return []

    entries: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # skip malformed lines

    if limit is not None:
        return entries[-limit:]
    return entries
