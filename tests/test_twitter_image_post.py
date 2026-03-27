"""End-to-end tests for the Twitter image-post workflow.

Proves the complete path from a post.json with a media attachment through
publish_to_platform, upload_asset, _call_twitter_upload_api, and back to the
tweet delivery adapter.

Coverage:
  TestImagePostEndToEnd    — file_path flows through pipeline to upload API;
                             media_id returned by upload reaches tweet payload;
                             success/failure result shapes; two-image case
  TestImagePostValidation  — validate_asset blocks missing alt_text, bad format;
                             missing file_path and unreadable file produce
                             MEDIA_UPLOAD_FAILED at the pipeline level
  TestImagePostResultShape — result fields present and correctly typed for both
                             success and failure cases
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.platform_adapters.base import (
    MEDIA_UPLOAD_FAILED,
    AUTH_ERROR,
)
from tools.platform_adapters.twitter import get_adapter
from tools.publish_pipeline import publish_to_platform, validate_pipeline_result


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_CREDS = {
    "TWITTER_API_KEY":       "test_key",
    "TWITTER_API_SECRET":    "test_secret",
    "TWITTER_ACCESS_TOKEN":  "test_token",
    "TWITTER_ACCESS_SECRET": "test_token_secret",
}

_TWEET_SUCCESS_BODY = json.dumps({"data": {"id": "tweet-img-001", "text": "..."}})


def _tweet_http(status: int = 201, body: str = _TWEET_SUCCESS_BODY):
    """Return a mock HTTP function for the tweet delivery endpoint."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body.encode()
    return lambda req: resp


def _capturing_tweet_http(status: int = 201, body: str = _TWEET_SUCCESS_BODY):
    """Return a mock HTTP function that records every request it receives."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body.encode()
    calls: list = []

    def _fn(request):
        calls.append(request)
        return resp

    _fn.calls = calls
    return _fn


def _upload_spy(media_id: str = "9876543210"):
    """Return an upload API function that records its arguments and succeeds."""
    calls: list = []

    def _fn(asset, credentials):
        calls.append({"asset": dict(asset), "credentials": credentials})
        return {"success": True, "asset_ref": media_id}

    _fn.calls = calls
    return _fn


def _temp_png() -> str:
    """Write a minimal fake PNG to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.write(fd, b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)   # fake PNG header
    os.close(fd)
    return path


def _valid_media_item(file_path: str) -> dict:
    """Return a media item that passes validate_asset for Twitter product_photo."""
    return {
        "asset_type": "product_photo",
        "format":     "png",
        "alt_text":   "A product photo used in testing",
        "context":    "social_post",
        "file_path":  file_path,
    }


def _image_post(file_path: str, content: str = "Check out this photo!") -> dict:
    return {
        "platform": "twitter",
        "content":  content,
        "media":    [_valid_media_item(file_path)],
    }


# ---------------------------------------------------------------------------
# TestImagePostEndToEnd
# ---------------------------------------------------------------------------

