"""Tests for tools/platform_adapters.

Coverage:
  TestStubAdapter           — success/failure/exception modes, validate called
  TestErrorCodes            — constants present, ALL_ERROR_CODES membership
  TestIsRetryable           — retryable and non-retryable codes
  TestClassifyHttpError     — HTTP status → canonical code mapping
  TestValidateAdapterResult — shape validation, good and bad inputs
  TestRegistry              — get_adapter raises on unknown, known platforms resolve
  TestDispatchAdapter       — dispatch by platform, unknown platform, missing platform
  TestCredentialResolution  — platform adapters read env when credentials=None
  TestPlatformModuleShapes  — each platform module exports required symbols
"""

import os
import unittest

from tools.platform_adapters import (
    AUTH_ERROR,
    CONTENT_REJECTED,
    MEDIA_UPLOAD_FAILED,
    NETWORK_ERROR,
    PERMISSION_ERROR,
    PLATFORM_UNAVAILABLE,
    RATE_LIMITED,
    TIMEOUT,
    UNKNOWN_ERROR,
    ALL_ERROR_CODES,
    StubAdapter,
    classify_http_error,
    get_adapter,
    get_dispatch_adapter,
    is_retryable,
    validate_adapter_result,
)

# ---------------------------------------------------------------------------
# Minimal queue entry used by most tests
# ---------------------------------------------------------------------------

_ENTRY = {
    "queue_id":   "q_test0001",
    "post_id":    "post_001",
    "platform":   "stub",
    "content":    "hello world",
    "slot":       "2026-03-25T09:00:00+00:00",
    "media":      [],
    "actor":      "test_user",
    "created_at": "2026-03-24T10:00:00+00:00",
}


# ---------------------------------------------------------------------------
# TestStubAdapter
# ---------------------------------------------------------------------------

class TestStubAdapter(unittest.TestCase):

    def test_default_success(self):
        adapter = StubAdapter()
        result = adapter(_ENTRY)
        self.assertTrue(result["success"])
        self.assertEqual(result["platform_post_id"], "stub_pid")
        self.assertIsNone(result["platform_response"])

    def test_custom_platform_post_id(self):
        adapter = StubAdapter(platform_post_id="custom_123")
        result = adapter(_ENTRY)
        self.assertTrue(result["success"])
        self.assertEqual(result["platform_post_id"], "custom_123")

    def test_platform_post_id_none(self):
        adapter = StubAdapter(platform_post_id=None)
        result = adapter(_ENTRY)
        self.assertTrue(result["success"])
        self.assertIsNone(result["platform_post_id"])

    def test_failure_mode(self):
        adapter = StubAdapter(success=False, error_code=RATE_LIMITED, message="too many")
        result = adapter(_ENTRY)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], RATE_LIMITED)
        self.assertEqual(result["message"], "too many")

    def test_failure_includes_retryable_flag(self):
        adapter = StubAdapter(success=False, error_code=RATE_LIMITED)
        result = adapter(_ENTRY)
        self.assertTrue(result["retryable"])

    def test_failure_non_retryable(self):
        adapter = StubAdapter(success=False, error_code=AUTH_ERROR)
        result = adapter(_ENTRY)
        self.assertFalse(result["retryable"])

    def test_raise_exception(self):
        adapter = StubAdapter(raise_exception=True, exception_message="simulated crash")
        with self.assertRaises(RuntimeError) as ctx:
            adapter(_ENTRY)
        self.assertIn("simulated crash", str(ctx.exception))

    def test_custom_platform_response(self):
        resp = {"raw": "body"}
        adapter = StubAdapter(platform_response=resp)
        result = adapter(_ENTRY)
        self.assertEqual(result["platform_response"], resp)

    def test_validate_called_on_success(self):
        # validate_adapter_result is called internally; a misconfigured stub
        # would raise ValueError — success path should not raise
        adapter = StubAdapter()
        try:
            adapter(_ENTRY)
        except ValueError:
            self.fail("StubAdapter raised ValueError on valid success result")

    def test_validate_called_on_failure(self):
        adapter = StubAdapter(success=False, error_code=UNKNOWN_ERROR, message="x")
        try:
            adapter(_ENTRY)
        except ValueError:
            self.fail("StubAdapter raised ValueError on valid failure result")


# ---------------------------------------------------------------------------
# TestErrorCodes
# ---------------------------------------------------------------------------

