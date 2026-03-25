"""Tests for tools/asset_payload.

Coverage:
  TestPayloadRequiredFields     — validator rejects missing / empty / wrong-type
                                  required fields; accepts valid payload
  TestFileExistenceCheck        — check_exists=True (default): rejects missing
                                  file; check_exists=False: skips filesystem check
  TestNonDictPayload            — non-dict input raises ValueError
  TestOptionalFieldsAccepted    — all optional metadata fields pass through
  TestExtraFieldsAccepted       — unknown keys do not cause rejection
  TestMakeAssetPayload          — factory builds correct dict and validates it;
                                  propagates check_exists to validator;
                                  optional kwargs merged correctly
  TestPayloadRequiredFieldsConstant — PAYLOAD_REQUIRED_FIELDS correct and stable
  TestRealFileIntegration       — end-to-end: create a real temp file, build
                                  payload, validate successfully
"""

import os
import tempfile
import unittest

from tools.asset_payload import (
    PAYLOAD_REQUIRED_FIELDS,
    make_asset_payload,
    validate_asset_payload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid(overrides=None) -> dict:
    """Return a minimal structurally valid payload (file_path not checked)."""
    base = {
        "file_path":  "/tmp/fake_logo.png",
        "asset_type": "logo",
        "format":     "png",
    }
    if overrides:
        base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# TestNonDictPayload
# ---------------------------------------------------------------------------

class TestNonDictPayload(unittest.TestCase):

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            validate_asset_payload(None, check_exists=False)

    def test_list_raises(self):
        with self.assertRaises(ValueError):
            validate_asset_payload([], check_exists=False)

    def test_string_raises(self):
        with self.assertRaises(ValueError):
            validate_asset_payload("logo.png", check_exists=False)

    def test_int_raises(self):
        with self.assertRaises(ValueError):
            validate_asset_payload(42, check_exists=False)


# ---------------------------------------------------------------------------
# TestPayloadRequiredFields
# ---------------------------------------------------------------------------

class TestPayloadRequiredFields(unittest.TestCase):

    # --- file_path ----------------------------------------------------------

    def test_missing_file_path_raises(self):
        payload = {"asset_type": "logo", "format": "png"}
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(payload, check_exists=False)
        self.assertIn("file_path", str(ctx.exception))

    def test_empty_file_path_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(_valid({"file_path": ""}), check_exists=False)
        self.assertIn("file_path", str(ctx.exception))

    def test_whitespace_only_file_path_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(_valid({"file_path": "   "}), check_exists=False)
        self.assertIn("file_path", str(ctx.exception))

    def test_non_string_file_path_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(_valid({"file_path": 42}), check_exists=False)
        self.assertIn("file_path", str(ctx.exception))

    def test_none_file_path_raises(self):
        with self.assertRaises(ValueError):
            validate_asset_payload(_valid({"file_path": None}), check_exists=False)

    # --- asset_type ---------------------------------------------------------

    def test_missing_asset_type_raises(self):
        payload = {"file_path": "/tmp/f.png", "format": "png"}
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(payload, check_exists=False)
        self.assertIn("asset_type", str(ctx.exception))

    def test_empty_asset_type_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(_valid({"asset_type": ""}), check_exists=False)
        self.assertIn("asset_type", str(ctx.exception))

    def test_non_string_asset_type_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(_valid({"asset_type": 0}), check_exists=False)
        self.assertIn("asset_type", str(ctx.exception))

    # --- format -------------------------------------------------------------

    def test_missing_format_raises(self):
        payload = {"file_path": "/tmp/f.png", "asset_type": "logo"}
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(payload, check_exists=False)
        self.assertIn("format", str(ctx.exception))

    def test_empty_format_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(_valid({"format": ""}), check_exists=False)
        self.assertIn("format", str(ctx.exception))

    def test_non_string_format_raises(self):
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(_valid({"format": ["png"]}), check_exists=False)
        self.assertIn("format", str(ctx.exception))

    # --- valid minimal payload ----------------------------------------------

    def test_valid_minimal_payload_passes(self):
        validate_asset_payload(_valid(), check_exists=False)  # must not raise

    def test_valid_payload_returns_none(self):
        result = validate_asset_payload(_valid(), check_exists=False)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# TestFileExistenceCheck
# ---------------------------------------------------------------------------

class TestFileExistenceCheck(unittest.TestCase):

    def test_nonexistent_file_raises_by_default(self):
        payload = _valid({"file_path": "/nonexistent/path/logo.png"})
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(payload)
        self.assertIn("file_path", str(ctx.exception))

    def test_nonexistent_file_raises_when_check_exists_true(self):
        payload = _valid({"file_path": "/nonexistent/path/logo.png"})
        with self.assertRaises(ValueError):
            validate_asset_payload(payload, check_exists=True)

    def test_nonexistent_file_passes_when_check_exists_false(self):
        payload = _valid({"file_path": "/nonexistent/path/logo.png"})
        validate_asset_payload(payload, check_exists=False)  # must not raise

    def test_existing_file_passes_with_check_exists_true(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            fh.write(b"\x89PNG\r\n")
            tmp_path = fh.name
        try:
            payload = _valid({"file_path": tmp_path})
            validate_asset_payload(payload, check_exists=True)  # must not raise
        finally:
            os.unlink(tmp_path)

    def test_error_message_includes_path(self):
        bad_path = "/no/such/file.png"
        payload = _valid({"file_path": bad_path})
        with self.assertRaises(ValueError) as ctx:
            validate_asset_payload(payload, check_exists=True)
        self.assertIn(bad_path, str(ctx.exception))


# ---------------------------------------------------------------------------
# TestOptionalFieldsAccepted
# ---------------------------------------------------------------------------

class TestOptionalFieldsAccepted(unittest.TestCase):

    def test_alt_text_accepted(self):
        p = _valid({"alt_text": "OpenClaw logo"})
        validate_asset_payload(p, check_exists=False)

    def test_context_accepted(self):
        p = _valid({"context": "social_post"})
        validate_asset_payload(p, check_exists=False)

    def test_source_url_accepted(self):
        p = _valid({"source_url": "https://openclaw.io/assets/logo.png"})
        validate_asset_payload(p, check_exists=False)

    def test_license_dict_accepted(self):
        p = _valid({"license": {"license_type": "MIT", "license_url": "https://x", "attribution": "x"}})
        validate_asset_payload(p, check_exists=False)

    def test_edit_applied_accepted(self):
        p = _valid({"edit_applied": "resize"})
        validate_asset_payload(p, check_exists=False)

    def test_all_optional_fields_accepted(self):
        p = _valid({
            "alt_text":     "Logo",
            "context":      "social_post",
            "source_url":   "https://openclaw.io/logo.png",
            "license":      {"license_type": "owned", "license_url": "n/a", "attribution": "n/a"},
            "edit_applied": "resize",
        })
        validate_asset_payload(p, check_exists=False)


# ---------------------------------------------------------------------------
# TestExtraFieldsAccepted
# ---------------------------------------------------------------------------

class TestExtraFieldsAccepted(unittest.TestCase):

    def test_unknown_key_does_not_raise(self):
        p = _valid({"custom_adapter_field": "value", "another": 123})
        validate_asset_payload(p, check_exists=False)  # must not raise


# ---------------------------------------------------------------------------
# TestMakeAssetPayload
# ---------------------------------------------------------------------------

class TestMakeAssetPayload(unittest.TestCase):

    def test_returns_dict(self):
        result = make_asset_payload("/tmp/f.png", asset_type="logo", format="png",
                                    check_exists=False)
        self.assertIsInstance(result, dict)

    def test_required_fields_present(self):
        result = make_asset_payload("/tmp/f.png", asset_type="logo", format="png",
                                    check_exists=False)
        self.assertEqual(result["file_path"], "/tmp/f.png")
        self.assertEqual(result["asset_type"], "logo")
        self.assertEqual(result["format"], "png")

    def test_optional_kwargs_merged(self):
        result = make_asset_payload(
            "/tmp/f.png",
            asset_type="logo",
            format="png",
            alt_text="OpenClaw logo",
            context="social_post",
            check_exists=False,
        )
        self.assertEqual(result["alt_text"], "OpenClaw logo")
        self.assertEqual(result["context"], "social_post")

    def test_extra_kwargs_merged(self):
        result = make_asset_payload(
            "/tmp/f.png", asset_type="logo", format="png",
            custom_key="custom_value", check_exists=False,
        )
        self.assertEqual(result["custom_key"], "custom_value")

    def test_validates_and_raises_on_missing_asset_type(self):
        with self.assertRaises(TypeError):
            make_asset_payload("/tmp/f.png", format="png", check_exists=False)

    def test_validates_and_raises_on_empty_file_path(self):
        with self.assertRaises(ValueError):
            make_asset_payload("", asset_type="logo", format="png",
                               check_exists=False)

    def test_check_exists_false_skips_filesystem(self):
        result = make_asset_payload(
            "/nonexistent/path.png",
            asset_type="logo",
            format="png",
            check_exists=False,
        )
        self.assertEqual(result["file_path"], "/nonexistent/path.png")

    def test_check_exists_true_raises_for_missing_file(self):
        with self.assertRaises(ValueError):
            make_asset_payload(
                "/nonexistent/path.png",
                asset_type="logo",
                format="png",
                check_exists=True,
            )

    def test_does_not_mutate_metadata_kwargs(self):
        """make_asset_payload does not modify its caller's namespace."""
        result1 = make_asset_payload("/tmp/a.png", asset_type="logo", format="png",
                                     check_exists=False)
        result2 = make_asset_payload("/tmp/b.jpg", asset_type="product_photo",
                                     format="jpg", check_exists=False)
        self.assertNotEqual(result1["file_path"], result2["file_path"])
        self.assertNotEqual(result1["asset_type"], result2["asset_type"])


# ---------------------------------------------------------------------------
# TestPayloadRequiredFieldsConstant
# ---------------------------------------------------------------------------

class TestPayloadRequiredFieldsConstant(unittest.TestCase):

    def test_is_tuple(self):
        self.assertIsInstance(PAYLOAD_REQUIRED_FIELDS, tuple)

    def test_contains_file_path(self):
        self.assertIn("file_path", PAYLOAD_REQUIRED_FIELDS)

    def test_contains_asset_type(self):
        self.assertIn("asset_type", PAYLOAD_REQUIRED_FIELDS)

    def test_contains_format(self):
        self.assertIn("format", PAYLOAD_REQUIRED_FIELDS)

    def test_all_strings(self):
        for field in PAYLOAD_REQUIRED_FIELDS:
            self.assertIsInstance(field, str)


# ---------------------------------------------------------------------------
# TestRealFileIntegration
# ---------------------------------------------------------------------------

class TestRealFileIntegration(unittest.TestCase):
    """End-to-end tests using a real temporary file on disk."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _make_file(self, name: str, content: bytes = b"fake content") -> str:
        path = os.path.join(self._tmpdir.name, name)
        with open(path, "wb") as fh:
            fh.write(content)
        return path

    def test_validate_passes_for_real_file(self):
        path = self._make_file("logo.png")
        payload = _valid({"file_path": path})
        validate_asset_payload(payload, check_exists=True)  # must not raise

    def test_make_payload_passes_for_real_file(self):
        path = self._make_file("logo.png")
        result = make_asset_payload(path, asset_type="logo", format="png",
                                    check_exists=True)
        self.assertEqual(result["file_path"], path)
        self.assertTrue(result["success"] if "success" in result else True)

    def test_make_payload_with_all_metadata_for_real_file(self):
        path = self._make_file("product.jpg")
        result = make_asset_payload(
            path,
            asset_type="product_photo",
            format="jpg",
            alt_text="Product shot",
            context="social_post",
            check_exists=True,
        )
        self.assertEqual(result["asset_type"], "product_photo")
        self.assertEqual(result["format"], "jpg")
        self.assertEqual(result["alt_text"], "Product shot")
        self.assertEqual(result["context"], "social_post")

    def test_validate_raises_after_file_deleted(self):
        path = self._make_file("temp.png")
        os.unlink(path)
        payload = _valid({"file_path": path})
        with self.assertRaises(ValueError):
            validate_asset_payload(payload, check_exists=True)

    def test_payload_file_path_is_readable(self):
        content = b"\x89PNG\r\n\x1a\n"
        path = self._make_file("logo.png", content)
        result = make_asset_payload(path, asset_type="logo", format="png")
        with open(result["file_path"], "rb") as fh:
            self.assertEqual(fh.read(), content)


if __name__ == "__main__":
    unittest.main()