class TestImagePostEndToEnd(unittest.TestCase):
    """Proves that file_path → upload → media_id → tweet is wired correctly."""

    def test_file_path_reaches_upload_api(self):
        """file_path set in the media item must reach _call_twitter_upload_api."""
        path = _temp_png()
        try:
            spy = _upload_spy()
            adapter = get_adapter(_CREDS, _http_fn=_tweet_http())
            with patch("tools.platform_adapters.twitter._call_twitter_upload_api", spy):
                publish_to_platform(
                    _image_post(path),
                    credentials=_CREDS,
                    _adapter=adapter,
                )
            self.assertEqual(len(spy.calls), 1)
            self.assertEqual(spy.calls[0]["asset"]["file_path"], path)
        finally:
            os.unlink(path)

    def test_upload_media_id_appears_in_tweet_payload(self):
        """asset_ref returned by the upload API must appear in tweet body as media_ids."""
        path = _temp_png()
        try:
            http_fn = _capturing_tweet_http()
            adapter = get_adapter(_CREDS, _http_fn=http_fn)
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                return_value={"success": True, "asset_ref": "MEDIA_ID_XYZ"},
            ):
                publish_to_platform(
                    _image_post(path),
                    credentials=_CREDS,
                    _adapter=adapter,
                )
            self.assertEqual(len(http_fn.calls), 1)
            tweet_body = json.loads(http_fn.calls[0].data.decode())
            self.assertIn("media", tweet_body)
            self.assertEqual(tweet_body["media"]["media_ids"], ["MEDIA_ID_XYZ"])
        finally:
            os.unlink(path)

    def test_successful_image_post_returns_success_true(self):
        """A valid image post with mocked upload and delivery should succeed."""
        path = _temp_png()
        try:
            adapter = get_adapter(_CREDS, _http_fn=_tweet_http())
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                return_value={"success": True, "asset_ref": "111222333"},
            ):
                result = publish_to_platform(
                    _image_post(path),
                    credentials=_CREDS,
                    _adapter=adapter,
                )
            self.assertTrue(result["success"])
        finally:
            os.unlink(path)

    def test_successful_image_post_has_post_id(self):
        path = _temp_png()
        try:
            adapter = get_adapter(_CREDS, _http_fn=_tweet_http())
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                return_value={"success": True, "asset_ref": "111222333"},
            ):
                result = publish_to_platform(
                    _image_post(path),
                    credentials=_CREDS,
                    _adapter=adapter,
                )
            self.assertEqual(result["post_id"], "tweet-img-001")
        finally:
            os.unlink(path)

    def test_successful_image_post_media_results_populated(self):
        """media_results must record the asset_ref returned by the upload."""
        path = _temp_png()
        try:
            adapter = get_adapter(_CREDS, _http_fn=_tweet_http())
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                return_value={"success": True, "asset_ref": "ASSET_REF_1"},
            ):
                result = publish_to_platform(
                    _image_post(path),
                    credentials=_CREDS,
                    _adapter=adapter,
                )
            self.assertEqual(len(result["media_results"]), 1)
            self.assertTrue(result["media_results"][0]["success"])
            self.assertEqual(result["media_results"][0]["asset_ref"], "ASSET_REF_1")
        finally:
            os.unlink(path)

    def test_upload_failure_prevents_tweet(self):
        """If the media upload fails the tweet endpoint must never be called."""
        path = _temp_png()
        try:
            http_fn = _capturing_tweet_http()
            adapter = get_adapter(_CREDS, _http_fn=http_fn)
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                return_value={
                    "success":    False,
                    "error_code": MEDIA_UPLOAD_FAILED,
                    "message":    "upload rejected",
                },
            ):
                result = publish_to_platform(
                    _image_post(path),
                    credentials=_CREDS,
                    _adapter=adapter,
                )
            # Tweet endpoint was never contacted.
            self.assertEqual(len(http_fn.calls), 0)
            self.assertFalse(result["success"])
        finally:
            os.unlink(path)

    def test_upload_failure_error_code_in_result(self):
        path = _temp_png()
        try:
            adapter = get_adapter(_CREDS, _http_fn=_tweet_http())
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                return_value={
                    "success":    False,
                    "error_code": MEDIA_UPLOAD_FAILED,
                    "message":    "upload rejected",
                },
            ):
                result = publish_to_platform(
                    _image_post(path),
                    credentials=_CREDS,
                    _adapter=adapter,
                )
            codes = [e["code"] for e in result["errors"]]
            self.assertIn("MEDIA_UPLOAD_FAILED", codes)
        finally:
            os.unlink(path)

    def test_two_images_both_media_ids_in_tweet(self):
        """Two media items → two upload calls → both media_ids forwarded to tweet."""
        path1, path2 = _temp_png(), _temp_png()
        try:
            upload_call_count = {"n": 0}
            media_ids = ["ID_ALPHA", "ID_BETA"]

            def _sequential_upload(asset, credentials):
                idx = upload_call_count["n"]
                upload_call_count["n"] += 1
                return {"success": True, "asset_ref": media_ids[idx]}

            http_fn = _capturing_tweet_http()
            adapter = get_adapter(_CREDS, _http_fn=http_fn)
            post = {
                "platform": "twitter",
                "content":  "Two photos!",
                "media": [
                    _valid_media_item(path1),
                    _valid_media_item(path2),
                ],
            }
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                side_effect=_sequential_upload,
            ):
                result = publish_to_platform(post, credentials=_CREDS, _adapter=adapter)

            self.assertTrue(result["success"])
            self.assertEqual(len(result["media_results"]), 2)
            # Both media_ids must appear in the tweet body.
            self.assertEqual(len(http_fn.calls), 1)
            tweet_body = json.loads(http_fn.calls[0].data.decode())
            self.assertEqual(tweet_body["media"]["media_ids"], ["ID_ALPHA", "ID_BETA"])
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_all_other_media_items_skipped_when_one_upload_fails(self):
        """If the first of two uploads fails the pipeline stops immediately."""
        path1, path2 = _temp_png(), _temp_png()
        try:
            upload_call_count = {"n": 0}

            def _first_fails(asset, credentials):
                upload_call_count["n"] += 1
                if upload_call_count["n"] == 1:
                    return {"success": False, "error_code": MEDIA_UPLOAD_FAILED,
                            "message": "rejected"}
                return {"success": True, "asset_ref": "SHOULD_NOT_REACH"}

            http_fn = _capturing_tweet_http()
            adapter = get_adapter(_CREDS, _http_fn=http_fn)
            post = {
                "platform": "twitter",
                "content":  "Two photos",
                "media": [_valid_media_item(path1), _valid_media_item(path2)],
            }
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                side_effect=_first_fails,
            ):
                result = publish_to_platform(post, credentials=_CREDS, _adapter=adapter)

            # Pipeline should stop, tweet endpoint not called.
            self.assertFalse(result["success"])
            self.assertEqual(len(http_fn.calls), 0)
        finally:
            os.unlink(path1)
            os.unlink(path2)