class TestErrorCodes(unittest.TestCase):

    def test_all_constants_are_strings(self):
        codes = [
            AUTH_ERROR, PERMISSION_ERROR, CONTENT_REJECTED, RATE_LIMITED,
            MEDIA_UPLOAD_FAILED, NETWORK_ERROR, PLATFORM_UNAVAILABLE,
            TIMEOUT, UNKNOWN_ERROR,
        ]
        for code in codes:
            self.assertIsInstance(code, str, msg=f"{code!r} is not a str")

    def test_all_error_codes_contains_every_constant(self):
        expected = {
            AUTH_ERROR, PERMISSION_ERROR, CONTENT_REJECTED, RATE_LIMITED,
            MEDIA_UPLOAD_FAILED, NETWORK_ERROR, PLATFORM_UNAVAILABLE,
            TIMEOUT, UNKNOWN_ERROR,
        }
        self.assertEqual(ALL_ERROR_CODES, expected)

    def test_all_error_codes_is_frozenset(self):
        self.assertIsInstance(ALL_ERROR_CODES, frozenset)

    def test_constants_are_unique(self):
        codes = [
            AUTH_ERROR, PERMISSION_ERROR, CONTENT_REJECTED, RATE_LIMITED,
            MEDIA_UPLOAD_FAILED, NETWORK_ERROR, PLATFORM_UNAVAILABLE,
            TIMEOUT, UNKNOWN_ERROR,
        ]
        self.assertEqual(len(codes), len(set(codes)))


# ---------------------------------------------------------------------------
# TestIsRetryable
# ---------------------------------------------------------------------------

class TestIsRetryable(unittest.TestCase):

    def test_retryable_codes(self):
        for code in (RATE_LIMITED, NETWORK_ERROR, PLATFORM_UNAVAILABLE, TIMEOUT):
            self.assertTrue(is_retryable(code), msg=f"{code} should be retryable")

    def test_non_retryable_codes(self):
        for code in (AUTH_ERROR, PERMISSION_ERROR, CONTENT_REJECTED,
                     MEDIA_UPLOAD_FAILED, UNKNOWN_ERROR):
            self.assertFalse(is_retryable(code), msg=f"{code} should not be retryable")

    def test_unknown_string_is_not_retryable(self):
        self.assertFalse(is_retryable("COMPLETELY_MADE_UP"))


# ---------------------------------------------------------------------------
# TestClassifyHttpError
# ---------------------------------------------------------------------------

class TestClassifyHttpError(unittest.TestCase):

    def test_401_auth(self):
        self.assertEqual(classify_http_error(401), AUTH_ERROR)

    def test_403_auth(self):
        self.assertEqual(classify_http_error(403), AUTH_ERROR)

    def test_429_rate_limited(self):
        self.assertEqual(classify_http_error(429), RATE_LIMITED)

    def test_400_content_rejected(self):
        self.assertEqual(classify_http_error(400), CONTENT_REJECTED)

    def test_422_content_rejected(self):
        self.assertEqual(classify_http_error(422), CONTENT_REJECTED)

    def test_500_platform_unavailable(self):
        self.assertEqual(classify_http_error(500), PLATFORM_UNAVAILABLE)

    def test_503_platform_unavailable(self):
        self.assertEqual(classify_http_error(503), PLATFORM_UNAVAILABLE)

    def test_599_platform_unavailable(self):
        self.assertEqual(classify_http_error(599), PLATFORM_UNAVAILABLE)

    def test_200_unknown(self):
        # 200 passed to classify_http_error (shouldn't happen, but must not crash)
        self.assertEqual(classify_http_error(200), UNKNOWN_ERROR)

    def test_418_unknown(self):
        self.assertEqual(classify_http_error(418), UNKNOWN_ERROR)

    def test_body_parameter_accepted(self):
        # body is accepted but unused in base; must not raise
        result = classify_http_error(401, body='{"error": "bad token"}')
        self.assertEqual(result, AUTH_ERROR)


# ---------------------------------------------------------------------------
# TestValidateAdapterResult
# ---------------------------------------------------------------------------

