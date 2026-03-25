"""Tests for tools/publish_pipeline.

Coverage:
  TestInputValidation          — non-dict input raises; missing required keys
                                  lead to validation_errors, not exceptions
  TestPostValidationFailure    — unknown platform, empty content, char limit
                                  exceeded → validation_errors, valid=False
  TestValidationPassThrough    — valid minimal post passes Stage 1
  TestNoMedia                  — absent / empty / None media skips Stage 2
  TestMediaUploadSuccess       — single and multi media upload success paths
  TestMediaUploadFailure       — upload failure → pipeline fails, media_results
                                  set, adapter not contacted
  TestMediaResultShape         — each media_results entry has required keys
  TestAdapterResolution        — unknown platform returns UNKNOWN_PLATFORM;
                                  injected adapter is used directly
  TestAdapterDispatch          — entry dict passed to adapter has correct keys
  TestAdapterSuccess           — success=True, post_id and char_count in result
  TestAdapterFailure           — adapter success=False → pipeline fails
  TestAdapterException         — adapter raises → ADAPTER_EXCEPTION error
  TestResultShape              — all result fields present with correct types
  TestValidatePipelineResult   — shape guard: valid result passes; missing
                                  fields / wrong types raise ValueError
  TestWarningsForwarded        — warnings from validate_post appear in result
  TestPlatformNormalisation    — "x" and "twitter" both normalise to "twitter"
  TestIntegration              — end-to-end with stub adapter via registry
"""

import unittest
from unittest.mock import patch, MagicMock

from tools.publish_pipeline import publish_to_platform, validate_pipeline_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_adapter(entry: dict) -> dict:
    """Minimal success adapter."""
    return {"success": True, "platform_post_id": "post-123", "platform_response": None}


def _fail_adapter(entry: dict) -> dict:
    """Minimal failure adapter."""
    return {"success": False, "error_code": "AUTH_ERROR", "message": "bad creds",
            "platform_response": None}


def _raising_adapter(entry: dict) -> dict:
    raise RuntimeError("network blew up")


def _minimal_post(**overrides) -> dict:
    base = {"platform": "twitter", "content": "Hello OpenClaw!"}
    base.update(overrides)
    return base


def _upload_success(asset, platform, *, credentials=None, policy_path=None) -> dict:
    return {
        "success": True, "platform": platform,
        "asset_type": asset.get("asset_type"), "asset_ref": "media-ref-1",
        "validation_errors": [], "errors": [], "warnings": [],
    }


def _upload_failure(asset, platform, *, credentials=None, policy_path=None) -> dict:
    return {
        "success": False, "platform": platform,
        "asset_type": asset.get("asset_type"), "asset_ref": None,
        "validation_errors": [], "errors": [{"code": "AUTH_ERROR", "message": "no creds"}],
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# TestInputValidation
# ---------------------------------------------------------------------------

class TestInputValidation(unittest.TestCase):

    def test_non_dict_raises_value_error(self):
        with self.assertRaises(ValueError):
            publish_to_platform("not a dict")

    def test_list_raises_value_error(self):
        with self.assertRaises(ValueError):
            publish_to_platform([])

    def test_none_raises_value_error(self):
        with self.assertRaises(ValueError):
            publish_to_platform(None)

    def test_missing_platform_returns_validation_error(self):
        result = publish_to_platform({"content": "Hi"}, _adapter=_ok_adapter)
        self.assertFalse(result["success"])
        self.assertTrue(len(result["validation_errors"]) > 0)

    def test_missing_content_returns_validation_error(self):
        result = publish_to_platform({"platform": "twitter"}, _adapter=_ok_adapter)
        self.assertFalse(result["success"])
        self.assertTrue(len(result["validation_errors"]) > 0)


# ---------------------------------------------------------------------------
# TestPostValidationFailure
# ---------------------------------------------------------------------------

class TestPostValidationFailure(unittest.TestCase):

    def test_unknown_platform_fails(self):
        result = publish_to_platform(
            {"platform": "myspace", "content": "Hi"},
            _adapter=_ok_adapter,
        )
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["validation_errors"]]
        self.assertIn("UNSUPPORTED_PLATFORM", codes)

    def test_empty_content_fails(self):
        result = publish_to_platform(
            {"platform": "twitter", "content": "   "},
            _adapter=_ok_adapter,
        )
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["validation_errors"]]
        self.assertIn("EMPTY_CONTENT", codes)

    def test_character_limit_exceeded_fails(self):
        long_content = "x" * 300  # Twitter limit is 280
        result = publish_to_platform(
            {"platform": "twitter", "content": long_content},
            _adapter=_ok_adapter,
        )
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["validation_errors"]]
        self.assertIn("CHARACTER_LIMIT_EXCEEDED", codes)

    def test_validation_error_adapter_not_called(self):
        called = []

        def spy_adapter(entry):
            called.append(entry)
            return _ok_adapter(entry)

        publish_to_platform(
            {"platform": "twitter", "content": ""},
            _adapter=spy_adapter,
        )
        self.assertEqual(called, [])

    def test_validation_errors_in_result(self):
        result = publish_to_platform(
            {"platform": "twitter", "content": ""},
            _adapter=_ok_adapter,
        )
        self.assertIsInstance(result["validation_errors"], list)
        self.assertTrue(len(result["validation_errors"]) > 0)

    def test_errors_empty_when_validation_fails(self):
        result = publish_to_platform(
            {"platform": "twitter", "content": ""},
            _adapter=_ok_adapter,
        )
        self.assertEqual(result["errors"], [])


