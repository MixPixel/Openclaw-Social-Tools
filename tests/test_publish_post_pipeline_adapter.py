"""Tests for get_pipeline_adapter() — the bridge between publish_post and
publish_to_platform.

Coverage:
  TestPipelineAdapterTranslation  — adapter callable builds the correct post dict
                                    from a queue entry and translates the
                                    publish_to_platform result back to the
                                    adapter contract
  TestPipelineAdapterIntegration  — end-to-end: queue entry → publish_post with
                                    get_pipeline_adapter → mock HTTP → result
                                    recorded in queue store
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.approval_state_manager import manage_approval_state
from tools.publish_post import publish_post, get_pipeline_adapter


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_CREDS = {
    "TWITTER_API_KEY":       "test_key",
    "TWITTER_API_SECRET":    "test_secret",
    "TWITTER_ACCESS_TOKEN":  "test_token",
    "TWITTER_ACCESS_SECRET": "test_token_secret",
}

_TWEET_SUCCESS_BODY = json.dumps({"data": {"id": "scheduled_tweet_001"}})

# Fixed timestamps
_NOW   = "2026-03-25T10:00:00+00:00"
_SLOT  = "2026-03-25T09:00:00+00:00"   # in the past → due
_CREATED = "2026-03-25T08:00:00+00:00"


def _mock_tweet_http(status: int = 201, body: str = _TWEET_SUCCESS_BODY):
    """Return a mock urlopen replacement for tweet delivery."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body.encode()
    return lambda req: resp


def _queue_entry(content: str = "Hello from the queue!", media=None) -> dict:
    return {
        "queue_id":   "q_pipeline_001",
        "post_id":    "post_pipeline_001",
        "platform":   "twitter",
        "content":    content,
        "slot":       _SLOT,
        "media":      media or [],
        "actor":      "scheduler",
        "created_at": _CREATED,
    }


# ---------------------------------------------------------------------------
# TestPipelineAdapterTranslation
# ---------------------------------------------------------------------------