class TestValidateAdapterResult(unittest.TestCase):

    def test_valid_success(self):
        validate_adapter_result({
            "success": True,
            "platform_post_id": "pid_1",
            "platform_response": None,
        })  # must not raise

    def test_valid_failure(self):
        validate_adapter_result({
            "success": False,
            "error_code": AUTH_ERROR,
            "message": "bad token",
        })  # must not raise

    def test_missing_success_raises(self):
        with self.assertRaises(ValueError):
            validate_adapter_result({"platform_post_id": "x", "platform_response": None})

    def test_success_missing_platform_post_id_raises(self):
        with self.assertRaises(ValueError):
            validate_adapter_result({"success": True, "platform_response": None})

    def test_success_missing_platform_response_raises(self):
        with self.assertRaises(ValueError):
            validate_adapter_result({"success": True, "platform_post_id": "x"})

    def test_failure_missing_error_code_raises(self):
        with self.assertRaises(ValueError):
            validate_adapter_result({"success": False, "message": "oops"})

    def test_failure_missing_message_raises(self):
        with self.assertRaises(ValueError):
            validate_adapter_result({"success": False, "error_code": AUTH_ERROR})

    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            validate_adapter_result("not a dict")  # type: ignore

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            validate_adapter_result(None)  # type: ignore


# ---------------------------------------------------------------------------
# TestRegistry
# ---------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):

    def test_unknown_platform_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            get_adapter("nonexistent_platform")
        self.assertIn("nonexistent_platform", str(ctx.exception))

    def test_stub_returns_callable(self):
        adapter = get_adapter("stub")
        self.assertTrue(callable(adapter))

    def test_stub_returns_success(self):
        adapter = get_adapter("stub")
        result = adapter(_ENTRY)
        self.assertTrue(result["success"])

    def test_twitter_returns_callable(self):
        adapter = get_adapter("twitter", credentials={
            "TWITTER_API_KEY": "k",
            "TWITTER_API_SECRET": "s",
            "TWITTER_ACCESS_TOKEN": "t",
            "TWITTER_ACCESS_SECRET": "ts",
        })
        self.assertTrue(callable(adapter))

    def test_linkedin_returns_callable(self):
        adapter = get_adapter("linkedin", credentials={"LINKEDIN_ACCESS_TOKEN": "tok"})
        self.assertTrue(callable(adapter))

    def test_instagram_returns_callable(self):
        adapter = get_adapter("instagram", credentials={
            "INSTAGRAM_ACCESS_TOKEN": "tok",
            "INSTAGRAM_BUSINESS_ACCOUNT_ID": "bid",
        })
        self.assertTrue(callable(adapter))

    def test_facebook_returns_callable(self):
        adapter = get_adapter("facebook", credentials={
            "FACEBOOK_PAGE_ACCESS_TOKEN": "tok",
            "FACEBOOK_PAGE_ID": "pid",
        })
        self.assertTrue(callable(adapter))

    def test_mastodon_returns_callable(self):
        adapter = get_adapter("mastodon", credentials={
            "MASTODON_ACCESS_TOKEN": "tok",
            "MASTODON_INSTANCE_URL": "https://mastodon.social",
        })
        self.assertTrue(callable(adapter))

    def test_empty_string_platform_raises(self):
        with self.assertRaises(ValueError):
            get_adapter("")


# ---------------------------------------------------------------------------
# TestDispatchAdapter
# ---------------------------------------------------------------------------

class TestDispatchAdapter(unittest.TestCase):

    def test_dispatch_to_stub(self):
        dispatch = get_dispatch_adapter()
        entry = dict(_ENTRY, platform="stub")
        result = dispatch(entry)
        self.assertTrue(result["success"])

    def test_unknown_platform_returns_failure_dict(self):
        dispatch = get_dispatch_adapter()
        entry = dict(_ENTRY, platform="tiktok")
        result = dispatch(entry)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], UNKNOWN_ERROR)
        self.assertIn("tiktok", result["message"])

    def test_unknown_platform_does_not_raise(self):
        dispatch = get_dispatch_adapter()
        entry = dict(_ENTRY, platform="tiktok")
        try:
            result = dispatch(entry)
        except Exception as exc:
            self.fail(f"get_dispatch_adapter raised unexpectedly: {exc}")

    def test_missing_platform_field_returns_failure(self):
        dispatch = get_dispatch_adapter()
        entry = {k: v for k, v in _ENTRY.items() if k != "platform"}
        result = dispatch(entry)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], UNKNOWN_ERROR)

    def test_empty_platform_field_returns_failure(self):
        dispatch = get_dispatch_adapter()
        entry = dict(_ENTRY, platform="")
        result = dispatch(entry)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], UNKNOWN_ERROR)

    def test_dispatch_failure_result_is_valid(self):
        dispatch = get_dispatch_adapter()
        entry = dict(_ENTRY, platform="unknown_xyz")
        result = dispatch(entry)
        # Should not raise — shape must be valid
        try:
            validate_adapter_result(result)
        except ValueError as exc:
            self.fail(f"dispatch failure result failed validation: {exc}")

    def test_dispatch_returns_callable(self):
        dispatch = get_dispatch_adapter()
        self.assertTrue(callable(dispatch))