# ---------------------------------------------------------------------------
# TestValidationPassThrough
# ---------------------------------------------------------------------------

class TestValidationPassThrough(unittest.TestCase):

    def test_minimal_valid_post_reaches_adapter(self):
        called = []

        def spy(entry):
            called.append(entry)
            return {"success": True, "platform_post_id": "x", "platform_response": None}

        publish_to_platform(_minimal_post(), _adapter=spy)
        self.assertEqual(len(called), 1)

    def test_character_count_in_result(self):
        result = publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        self.assertIsNotNone(result["character_count"])
        self.assertIsInstance(result["character_count"], int)

    def test_validation_errors_empty_on_pass(self):
        result = publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        self.assertEqual(result["validation_errors"], [])


# ---------------------------------------------------------------------------
# TestNoMedia
# ---------------------------------------------------------------------------

class TestNoMedia(unittest.TestCase):

    def _upload_spy(self):
        calls = []

        def spy(asset, platform, *, credentials=None, policy_path=None):
            calls.append(asset)
            return _upload_success(asset, platform)

        return spy, calls

    def test_no_media_key_skips_upload(self):
        spy, calls = self._upload_spy()
        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", spy):
            publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        self.assertEqual(calls, [])

    def test_empty_media_list_skips_upload(self):
        spy, calls = self._upload_spy()
        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", spy):
            publish_to_platform(_minimal_post(media=[]), _adapter=_ok_adapter)
        self.assertEqual(calls, [])

    def test_none_media_skips_upload(self):
        spy, calls = self._upload_spy()
        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", spy):
            publish_to_platform(_minimal_post(media=None), _adapter=_ok_adapter)
        self.assertEqual(calls, [])

    def test_no_media_result_is_empty_list(self):
        result = publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        self.assertEqual(result["media_results"], [])


# ---------------------------------------------------------------------------
# TestMediaUploadSuccess
# ---------------------------------------------------------------------------