# ---------------------------------------------------------------------------
# TestImagePostValidation
# ---------------------------------------------------------------------------

class TestImagePostValidation(unittest.TestCase):
    """validate_asset blocks invalid media items before any upload is attempted."""

    def _run(self, media_item: dict) -> dict:
        """Run publish_to_platform with a single media item; upload never needed."""
        adapter = get_adapter(_CREDS, _http_fn=_tweet_http())
        return publish_to_platform(
            {"platform": "twitter", "content": "Hello!", "media": [media_item]},
            credentials=_CREDS,
            _adapter=adapter,
        )

    def test_missing_alt_text_fails_with_alt_text_required(self):
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            result = self._run({
                "asset_type": "product_photo",
                "format":     "png",
                "context":    "social_post",
                "file_path":  path,
                # alt_text deliberately absent
            })
            self.assertFalse(result["success"])
            all_errors = (
                result["media_results"][0]["validation_errors"]
                if result.get("media_results") else []
            )
            codes = [e["code"] for e in all_errors]
            self.assertIn("ALT_TEXT_REQUIRED", codes)
        finally:
            os.unlink(path)

    def test_invalid_format_fails_with_format_not_allowed(self):
        fd, path = tempfile.mkstemp(suffix=".bmp")
        os.close(fd)
        try:
            result = self._run({
                "asset_type": "product_photo",
                "format":     "bmp",          # not in Twitter's allowed formats
                "alt_text":   "A test image",
                "context":    "social_post",
                "file_path":  path,
            })
            self.assertFalse(result["success"])
            all_errors = (
                result["media_results"][0]["validation_errors"]
                if result.get("media_results") else []
            )
            codes = [e["code"] for e in all_errors]
            self.assertIn("FORMAT_NOT_ALLOWED", codes)
        finally:
            os.unlink(path)

    def test_missing_file_path_returns_media_upload_failed(self):
        """No file_path in media item → upload returns MEDIA_UPLOAD_FAILED."""
        result = self._run({
            "asset_type": "product_photo",
            "format":     "png",
            "alt_text":   "Missing file path",
            "context":    "social_post",
            # file_path deliberately absent
        })
        self.assertFalse(result["success"])
        # Either in media_results[0].errors or top-level errors
        media_errors = (
            result["media_results"][0]["errors"]
            if result.get("media_results") else []
        )
        top_errors = result.get("errors", [])
        all_codes = [e["code"] for e in media_errors + top_errors]
        self.assertTrue(
            any("MEDIA_UPLOAD_FAILED" in c for c in all_codes),
            f"Expected MEDIA_UPLOAD_FAILED in errors, got: {all_codes}",
        )

    def test_nonexistent_file_returns_media_upload_failed(self):
        """file_path pointing to a missing file → MEDIA_UPLOAD_FAILED."""
        result = self._run({
            "asset_type": "product_photo",
            "format":     "png",
            "alt_text":   "File does not exist",
            "context":    "social_post",
            "file_path":  "/tmp/this_file_does_not_exist_openclaw_test.png",
        })
        self.assertFalse(result["success"])
        media_errors = (
            result["media_results"][0]["errors"]
            if result.get("media_results") else []
        )
        top_errors = result.get("errors", [])
        all_codes = [e["code"] for e in media_errors + top_errors]
        self.assertTrue(
            any("MEDIA_UPLOAD_FAILED" in c for c in all_codes),
            f"Expected MEDIA_UPLOAD_FAILED in errors, got: {all_codes}",
        )

    def test_unknown_asset_type_fails_with_unknown_asset_type(self):
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            result = self._run({
                "asset_type": "mystery_asset",
                "format":     "png",
                "alt_text":   "Unknown type",
                "context":    "social_post",
                "file_path":  path,
            })
            self.assertFalse(result["success"])
            all_errors = (
                result["media_results"][0]["validation_errors"]
                if result.get("media_results") else []
            )
            codes = [e["code"] for e in all_errors]
            self.assertIn("UNKNOWN_ASSET_TYPE", codes)
        finally:
            os.unlink(path)

    def test_invalid_context_fails_with_context_not_allowed(self):
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            result = self._run({
                "asset_type": "product_photo",
                "format":     "png",
                "alt_text":   "Bad context",
                "context":    "press",   # not in product_photo's allowed_contexts
                "file_path":  path,
            })
            self.assertFalse(result["success"])
            all_errors = (
                result["media_results"][0]["validation_errors"]
                if result.get("media_results") else []
            )
            codes = [e["code"] for e in all_errors]
            self.assertIn("CONTEXT_NOT_ALLOWED", codes)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# TestImagePostResultShape
