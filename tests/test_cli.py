"""Tests for the CLI command routing."""

import pytest
from unittest.mock import MagicMock, patch

from openclaw.adapters.base import PostResult
from openclaw.cli import build_parser, cmd_post, cmd_queue, cmd_run
import openclaw.queue as q


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_QUEUE_FILE", str(tmp_path / "queue.json"))


def _post_result(post_id: str = "urn:li:share:1") -> PostResult:
    return PostResult(
        platform="linkedin",
        post_id=post_id,
        url=f"https://www.linkedin.com/feed/update/{post_id}",
    )


class TestParser:
    def test_post_command_parsed(self):
        parser = build_parser()
        args = parser.parse_args(["post", "Hello world"])
        assert args.command == "post"
        assert args.text == "Hello world"
        assert args.func is cmd_post

    def test_queue_command_parsed(self):
        parser = build_parser()
        args = parser.parse_args(["queue", "Queued post"])
        assert args.command == "queue"
        assert args.text == "Queued post"
        assert args.func is cmd_queue

    def test_run_command_parsed(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.command == "run"
        assert args.func is cmd_run

    def test_no_command_exits(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestCmdPost:
    def test_prints_post_id_and_url(self, capsys):
        args = build_parser().parse_args(["post", "Hello"])
        with patch("openclaw.cli.LinkedInAdapter") as MockAdapter, \
             patch("openclaw.cli.publish", return_value=_post_result()) as mock_publish:
            cmd_post(args)

        out = capsys.readouterr().out
        assert "urn:li:share:1" in out
        assert "linkedin.com" in out

    def test_calls_publish_with_text(self):
        args = build_parser().parse_args(["post", "My text"])
        with patch("openclaw.cli.LinkedInAdapter"), \
             patch("openclaw.cli.publish", return_value=_post_result()) as mock_publish:
            cmd_post(args)

        mock_publish.assert_called_once()
        _, call_text = mock_publish.call_args[0]
        assert call_text == "My text"


class TestCmdQueue:
    def test_enqueues_job_and_prints_id(self, capsys):
        args = build_parser().parse_args(["queue", "Deferred post"])
        cmd_queue(args)
        out = capsys.readouterr().out
        assert "Queued job" in out
        assert len(q.list_pending()) == 1
        assert q.list_pending()[0]["text"] == "Deferred post"


class TestCmdRun:
    def test_processes_pending_jobs(self, capsys):
        q.enqueue("linkedin", "Job A")
        q.enqueue("linkedin", "Job B")

        args = build_parser().parse_args(["run"])
        with patch("openclaw.cli.LinkedInAdapter"), \
             patch("openclaw.cli.publish", return_value=_post_result()):
            cmd_run(args)

        assert q.list_pending() == []
        out = capsys.readouterr().out
        assert out.count("[done]") == 2

    def test_marks_failed_on_error(self, capsys):
        q.enqueue("linkedin", "Bad post")

        args = build_parser().parse_args(["run"])
        with patch("openclaw.cli.LinkedInAdapter"), \
             patch("openclaw.cli.publish", side_effect=Exception("401")):
            cmd_run(args)

        jobs = q._load()
        assert jobs[0]["status"] == "failed"
        assert "401" in capsys.readouterr().err

    def test_no_pending_jobs_message(self, capsys):
        args = build_parser().parse_args(["run"])
        with patch("openclaw.cli.LinkedInAdapter"):
            cmd_run(args)
        assert "No pending jobs" in capsys.readouterr().out