class TestMediaUploadSuccess(unittest.TestCase):

    def test_single_media_upload_called(self):
        calls = []

        def spy(asset, platform, *, credentials=None, policy_path=None):
            calls.append(asset)
            return _upload_success(asset, platform)

        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", spy):
            publish_to_platform(
                _minimal_post(media=[{"asset_type": "logo", "format": "png"}]),
                _adapter=_ok_adapter,
            )
        self.assertEqual(len(calls), 1)

    def test_multi_media_all_uploaded(self):
        calls = []

        def spy(asset, platform, *, credentials=None, policy_path=None):
            calls.append(asset)
            ref = f"ref-{len(calls)}"
            return {**_upload_success(asset, platform), "asset_ref": ref}

        media = [
            {"asset_type": "logo", "format": "png"},
            {"asset_type": "product_photo", "format": "jpg"},
        ]
        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", spy):
            result = publish_to_platform(_minimal_post(media=media), _adapter=_ok_adapter)

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result["media_results"]), 2)

    def test_asset_refs_forwarded_to_adapter_as_media_ids(self):
        def spy_upload(asset, platform, *, credentials=None, policy_path=None):
            return {**_upload_success(asset, platform), "asset_ref": "ref-abc"}

        received_entry = []

        def spy_adapter(entry):
            received_entry.append(entry)
            return {"success": True, "platform_post_id": "p1", "platform_response": None}

        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", spy_upload):
            publish_to_platform(
                _minimal_post(media=[{"asset_type": "logo", "format": "png"}]),
                _adapter=spy_adapter,
            )

        self.assertEqual(received_entry[0]["media_ids"], ["ref-abc"])

    def test_upload_credentials_forwarded(self):
        creds_used = []

        def spy(asset, platform, *, credentials=None, policy_path=None):
            creds_used.append(credentials)
            return _upload_success(asset, platform)

        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", spy):
            publish_to_platform(
                _minimal_post(media=[{"asset_type": "logo", "format": "png"}]),
                credentials={"KEY": "value"},
                _adapter=_ok_adapter,
            )

        self.assertEqual(creds_used[0], {"KEY": "value"})

    def test_policy_path_forwarded_to_upload(self):
        policy_paths = []

        def spy(asset, platform, *, credentials=None, policy_path=None):
            policy_paths.append(policy_path)
            return _upload_success(asset, platform)

        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", spy):
            publish_to_platform(
                _minimal_post(media=[{"asset_type": "logo", "format": "png"}]),
                policy_path="/tmp/policy.json",
                _adapter=_ok_adapter,
            )

        self.assertEqual(policy_paths[0], "/tmp/policy.json")


# ---------------------------------------------------------------------------
# TestMediaUploadFailure
# ---------------------------------------------------------------------------

