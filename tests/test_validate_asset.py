"""Tests for tools/validate_asset.

Coverage:
  TestErrorCodeConstants        — all constants are strings, unique, in ALL_ERROR_CODES
  TestValidateAssetResult       — shape validator: valid shape passes; missing fields,
                                  wrong types raise ValueError
  TestHardStopUnknownPlatform   — UNKNOWN_PLATFORM returned immediately; message names
                                  platform; no further errors accumulated
  TestHardStopUploadNotSupported — UPLOAD_NOT_SUPPORTED via mock.patch on
                                  supports_capability; no further errors accumulated
  TestNormalisation             — platform/asset_type/format/context normalised
                                  (lowercased, stripped) before checks
  TestFormatValidation          — format in media_formats passes; format not in fails;
                                  missing format → FORMAT_NOT_ALLOWED; empty string →
                                  FORMAT_NOT_ALLOWED; case-normalised before check
  TestAssetTypeValidation       — known type passes; unknown type → UNKNOWN_ASSET_TYPE;
                                  missing asset_type → UNKNOWN_ASSET_TYPE; format/
                                  alt_text checks still run for unknown asset type
  TestContextValidation         — context in allowed_contexts passes; context not in →
                                  CONTEXT_NOT_ALLOWED; no context skips check; unknown
                                  asset type skips context check
  TestSourceUrlProvenance       — forbidden pattern → FORBIDDEN_SOURCE; unapproved
                                  domain → SOURCE_NOT_APPROVED; approved domain passes;
                                  no source_url skips check; both errors can coexist
  TestLicenseValidation         — require_license true + complete record = pass;
                                  missing record → LICENSE_REQUIRED; incomplete record
                                  → LICENSE_REQUIRED naming missing fields; asset type
                                  with require_license false skips check
  TestAttributionValidation     — require_attribution true + attribution present = pass;
                                  missing → ATTRIBUTION_REQUIRED; require_attribution
                                  false skips check
  TestAltTextValidation         — require_alt_text true + present = pass; absent →
                                  ALT_TEXT_REQUIRED; empty string → ALT_TEXT_REQUIRED;
                                  non-string alt_text → ALT_TEXT_REQUIRED
  TestEditRuleValidation        — locked + any edit → EDIT_NOT_PERMITTED; reference_only
                                  + any edit → EDIT_NOT_PERMITTED; resizable_only +
                                  "resize" = pass; resizable_only + "crop" →
                                  EDIT_NOT_PERMITTED; croppable_only + "crop" = pass;
                                  croppable_only + "resize" → EDIT_NOT_PERMITTED;
                                  editable + any edit = pass; no edit_applied skips
  TestMultiErrorAccumulation    — multiple independent errors all returned in one pass
  TestValidCases                — fully valid logo; fully valid generated_graphic;
                                  customer_photo with complete license
  TestResultShape               — errors/warnings always lists; valid is bool; asset_type
                                  and platform always in result; warnings always []
  TestRealPolicyIntegration     — integration tests against real config/asset_policy.json
                                  with no policy_path injection; confirms real policy and
                                  capability registry are both exercised end-to-end
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from tools.validate_asset import (
    ALL_ERROR_CODES,
    ALT_TEXT_REQUIRED,
    ATTRIBUTION_REQUIRED,
    CONTEXT_NOT_ALLOWED,
    EDIT_NOT_PERMITTED,
    FORBIDDEN_SOURCE,
    FORMAT_NOT_ALLOWED,
    LICENSE_REQUIRED,
    SOURCE_NOT_APPROVED,
    UNKNOWN_ASSET_TYPE,
    UNKNOWN_PLATFORM,
    UPLOAD_NOT_SUPPORTED,
    validate_asset,
    validate_asset_result,
)
from tools.validate_asset.validate_asset import _clear_policy_cache

# ---------------------------------------------------------------------------
# Helpers — minimal valid asset descriptors for each commonly tested type
# ---------------------------------------------------------------------------

def _logo(overrides=None) -> dict:
    base = {
        "asset_type": "logo",
        "format":     "png",
        "alt_text":   "OpenClaw logo",
        "context":    "social_post",
    }
    if overrides:
        base.update(overrides)
    return base


def _generated_graphic(overrides=None) -> dict:
    base = {
        "asset_type": "generated_graphic",
        "format":     "jpeg",
        "alt_text":   "Q1 growth chart",
        "context":    "social_post",
    }
    if overrides:
        base.update(overrides)
    return base


def _customer_photo(overrides=None) -> dict:
    base = {
        "asset_type": "customer_photo",
        "format":     "jpeg",
        "alt_text":   "Customer at event",
        "context":    "social_post",
        "license": {
            "license_type": "permission_granted",
            "license_url":  "https://openclaw.io/permissions/cust001",
            "attribution":  "Photo by Jane Doe, used with permission.",
        },
    }
    if overrides:
        base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Minimal custom policy for isolation (no placeholder strings in domains)
# ---------------------------------------------------------------------------

_MINIMAL_POLICY = {
    "version": "test",
    "approved_source_domains": ["openclaw.io", "assets.openclaw.io"],
    "forbidden_url_patterns":  ["shutterstock\\.com", "gettyimages\\.com"],
    "required_license_fields": ["license_type", "license_url", "attribution"],
    "require_alt_text": True,
    "usage_policies": {
        "logo": {
            "edit_rule":          "locked",
            "require_license":    False,
            "require_attribution": False,
            "allowed_contexts":   ["social_post", "website", "email", "press"],
        },
        "generated_graphic": {
            "edit_rule":          "editable",
            "require_license":    False,
            "require_attribution": False,
            "allowed_contexts":   ["social_post", "website", "email", "blog"],
        },
        "customer_photo": {
            "edit_rule":          "croppable_only",
            "require_license":    True,
            "require_attribution": True,
            "allowed_contexts":   ["social_post"],
        },
        "stock_photo": {
            "edit_rule":          "resizable_only",
            "require_license":    True,
            "require_attribution": True,
            "allowed_contexts":   ["social_post", "website"],
        },
        "website_screenshot": {
            "edit_rule":          "reference_only",
            "require_license":    False,
            "require_attribution": False,
            "allowed_contexts":   ["social_post", "blog"],
        },
    },
}


class _PolicyFileMixin:
    """Mixin that writes a temp policy file and clears the cache around each test."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._policy_path = os.path.join(self._tmpdir.name, "asset_policy.json")
        with open(self._policy_path, "w", encoding="utf-8") as fh:
            json.dump(_MINIMAL_POLICY, fh)
        _clear_policy_cache()

    def tearDown(self):
        _clear_policy_cache()
        self._tmpdir.cleanup()

    def _validate(self, asset: dict, platform: str = "twitter") -> dict:
        return validate_asset(asset, platform, policy_path=self._policy_path)


