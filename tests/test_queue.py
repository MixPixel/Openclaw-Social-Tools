"""Tests for the JSON file-backed queue."""

import json
import pytest

import openclaw.queue as q


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    """Point the queue at a temp file for each test."""
    monkeypatch.setenv("OPENCLAW_QUEUE_FILE", str(tmp_path / "queue.json"))


class TestEnqueue:
    def test_creates_pending_job(self):
        job_id = q.enqueue("linkedin", "Hello")
        jobs = q.list_pending()
        assert len(jobs) == 1
        assert jobs[0]["id"] == job_id
        assert jobs[0]["status"] == "pending"
        assert jobs[0]["text"] == "Hello"
        assert jobs[0]["platform"] == "linkedin"

    def test_returns_unique_ids(self):
        ids = {q.enqueue("linkedin", f"post {i}") for i in range(5)}
        assert len(ids) == 5

    def test_multiple_jobs_accumulate(self):
        q.enqueue("linkedin", "a")
        q.enqueue("linkedin", "b")
        assert len(q.list_pending()) == 2


class TestMarkDone:
    def test_sets_status_to_done(self):
        job_id = q.enqueue("linkedin", "Hello")
        q.mark_done(job_id, "urn:li:share:999")
        assert len(q.list_pending()) == 0

    def test_records_post_id(self):
        job_id = q.enqueue("linkedin", "Hello")
        q.mark_done(job_id, "urn:li:share:999")
        path = q._queue_path()
        items = json.loads(path.read_text())
        job = next(i for i in items if i["id"] == job_id)
        assert job["post_id"] == "urn:li:share:999"
        assert "completed_at" in job

    def test_does_not_affect_other_jobs(self):
        id_a = q.enqueue("linkedin", "a")
        id_b = q.enqueue("linkedin", "b")
        q.mark_done(id_a, "x")
        pending = q.list_pending()
        assert len(pending) == 1
        assert pending[0]["id"] == id_b


class TestMarkFailed:
    def test_sets_status_to_failed(self):
        job_id = q.enqueue("linkedin", "Hello")
        q.mark_failed(job_id, "401 Unauthorized")
        assert len(q.list_pending()) == 0

    def test_records_error(self):
        job_id = q.enqueue("linkedin", "Hello")
        q.mark_failed(job_id, "some error")
        path = q._queue_path()
        items = json.loads(path.read_text())
        job = next(i for i in items if i["id"] == job_id)
        assert job["error"] == "some error"
        assert "failed_at" in job


class TestListPending:
    def test_excludes_done_and_failed(self):
        id_pending = q.enqueue("linkedin", "p")
        id_done = q.enqueue("linkedin", "d")
        id_failed = q.enqueue("linkedin", "f")
        q.mark_done(id_done, "x")
        q.mark_failed(id_failed, "err")
        pending = q.list_pending()
        assert len(pending) == 1
        assert pending[0]["id"] == id_pending

    def test_empty_queue_returns_empty_list(self):
        assert q.list_pending() == []