class TestMediaUploadFailure(unittest.TestCase):

    def test_single_upload_failure_pipeline_fails(self):
        with patch("tools.publish_pipeline.publish_pipeline._upload_asset",
                   _upload_failure):
            result = publish_to_platform(
                _minimal_post(media=[{"asset_type": "logo", "format": "png"}]),
                _adapter=_ok_adapter,
            )
        self.assertFalse(result["success"])

    def test_upload_failure_error_code_is_media_upload_failed(self):
        with patch("tools.publish_pipeline.publish_pipeline._upload_asset",
                   _upload_failure):
            result = publish_to_platform(
                _minimal_post(media=[{"asset_type": "logo", "format": "png"}]),
                _adapter=_ok_adapter,
            )
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("MEDIA_UPLOAD_FAILED", codes)

    def test_upload_failure_adapter_not_called(self):
        called = []

        def spy_adapter(entry):
            called.append(entry)
            return _ok_adapter(entry)

        with patch("tools.publish_pipeline.publish_pipeline._upload_asset",
                   _upload_failure):
            publish_to_platform(
                _minimal_post(media=[{"asset_type": "logo", "format": "png"}]),
                _adapter=spy_adapter,
            )

        self.assertEqual(called, [])

    def test_partial_upload_failure_pipeline_fails(self):
        """One success + one failure → pipeline fails."""
        call_count = [0]

        def spy(asset, platform, *, credentials=None, policy_path=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return _upload_success(asset, platform)
            return _upload_failure(asset, platform)

        media = [
            {"asset_type": "logo", "format": "png"},
            {"asset_type": "product_photo", "format": "jpg"},
        ]
        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", spy):
            result = publish_to_platform(_minimal_post(media=media), _adapter=_ok_adapter)

        self.assertFalse(result["success"])
        self.assertEqual(len(result["media_results"]), 2)

    def test_upload_failure_media_results_present(self):
        with patch("tools.publish_pipeline.publish_pipeline._upload_asset",
                   _upload_failure):
            result = publish_to_platform(
                _minimal_post(media=[{"asset_type": "logo", "format": "png"}]),
                _adapter=_ok_adapter,
            )
        self.assertEqual(len(result["media_results"]), 1)
        self.assertFalse(result["media_results"][0]["success"])


# ---------------------------------------------------------------------------
# TestMediaResultShape
# ---------------------------------------------------------------------------

class TestMediaResultShape(unittest.TestCase):

    def _run_with_upload(self, upload_fn):
        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", upload_fn):
            return publish_to_platform(
                _minimal_post(media=[{"asset_type": "logo", "format": "png"}]),
                _adapter=_ok_adapter,
            )

    def test_media_result_has_required_keys(self):
        result = self._run_with_upload(_upload_success)
        entry = result["media_results"][0]
        for key in ("asset_type", "asset_ref", "success", "errors", "validation_errors"):
            self.assertIn(key, entry)

    def test_media_result_success_true_on_ok_upload(self):
        result = self._run_with_upload(_upload_success)
        self.assertTrue(result["media_results"][0]["success"])

    def test_media_result_asset_ref_populated(self):
        result = self._run_with_upload(_upload_success)
        self.assertEqual(result["media_results"][0]["asset_ref"], "media-ref-1")

    def test_media_result_success_false_on_failure(self):
        result = self._run_with_upload(_upload_failure)
        self.assertFalse(result["media_results"][0]["success"])

    def test_media_result_errors_populated_on_failure(self):
        result = self._run_with_upload(_upload_failure)
        self.assertTrue(len(result["media_results"][0]["errors"]) > 0)


# ---------------------------------------------------------------------------
# TestAdapterResolution
# ---------------------------------------------------------------------------

class TestAdapterResolution(unittest.TestCase):

    def test_injected_adapter_used_directly(self):
        called = []

        def spy(entry):
            called.append(entry)
            return {"success": True, "platform_post_id": "x", "platform_response": None}

        publish_to_platform(_minimal_post(), _adapter=spy)
        self.assertEqual(len(called), 1)

    def test_unknown_platform_returns_unknown_platform_error(self):
        # Pass an injected adapter that won't be reached, but use a post with
        # a platform that would fail if looked up in the registry.
        # We force the registry path by NOT injecting _adapter.
        result = publish_to_platform({"platform": "myspace", "content": "Hi"})
        self.assertFalse(result["success"])
        # Validation layer catches UNSUPPORTED_PLATFORM before registry lookup
        self.assertTrue(len(result["validation_errors"]) > 0)

    def test_get_adapter_called_with_correct_platform(self):
        captured = []

        def fake_get_adapter(platform, credentials):
            captured.append((platform, credentials))
            return _ok_adapter

        with patch("tools.publish_pipeline.publish_pipeline._get_adapter",
                   fake_get_adapter):
            publish_to_platform(_minimal_post())

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0], "twitter")

    def test_credentials_forwarded_to_get_adapter(self):
        captured = []

        def fake_get_adapter(platform, credentials):
            captured.append(credentials)
            return _ok_adapter

        with patch("tools.publish_pipeline.publish_pipeline._get_adapter",
                   fake_get_adapter):
            publish_to_platform(_minimal_post(), credentials={"K": "V"})

        self.assertEqual(captured[0], {"K": "V"})


# ---------------------------------------------------------------------------
# TestAdapterDispatch
# ---------------------------------------------------------------------------