class TestPipelineAdapterTranslation(unittest.TestCase):
    """Verify the adapter callable's input/output translation in isolation."""

    def _run_adapter(self, entry: dict, pipeline_result: dict) -> dict:
        """Call the pipeline adapter with a fake publish_to_platform return value."""
        adapter = get_pipeline_adapter(credentials=_CREDS)
        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
            return_value=pipeline_result,
        ) as mock_pipeline:
            result = adapter(entry)
        return result, mock_pipeline

    # --- Input translation ---

    def test_platform_forwarded_to_pipeline(self):
        entry = _queue_entry()
        _, mock = self._run_adapter(
            entry,
            {"success": True, "post_id": "pid", "character_count": 5,
             "media_results": [], "warnings": []},
        )
        call_args = mock.call_args
        post = call_args[0][0]          # first positional arg
        self.assertEqual(post["platform"], "twitter")

    def test_content_forwarded_to_pipeline(self):
        entry = _queue_entry(content="Scheduled post content")
        _, mock = self._run_adapter(
            entry,
            {"success": True, "post_id": "pid", "character_count": 22,
             "media_results": [], "warnings": []},
        )
        post = mock.call_args[0][0]
        self.assertEqual(post["content"], "Scheduled post content")

    def test_media_forwarded_when_non_empty(self):
        media_items = [{"asset_type": "product_photo", "format": "png",
                        "alt_text": "test", "context": "social_post",
                        "file_path": "/tmp/img.png"}]
        entry = _queue_entry(media=media_items)
        _, mock = self._run_adapter(
            entry,
            {"success": True, "post_id": "pid", "character_count": 5,
             "media_results": [{"success": True, "asset_ref": "m1"}], "warnings": []},
        )
        post = mock.call_args[0][0]
        self.assertEqual(post["media"], media_items)

    def test_empty_media_list_not_forwarded(self):
        """Empty media list should not appear in post dict (avoids pipeline noise)."""
        entry = _queue_entry(media=[])
        _, mock = self._run_adapter(
            entry,
            {"success": True, "post_id": "pid", "character_count": 5,
             "media_results": [], "warnings": []},
        )
        post = mock.call_args[0][0]
        self.assertNotIn("media", post)

    def test_optional_fields_forwarded(self):
        entry = {**_queue_entry(),
                 "hashtags": ["python"], "mentions": ["user"], "links": ["https://x.com"]}
        _, mock = self._run_adapter(
            entry,
            {"success": True, "post_id": "pid", "character_count": 5,
             "media_results": [], "warnings": []},
        )
        post = mock.call_args[0][0]
        self.assertEqual(post["hashtags"], ["python"])
        self.assertEqual(post["mentions"], ["user"])
        self.assertEqual(post["links"], ["https://x.com"])

    def test_credentials_passed_to_pipeline(self):
        entry = _queue_entry()
        _, mock = self._run_adapter(
            entry,
            {"success": True, "post_id": "pid", "character_count": 5,
             "media_results": [], "warnings": []},
        )
        kwargs = mock.call_args[1]
        self.assertEqual(kwargs.get("credentials"), _CREDS)

    # --- Output translation: success ---

    def test_success_returns_success_true(self):
        result, _ = self._run_adapter(
            _queue_entry(),
            {"success": True, "post_id": "tweet_abc", "character_count": 20,
             "media_results": [], "warnings": []},
        )
        self.assertTrue(result["success"])

    def test_success_maps_post_id_to_platform_post_id(self):
        result, _ = self._run_adapter(
            _queue_entry(),
            {"success": True, "post_id": "tweet_abc", "character_count": 20,
             "media_results": [], "warnings": []},
        )
        self.assertEqual(result["platform_post_id"], "tweet_abc")

    def test_success_platform_response_contains_character_count(self):
        result, _ = self._run_adapter(
            _queue_entry(),
            {"success": True, "post_id": "x", "character_count": 42,
             "media_results": [], "warnings": []},
        )
        self.assertEqual(result["platform_response"]["character_count"], 42)

    def test_success_platform_response_contains_media_results(self):
        media_results = [{"success": True, "asset_ref": "m1"}]
        result, _ = self._run_adapter(
            _queue_entry(),
            {"success": True, "post_id": "x", "character_count": 5,
             "media_results": media_results, "warnings": []},
        )
        self.assertEqual(result["platform_response"]["media_results"], media_results)

    # --- Output translation: failure ---

    def test_adapter_error_maps_to_failure(self):
        result, _ = self._run_adapter(
            _queue_entry(),
            {"success": False, "post_id": None, "character_count": None,
             "validation_errors": [],
             "media_results": [],
             "errors": [{"code": "AUTH_ERROR", "message": "bad credentials"}],
             "warnings": []},
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "AUTH_ERROR")
        self.assertEqual(result["message"], "bad credentials")

    def test_validation_error_maps_to_failure(self):
        result, _ = self._run_adapter(
            _queue_entry(),
            {"success": False, "post_id": None, "character_count": 400,
             "validation_errors": [{"code": "CONTENT_TOO_LONG",
                                    "message": "exceeds 280 chars"}],
             "media_results": [],
             "errors": [],
             "warnings": []},
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "CONTENT_TOO_LONG")

    def test_adapter_errors_take_precedence_over_validation_errors(self):
        """When both errors and validation_errors are present, errors win."""
        result, _ = self._run_adapter(
            _queue_entry(),
            {"success": False, "post_id": None, "character_count": None,
             "validation_errors": [{"code": "CONTENT_TOO_LONG", "message": "long"}],
             "media_results": [],
             "errors": [{"code": "RATE_LIMITED", "message": "slow down"}],
             "warnings": []},
        )
        self.assertEqual(result["error_code"], "RATE_LIMITED")

    def test_failure_platform_response_includes_all_error_fields(self):
        ve = [{"code": "CONTENT_TOO_LONG", "message": "too long"}]
        errs = [{"code": "RATE_LIMITED", "message": "slow"}]
        result, _ = self._run_adapter(
            _queue_entry(),
            {"success": False, "post_id": None, "character_count": None,
             "validation_errors": ve, "media_results": [],
             "errors": errs, "warnings": []},
        )
        pr = result["platform_response"]
        self.assertEqual(pr["validation_errors"], ve)
        self.assertEqual(pr["errors"], errs)

    def test_no_errors_at_all_uses_fallback_code(self):
        result, _ = self._run_adapter(
            _queue_entry(),
            {"success": False, "post_id": None, "character_count": None,
             "validation_errors": [], "media_results": [],
             "errors": [], "warnings": []},
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "PUBLISH_FAILED")


# ---------------------------------------------------------------------------
# TestPipelineAdapterIntegration
# ---------------------------------------------------------------------------

