"""Tests for publish_to_platform dry_run mode and the --dry-run CLI flag.

Coverage:
  TestDryRunTextPost      — text-only posts: validation still runs, no network
  TestDryRunMediaPost     — media posts: policy check runs, no HTTP upload
  TestDryRunCLI           — --dry-run flag via subprocess
  TestGetPipelineAdapterDryRun — get_pipeline_adapter(dry_run=True) integration
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.publish_pipeline import publish_to_platform
from tools.publish_post import publish_post, get_pipeline_adapter

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _text_post(content: str = "Hello from dry-run!", platform: str = "twitter") -> dict:
    return {"platform": platform, "content": content}


def _media_post(file_path: str = "/tmp/img.png") -> dict:
    return {
        "platform": "twitter",
        "content":  "Check out this photo!",
        "media": [
            {
                "asset_type": "product_photo",
                "format":     "png",
                "alt_text":   "A product photo for dry-run testing",
                "context":    "social_post",
                "file_path":  file_path,
            }
        ],
    }


# ---------------------------------------------------------------------------
# TestDryRunTextPost
# ---------------------------------------------------------------------------

class TestDryRunTextPost(unittest.TestCase):
    """Text posts: validation runs, adapter + upload are never called."""

    def test_dry_run_returns_success_true_for_valid_post(self):
        result = publish_to_platform(_text_post(), dry_run=True)
        self.assertTrue(result["success"])

    def test_dry_run_result_has_dry_run_field(self):
        result = publish_to_platform(_text_post(), dry_run=True)
        self.assertIs(result.get("dry_run"), True)

    def test_dry_run_post_id_is_none(self):
        result = publish_to_platform(_text_post(), dry_run=True)
        self.assertIsNone(result["post_id"])

    def test_dry_run_character_count_populated(self):
        result = publish_to_platform(_text_post(content="Hello!"), dry_run=True)
        self.assertIsInstance(result["character_count"], int)
        self.assertGreater(result["character_count"], 0)

    def test_dry_run_empty_media_results(self):
        result = publish_to_platform(_text_post(), dry_run=True)
        self.assertEqual(result["media_results"], [])

    def test_dry_run_validation_still_rejects_too_long_content(self):
        """Content validation must not be weakened in dry-run mode."""
        result = publish_to_platform(_text_post(content="x" * 300), dry_run=True)
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["validation_errors"]]
        self.assertIn("CHARACTER_LIMIT_EXCEEDED", codes)

    def test_dry_run_validation_still_rejects_missing_platform(self):
        result = publish_to_platform({"content": "Hello!"}, dry_run=True)
        self.assertFalse(result["success"])

    def test_dry_run_adapter_never_called(self):
        mock_adapter = MagicMock()
        publish_to_platform(_text_post(), dry_run=True, _adapter=mock_adapter)
        mock_adapter.assert_not_called()

    def test_dry_run_upload_asset_never_called(self):
        with patch(
            "tools.publish_pipeline.publish_pipeline._upload_asset"
        ) as mock_upload:
            publish_to_platform(_text_post(), dry_run=True)
        mock_upload.assert_not_called()

    def test_non_dry_run_does_not_add_dry_run_field(self):
        """Real runs must not silently include dry_run=True."""
        mock_adapter = MagicMock(return_value={
            "success": True, "platform_post_id": "pid", "platform_response": None,
        })
        result = publish_to_platform(_text_post(), dry_run=False, _adapter=mock_adapter)
        self.assertNotIn("dry_run", result)


# ---------------------------------------------------------------------------
# TestDryRunMediaPost
# ---------------------------------------------------------------------------

class TestDryRunMediaPost(unittest.TestCase):
    """Media posts: policy validation runs, HTTP upload is skipped."""

    def test_dry_run_valid_media_returns_success_true(self):
        result = publish_to_platform(_media_post(), dry_run=True)
        self.assertTrue(result["success"])

    def test_dry_run_valid_media_asset_ref_is_synthetic(self):
        result = publish_to_platform(_media_post(), dry_run=True)
        self.assertEqual(len(result["media_results"]), 1)
        self.assertEqual(result["media_results"][0]["asset_ref"], "dry_run_0")

    def test_dry_run_two_images_get_indexed_refs(self):
        post = {
            "platform": "twitter",
            "content":  "Two images!",
            "media": [
                {"asset_type": "product_photo", "format": "png",
                 "alt_text": "first", "context": "social_post", "file_path": "/a.png"},
                {"asset_type": "product_photo", "format": "jpeg",
                 "alt_text": "second", "context": "social_post", "file_path": "/b.jpg"},
            ],
        }
        result = publish_to_platform(post, dry_run=True)
        self.assertTrue(result["success"])
        refs = [m["asset_ref"] for m in result["media_results"]]
        self.assertEqual(refs, ["dry_run_0", "dry_run_1"])

    def test_dry_run_media_success_field_is_true(self):
        result = publish_to_platform(_media_post(), dry_run=True)
        self.assertTrue(result["media_results"][0]["success"])

    def test_dry_run_invalid_media_format_fails(self):
        """Format policy check must still reject disallowed formats."""
        post = _media_post()
        post["media"][0]["format"] = "bmp"   # not allowed by Twitter
        result = publish_to_platform(post, dry_run=True)
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["media_results"][0]["validation_errors"]]
        self.assertIn("FORMAT_NOT_ALLOWED", codes)

    def test_dry_run_missing_alt_text_fails(self):
        """Alt-text policy must still be enforced in dry-run mode."""
        post = _media_post()
        post["media"][0].pop("alt_text")
        result = publish_to_platform(post, dry_run=True)
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["media_results"][0]["validation_errors"]]
        self.assertIn("ALT_TEXT_REQUIRED", codes)

    def test_dry_run_unknown_asset_type_fails(self):
        post = _media_post()
        post["media"][0]["asset_type"] = "unknown_type"
        result = publish_to_platform(post, dry_run=True)
        self.assertFalse(result["success"])

    def test_dry_run_upload_asset_never_called(self):
        with patch(
            "tools.publish_pipeline.publish_pipeline._upload_asset"
        ) as mock_upload:
            publish_to_platform(_media_post(), dry_run=True)
        mock_upload.assert_not_called()

    def test_dry_run_media_failure_error_code_is_media_upload_failed(self):
        post = _media_post()
        post["media"][0]["format"] = "bmp"
        result = publish_to_platform(post, dry_run=True)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("MEDIA_UPLOAD_FAILED", codes)

    def test_dry_run_media_dry_run_field_present_on_failure(self):
        post = _media_post()
        post["media"][0]["format"] = "bmp"
        result = publish_to_platform(post, dry_run=True)
        self.assertIs(result.get("dry_run"), True)


# ---------------------------------------------------------------------------
# TestDryRunCLI
# ---------------------------------------------------------------------------

class TestDryRunCLI(unittest.TestCase):
    """--dry-run flag via subprocess."""

    def _run_cli(self, payload: dict, extra_args: list | None = None) -> tuple[int, dict]:
        cmd = [sys.executable, "-m", "tools.publish_pipeline"]
        if extra_args:
            cmd.extend(extra_args)
        env = os.environ.copy()
        env["PYTHONPATH"] = _REPO_ROOT
        proc = subprocess.run(
            cmd,
            input=json.dumps(payload).encode(),
            capture_output=True,
            env=env,
            cwd=_REPO_ROOT,
        )
        result = json.loads(proc.stdout.decode())
        return proc.returncode, result

    def test_dry_run_valid_post_exits_0(self):
        code, result = self._run_cli(
            {"platform": "twitter", "content": "Hello dry-run!"},
            extra_args=["--dry-run"],
        )
        self.assertEqual(code, 0)
        self.assertTrue(result["success"])

    def test_dry_run_result_has_dry_run_true(self):
        _, result = self._run_cli(
            {"platform": "twitter", "content": "Hello dry-run!"},
            extra_args=["--dry-run"],
        )
        self.assertIs(result.get("dry_run"), True)

    def test_dry_run_invalid_post_exits_1(self):
        code, result = self._run_cli(
            {"platform": "twitter", "content": "x" * 300},
            extra_args=["--dry-run"],
        )
        self.assertEqual(code, 1)
        self.assertFalse(result["success"])

    def test_dry_run_platform_flag_plus_dry_run(self):
        code, result = self._run_cli(
            {"content": "Hello from CLI!"},
            extra_args=["--platform", "twitter", "--dry-run"],
        )
        self.assertEqual(code, 0)
        self.assertIs(result.get("dry_run"), True)

    def test_dry_run_no_credentials_needed(self):
        """--dry-run must not fail just because credentials are absent."""
        env = {k: v for k, v in os.environ.items()
               if k not in ("TWITTER_API_KEY", "TWITTER_API_SECRET",
                            "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET")}
        env["PYTHONPATH"] = _REPO_ROOT
        proc = subprocess.run(
            [sys.executable, "-m", "tools.publish_pipeline",
             "--platform", "twitter", "--dry-run"],
            input=json.dumps({"content": "No creds needed for dry-run"}).encode(),
            capture_output=True,
            env=env,
            cwd=_REPO_ROOT,
        )
        result = json.loads(proc.stdout.decode())
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(result["success"])


# ---------------------------------------------------------------------------
# TestGetPipelineAdapterDryRun
# ---------------------------------------------------------------------------

class TestGetPipelineAdapterDryRun(unittest.TestCase):
    """get_pipeline_adapter(dry_run=True) threads dry_run into publish_to_platform."""

    def _queue_entry(self, content: str = "Queued dry-run post") -> dict:
        return {
            "queue_id":   "q_dr_001",
            "post_id":    "post_dr_001",
            "platform":   "twitter",
            "content":    content,
            "slot":       "2026-03-25T09:00:00+00:00",
            "created_at": "2026-03-25T08:00:00+00:00",
        }

    def test_pipeline_adapter_dry_run_calls_publish_to_platform_with_dry_run_true(self):
        adapter = get_pipeline_adapter(dry_run=True)
        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
            return_value={
                "success": True, "post_id": None, "character_count": 20,
                "media_results": [], "errors": [], "validation_errors": [],
                "warnings": [], "dry_run": True,
            },
        ) as mock_pipeline:
            adapter(self._queue_entry())

        _, kwargs = mock_pipeline.call_args
        self.assertIs(kwargs.get("dry_run"), True)

    def test_pipeline_adapter_dry_run_returns_success_true_on_valid_content(self):
        adapter = get_pipeline_adapter(dry_run=True)
        with patch(
            "tools.publish_post.publish_post._publish_to_platform",
            return_value={
                "success": True, "post_id": None, "character_count": 20,
                "media_results": [], "errors": [], "validation_errors": [],
                "warnings": [], "dry_run": True,
            },
        ):
            result = adapter(self._queue_entry())
        self.assertTrue(result["success"])

    def test_pipeline_adapter_dry_run_no_http_for_text_post(self):
        """End-to-end: adapter with dry_run=True makes no network calls."""
        adapter = get_pipeline_adapter(dry_run=True)
        with patch("tools.publish_pipeline.publish_pipeline._upload_asset") as mu, \
             patch("tools.publish_pipeline.publish_pipeline._get_adapter") as ma:
            result = adapter(self._queue_entry())

        mu.assert_not_called()
        ma.assert_not_called()
        self.assertTrue(result["success"])

    def test_pipeline_adapter_dry_run_validation_failure_propagates(self):
        """Validation errors in dry_run mode surface as adapter failures."""
        adapter = get_pipeline_adapter(dry_run=True)
        long_entry = self._queue_entry(content="x" * 300)
        result = adapter(long_entry)
        self.assertFalse(result["success"])
        self.assertIn("error_code", result)


if __name__ == "__main__":
    unittest.main()