# ---------------------------------------------------------------------------
# TestErrorCodeConstants
# ---------------------------------------------------------------------------

class TestErrorCodeConstants(unittest.TestCase):

    _CODES = [
        UNKNOWN_PLATFORM, UPLOAD_NOT_SUPPORTED, UNKNOWN_ASSET_TYPE,
        FORMAT_NOT_ALLOWED, CONTEXT_NOT_ALLOWED,
        FORBIDDEN_SOURCE, SOURCE_NOT_APPROVED,
        LICENSE_REQUIRED, ATTRIBUTION_REQUIRED,
        ALT_TEXT_REQUIRED, EDIT_NOT_PERMITTED,
    ]

    def test_all_constants_are_strings(self):
        for code in self._CODES:
            with self.subTest(code=code):
                self.assertIsInstance(code, str)

    def test_all_constants_are_nonempty(self):
        for code in self._CODES:
            with self.subTest(code=code):
                self.assertTrue(code.strip())

    def test_constants_are_unique(self):
        self.assertEqual(len(self._CODES), len(set(self._CODES)))

    def test_all_error_codes_is_frozenset(self):
        self.assertIsInstance(ALL_ERROR_CODES, frozenset)

    def test_all_error_codes_contains_every_constant(self):
        for code in self._CODES:
            with self.subTest(code=code):
                self.assertIn(code, ALL_ERROR_CODES)

    def test_all_error_codes_size_matches(self):
        self.assertEqual(len(ALL_ERROR_CODES), len(self._CODES))


# ---------------------------------------------------------------------------
# TestValidateAssetResult
# ---------------------------------------------------------------------------