class TestPipelineAdapterIntegration(unittest.TestCase):
    """Full queue → publish_post + pipeline adapter → platform → queue store."""

    def setUp(self):
        fd, self.queue_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.queue_path)

        fd, self.approval_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.approval_path)

    def tearDown(self):
        for path in (self.queue_path, self.approval_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _write_queue(self, entries: dict) -> None:
        with open(self.queue_path, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)

    def _read_queue(self) -> dict:
        with open(self.queue_path, encoding="utf-8") as fh:
            return json.load(fh)

    def _setup_approval(self, post_id: str) -> None:
        for step in [
            {"action": "create",     "post_id": post_id, "actor": "test",
             "timestamp": "2026-03-25T08:00:00+00:00"},
            {"action": "transition", "post_id": post_id, "actor": "test",
             "current_state": "draft",            "target_state": "pending_approval",
             "timestamp": "2026-03-25T08:01:00+00:00"},
            {"action": "transition", "post_id": post_id, "actor": "test",
             "current_state": "pending_approval", "target_state": "approved",
             "timestamp": "2026-03-25T08:02:00+00:00"},
            {"action": "transition", "post_id": post_id, "actor": "test",
             "current_state": "approved",         "target_state": "scheduled",
             "timestamp": "2026-03-25T08:03:00+00:00"},
        ]:
            manage_approval_state({**step, "store_path": self.approval_path})

    def _run(self, adapter):
        return publish_post(
            {
                "queue_store_path":    self.queue_path,
                "approval_store_path": self.approval_path,
                "now":                 _NOW,
            },
            _adapter=adapter,
        )

    def test_successful_delivery_marks_queue_entry_posted(self):
        entry = _queue_entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])

        from tools.platform_adapters.twitter import get_adapter
        twitter_adapter = get_adapter(_CREDS, _http_fn=_mock_tweet_http())
        adapter = get_pipeline_adapter(credentials=_CREDS)

        with patch("tools.platform_adapters.twitter._call_twitter_api",
                   wraps=lambda payload, creds, _http_fn=None: (201, _TWEET_SUCCESS_BODY)):
            result = self._run(adapter)

        self.assertTrue(result["success"])
        queue = self._read_queue()
        self.assertEqual(queue[entry["queue_id"]]["status"], "posted")

    def test_successful_delivery_stores_platform_post_id(self):
        entry = _queue_entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])

        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
            return_value={
                "success": True, "post_id": "scheduled_tweet_001",
                "character_count": 21, "media_results": [],
                "errors": [], "validation_errors": [], "warnings": [],
            },
        ):
            result = self._run(get_pipeline_adapter(credentials=_CREDS))

        queue = self._read_queue()
        self.assertEqual(
            queue[entry["queue_id"]]["platform_post_id"], "scheduled_tweet_001"
        )

    def test_failed_delivery_marks_queue_entry_failed(self):
        entry = _queue_entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])

        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
            return_value={
                "success": False, "post_id": None,
                "character_count": None, "media_results": [],
                "errors": [{"code": "AUTH_ERROR", "message": "bad creds"}],
                "validation_errors": [], "warnings": [],
            },
        ):
            result = self._run(get_pipeline_adapter(credentials=_CREDS))

        self.assertTrue(result["success"])   # publish_post itself succeeded
        queue = self._read_queue()
        self.assertEqual(queue[entry["queue_id"]]["status"], "failed")
        self.assertEqual(queue[entry["queue_id"]]["error_code"], "AUTH_ERROR")

    def test_validation_failure_marks_queue_entry_failed(self):
        entry = _queue_entry(content="x" * 500)  # too long for Twitter
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])

        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
            return_value={
                "success": False, "post_id": None,
                "character_count": 500, "media_results": [],
                "errors": [],
                "validation_errors": [{"code": "CONTENT_TOO_LONG",
                                       "message": "exceeds 280 chars"}],
                "warnings": [],
            },
        ):
            result = self._run(get_pipeline_adapter(credentials=_CREDS))

        queue = self._read_queue()
        self.assertEqual(queue[entry["queue_id"]]["status"], "failed")
        self.assertEqual(queue[entry["queue_id"]]["error_code"], "CONTENT_TOO_LONG")

    def test_result_contains_post_outcome(self):
        entry = _queue_entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])

        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
            return_value={
                "success": True, "post_id": "pid_xyz",
                "character_count": 21, "media_results": [],
                "errors": [], "validation_errors": [], "warnings": [],
            },
        ):
            result = self._run(get_pipeline_adapter(credentials=_CREDS))

        self.assertEqual(result["posted"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["results"][0]["outcome"], "posted")
        self.assertEqual(result["results"][0]["platform_post_id"], "pid_xyz")

    def test_dry_run_does_not_call_pipeline(self):
        entry = _queue_entry()
        self._write_queue({entry["queue_id"]: entry})

        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
        ) as mock_pipeline:
            result = publish_post(
                {
                    "queue_store_path":    self.queue_path,
                    "approval_store_path": self.approval_path,
                    "now":                 _NOW,
                    "dry_run":             True,
                },
                _adapter=get_pipeline_adapter(credentials=_CREDS),
            )

        mock_pipeline.assert_not_called()
        self.assertEqual(result["results"][0]["outcome"], "dry_run")

    def test_pipeline_exception_caught_as_adapter_exception(self):
        """If publish_to_platform raises unexpectedly, publish_post records ADAPTER_EXCEPTION."""
        entry = _queue_entry()
        self._write_queue({entry["queue_id"]: entry})
        self._setup_approval(entry["post_id"])

        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
            side_effect=RuntimeError("unexpected crash"),
        ):
            result = self._run(get_pipeline_adapter(credentials=_CREDS))

        # publish_post catches adapter exceptions and records them.
        queue = self._read_queue()
        self.assertEqual(queue[entry["queue_id"]]["status"], "failed")
        self.assertEqual(queue[entry["queue_id"]]["error_code"], "ADAPTER_EXCEPTION")


if __name__ == "__main__":
    unittest.main()
