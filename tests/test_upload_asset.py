"""Tests for tools/upload_asset.

Coverage:
  TestValidateUploadResult      — shape validator: valid shape passes; missing fields,
                                  wrong types raise ValueError
  TestHardStopUnknownPlatform   — unknown platform → validation_errors contain
                                  UNKNOWN_PLATFORM; success=False; adapter not called
  TestHardStopUploadNotSupported — UPLOAD_NOT_SUPPORTED in validation_errors via mock;
                                  adapter not called
  TestValidationFailureShortCircuit — any validation failure → success=False;
                                  validation_errors non-empty; errors=[]; adapter not called
  TestAdapterLoadError          — ImportError on module import → ADAPTER_LOAD_ERROR
                                  in errors; validation_errors=[]
  TestUploadNotImplemented      — adapter missing upload_asset attr → UPLOAD_NOT_IMPLEMENTED;
                                  adapter raising NotImplementedError → UPLOAD_NOT_IMPLEMENTED
  TestAdapterException          — adapter raises unexpected exception → ADAPTER_EXCEPTION
  TestAdapterFailureResult      — adapter returns success=False → errors populated with
                                  adapter code; validation_errors=[]
  TestSuccessfulUpload          — adapter returns success=True → success=True;
                                  asset_ref from adapter; validation_errors=[]; errors=[]
  TestResultShape               — all result fields always present; validation_errors and
                                  errors are lists; warnings always []; platform and
                                  asset_type always in result; validate_upload_result passes
  TestPlatformNormalisation     — mixed-case / whitespace platform normalised correctly
  TestValidationAndErrorSeparation — validation_errors vs errors are mutually exclusive
                                  in normal flow; both always present
  TestRealPolicyIntegration     — integration tests against real config/asset_policy.json
                                  with no policy_path injection; confirms validate_asset
                                  is called against the real policy before adapter dispatch
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.upload_asset import upload_asset, validate_upload_result
from tools.validate_asset.validate_asset import _clear_policy_cache

# ---------------------------------------------------------------------------
# Helpers — minimal policy for test isolation
# ---------------------------------------------------------------------------

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
        "customer_photo": {
            "edit_rule":           "croppable_only",
            "require_license":     True,
            "require_attribution": True,
            "allowed_contexts":    ["social_post"],
        },
        "generated_graphic": {
            "edit_rule":           "editable",
            "require_license":     False,
            "require_attribution": False,
            "allowed_contexts":    ["social_post", "website", "email", "blog"],
        },
    },
}

_VALID_LOGO = {
    "asset_type": "logo",
    "format":     "png",
    "alt_text":   "OpenClaw logo",
    "context":    "social_post",
}


def _make_success_module(asset_ref="media_12345"):
    """Return a mock module whose upload_asset() succeeds."""
    m = MagicMock()
    m.upload_asset.return_value = {"success": True, "asset_ref": asset_ref}
    return m


def _make_failure_module(error_code="MEDIA_UPLOAD_FAILED", message="upload failed"):
    """Return a mock module whose upload_asset() returns a failure dict."""
    m = MagicMock()
    m.upload_asset.return_value = {
        "success":    False,
        "error_code": error_code,
        "message":    message,
    }
    return m


class _PolicyFileMixin:
    """Write a temp policy file and clear cache around each test."""

    def setUp(self):
        self._tmpdir     = tempfile.TemporaryDirectory()
        self._policy_path = os.path.join(self._tmpdir.name, "asset_policy.json")
        with open(self._policy_path, "w", encoding="utf-8") as fh:
            json.dump(_MINIMAL_POLICY, fh)
        _clear_policy_cache()

    def tearDown(self):
        _clear_policy_cache()
        self._tmpdir.cleanup()

    def _upload(self, asset=None, platform="twitter", **kwargs):
        if asset is None:
            asset = _VALID_LOGO.copy()
        return upload_asset(asset, platform, policy_path=self._policy_path, **kwargs)

    def _upload_patched(self, mock_module, asset=None, platform="twitter", **kwargs):
        """Call _upload with importlib.import_module mocked to return mock_module."""
        _target = "tools.upload_asset.upload_asset.importlib.import_module"
        with patch(_target, return_value=mock_module):
            return self._upload(asset=asset, platform=platform, **kwargs)


# ---------------------------------------------------------------------------
# TestValidateUploadResult
# ---------------------------------------------------------------------------

class TestValidateUploadResult(unittest.TestCase):

    def _valid(self, **overrides):
        base = {
            "success":           True,
            "platform":          "twitter",
            "asset_type":        "logo",
            "asset_ref":         None,
            "validation_errors": [],
            "errors":            [],
            "warnings":          [],
        }
        base.update(overrides)
        return base

    def test_valid_shape_passes(self):
        validate_upload_result(self._valid())  # must not raise

    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            validate_upload_result("not a dict")

    def test_missing_success_raises(self):
        d = self._valid()
        del d["success"]
        with self.assertRaises(ValueError):
            validate_upload_result(d)

    def test_missing_platform_raises(self):
        d = self._valid()
        del d["platform"]
        with self.assertRaises(ValueError):
            validate_upload_result(d)

    def test_missing_asset_ref_raises(self):
        d = self._valid()
        del d["asset_ref"]
        with self.assertRaises(ValueError):
            validate_upload_result(d)

    def test_missing_validation_errors_raises(self):
        d = self._valid()
        del d["validation_errors"]
        with self.assertRaises(ValueError):
            validate_upload_result(d)

    def test_missing_errors_raises(self):
        d = self._valid()
        del d["errors"]
        with self.assertRaises(ValueError):
            validate_upload_result(d)

    def test_missing_warnings_raises(self):
        d = self._valid()
        del d["warnings"]
        with self.assertRaises(ValueError):
            validate_upload_result(d)

    def test_success_non_bool_raises(self):
        with self.assertRaises(ValueError):
            validate_upload_result(self._valid(success="yes"))

    def test_validation_errors_non_list_raises(self):
        with self.assertRaises(ValueError):
            validate_upload_result(self._valid(validation_errors=None))

    def test_errors_non_list_raises(self):
        with self.assertRaises(ValueError):
            validate_upload_result(self._valid(errors="oops"))

    def test_warnings_non_list_raises(self):
        with self.assertRaises(ValueError):
            validate_upload_result(self._valid(warnings={}))


# ---------------------------------------------------------------------------
# TestHardStopUnknownPlatform
# ---------------------------------------------------------------------------

class TestHardStopUnknownPlatform(_PolicyFileMixin, unittest.TestCase):

    def test_returns_false(self):
        result = self._upload(platform="notaplatform")
        self.assertFalse(result["success"])

    def test_unknown_platform_in_validation_errors(self):
        result = self._upload(platform="notaplatform")
        codes = [e["code"] for e in result["validation_errors"]]
        self.assertIn("UNKNOWN_PLATFORM", codes)

    def test_errors_empty_for_unknown_platform(self):
        result = self._upload(platform="notaplatform")
        self.assertEqual(result["errors"], [])

    def test_no_further_errors_accumulated(self):
        result = self._upload(platform="notaplatform")
        self.assertEqual(len(result["validation_errors"]), 1)


# ---------------------------------------------------------------------------
# TestHardStopUploadNotSupported
# ---------------------------------------------------------------------------

class TestHardStopUploadNotSupported(_PolicyFileMixin, unittest.TestCase):
    """Mock supports_capability to return False for a known platform."""

    _MOCK_TARGET = "tools.validate_asset.validate_asset.supports_capability"

    def test_upload_not_supported_in_validation_errors(self):
        with patch(self._MOCK_TARGET, return_value=False):
            result = self._upload()
        codes = [e["code"] for e in result["validation_errors"]]
        self.assertIn("UPLOAD_NOT_SUPPORTED", codes)

    def test_success_false_when_upload_not_supported(self):
        with patch(self._MOCK_TARGET, return_value=False):
            result = self._upload()
        self.assertFalse(result["success"])

    def test_errors_empty_when_upload_not_supported(self):
        with patch(self._MOCK_TARGET, return_value=False):
            result = self._upload()
        self.assertEqual(result["errors"], [])


# ---------------------------------------------------------------------------
# TestValidationFailureShortCircuit
# ---------------------------------------------------------------------------

class TestValidationFailureShortCircuit(_PolicyFileMixin, unittest.TestCase):
    """Validation failure must return early; adapter must not be called."""

    _IMPORT_TARGET = "tools.upload_asset.upload_asset.importlib.import_module"

    def test_bad_format_skips_adapter(self):
        with patch(self._IMPORT_TARGET) as mock_import:
            result = self._upload({"asset_type": "logo", "format": "tiff", "alt_text": "x"})
        mock_import.assert_not_called()
        self.assertFalse(result["success"])

    def test_missing_alt_text_skips_adapter(self):
        with patch(self._IMPORT_TARGET) as mock_import:
            result = self._upload({"asset_type": "logo", "format": "png"})
        mock_import.assert_not_called()
        self.assertFalse(result["success"])

    def test_validation_errors_populated_on_failure(self):
        result = self._upload({"asset_type": "logo", "format": "tiff", "alt_text": "x"})
        self.assertNotEqual(result["validation_errors"], [])

    def test_errors_empty_on_validation_failure(self):
        result = self._upload({"asset_type": "logo", "format": "tiff", "alt_text": "x"})
        self.assertEqual(result["errors"], [])

    def test_validation_errors_is_list_of_dicts_with_code(self):
        result = self._upload({"asset_type": "logo", "format": "tiff", "alt_text": "x"})
        for err in result["validation_errors"]:
            self.assertIsInstance(err, dict)
            self.assertIn("code", err)


# ---------------------------------------------------------------------------
# TestAdapterLoadError
# ---------------------------------------------------------------------------

class TestAdapterLoadError(_PolicyFileMixin, unittest.TestCase):

    _IMPORT_TARGET = "tools.upload_asset.upload_asset.importlib.import_module"

    def test_import_error_returns_adapter_load_error(self):
        with patch(self._IMPORT_TARGET, side_effect=ImportError("no module")):
            result = self._upload()
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("ADAPTER_LOAD_ERROR", codes)

    def test_import_error_validation_errors_empty(self):
        with patch(self._IMPORT_TARGET, side_effect=ImportError("no module")):
            result = self._upload()
        self.assertEqual(result["validation_errors"], [])

    def test_adapter_load_error_message_contains_platform(self):
        with patch(self._IMPORT_TARGET, side_effect=ImportError("missing dep")):
            result = self._upload(platform="twitter")
        msg = result["errors"][0]["message"]
        self.assertIn("twitter", msg)


# ---------------------------------------------------------------------------
# TestUploadNotImplemented
# ---------------------------------------------------------------------------

class TestUploadNotImplemented(_PolicyFileMixin, unittest.TestCase):

    _IMPORT_TARGET = "tools.upload_asset.upload_asset.importlib.import_module"

    def test_missing_upload_fn_returns_upload_not_implemented(self):
        """Module with no upload_asset attribute → UPLOAD_NOT_IMPLEMENTED."""
        mock_module = MagicMock(spec=[])  # no attributes
        with patch(self._IMPORT_TARGET, return_value=mock_module):
            result = self._upload()
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("UPLOAD_NOT_IMPLEMENTED", codes)

    def test_missing_upload_fn_success_false(self):
        mock_module = MagicMock(spec=[])
        with patch(self._IMPORT_TARGET, return_value=mock_module):
            result = self._upload()
        self.assertFalse(result["success"])

    def test_upload_fn_raises_not_implemented(self):
        """upload_asset() raises NotImplementedError → UPLOAD_NOT_IMPLEMENTED."""
        mock_module = MagicMock()
        mock_module.upload_asset.side_effect = NotImplementedError("not done")
        with patch(self._IMPORT_TARGET, return_value=mock_module):
            result = self._upload()
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("UPLOAD_NOT_IMPLEMENTED", codes)

    def test_not_implemented_validation_errors_empty(self):
        mock_module = MagicMock(spec=[])
        with patch(self._IMPORT_TARGET, return_value=mock_module):
            result = self._upload()
        self.assertEqual(result["validation_errors"], [])


# ---------------------------------------------------------------------------
# TestAdapterException
# ---------------------------------------------------------------------------

class TestAdapterException(_PolicyFileMixin, unittest.TestCase):

    _IMPORT_TARGET = "tools.upload_asset.upload_asset.importlib.import_module"

    def test_unexpected_exception_returns_adapter_exception(self):
        mock_module = MagicMock()
        mock_module.upload_asset.side_effect = RuntimeError("network timeout")
        with patch(self._IMPORT_TARGET, return_value=mock_module):
            result = self._upload()
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("ADAPTER_EXCEPTION", codes)

    def test_adapter_exception_success_false(self):
        mock_module = MagicMock()
        mock_module.upload_asset.side_effect = ValueError("unexpected")
        with patch(self._IMPORT_TARGET, return_value=mock_module):
            result = self._upload()
        self.assertFalse(result["success"])

    def test_adapter_exception_message_preserved(self):
        mock_module = MagicMock()
        mock_module.upload_asset.side_effect = RuntimeError("disk full")
        with patch(self._IMPORT_TARGET, return_value=mock_module):
            result = self._upload()
        self.assertIn("disk full", result["errors"][0]["message"])

    def test_adapter_exception_validation_errors_empty(self):
        mock_module = MagicMock()
        mock_module.upload_asset.side_effect = RuntimeError("crash")
        with patch(self._IMPORT_TARGET, return_value=mock_module):
            result = self._upload()
        self.assertEqual(result["validation_errors"], [])


# ---------------------------------------------------------------------------
# TestAdapterFailureResult
# ---------------------------------------------------------------------------

class TestAdapterFailureResult(_PolicyFileMixin, unittest.TestCase):

    _IMPORT_TARGET = "tools.upload_asset.upload_asset.importlib.import_module"

    def test_adapter_failure_returns_false(self):
        result = self._upload_patched(_make_failure_module())
        self.assertFalse(result["success"])

    def test_adapter_error_code_in_errors(self):
        result = self._upload_patched(
            _make_failure_module(error_code="MEDIA_UPLOAD_FAILED")
        )
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("MEDIA_UPLOAD_FAILED", codes)

    def test_adapter_message_preserved(self):
        result = self._upload_patched(
            _make_failure_module(message="file too large")
        )
        self.assertIn("file too large", result["errors"][0]["message"])

    def test_adapter_failure_validation_errors_empty(self):
        result = self._upload_patched(_make_failure_module())
        self.assertEqual(result["validation_errors"], [])

    def test_adapter_failure_asset_ref_none(self):
        result = self._upload_patched(_make_failure_module())
        self.assertIsNone(result["asset_ref"])


# ---------------------------------------------------------------------------
# TestSuccessfulUpload
# ---------------------------------------------------------------------------

class TestSuccessfulUpload(_PolicyFileMixin, unittest.TestCase):

    _IMPORT_TARGET = "tools.upload_asset.upload_asset.importlib.import_module"

    def test_success_true(self):
        result = self._upload_patched(_make_success_module())
        self.assertTrue(result["success"])

    def test_asset_ref_from_adapter(self):
        result = self._upload_patched(_make_success_module(asset_ref="media_xyz"))
        self.assertEqual(result["asset_ref"], "media_xyz")

    def test_asset_ref_none_when_adapter_returns_none(self):
        m = MagicMock()
        m.upload_asset.return_value = {"success": True, "asset_ref": None}
        result = self._upload_patched(m)
        self.assertIsNone(result["asset_ref"])

    def test_validation_errors_empty_on_success(self):
        result = self._upload_patched(_make_success_module())
        self.assertEqual(result["validation_errors"], [])

    def test_errors_empty_on_success(self):
        result = self._upload_patched(_make_success_module())
        self.assertEqual(result["errors"], [])

    def test_platform_in_result(self):
        result = self._upload_patched(_make_success_module(), platform="twitter")
        self.assertEqual(result["platform"], "twitter")

    def test_asset_type_in_result(self):
        result = self._upload_patched(_make_success_module())
        self.assertEqual(result["asset_type"], "logo")

    def test_upload_fn_called_with_asset_and_credentials(self):
        mock_module = _make_success_module()
        creds = {"TWITTER_API_KEY": "k"}
        with patch(self._IMPORT_TARGET, return_value=mock_module):
            self._upload(credentials=creds)
        mock_module.upload_asset.assert_called_once_with(_VALID_LOGO, creds)

    def test_upload_fn_called_with_empty_dict_when_no_credentials(self):
        mock_module = _make_success_module()
        with patch(self._IMPORT_TARGET, return_value=mock_module):
            self._upload()
        _, called_creds = mock_module.upload_asset.call_args[0]
        self.assertEqual(called_creds, {})


# ---------------------------------------------------------------------------
# TestResultShape
# ---------------------------------------------------------------------------

class TestResultShape(_PolicyFileMixin, unittest.TestCase):

    _IMPORT_TARGET = "tools.upload_asset.upload_asset.importlib.import_module"

    def _result_success(self):
        return self._upload_patched(_make_success_module())

    def _result_adapter_fail(self):
        return self._upload_patched(_make_failure_module())

    def _result_validation_fail(self):
        return self._upload({"asset_type": "logo", "format": "tiff", "alt_text": "x"})

    def test_success_is_bool_on_success(self):
        self.assertIsInstance(self._result_success()["success"], bool)

    def test_success_is_bool_on_adapter_failure(self):
        self.assertIsInstance(self._result_adapter_fail()["success"], bool)

    def test_success_is_bool_on_validation_failure(self):
        self.assertIsInstance(self._result_validation_fail()["success"], bool)

    def test_validation_errors_always_list(self):
        for r in (self._result_success(), self._result_adapter_fail(), self._result_validation_fail()):
            self.assertIsInstance(r["validation_errors"], list)

    def test_errors_always_list(self):
        for r in (self._result_success(), self._result_adapter_fail(), self._result_validation_fail()):
            self.assertIsInstance(r["errors"], list)

    def test_warnings_always_list(self):
        for r in (self._result_success(), self._result_adapter_fail(), self._result_validation_fail()):
            self.assertIsInstance(r["warnings"], list)

    def test_warnings_always_empty(self):
        for r in (self._result_success(), self._result_adapter_fail(), self._result_validation_fail()):
            self.assertEqual(r["warnings"], [])

    def test_platform_always_present(self):
        for r in (self._result_success(), self._result_adapter_fail(), self._result_validation_fail()):
            self.assertIn("platform", r)

    def test_asset_type_always_present(self):
        for r in (self._result_success(), self._result_adapter_fail(), self._result_validation_fail()):
            self.assertIn("asset_type", r)

    def test_asset_ref_always_present(self):
        for r in (self._result_success(), self._result_adapter_fail(), self._result_validation_fail()):
            self.assertIn("asset_ref", r)

    def test_validate_upload_result_passes_on_all_outcomes(self):
        for r in (self._result_success(), self._result_adapter_fail(), self._result_validation_fail()):
            validate_upload_result(r)  # must not raise


# ---------------------------------------------------------------------------
# TestPlatformNormalisation
# ---------------------------------------------------------------------------

class TestPlatformNormalisation(_PolicyFileMixin, unittest.TestCase):

    _IMPORT_TARGET = "tools.upload_asset.upload_asset.importlib.import_module"

    def test_uppercase_platform_normalised(self):
        result = self._upload_patched(_make_success_module(), platform="TWITTER")
        self.assertEqual(result["platform"], "twitter")

    def test_whitespace_platform_normalised(self):
        result = self._upload_patched(_make_success_module(), platform="  twitter  ")
        self.assertEqual(result["platform"], "twitter")

    def test_mixed_case_with_whitespace_normalised(self):
        result = self._upload_patched(_make_success_module(), platform=" Twitter ")
        self.assertEqual(result["platform"], "twitter")

    def test_unknown_platform_normalised_in_result(self):
        result = self._upload(platform="NOTAPLATFORM")
        self.assertEqual(result["platform"], "notaplatform")


# ---------------------------------------------------------------------------
# TestValidationAndErrorSeparation
# ---------------------------------------------------------------------------

class TestValidationAndErrorSeparation(_PolicyFileMixin, unittest.TestCase):
    """validation_errors and errors are mutually exclusive in normal flow."""

    _IMPORT_TARGET = "tools.upload_asset.upload_asset.importlib.import_module"

    def test_on_validation_failure_errors_is_empty(self):
        result = self._upload({"asset_type": "logo", "format": "tiff", "alt_text": "x"})
        self.assertEqual(result["errors"], [])
        self.assertNotEqual(result["validation_errors"], [])

    def test_on_adapter_failure_validation_errors_is_empty(self):
        result = self._upload_patched(_make_failure_module())
        self.assertEqual(result["validation_errors"], [])
        self.assertNotEqual(result["errors"], [])

    def test_on_success_both_empty(self):
        result = self._upload_patched(_make_success_module())
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["errors"], [])

    def test_on_unknown_platform_errors_is_empty(self):
        result = self._upload(platform="fake")
        self.assertEqual(result["errors"], [])
        self.assertNotEqual(result["validation_errors"], [])


# ---------------------------------------------------------------------------
# TestRealPolicyIntegration
# ---------------------------------------------------------------------------

class TestRealPolicyIntegration(unittest.TestCase):
    """Integration tests with no policy_path injection.

    Uses the real config/asset_policy.json resolved via the Path(__file__)
    anchor inside validate_asset.  The adapter layer is still mocked so
    no network calls are made.  No source_url is provided to avoid
    interference from placeholder strings in approved_source_domains.
    """

    _IMPORT_TARGET = "tools.upload_asset.upload_asset.importlib.import_module"

    def setUp(self):
        _clear_policy_cache()

    def tearDown(self):
        _clear_policy_cache()

    def test_real_policy_validation_pass_reaches_adapter(self):
        """A valid logo reaches the real twitter adapter (which fails on missing creds)."""
        result = upload_asset(
            {"asset_type": "logo", "format": "png", "alt_text": "OpenClaw logo"},
            "twitter",
        )
        # Validation passed; twitter adapter returns AUTH_ERROR when no credentials
        # are provided (no credentials dict passed, so credentials defaults to {}).
        self.assertEqual(result["validation_errors"], [])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn("AUTH_ERROR", codes)

    def test_real_policy_missing_alt_text_fails_before_adapter(self):
        """Real policy require_alt_text: true triggers validation failure."""
        with patch(self._IMPORT_TARGET) as mock_import:
            result = upload_asset(
                {"asset_type": "logo", "format": "png"},
                "twitter",
            )
        mock_import.assert_not_called()
        codes = [e["code"] for e in result["validation_errors"]]
        self.assertIn("ALT_TEXT_REQUIRED", codes)

    def test_real_policy_unknown_platform_fails(self):
        """Unknown platform → validation failure, no adapter attempted."""
        result = upload_asset(
            {"asset_type": "logo", "format": "png", "alt_text": "x"},
            "notaplatform",
        )
        self.assertFalse(result["success"])
        codes = [e["code"] for e in result["validation_errors"]]
        self.assertIn("UNKNOWN_PLATFORM", codes)
        self.assertEqual(result["errors"], [])

    def test_real_policy_successful_upload_via_mock_adapter(self):
        """Full end-to-end: real policy passes, mock adapter succeeds."""
        with patch(self._IMPORT_TARGET, return_value=_make_success_module("real_media_id")):
            result = upload_asset(
                {"asset_type": "logo", "format": "png", "alt_text": "OpenClaw logo"},
                "twitter",
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["asset_ref"], "real_media_id")
        self.assertEqual(result["validation_errors"], [])
        self.assertEqual(result["errors"], [])

    def test_result_shape_valid_on_real_policy_result(self):
        result = upload_asset(
            {"asset_type": "logo", "format": "png", "alt_text": "OpenClaw logo"},
            "twitter",
        )
        validate_upload_result(result)  # must not raise


if __name__ == "__main__":
    unittest.main()
