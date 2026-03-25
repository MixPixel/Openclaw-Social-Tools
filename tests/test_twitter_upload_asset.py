"""Tests for the twitter adapter's upload_asset() function.

Coverage:
  TestCredentials           — missing / partial / complete credentials
  TestDefaultApiNotImplemented — default _call_twitter_upload_api raises
                                NotImplementedError → UPLOAD_NOT_IMPLEMENTED
  TestApiSuccess            — mock API returns success → asset_ref forwarded
  TestApiFailure            — mock API returns failure dict → forwarded as-is
  TestApiException          — mock API raises exception → MEDIA_UPLOAD_FAILED
  TestResultShape           — result always has required keys; success is bool
  TestIntegrationViaOrchestrator — full path through tools/upload_asset/upload_asset.py
                                into the real twitter adapter module; no import mock
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from tools.platform_adapters.twitter import (
    REQUIRED_CREDENTIALS,
    upload_asset as twitter_upload_asset,
)
from tools.platform_adapters.base import AUTH_ERROR, MEDIA_UPLOAD_FAILED
from tools.upload_asset import upload_asset as orchestrate_upload
from tools.validate_asset.validate_asset import _clear_policy_cache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_CREDS = {
    "TWITTER_API_KEY":         "key_abc",
    "TWITTER_API_SECRET":      "secret_abc",
    "TWITTER_ACCESS_TOKEN":    "token_abc",
    "TWITTER_ACCESS_SECRET":   "tsecret_abc",
}

_VALID_LOGO = {
    "asset_type": "logo",
    "format":     "png",
    "alt_text":   "OpenClaw logo",
    "context":    "social_post",
}

_MINIMAL_POLICY = {
    "version": "test",
    "approved_source_domains": ["openclaw.io"],
    "forbidden_url_patterns":  ["shutterstock\\.com"],
    "required_license_fields": ["license_type", "license_url", "attribution"],
    "require_alt_text": True,
    "usage_policies": {
        "logo": {
            "edit_rule":           "locked",
            "require_license":     False,
            "require_attribution": False,
            "allowed_contexts":    ["social_post", "website", "email", "press"],
        },
    },
}


class _PolicyFileMixin:
    def setUp(self):
        self._tmpdir     = tempfile.TemporaryDirectory()
        self._policy_path = os.path.join(self._tmpdir.name, "asset_policy.json")
        with open(self._policy_path, "w", encoding="utf-8") as fh:
            json.dump(_MINIMAL_POLICY, fh)
        _clear_policy_cache()

    def tearDown(self):
        _clear_policy_cache()
        self._tmpdir.cleanup()


# ---------------------------------------------------------------------------
# TestCredentials
# ---------------------------------------------------------------------------

class TestCredentials(unittest.TestCase):

    def test_empty_credentials_returns_auth_error(self):
        result = twitter_upload_asset(_VALID_LOGO, {})
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_all_missing_credentials_listed_in_message(self):
        result = twitter_upload_asset(_VALID_LOGO, {})
        for key in REQUIRED_CREDENTIALS:
            self.assertIn(key, result["message"])

    def test_partial_credentials_returns_auth_error(self):
        partial = {"TWITTER_API_KEY": "k"}
        result = twitter_upload_asset(_VALID_LOGO, partial)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_partial_credentials_message_names_only_missing(self):
        partial = {"TWITTER_API_KEY": "k", "TWITTER_API_SECRET": "s"}
        result = twitter_upload_asset(_VALID_LOGO, partial)
        self.assertNotIn("TWITTER_API_KEY", result["message"])
        self.assertNotIn("TWITTER_API_SECRET", result["message"])
        self.assertIn("TWITTER_ACCESS_TOKEN", result["message"])
        self.assertIn("TWITTER_ACCESS_SECRET", result["message"])

    def test_full_credentials_reach_upload_api(self):
        """With full creds, the default API is called (raises NotImplementedError)."""
        result = twitter_upload_asset(_VALID_LOGO, _FULL_CREDS)
        # Default _call_twitter_upload_api raises NotImplementedError
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "UPLOAD_NOT_IMPLEMENTED")

    def test_empty_string_credential_treated_as_missing(self):
        creds = {k: "" for k in REQUIRED_CREDENTIALS}
        result = twitter_upload_asset(_VALID_LOGO, creds)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)


# ---------------------------------------------------------------------------
# TestDefaultApiNotImplemented
# ---------------------------------------------------------------------------

class TestDefaultApiNotImplemented(unittest.TestCase):

    def test_default_api_returns_upload_not_implemented(self):
        result = twitter_upload_asset(_VALID_LOGO, _FULL_CREDS)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "UPLOAD_NOT_IMPLEMENTED")

    def test_upload_not_implemented_message_is_non_empty(self):
        result = twitter_upload_asset(_VALID_LOGO, _FULL_CREDS)
        self.assertIsInstance(result["message"], str)
        self.assertGreater(len(result["message"]), 0)

    def test_upload_not_implemented_mentions_twitter(self):
        result = twitter_upload_asset(_VALID_LOGO, _FULL_CREDS)
        self.assertIn("Twitter", result["message"])


# ---------------------------------------------------------------------------
# TestApiSuccess
# ---------------------------------------------------------------------------

class TestApiSuccess(unittest.TestCase):

    def _upload(self, asset=None, asset_ref="media_99999"):
        mock_api = lambda a, c: {"success": True, "asset_ref": asset_ref}
        return twitter_upload_asset(asset or _VALID_LOGO, _FULL_CREDS, _upload_api=mock_api)

    def test_success_true(self):
        self.assertTrue(self._upload()["success"])

    def test_asset_ref_forwarded(self):
        result = self._upload(asset_ref="media_12345")
        self.assertEqual(result["asset_ref"], "media_12345")

    def test_asset_ref_none_forwarded(self):
        mock_api = lambda a, c: {"success": True, "asset_ref": None}
        result = twitter_upload_asset(_VALID_LOGO, _FULL_CREDS, _upload_api=mock_api)
        self.assertIsNone(result["asset_ref"])

    def test_api_called_with_asset_and_credentials(self):
        calls = []
        def mock_api(asset, creds):
            calls.append((asset, creds))
            return {"success": True, "asset_ref": "x"}
        twitter_upload_asset(_VALID_LOGO, _FULL_CREDS, _upload_api=mock_api)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], _VALID_LOGO)
        self.assertEqual(calls[0][1], _FULL_CREDS)


# ---------------------------------------------------------------------------
# TestApiFailure
# ---------------------------------------------------------------------------

class TestApiFailure(unittest.TestCase):

    def _upload_with_failure(self, error_code="MEDIA_UPLOAD_FAILED", message="too big"):
        mock_api = lambda a, c: {
            "success":    False,
            "error_code": error_code,
            "message":    message,
        }
        return twitter_upload_asset(_VALID_LOGO, _FULL_CREDS, _upload_api=mock_api)

    def test_failure_forwarded_as_is(self):
        result = self._upload_with_failure(error_code="RATE_LIMITED", message="slow down")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "RATE_LIMITED")
        self.assertEqual(result["message"], "slow down")

    def test_media_upload_failed_forwarded(self):
        result = self._upload_with_failure(error_code=MEDIA_UPLOAD_FAILED)
        self.assertEqual(result["error_code"], MEDIA_UPLOAD_FAILED)

    def test_auth_error_from_api_forwarded(self):
        result = self._upload_with_failure(error_code=AUTH_ERROR, message="token expired")
        self.assertEqual(result["error_code"], AUTH_ERROR)


# ---------------------------------------------------------------------------
# TestApiException
# ---------------------------------------------------------------------------

class TestApiException(unittest.TestCase):

    def test_runtime_error_returns_media_upload_failed(self):
        def mock_api(a, c):
            raise RuntimeError("connection refused")
        result = twitter_upload_asset(_VALID_LOGO, _FULL_CREDS, _upload_api=mock_api)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], MEDIA_UPLOAD_FAILED)

    def test_exception_message_preserved(self):
        def mock_api(a, c):
            raise ConnectionError("network timeout")
        result = twitter_upload_asset(_VALID_LOGO, _FULL_CREDS, _upload_api=mock_api)
        self.assertIn("network timeout", result["message"])

    def test_not_implemented_returns_upload_not_implemented(self):
        def mock_api(a, c):
            raise NotImplementedError("chunked upload not done")
        result = twitter_upload_asset(_VALID_LOGO, _FULL_CREDS, _upload_api=mock_api)
        self.assertEqual(result["error_code"], "UPLOAD_NOT_IMPLEMENTED")

    def test_not_implemented_message_preserved(self):
        def mock_api(a, c):
            raise NotImplementedError("chunked upload not done")
        result = twitter_upload_asset(_VALID_LOGO, _FULL_CREDS, _upload_api=mock_api)
        self.assertIn("chunked upload not done", result["message"])


# ---------------------------------------------------------------------------
# TestResultShape
# ---------------------------------------------------------------------------

class TestResultShape(unittest.TestCase):

    def _success_result(self):
        mock_api = lambda a, c: {"success": True, "asset_ref": "mid_1"}
        return twitter_upload_asset(_VALID_LOGO, _FULL_CREDS, _upload_api=mock_api)

    def _failure_result(self):
        mock_api = lambda a, c: {"success": False, "error_code": "RATE_LIMITED", "message": "x"}
        return twitter_upload_asset(_VALID_LOGO, _FULL_CREDS, _upload_api=mock_api)

    def _auth_error_result(self):
        return twitter_upload_asset(_VALID_LOGO, {})

    def test_success_is_bool_on_success(self):
        self.assertIsInstance(self._success_result()["success"], bool)

    def test_success_is_bool_on_failure(self):
        self.assertIsInstance(self._failure_result()["success"], bool)

    def test_success_is_bool_on_auth_error(self):
        self.assertIsInstance(self._auth_error_result()["success"], bool)

    def test_success_result_has_asset_ref(self):
        self.assertIn("asset_ref", self._success_result())

    def test_failure_result_has_error_code(self):
        self.assertIn("error_code", self._failure_result())

    def test_failure_result_has_message(self):
        self.assertIn("message", self._failure_result())

    def test_auth_error_result_has_error_code(self):
        self.assertIn("error_code", self._auth_error_result())


# ---------------------------------------------------------------------------
# TestIntegrationViaOrchestrator
# ---------------------------------------------------------------------------

class TestIntegrationViaOrchestrator(_PolicyFileMixin, unittest.TestCase):
    """Full path: orchestrate_upload → twitter.upload_asset → _upload_api mock.

    No importlib.import_module mock. The orchestrator loads the real twitter
    module and calls its upload_asset() function.  Only _call_twitter_upload_api
    is patched at the twitter module level to control the HTTP layer.
    """

    _API_TARGET = "tools.platform_adapters.twitter._call_twitter_upload_api"

    def test_full_success_path(self):
        """Validation passes, twitter adapter succeeds, orchestrator returns success."""
        with patch(self._API_TARGET, return_value={"success": True, "asset_ref": "tw_media_42"}):
            result = orchestrate_upload(
                _VALID_LOGO,
                "twitter",
                credentials=_FULL_CREDS,
                policy_path=self._policy_path,
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["asset_ref"], "tw_media_42")
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["errors"], [])

    def test_full_path_platform_in_result(self):
        with patch(self._API_TARGET, return_value={"success": True, "asset_ref": "x"}):
            result = orchestrate_upload(
                _VALID_LOGO, "twitter",
                credentials=_FULL_CREDS,
                policy_path=self._policy_path,
            )
        self.assertEqual(result["platform"], "twitter")

    def test_full_path_asset_type_in_result(self):
        with patch(self._API_TARGET, return_value={"success": True, "asset_ref": "x"}):
            result = orchestrate_upload(
                _VALID_LOGO, "twitter",
                credentials=_FULL_CREDS,
                policy_path=self._policy_path,
            )
        self.assertEqual(result["asset_type"], "logo")

    def test_auth_failure_surfaces_through_orchestrator(self):
        """Missing credentials → AUTH_ERROR in orchestrator errors list."""
        result = orchestrate_upload(
            _VALID_LOGO,
            "twitter",
            credentials={},
            policy_path=self._policy_path,
        )
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(AUTH_ERROR, codes)
        self.assertEqual(result["validation_errors"], [])

    def test_api_failure_surfaces_through_orchestrator(self):
        """Adapter returning failure → orchestrator errors non-empty."""
        with patch(self._API_TARGET, return_value={
            "success":    False,
            "error_code": MEDIA_UPLOAD_FAILED,
            "message":    "file too large",
        }):
            result = orchestrate_upload(
                _VALID_LOGO,
                "twitter",
                credentials=_FULL_CREDS,
                policy_path=self._policy_path,
            )
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(MEDIA_UPLOAD_FAILED, codes)

    def test_adapter_exception_surfaces_through_orchestrator(self):
        """Adapter raising exception → ADAPTER_EXCEPTION in orchestrator errors."""
        with patch(self._API_TARGET, side_effect=RuntimeError("network fail")):
            result = orchestrate_upload(
                _VALID_LOGO,
                "twitter",
                credentials=_FULL_CREDS,
                policy_path=self._policy_path,
            )
        self.assertFalse(result["success"])
        # twitter.upload_asset catches RuntimeError → MEDIA_UPLOAD_FAILED
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(MEDIA_UPLOAD_FAILED, codes)

    def test_validation_failure_skips_adapter(self):
        """Invalid asset → validation failure, twitter adapter never called."""
        with patch(self._API_TARGET) as mock_api:
            result = orchestrate_upload(
                {"asset_type": "logo", "format": "tiff", "alt_text": "x"},
                "twitter",
                credentials=_FULL_CREDS,
                policy_path=self._policy_path,
            )
        mock_api.assert_not_called()
        self.assertFalse(result["success"])
        self.assertNotEqual(result["validation_errors"], [])

    def test_not_implemented_surfaces_through_orchestrator(self):
        """Default API (NotImplementedError) → UPLOAD_NOT_IMPLEMENTED in orchestrator."""
        # No credentials patch; _call_twitter_upload_api is real (raises NotImplementedError)
        result = orchestrate_upload(
            _VALID_LOGO,
            "twitter",
            credentials=_FULL_CREDS,
            policy_path=self._policy_path,
        )
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("UPLOAD_NOT_IMPLEMENTED", codes)


if __name__ == "__main__":
    unittest.main()