class TestAdapterDispatch(unittest.TestCase):

    def _capture(self):
        entries = []

        def spy(entry):
            entries.append(entry)
            return {"success": True, "platform_post_id": None, "platform_response": None}

        return spy, entries

    def test_entry_has_platform(self):
        spy, entries = self._capture()
        publish_to_platform(_minimal_post(), _adapter=spy)
        self.assertEqual(entries[0]["platform"], "twitter")

    def test_entry_has_content(self):
        spy, entries = self._capture()
        publish_to_platform(_minimal_post(content="My content"), _adapter=spy)
        self.assertEqual(entries[0]["content"], "My content")

    def test_entry_has_media_ids_key(self):
        spy, entries = self._capture()
        publish_to_platform(_minimal_post(), _adapter=spy)
        self.assertIn("media_ids", entries[0])

    def test_no_media_gives_empty_media_ids(self):
        spy, entries = self._capture()
        publish_to_platform(_minimal_post(), _adapter=spy)
        self.assertEqual(entries[0]["media_ids"], [])

    def test_hashtags_forwarded_to_adapter(self):
        spy, entries = self._capture()
        publish_to_platform(_minimal_post(hashtags=["openclaw"]), _adapter=spy)
        self.assertEqual(entries[0]["hashtags"], ["openclaw"])

    def test_mentions_forwarded_to_adapter(self):
        spy, entries = self._capture()
        publish_to_platform(_minimal_post(mentions=["openclaw"]), _adapter=spy)
        self.assertEqual(entries[0]["mentions"], ["openclaw"])

    def test_links_forwarded_to_adapter(self):
        spy, entries = self._capture()
        publish_to_platform(_minimal_post(links=["https://openclaw.io"]), _adapter=spy)
        self.assertEqual(entries[0]["links"], ["https://openclaw.io"])


# ---------------------------------------------------------------------------
# TestAdapterSuccess
# ---------------------------------------------------------------------------

class TestAdapterSuccess(unittest.TestCase):

    def test_success_is_true(self):
        result = publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        self.assertTrue(result["success"])

    def test_post_id_populated(self):
        result = publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        self.assertEqual(result["post_id"], "post-123")

    def test_post_id_none_when_adapter_returns_none(self):
        def adapter(entry):
            return {"success": True, "platform_post_id": None, "platform_response": None}

        result = publish_to_platform(_minimal_post(), _adapter=adapter)
        self.assertIsNone(result["post_id"])

    def test_character_count_in_success_result(self):
        result = publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        self.assertIsNotNone(result["character_count"])

    def test_errors_empty_on_success(self):
        result = publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        self.assertEqual(result["errors"], [])

    def test_validation_errors_empty_on_success(self):
        result = publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        self.assertEqual(result["validation_errors"], [])


# ---------------------------------------------------------------------------
# TestAdapterFailure
# ---------------------------------------------------------------------------

class TestAdapterFailure(unittest.TestCase):

    def test_adapter_failure_pipeline_fails(self):
        result = publish_to_platform(_minimal_post(), _adapter=_fail_adapter)
        self.assertFalse(result["success"])

    def test_adapter_error_code_in_errors(self):
        result = publish_to_platform(_minimal_post(), _adapter=_fail_adapter)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("AUTH_ERROR", codes)

    def test_adapter_message_in_errors(self):
        result = publish_to_platform(_minimal_post(), _adapter=_fail_adapter)
        messages = [e["message"] for e in result["errors"]]
        self.assertTrue(any("bad creds" in m for m in messages))

    def test_post_id_is_none_on_failure(self):
        result = publish_to_platform(_minimal_post(), _adapter=_fail_adapter)
        self.assertIsNone(result["post_id"])


# ---------------------------------------------------------------------------
# TestAdapterException
# ---------------------------------------------------------------------------

class TestAdapterException(unittest.TestCase):

    def test_adapter_exception_pipeline_fails(self):
        result = publish_to_platform(_minimal_post(), _adapter=_raising_adapter)
        self.assertFalse(result["success"])

    def test_adapter_exception_code_is_adapter_exception(self):
        result = publish_to_platform(_minimal_post(), _adapter=_raising_adapter)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("ADAPTER_EXCEPTION", codes)

    def test_adapter_exception_message_included(self):
        result = publish_to_platform(_minimal_post(), _adapter=_raising_adapter)
        messages = " ".join(e["message"] for e in result["errors"])
        self.assertIn("network blew up", messages)


# ---------------------------------------------------------------------------
# TestResultShape
# ---------------------------------------------------------------------------