class TestValidateAssetResult(unittest.TestCase):

    def _valid_result(self, **overrides):
        base = {
            "valid":      True,
            "platform":   "twitter",
            "asset_type": "logo",
            "errors":     [],
            "warnings":   [],
        }
        base.update(overrides)
        return base

    def test_valid_shape_passes(self):
        validate_asset_result(self._valid_result())  # must not raise

    def test_valid_false_passes(self):
        validate_asset_result(self._valid_result(valid=False, errors=[{"code": "X", "message": "y"}]))

    def test_missing_valid_raises(self):
        r = self._valid_result()
        del r["valid"]
        with self.assertRaises(ValueError):
            validate_asset_result(r)

    def test_missing_errors_raises(self):
        r = self._valid_result()
        del r["errors"]
        with self.assertRaises(ValueError):
            validate_asset_result(r)

    def test_missing_warnings_raises(self):
        r = self._valid_result()
        del r["warnings"]
        with self.assertRaises(ValueError):
            validate_asset_result(r)

    def test_missing_asset_type_raises(self):
        r = self._valid_result()
        del r["asset_type"]
        with self.assertRaises(ValueError):
            validate_asset_result(r)

    def test_valid_wrong_type_raises(self):
        with self.assertRaises(ValueError):
            validate_asset_result(self._valid_result(valid="yes"))

    def test_errors_wrong_type_raises(self):
        with self.assertRaises(ValueError):
            validate_asset_result(self._valid_result(errors="none"))

    def test_warnings_wrong_type_raises(self):
        with self.assertRaises(ValueError):
            validate_asset_result(self._valid_result(warnings="none"))

    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            validate_asset_result("not a dict")  # type: ignore[arg-type]

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            validate_asset_result(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestHardStopUnknownPlatform
# ---------------------------------------------------------------------------

class TestHardStopUnknownPlatform(_PolicyFileMixin, unittest.TestCase):

    def test_unknown_platform_returns_error(self):
        result = self._validate(_logo(), platform="tiktok")
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(UNKNOWN_PLATFORM, codes)

    def test_unknown_platform_message_names_platform(self):
        result = self._validate(_logo(), platform="tiktok")
        msg = result["errors"][0]["message"]
        self.assertIn("tiktok", msg)

    def test_unknown_platform_is_only_error(self):
        # Hard stop — no subsequent errors accumulated
        result = self._validate(_logo(), platform="tiktok")
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], UNKNOWN_PLATFORM)

    def test_unknown_platform_normalised_in_result(self):
        result = self._validate(_logo(), platform="  TikTok  ")
        self.assertEqual(result["platform"], "tiktok")

    def test_empty_platform_raises_unknown_platform(self):
        result = self._validate(_logo(), platform="")
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(UNKNOWN_PLATFORM, codes)


# ---------------------------------------------------------------------------
# TestHardStopUploadNotSupported
# ---------------------------------------------------------------------------

class TestHardStopUploadNotSupported(_PolicyFileMixin, unittest.TestCase):

    def test_upload_not_supported_returns_error(self):
        with patch(
            "tools.validate_asset.validate_asset.supports_capability",
            return_value=False,
        ):
            result = self._validate(_logo(), platform="twitter")
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(UPLOAD_NOT_SUPPORTED, codes)

    def test_upload_not_supported_is_only_error(self):
        with patch(
            "tools.validate_asset.validate_asset.supports_capability",
            return_value=False,
        ):
            result = self._validate(_logo(), platform="twitter")
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], UPLOAD_NOT_SUPPORTED)

    def test_upload_not_supported_message_names_platform(self):
        with patch(
            "tools.validate_asset.validate_asset.supports_capability",
            return_value=False,
        ):
            result = self._validate(_logo(), platform="twitter")
        msg = result["errors"][0]["message"]
        # display_name "Twitter / X" or platform ID should appear
        self.assertTrue(
            "twitter" in msg.lower() or "twitter / x" in msg.lower(),
            f"Platform not mentioned in: {msg}",
        )


# ---------------------------------------------------------------------------
# TestNormalisation
# ---------------------------------------------------------------------------

class TestNormalisation(_PolicyFileMixin, unittest.TestCase):

    def test_platform_lowercased_in_result(self):
        result = self._validate(_logo(), platform="Twitter")
        self.assertEqual(result["platform"], "twitter")

    def test_platform_stripped_in_result(self):
        result = self._validate(_logo(), platform="  twitter  ")
        self.assertEqual(result["platform"], "twitter")

    def test_asset_type_lowercased(self):
        asset = _logo({"asset_type": "LOGO"})
        result = self._validate(asset)
        self.assertEqual(result["asset_type"], "logo")

    def test_asset_type_stripped(self):
        asset = _logo({"asset_type": "  logo  "})
        result = self._validate(asset)
        self.assertEqual(result["asset_type"], "logo")

    def test_format_normalised_before_check(self):
        # "PNG" should be treated as "png" and accepted for twitter
        asset = _logo({"format": "PNG"})
        result = self._validate(asset)
        self.assertTrue(result["valid"], result["errors"])

    def test_context_normalised_before_check(self):
        asset = _logo({"context": "SOCIAL_POST"})
        result = self._validate(asset)
        self.assertTrue(result["valid"], result["errors"])


# ---------------------------------------------------------------------------
# TestFormatValidation
# ---------------------------------------------------------------------------