# ---------------------------------------------------------------------------

class TestImagePostResultShape(unittest.TestCase):
    """Result dict must have the required shape in all image-post paths."""

    def test_success_result_passes_shape_validator(self):
        path = _temp_png()
        try:
            adapter = get_adapter(_CREDS, _http_fn=_tweet_http())
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                return_value={"success": True, "asset_ref": "SHAPE_TEST_ID"},
            ):
                result = publish_to_platform(
                    _image_post(path), credentials=_CREDS, _adapter=adapter
                )
            validate_pipeline_result(result)  # must not raise
        finally:
            os.unlink(path)

    def test_upload_failure_result_passes_shape_validator(self):
        path = _temp_png()
        try:
            adapter = get_adapter(_CREDS, _http_fn=_tweet_http())
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                return_value={
                    "success": False, "error_code": MEDIA_UPLOAD_FAILED,
                    "message": "rejected",
                },
            ):
                result = publish_to_platform(
                    _image_post(path), credentials=_CREDS, _adapter=adapter
                )
            validate_pipeline_result(result)  # must not raise
        finally:
            os.unlink(path)

    def test_validation_failure_result_passes_shape_validator(self):
        # No file needed — validation fails before upload.
        adapter = get_adapter(_CREDS, _http_fn=_tweet_http())
        result = publish_to_platform(
            {"content": "Hi!", "media": [{"asset_type": "product_photo",
                                          "format": "png",
                                          "context": "social_post"}]},
            # alt_text absent → ALT_TEXT_REQUIRED
            credentials=_CREDS,
            _adapter=adapter,
        )
        validate_pipeline_result(result)  # must not raise

    def test_image_post_platform_is_twitter(self):
        path = _temp_png()
        try:
            adapter = get_adapter(_CREDS, _http_fn=_tweet_http())
            with patch(
                "tools.platform_adapters.twitter._call_twitter_upload_api",
                return_value={"success": True, "asset_ref": "XYZ"},
            ):
                result = publish_to_platform(
                    _image_post(path, content="Hello!"),
                    credentials=_CREDS,
                    _adapter=adapter,
                    # platform injected via --platform flag or JSON field
                )
            self.assertEqual(result["platform"], "twitter")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