# ---------------------------------------------------------------------------
# TestCredentialResolution
# ---------------------------------------------------------------------------

class TestCredentialResolution(unittest.TestCase):
    """Each platform adapter returns AUTH_ERROR when credentials are missing,
    either from an explicit empty dict or from an empty environment."""

    def _call_with_empty_creds(self, platform: str, cred_keys: list[str]) -> dict:
        """Call the platform adapter with all credentials set to empty string."""
        creds = {k: "" for k in cred_keys}
        adapter = get_adapter(platform, credentials=creds)
        return adapter(_ENTRY)

    def test_twitter_missing_creds_returns_auth_error(self):
        result = self._call_with_empty_creds("twitter", [
            "TWITTER_API_KEY", "TWITTER_API_SECRET",
            "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET",
        ])
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_linkedin_missing_creds_returns_auth_error(self):
        result = self._call_with_empty_creds("linkedin", ["LINKEDIN_ACCESS_TOKEN"])
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_instagram_missing_creds_returns_auth_error(self):
        result = self._call_with_empty_creds("instagram", [
            "INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        ])
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_facebook_missing_creds_returns_auth_error(self):
        result = self._call_with_empty_creds("facebook", [
            "FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ID",
        ])
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_mastodon_missing_creds_returns_auth_error(self):
        result = self._call_with_empty_creds("mastodon", [
            "MASTODON_ACCESS_TOKEN", "MASTODON_INSTANCE_URL",
        ])
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_env_var_resolution_no_env_set(self):
        """get_adapter(platform) with no env vars set returns AUTH_ERROR cleanly."""
        # Clear relevant env vars, then call without explicit credentials.
        keys = [
            "MASTODON_ACCESS_TOKEN", "MASTODON_INSTANCE_URL",
        ]
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            adapter = get_adapter("mastodon")  # credentials=None → reads env
            result = adapter(_ENTRY)
            self.assertFalse(result["success"])
            self.assertEqual(result["error_code"], AUTH_ERROR)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_partial_creds_returns_auth_error(self):
        """Only some credentials present → still AUTH_ERROR."""
        adapter = get_adapter("twitter", credentials={
            "TWITTER_API_KEY": "present",
            "TWITTER_API_SECRET": "",
            "TWITTER_ACCESS_TOKEN": "",
            "TWITTER_ACCESS_SECRET": "",
        })
        result = adapter(_ENTRY)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)
        self.assertIn("TWITTER_API_SECRET", result["message"])


# ---------------------------------------------------------------------------
# TestPlatformModuleShapes
# ---------------------------------------------------------------------------

class TestPlatformModuleShapes(unittest.TestCase):
    """Each platform module must export REQUIRED_CREDENTIALS, _build_payload,
    _parse_response, a PlatformAdapter class, a get_adapter factory, and
    an upload_asset function."""

    _PLATFORMS = ["twitter", "linkedin", "instagram", "facebook", "mastodon"]

    def _import_module(self, platform: str):
        import importlib
        return importlib.import_module(f"tools.platform_adapters.{platform}")

    def test_required_credentials_is_tuple(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                self.assertIsInstance(mod.REQUIRED_CREDENTIALS, tuple,
                                      msg=f"{platform}.REQUIRED_CREDENTIALS must be a tuple")
                self.assertGreater(len(mod.REQUIRED_CREDENTIALS), 0,
                                   msg=f"{platform}.REQUIRED_CREDENTIALS must not be empty")

    def test_build_payload_is_callable(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                self.assertTrue(callable(mod._build_payload),
                                msg=f"{platform}._build_payload must be callable")

    def test_parse_response_is_callable(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                self.assertTrue(callable(mod._parse_response),
                                msg=f"{platform}._parse_response must be callable")

    # Manual mapping to handle non-trivial capitalisation (e.g. LinkedIn).
    _ADAPTER_CLASS_NAMES: dict[str, str] = {
        "twitter":   "TwitterAdapter",
        "linkedin":  "LinkedInAdapter",
        "instagram": "InstagramAdapter",
        "facebook":  "FacebookAdapter",
        "mastodon":  "MastodonAdapter",
    }

    def test_platform_adapter_class_exists(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                class_name = self._ADAPTER_CLASS_NAMES[platform]
                self.assertTrue(hasattr(mod, class_name),
                                msg=f"{platform} module must export {class_name}")
                cls = getattr(mod, class_name)
                self.assertTrue(callable(cls), msg=f"{class_name} must be callable")

    def test_get_adapter_factory_exists(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                self.assertTrue(hasattr(mod, "get_adapter"),
                                msg=f"{platform} module must export get_adapter()")
                self.assertTrue(callable(mod.get_adapter))

    def test_build_payload_raises_not_implemented(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                with self.assertRaises(NotImplementedError,
                                       msg=f"{platform}._build_payload should raise NotImplementedError"):
                    mod._build_payload(_ENTRY)

    def test_parse_response_raises_not_implemented(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                with self.assertRaises(NotImplementedError,
                                       msg=f"{platform}._parse_response should raise NotImplementedError"):
                    mod._parse_response(200, "{}")

    def test_upload_asset_is_callable(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                self.assertTrue(
                    hasattr(mod, "upload_asset") and callable(mod.upload_asset),
                    msg=f"{platform} module must export callable upload_asset()",
                )

    def test_platform_adapter_raises_not_implemented_with_full_creds(self):
        """With valid credentials, __call__ raises NotImplementedError (skeleton)."""
        full_creds = {
            "twitter":   {
                "TWITTER_API_KEY": "k", "TWITTER_API_SECRET": "s",
                "TWITTER_ACCESS_TOKEN": "t", "TWITTER_ACCESS_SECRET": "ts",
            },
            "linkedin":  {"LINKEDIN_ACCESS_TOKEN": "tok"},
            "instagram": {
                "INSTAGRAM_ACCESS_TOKEN": "tok",
                "INSTAGRAM_BUSINESS_ACCOUNT_ID": "bid",
            },
            "facebook":  {
                "FACEBOOK_PAGE_ACCESS_TOKEN": "tok",
                "FACEBOOK_PAGE_ID": "pid",
            },
            "mastodon":  {
                "MASTODON_ACCESS_TOKEN": "tok",
                "MASTODON_INSTANCE_URL": "https://mastodon.social",
            },
        }
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                adapter = get_adapter(platform, credentials=full_creds[platform])
                with self.assertRaises(NotImplementedError,
                                       msg=f"{platform} adapter should raise NotImplementedError"):
                    adapter(_ENTRY)


# ---------------------------------------------------------------------------
# TestAdapterUploadAsset
# ---------------------------------------------------------------------------

class TestAdapterUploadAsset(unittest.TestCase):
    """Covers upload_asset() across all five platform adapters.

    All platforms follow the same stub pattern (credential check +
    injectable _upload_api seam), so subtests run the same assertions
    against every module.
    """

    _PLATFORMS = ["twitter", "linkedin", "instagram", "facebook", "mastodon"]

    # Full credential sets per platform (values are arbitrary non-empty strings).
    _FULL_CREDS = {
        "twitter":   {
            "TWITTER_API_KEY": "k", "TWITTER_API_SECRET": "s",
            "TWITTER_ACCESS_TOKEN": "t", "TWITTER_ACCESS_SECRET": "ts",
        },
        "linkedin":  {"LINKEDIN_ACCESS_TOKEN": "tok"},
        "instagram": {
            "INSTAGRAM_ACCESS_TOKEN": "tok",
            "INSTAGRAM_BUSINESS_ACCOUNT_ID": "bid",
        },
        "facebook":  {
            "FACEBOOK_PAGE_ACCESS_TOKEN": "tok",
            "FACEBOOK_PAGE_ID": "pid",
        },
        "mastodon":  {
            "MASTODON_ACCESS_TOKEN": "tok",
            "MASTODON_INSTANCE_URL": "mastodon.social",
        },
    }

    _ASSET = {"asset_type": "logo", "format": "png", "alt_text": "x"}

    def _import_module(self, platform: str):
        import importlib
        return importlib.import_module(f"tools.platform_adapters.{platform}")

    # --- Credential checks --------------------------------------------------

    def test_empty_credentials_returns_auth_error(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                result = mod.upload_asset(self._ASSET, {})
                self.assertFalse(result["success"])
                self.assertEqual(result["error_code"], "AUTH_ERROR",
                                 msg=f"{platform}: expected AUTH_ERROR on empty creds")

    def test_missing_creds_message_names_keys(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                result = mod.upload_asset(self._ASSET, {})
                # At least one credential key name should appear in the message.
                import importlib as _il
                m = _il.import_module(f"tools.platform_adapters.{platform}")
                first_key = m.REQUIRED_CREDENTIALS[0]
                self.assertIn(first_key, result["message"])

    def test_empty_string_credentials_treated_as_missing(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                import importlib as _il
                m = _il.import_module(f"tools.platform_adapters.{platform}")
                empty_creds = {k: "" for k in m.REQUIRED_CREDENTIALS}
                result = mod.upload_asset(self._ASSET, empty_creds)
                self.assertFalse(result["success"])
                self.assertEqual(result["error_code"], "AUTH_ERROR")

    # --- Default API (NotImplementedError → UPLOAD_NOT_IMPLEMENTED) ---------

    def test_full_creds_default_api_returns_upload_not_implemented(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                creds = self._FULL_CREDS[platform]
                result = mod.upload_asset(self._ASSET, creds)
                self.assertFalse(result["success"])
                self.assertEqual(result["error_code"], "UPLOAD_NOT_IMPLEMENTED",
                                 msg=f"{platform}: expected UPLOAD_NOT_IMPLEMENTED from default API")

    def test_upload_not_implemented_message_is_non_empty(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                result = mod.upload_asset(self._ASSET, self._FULL_CREDS[platform])
                self.assertIsInstance(result["message"], str)
                self.assertGreater(len(result["message"]), 0)

    # --- Injected _upload_api (success) -------------------------------------

    def test_mock_api_success_returns_asset_ref(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                mock_api = lambda a, c: {"success": True, "asset_ref": f"{platform}_media_1"}
                result = mod.upload_asset(
                    self._ASSET, self._FULL_CREDS[platform], _upload_api=mock_api
                )
                self.assertTrue(result["success"])
                self.assertEqual(result["asset_ref"], f"{platform}_media_1")

    def test_mock_api_called_with_asset_and_credentials(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                calls = []
                def mock_api(asset, creds, _p=platform):
                    calls.append((asset, creds))
                    return {"success": True, "asset_ref": "x"}
                creds = self._FULL_CREDS[platform]
                mod.upload_asset(self._ASSET, creds, _upload_api=mock_api)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0], self._ASSET)
                self.assertEqual(calls[0][1], creds)

    # --- Injected _upload_api (failure) -------------------------------------

    def test_mock_api_failure_forwarded(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                mock_api = lambda a, c: {
                    "success": False, "error_code": "RATE_LIMITED", "message": "slow"
                }
                result = mod.upload_asset(
                    self._ASSET, self._FULL_CREDS[platform], _upload_api=mock_api
                )
                self.assertFalse(result["success"])
                self.assertEqual(result["error_code"], "RATE_LIMITED")

    # --- Exception handling -------------------------------------------------

    def test_runtime_error_returns_media_upload_failed(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                def mock_api(a, c):
                    raise RuntimeError("network fail")
                result = mod.upload_asset(
                    self._ASSET, self._FULL_CREDS[platform], _upload_api=mock_api
                )
                self.assertFalse(result["success"])
                self.assertEqual(result["error_code"], "MEDIA_UPLOAD_FAILED")

    def test_not_implemented_exception_from_api_returns_upload_not_implemented(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                def mock_api(a, c):
                    raise NotImplementedError("not done")
                result = mod.upload_asset(
                    self._ASSET, self._FULL_CREDS[platform], _upload_api=mock_api
                )
                self.assertEqual(result["error_code"], "UPLOAD_NOT_IMPLEMENTED")

    # --- Result shape -------------------------------------------------------

    def test_success_result_has_required_keys(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                mock_api = lambda a, c: {"success": True, "asset_ref": "ref"}
                result = mod.upload_asset(
                    self._ASSET, self._FULL_CREDS[platform], _upload_api=mock_api
                )
                self.assertIn("success", result)
                self.assertIn("asset_ref", result)

    def test_failure_result_has_required_keys(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                result = mod.upload_asset(self._ASSET, {})
                self.assertIn("success", result)
                self.assertIn("error_code", result)
                self.assertIn("message", result)

    def test_success_field_is_bool(self):
        for platform in self._PLATFORMS:
            with self.subTest(platform=platform):
                mod = self._import_module(platform)
                result = mod.upload_asset(self._ASSET, {})
                self.assertIsInstance(result["success"], bool)


if __name__ == "__main__":
    unittest.main()