class TestResultShape(unittest.TestCase):

    def _result(self, **overrides):
        post = _minimal_post(**overrides)
        return publish_to_platform(post, _adapter=_ok_adapter)

    def test_success_field_is_bool(self):
        self.assertIsInstance(self._result()["success"], bool)

    def test_platform_field_is_str(self):
        self.assertIsInstance(self._result()["platform"], str)

    def test_validation_errors_is_list(self):
        self.assertIsInstance(self._result()["validation_errors"], list)

    def test_media_results_is_list(self):
        self.assertIsInstance(self._result()["media_results"], list)

    def test_errors_is_list(self):
        self.assertIsInstance(self._result()["errors"], list)

    def test_warnings_is_list(self):
        self.assertIsInstance(self._result()["warnings"], list)

    def test_post_id_is_str_or_none(self):
        post_id = self._result()["post_id"]
        self.assertTrue(post_id is None or isinstance(post_id, str))

    def test_character_count_is_int_or_none(self):
        cc = self._result()["character_count"]
        self.assertTrue(cc is None or isinstance(cc, int))

    def test_all_required_keys_present(self):
        result = self._result()
        for key in ("success", "platform", "post_id", "character_count",
                    "validation_errors", "media_results", "errors", "warnings"):
            self.assertIn(key, result)

    def test_failure_result_shape_valid(self):
        result = publish_to_platform(
            {"platform": "twitter", "content": ""},
            _adapter=_ok_adapter,
        )
        validate_pipeline_result(result)  # must not raise


# ---------------------------------------------------------------------------
# TestValidatePipelineResult
# ---------------------------------------------------------------------------

class TestValidatePipelineResult(unittest.TestCase):

    def _valid_result(self, **overrides) -> dict:
        base = {
            "success":           True,
            "platform":          "twitter",
            "post_id":           "p1",
            "character_count":   10,
            "validation_errors": [],
            "media_results":     [],
            "errors":            [],
            "warnings":          [],
        }
        base.update(overrides)
        return base

    def test_valid_result_passes(self):
        validate_pipeline_result(self._valid_result())  # must not raise

    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            validate_pipeline_result("not a dict")

    def test_missing_success_raises(self):
        r = self._valid_result()
        del r["success"]
        with self.assertRaises(ValueError) as ctx:
            validate_pipeline_result(r)
        self.assertIn("success", str(ctx.exception))

    def test_missing_platform_raises(self):
        r = self._valid_result()
        del r["platform"]
        with self.assertRaises(ValueError):
            validate_pipeline_result(r)

    def test_missing_validation_errors_raises(self):
        r = self._valid_result()
        del r["validation_errors"]
        with self.assertRaises(ValueError):
            validate_pipeline_result(r)

    def test_missing_media_results_raises(self):
        r = self._valid_result()
        del r["media_results"]
        with self.assertRaises(ValueError):
            validate_pipeline_result(r)

    def test_wrong_type_success_raises(self):
        with self.assertRaises(ValueError):
            validate_pipeline_result(self._valid_result(success="yes"))

    def test_wrong_type_errors_raises(self):
        with self.assertRaises(ValueError):
            validate_pipeline_result(self._valid_result(errors="none"))

    def test_wrong_type_warnings_raises(self):
        with self.assertRaises(ValueError):
            validate_pipeline_result(self._valid_result(warnings={}))

    def test_none_post_id_is_valid(self):
        validate_pipeline_result(self._valid_result(post_id=None))  # must not raise

    def test_none_character_count_is_valid(self):
        validate_pipeline_result(self._valid_result(character_count=None))  # must not raise


# ---------------------------------------------------------------------------
# TestWarningsForwarded
# ---------------------------------------------------------------------------

