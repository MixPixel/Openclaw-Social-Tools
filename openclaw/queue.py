"""Simple JSON file-backed queue for deferred social posts.

Queue file location is controlled by the OPENCLAW_QUEUE_FILE env var
(default: queue.json in the current working directory).
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _queue_path() -> Path:
    return Path(os.environ.get("OPENCLAW_QUEUE_FILE", "queue.json"))


def _load() -> list[dict]:
    path = _queue_path()
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _save(items: list[dict]) -> None:
    _queue_path().write_text(json.dumps(items, indent=2))


def enqueue(platform: str, text: str) -> str:
    """Add a pending post to the queue. Returns the new job ID."""
    items = _load()
    job_id = str(uuid.uuid4())
    items.append(
        {
            "id": job_id,
            "platform": platform,
            "text": text,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save(items)
    return job_id


def list_pending() -> list[dict]:
    """Return all jobs with status == 'pending'."""
    return [j for j in _load() if j["status"] == "pending"]


def mark_done(job_id: str, post_id: str) -> None:
    items = _load()
    for item in items:
        if item["id"] == job_id:
            item["status"] = "done"
            item["post_id"] = post_id
            item["completed_at"] = datetime.now(timezone.utc).isoformat()
    _save(items)


def mark_failed(job_id: str, error: str) -> None:
    items = _load()
    for item in items:
        if item["id"] == job_id:
            item["status"] = "failed"
            item["error"] = error
            item["failed_at"] = datetime.now(timezone.utc).isoformat()
    _save(items)