class TestFormatValidation(_PolicyFileMixin, unittest.TestCase):

    def test_accepted_format_passes(self):
        result = self._validate(_logo({"format": "png"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(FORMAT_NOT_ALLOWED, codes)

    def test_unaccepted_format_returns_error(self):
        result = self._validate(_logo({"format": "tiff"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(FORMAT_NOT_ALLOWED, codes)

    def test_unaccepted_format_error_names_format(self):
        result = self._validate(_logo({"format": "tiff"}))
        err = next(e for e in result["errors"] if e["code"] == FORMAT_NOT_ALLOWED)
        self.assertIn("tiff", err["message"])

    def test_missing_format_returns_format_not_allowed(self):
        asset = _logo()
        del asset["format"]
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(FORMAT_NOT_ALLOWED, codes)

    def test_empty_string_format_returns_format_not_allowed(self):
        result = self._validate(_logo({"format": ""}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(FORMAT_NOT_ALLOWED, codes)

    def test_whitespace_only_format_returns_format_not_allowed(self):
        result = self._validate(_logo({"format": "   "}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(FORMAT_NOT_ALLOWED, codes)

    def test_format_with_dot_prefix_fails(self):
        # ".png" is not normalised to "png" — the dot must not be present
        result = self._validate(_logo({"format": ".png"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(FORMAT_NOT_ALLOWED, codes)

    def test_mp4_accepted_on_twitter(self):
        result = self._validate(_logo({"format": "mp4"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(FORMAT_NOT_ALLOWED, codes)

    def test_webm_accepted_on_mastodon_not_twitter(self):
        # webm is in mastodon's media_formats but not twitter's
        result_twitter = self._validate(_logo({"format": "webm"}), platform="twitter")
        result_mastodon = self._validate(_logo({"format": "webm"}), platform="mastodon")
        tw_codes = [e["code"] for e in result_twitter["errors"]]
        ma_codes = [e["code"] for e in result_mastodon["errors"]]
        self.assertIn(FORMAT_NOT_ALLOWED, tw_codes)
        self.assertNotIn(FORMAT_NOT_ALLOWED, ma_codes)

    def test_format_error_includes_accepted_formats(self):
        result = self._validate(_logo({"format": "tiff"}))
        err = next(e for e in result["errors"] if e["code"] == FORMAT_NOT_ALLOWED)
        self.assertIn("accepted_formats", err)
        self.assertIsInstance(err["accepted_formats"], list)

    def test_format_normalised_to_lowercase_for_lookup(self):
        # "JPEG" should resolve to "jpeg" and pass for twitter
        result = self._validate(_logo({"format": "JPEG"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(FORMAT_NOT_ALLOWED, codes)


# ---------------------------------------------------------------------------
# TestAssetTypeValidation
# ---------------------------------------------------------------------------

class TestAssetTypeValidation(_PolicyFileMixin, unittest.TestCase):

    def test_known_asset_type_passes(self):
        result = self._validate(_logo())
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(UNKNOWN_ASSET_TYPE, codes)

    def test_unknown_asset_type_returns_error(self):
        result = self._validate(_logo({"asset_type": "hologram"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(UNKNOWN_ASSET_TYPE, codes)

    def test_unknown_asset_type_names_type_in_message(self):
        result = self._validate(_logo({"asset_type": "hologram"}))
        err = next(e for e in result["errors"] if e["code"] == UNKNOWN_ASSET_TYPE)
        self.assertIn("hologram", err["message"])

    def test_missing_asset_type_returns_error(self):
        asset = _logo()
        del asset["asset_type"]
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(UNKNOWN_ASSET_TYPE, codes)

    def test_unknown_asset_type_does_not_block_format_check(self):
        # format check still runs even when asset_type is unknown
        result = self._validate({"asset_type": "hologram", "format": "tiff", "alt_text": "x"})
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(UNKNOWN_ASSET_TYPE, codes)
        self.assertIn(FORMAT_NOT_ALLOWED, codes)

    def test_unknown_asset_type_does_not_block_alt_text_check(self):
        result = self._validate({"asset_type": "hologram", "format": "png"})
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(UNKNOWN_ASSET_TYPE, codes)
        self.assertIn(ALT_TEXT_REQUIRED, codes)

    def test_asset_type_in_result(self):
        result = self._validate(_logo())
        self.assertEqual(result["asset_type"], "logo")

    def test_asset_type_none_when_missing(self):
        asset = _logo()
        del asset["asset_type"]
        result = self._validate(asset)
        self.assertIsNone(result["asset_type"])


# ---------------------------------------------------------------------------
# TestContextValidation
# ---------------------------------------------------------------------------

class TestContextValidation(_PolicyFileMixin, unittest.TestCase):

    def test_allowed_context_passes(self):
        result = self._validate(_logo({"context": "social_post"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(CONTEXT_NOT_ALLOWED, codes)

    def test_disallowed_context_returns_error(self):
        # "blog" is not in logo's allowed_contexts
        result = self._validate(_logo({"context": "blog"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(CONTEXT_NOT_ALLOWED, codes)

    def test_disallowed_context_names_context_in_message(self):
        result = self._validate(_logo({"context": "blog"}))
        err = next(e for e in result["errors"] if e["code"] == CONTEXT_NOT_ALLOWED)
        self.assertIn("blog", err["message"])

    def test_missing_context_skips_check(self):
        asset = _logo()
        del asset["context"]
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(CONTEXT_NOT_ALLOWED, codes)

    def test_empty_context_skips_check(self):
        result = self._validate(_logo({"context": ""}))
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(CONTEXT_NOT_ALLOWED, codes)

    def test_unknown_asset_type_skips_context_check(self):
        result = self._validate({"asset_type": "hologram", "format": "png",
                                 "alt_text": "x", "context": "social_post"})
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(CONTEXT_NOT_ALLOWED, codes)
        self.assertIn(UNKNOWN_ASSET_TYPE, codes)


# ---------------------------------------------------------------------------
# TestSourceUrlProvenance
# ---------------------------------------------------------------------------

class TestSourceUrlProvenance(_PolicyFileMixin, unittest.TestCase):

    def test_approved_domain_passes(self):
        asset = _logo({"source_url": "https://assets.openclaw.io/logo.png"})
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(FORBIDDEN_SOURCE, codes)
        self.assertNotIn(SOURCE_NOT_APPROVED, codes)

    def test_forbidden_pattern_returns_error(self):
        asset = _logo({"source_url": "https://www.shutterstock.com/image/photo.jpg"})
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(FORBIDDEN_SOURCE, codes)

    def test_forbidden_pattern_message_names_pattern(self):
        asset = _logo({"source_url": "https://www.shutterstock.com/photo.jpg"})
        result = self._validate(asset)
        err = next(e for e in result["errors"] if e["code"] == FORBIDDEN_SOURCE)
        self.assertIn("shutterstock", err["message"])

    def test_unapproved_domain_returns_source_not_approved(self):
        asset = _logo({"source_url": "https://unsplash.com/photo.jpg"})
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(SOURCE_NOT_APPROVED, codes)

    def test_unapproved_domain_names_hostname_in_error(self):
        asset = _logo({"source_url": "https://unsplash.com/photo.jpg"})
        result = self._validate(asset)
        err = next(e for e in result["errors"] if e["code"] == SOURCE_NOT_APPROVED)
        self.assertIn("unsplash.com", err["message"])

    def test_no_source_url_skips_provenance_checks(self):
        result = self._validate(_logo())
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(FORBIDDEN_SOURCE, codes)
        self.assertNotIn(SOURCE_NOT_APPROVED, codes)

    def test_forbidden_and_unapproved_both_returned(self):
        # shutterstock.com is both forbidden and unapproved → both errors
        asset = _logo({"source_url": "https://shutterstock.com/photo.jpg"})
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(FORBIDDEN_SOURCE, codes)
        self.assertIn(SOURCE_NOT_APPROVED, codes)

    def test_subdomain_of_approved_domain_passes(self):
        asset = _logo({"source_url": "https://media.openclaw.io/logo.png"})
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(SOURCE_NOT_APPROVED, codes)

    def test_empty_source_url_skips_check(self):
        result = self._validate(_logo({"source_url": ""}))
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(FORBIDDEN_SOURCE, codes)
        self.assertNotIn(SOURCE_NOT_APPROVED, codes)


# ---------------------------------------------------------------------------
# TestLicenseValidation
# ---------------------------------------------------------------------------

class TestLicenseValidation(_PolicyFileMixin, unittest.TestCase):

    def test_require_license_true_complete_record_passes(self):
        result = self._validate(_customer_photo())
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(LICENSE_REQUIRED, codes)

    def test_require_license_true_no_record_returns_error(self):
        asset = _customer_photo()
        del asset["license"]
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(LICENSE_REQUIRED, codes)

    def test_require_license_true_incomplete_record_returns_error(self):
        asset = _customer_photo({"license": {"license_type": "MIT"}})
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(LICENSE_REQUIRED, codes)

    def test_license_error_names_missing_fields(self):
        asset = _customer_photo({"license": {"license_type": "MIT"}})
        result = self._validate(asset)
        err = next(e for e in result["errors"] if e["code"] == LICENSE_REQUIRED)
        self.assertIn("missing_fields", err)
        self.assertIn("license_url", err["missing_fields"])
        self.assertIn("attribution", err["missing_fields"])

    def test_require_license_false_skips_check(self):
        # logo has require_license: false → no license error even without record
        asset = _logo()  # no license field
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(LICENSE_REQUIRED, codes)


# ---------------------------------------------------------------------------
# TestAttributionValidation
# ---------------------------------------------------------------------------

class TestAttributionValidation(_PolicyFileMixin, unittest.TestCase):

    def test_attribution_present_passes(self):
        result = self._validate(_customer_photo())
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(ATTRIBUTION_REQUIRED, codes)

    def test_attribution_missing_returns_error(self):
        asset = _customer_photo({
            "license": {
                "license_type": "permission_granted",
                "license_url":  "https://openclaw.io/perm/001",
                # attribution omitted
            }
        })
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(ATTRIBUTION_REQUIRED, codes)

    def test_attribution_empty_string_returns_error(self):
        asset = _customer_photo({
            "license": {
                "license_type": "permission_granted",
                "license_url":  "https://openclaw.io/perm/001",
                "attribution":  "",
            }
        })
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(ATTRIBUTION_REQUIRED, codes)

    def test_require_attribution_false_skips_check(self):
        # logo has require_attribution: false
        asset = _logo({"license": {"license_type": "MIT", "license_url": "http://x", "attribution": ""}})
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(ATTRIBUTION_REQUIRED, codes)

    def test_no_license_record_triggers_attribution_error(self):
        # require_attribution is true for customer_photo; no license dict → error
        asset = _customer_photo()
        del asset["license"]
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(ATTRIBUTION_REQUIRED, codes)


# ---------------------------------------------------------------------------
# TestAltTextValidation
# ---------------------------------------------------------------------------

class TestAltTextValidation(_PolicyFileMixin, unittest.TestCase):

    def test_alt_text_present_passes(self):
        result = self._validate(_logo())
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(ALT_TEXT_REQUIRED, codes)

    def test_missing_alt_text_returns_error(self):
        asset = _logo()
        del asset["alt_text"]
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(ALT_TEXT_REQUIRED, codes)

    def test_empty_string_alt_text_returns_error(self):
        result = self._validate(_logo({"alt_text": ""}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(ALT_TEXT_REQUIRED, codes)

    def test_whitespace_only_alt_text_returns_error(self):
        result = self._validate(_logo({"alt_text": "   "}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(ALT_TEXT_REQUIRED, codes)

    def test_non_string_alt_text_returns_error(self):
        result = self._validate(_logo({"alt_text": 42}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(ALT_TEXT_REQUIRED, codes)


# ---------------------------------------------------------------------------
# TestEditRuleValidation
# ---------------------------------------------------------------------------

class TestEditRuleValidation(_PolicyFileMixin, unittest.TestCase):

    def test_locked_any_edit_returns_edit_not_permitted(self):
        result = self._validate(_logo({"edit_applied": "resize"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(EDIT_NOT_PERMITTED, codes)

    def test_locked_any_edit_error_names_edit_and_rule(self):
        result = self._validate(_logo({"edit_applied": "resize"}))
        err = next(e for e in result["errors"] if e["code"] == EDIT_NOT_PERMITTED)
        self.assertIn("resize", err["message"])
        self.assertIn("locked", err["message"])

    def test_reference_only_any_edit_returns_edit_not_permitted(self):
        asset = {
            "asset_type":   "website_screenshot",
            "format":       "png",
            "alt_text":     "Screenshot",
            "context":      "social_post",
            "edit_applied": "colour_correct",
        }
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(EDIT_NOT_PERMITTED, codes)

    def test_resizable_only_resize_passes(self):
        asset = {
            "asset_type":   "stock_photo",
            "format":       "jpeg",
            "alt_text":     "Stock",
            "context":      "social_post",
            "edit_applied": "resize",
            "license": {
                "license_type": "commercial",
                "license_url":  "https://openclaw.io/lic/001",
                "attribution":  "Photographer Name",
            },
        }
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(EDIT_NOT_PERMITTED, codes)

    def test_resizable_only_crop_returns_edit_not_permitted(self):
        asset = {
            "asset_type":   "stock_photo",
            "format":       "jpeg",
            "alt_text":     "Stock",
            "context":      "social_post",
            "edit_applied": "crop",
            "license": {
                "license_type": "commercial",
                "license_url":  "https://openclaw.io/lic/001",
                "attribution":  "Photographer Name",
            },
        }
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(EDIT_NOT_PERMITTED, codes)

    def test_croppable_only_crop_passes(self):
        result = self._validate(_customer_photo({"edit_applied": "crop"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(EDIT_NOT_PERMITTED, codes)

    def test_croppable_only_resize_returns_edit_not_permitted(self):
        result = self._validate(_customer_photo({"edit_applied": "resize"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(EDIT_NOT_PERMITTED, codes)

    def test_editable_any_edit_passes(self):
        for edit in ("resize", "crop", "colour_correct", "composite", "blur"):
            with self.subTest(edit=edit):
                result = self._validate(_generated_graphic({"edit_applied": edit}))
                codes = [e["code"] for e in result["errors"]]
                self.assertNotIn(EDIT_NOT_PERMITTED, codes)

    def test_no_edit_applied_skips_check(self):
        asset = _logo()  # no edit_applied
        result = self._validate(asset)
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(EDIT_NOT_PERMITTED, codes)

    def test_empty_edit_applied_skips_check(self):
        result = self._validate(_logo({"edit_applied": ""}))
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(EDIT_NOT_PERMITTED, codes)

    def test_edit_not_permitted_error_includes_context_fields(self):
        result = self._validate(_logo({"edit_applied": "resize"}))
        err = next(e for e in result["errors"] if e["code"] == EDIT_NOT_PERMITTED)
        self.assertIn("edit_applied", err)
        self.assertIn("edit_rule", err)
        self.assertEqual(err["edit_applied"], "resize")
        self.assertEqual(err["edit_rule"], "locked")


# ---------------------------------------------------------------------------
# TestMultiErrorAccumulation
# ---------------------------------------------------------------------------

class TestMultiErrorAccumulation(_PolicyFileMixin, unittest.TestCase):

    def test_multiple_independent_errors_accumulated(self):
        # bad format + bad context + edit violation + missing alt_text
        asset = {
            "asset_type":   "logo",
            "format":       "tiff",        # FORMAT_NOT_ALLOWED
            "context":      "blog",        # CONTEXT_NOT_ALLOWED
            "edit_applied": "resize",      # EDIT_NOT_PERMITTED (locked)
            # alt_text missing              → ALT_TEXT_REQUIRED
        }
        result = self._validate(asset)
        codes = set(e["code"] for e in result["errors"])
        self.assertIn(FORMAT_NOT_ALLOWED, codes)
        self.assertIn(CONTEXT_NOT_ALLOWED, codes)
        self.assertIn(EDIT_NOT_PERMITTED, codes)
        self.assertIn(ALT_TEXT_REQUIRED, codes)
        self.assertFalse(result["valid"])

    def test_provenance_and_license_errors_coexist(self):
        # customer_photo: forbidden source URL + missing license
        asset = _customer_photo({
            "source_url": "https://shutterstock.com/photo.jpg",
        })
        del asset["license"]
        result = self._validate(asset)
        codes = set(e["code"] for e in result["errors"])
        self.assertIn(FORBIDDEN_SOURCE, codes)
        self.assertIn(SOURCE_NOT_APPROVED, codes)
        self.assertIn(LICENSE_REQUIRED, codes)
        self.assertIn(ATTRIBUTION_REQUIRED, codes)

    def test_unknown_asset_type_and_format_error_coexist(self):
        result = self._validate({"asset_type": "hologram", "format": "tiff", "alt_text": "x"})
        codes = set(e["code"] for e in result["errors"])
        self.assertIn(UNKNOWN_ASSET_TYPE, codes)
        self.assertIn(FORMAT_NOT_ALLOWED, codes)


# ---------------------------------------------------------------------------
# TestValidCases
# ---------------------------------------------------------------------------

class TestValidCases(_PolicyFileMixin, unittest.TestCase):

    def test_valid_logo(self):
        result = self._validate(_logo())
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])

    def test_valid_generated_graphic(self):
        result = self._validate(_generated_graphic())
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_valid_customer_photo_with_full_license(self):
        result = self._validate(_customer_photo())
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_valid_on_multiple_platforms(self):
        for platform in ("twitter", "linkedin", "instagram", "facebook", "mastodon"):
            with self.subTest(platform=platform):
                result = self._validate(_logo(), platform=platform)
                codes = [e["code"] for e in result["errors"]]
                # Only possible error for a clean logo is platform-specific
                # format issues — png is accepted on all platforms
                self.assertNotIn(UNKNOWN_PLATFORM, codes)
                self.assertNotIn(UPLOAD_NOT_SUPPORTED, codes)

    def test_valid_generated_graphic_with_edit(self):
        result = self._validate(_generated_graphic({"edit_applied": "resize"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(EDIT_NOT_PERMITTED, codes)

    def test_valid_logo_mp4_format(self):
        # mp4 is a valid format for twitter
        result = self._validate(_logo({"format": "mp4"}))
        codes = [e["code"] for e in result["errors"]]
        self.assertNotIn(FORMAT_NOT_ALLOWED, codes)


# ---------------------------------------------------------------------------
# TestResultShape
# ---------------------------------------------------------------------------

class TestResultShape(_PolicyFileMixin, unittest.TestCase):

    def test_errors_always_list(self):
        for asset in (_logo(), _logo({"format": "tiff"})):
            result = self._validate(asset)
            self.assertIsInstance(result["errors"], list)

    def test_warnings_always_empty_list(self):
        for asset in (_logo(), _logo({"format": "tiff"})):
            result = self._validate(asset)
            self.assertIsInstance(result["warnings"], list)
            self.assertEqual(result["warnings"], [])

    def test_valid_is_bool(self):
        result = self._validate(_logo())
        self.assertIsInstance(result["valid"], bool)

    def test_platform_always_in_result(self):
        result = self._validate(_logo(), platform="twitter")
        self.assertIn("platform", result)
        self.assertEqual(result["platform"], "twitter")

    def test_asset_type_in_result(self):
        result = self._validate(_logo())
        self.assertIn("asset_type", result)

    def test_validate_asset_result_passes_on_valid(self):
        result = self._validate(_logo())
        validate_asset_result(result)  # must not raise

    def test_validate_asset_result_passes_on_invalid(self):
        result = self._validate(_logo({"format": "tiff"}))
        validate_asset_result(result)  # must not raise

    def test_hard_stop_result_shape_is_valid(self):
        result = self._validate(_logo(), platform="tiktok")
        validate_asset_result(result)  # must not raise


# ---------------------------------------------------------------------------
# TestRealPolicyIntegration
# ---------------------------------------------------------------------------

class TestRealPolicyIntegration(unittest.TestCase):
    """Integration tests that call validate_asset() without policy_path injection.

    These tests exercise the real config/asset_policy.json resolved via the
    Path(__file__) anchor in validate_asset.py.  No source_url is provided so
    the placeholder strings in approved_source_domains / forbidden_url_patterns
    do not affect outcomes.
    """

    def setUp(self):
        _clear_policy_cache()

    def tearDown(self):
        _clear_policy_cache()

    def test_real_policy_loads(self):
        """validate_asset() loads real config/asset_policy.json without error."""
        result = validate_asset(
            {"asset_type": "logo", "format": "png", "alt_text": "x"},
            "twitter",
        )
        self.assertIsInstance(result, dict)

    def test_valid_logo_twitter(self):
        """logo + png + social_post + alt_text is fully valid on twitter."""
        result = validate_asset(
            {
                "asset_type": "logo",
                "format":     "png",
                "alt_text":   "OpenClaw logo",
                "context":    "social_post",
            },
            "twitter",
        )
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_missing_alt_text_fails(self):
        """Omitting alt_text triggers ALT_TEXT_REQUIRED (real require_alt_text: true)."""
        result = validate_asset(
            {"asset_type": "logo", "format": "png"},
            "twitter",
        )
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(ALT_TEXT_REQUIRED, codes)
        self.assertEqual(len(result["errors"]), 1)

    def test_customer_photo_missing_license(self):
        """customer_photo without license → LICENSE_REQUIRED + ATTRIBUTION_REQUIRED."""
        result = validate_asset(
            {
                "asset_type": "customer_photo",
                "format":     "jpeg",
                "alt_text":   "Jane at our event",
                "context":    "social_post",
            },
            "twitter",
        )
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(LICENSE_REQUIRED, codes)
        self.assertIn(ATTRIBUTION_REQUIRED, codes)

    def test_invalid_format_for_twitter(self):
        """tiff is not in twitter's media_formats → FORMAT_NOT_ALLOWED."""
        result = validate_asset(
            {"asset_type": "logo", "format": "tiff", "alt_text": "OpenClaw logo"},
            "twitter",
        )
        self.assertFalse(result["valid"])
        codes = [e["code"] for e in result["errors"]]
        self.assertIn(FORMAT_NOT_ALLOWED, codes)

    def test_unknown_platform_hard_stop(self):
        """Unregistered platform → UNKNOWN_PLATFORM; no further errors."""
        result = validate_asset(
            {"asset_type": "logo", "format": "png", "alt_text": "x"},
            "notaplatform",
        )
        self.assertFalse(result["valid"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["code"], UNKNOWN_PLATFORM)

    def test_result_shape_is_valid(self):
        """validate_asset_result() accepts the real-policy result without raising."""
        result = validate_asset(
            {
                "asset_type": "logo",
                "format":     "png",
                "alt_text":   "OpenClaw logo",
                "context":    "social_post",
            },
            "twitter",
        )
        validate_asset_result(result)  # must not raise


if __name__ == "__main__":
    unittest.main()