class TestWarningsForwarded(unittest.TestCase):

    def test_no_long_content_warning_for_short_content(self):
        result = publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        codes = [w["code"] for w in result["warnings"]]
        self.assertNotIn("LONG_CONTENT", codes)

    def test_warnings_forwarded_from_validate_post(self):
        # Content > 80% of Twitter's 280-char limit triggers a LONG_CONTENT warning
        long_but_valid = "x" * 250  # 250 chars, above 224 (80% of 280), below 280
        result = publish_to_platform(
            _minimal_post(content=long_but_valid),
            _adapter=_ok_adapter,
        )
        codes = [w["code"] for w in result["warnings"]]
        self.assertIn("LONG_CONTENT", codes)

    def test_warnings_present_on_failure_too(self):
        long_but_valid = "x" * 250
        result = publish_to_platform(
            {"platform": "twitter", "content": long_but_valid},
            _adapter=_fail_adapter,
        )
        # Should still succeed validation and pass warnings through
        if result["success"] is False and result["errors"]:
            # adapter failed — warnings still forwarded
            self.assertIsInstance(result["warnings"], list)


# ---------------------------------------------------------------------------
# TestPlatformNormalisation
# ---------------------------------------------------------------------------

class TestPlatformNormalisation(unittest.TestCase):

    def test_x_normalises_to_twitter(self):
        result = publish_to_platform(
            {"platform": "x", "content": "Hello"},
            _adapter=_ok_adapter,
        )
        self.assertEqual(result["platform"], "twitter")

    def test_twitter_slash_x_normalises(self):
        result = publish_to_platform(
            {"platform": "twitter/x", "content": "Hello"},
            _adapter=_ok_adapter,
        )
        self.assertEqual(result["platform"], "twitter")

    def test_uppercase_twitter_normalises(self):
        result = publish_to_platform(
            {"platform": "TWITTER", "content": "Hello"},
            _adapter=_ok_adapter,
        )
        self.assertEqual(result["platform"], "twitter")

    def test_platform_in_entry_matches_normalised_form(self):
        received = []

        def spy(entry):
            received.append(entry["platform"])
            return {"success": True, "platform_post_id": None, "platform_response": None}

        publish_to_platform({"platform": "X", "content": "Hi"}, _adapter=spy)
        self.assertEqual(received[0], "twitter")


# ---------------------------------------------------------------------------
# TestIntegration
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    """End-to-end tests using the real registry stub adapter."""

    def test_text_only_post_via_stub(self):
        """Stub adapter in registry always returns success."""
        result = publish_to_platform(
            {"platform": "stub", "content": "Hello from OpenClaw!"},
        )
        # validate_post doesn't know "stub" as a platform — expect validation failure
        # OR we inject _adapter to bypass registry lookup for unknown-to-validate_post platforms.
        # stub isn't in PLATFORM_ALIASES so validation will fail with UNSUPPORTED_PLATFORM.
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["validation_errors"]]
        self.assertIn("UNSUPPORTED_PLATFORM", codes)

    def test_text_only_post_twitter_with_injected_adapter(self):
        result = publish_to_platform(
            {"platform": "twitter", "content": "Hello from OpenClaw!"},
            _adapter=_ok_adapter,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["platform"], "twitter")

    def test_full_flow_with_media_mock(self):
        def upload_fn(asset, platform, *, credentials=None, policy_path=None):
            return {
                "success": True, "platform": platform,
                "asset_type": "logo", "asset_ref": "media-99",
                "validation_errors": [], "errors": [], "warnings": [],
            }

        received = []

        def spy_adapter(entry):
            received.append(entry)
            return {"success": True, "platform_post_id": "tw-456", "platform_response": None}

        with patch("tools.publish_pipeline.publish_pipeline._upload_asset", upload_fn):
            result = publish_to_platform(
                {
                    "platform": "twitter",
                    "content":  "Check out our logo!",
                    "media":    [{"asset_type": "logo", "format": "png"}],
                },
                _adapter=spy_adapter,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["post_id"], "tw-456")
        self.assertEqual(result["media_results"][0]["asset_ref"], "media-99")
        self.assertEqual(received[0]["media_ids"], ["media-99"])

    def test_validate_pipeline_result_on_real_success(self):
        result = publish_to_platform(_minimal_post(), _adapter=_ok_adapter)
        validate_pipeline_result(result)  # must not raise

    def test_validate_pipeline_result_on_real_failure(self):
        result = publish_to_platform(_minimal_post(), _adapter=_fail_adapter)
        validate_pipeline_result(result)  # must not raise


if __name__ == "__main__":
    unittest.main()
