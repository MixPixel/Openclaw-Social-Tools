"""Tests for config/brand.json and config/brand.schema.json.

Coverage:
  TestBrandJsonShape        — brand.json loads, all required fields present,
                              correct types, no extra top-level keys
  TestBrandHandles          — handles dict exists, keys are canonical platform IDs
                              (no "x"), values are non-empty strings
  TestBrandColours          — brand_colours values match hex pattern
  TestBrandHashtags         — default_hashtags values start with '#'
  TestBrandBio              — bio has 'short' and 'long' string fields
  TestBrandSchemaShape      — brand.schema.json is valid JSON, has expected
                              structure (title, required list, properties)
  TestBrandSchemaRequired   — schema required[] covers all expected fields
"""

import json
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_BRAND_JSON = _REPO_ROOT / "config" / "brand.json"
_SCHEMA_JSON = _REPO_ROOT / "config" / "brand.schema.json"

_REQUIRED_FIELDS = {
    "brand_id",
    "brand_name",
    "handles",
    "voice",
    "tone",
    "default_hashtags",
    "bio",
    "logo_path",
    "brand_colours",
    "forbidden_terms",
    "cta_phrases",
}

_CANONICAL_PLATFORMS = {"twitter", "linkedin", "instagram", "facebook", "mastodon"}

_HEX_COLOUR_RE = re.compile(r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


def _load_brand() -> dict:
    with open(_BRAND_JSON, encoding="utf-8") as f:
        return json.load(f)


def _load_schema() -> dict:
    with open(_SCHEMA_JSON, encoding="utf-8") as f:
        return json.load(f)


class TestBrandJsonShape(unittest.TestCase):
    """brand.json loads cleanly and has the required shape."""

    def setUp(self):
        self.brand = _load_brand()

    def test_is_dict(self):
        self.assertIsInstance(self.brand, dict)

    def test_required_fields_present(self):
        missing = _REQUIRED_FIELDS - self.brand.keys()
        self.assertFalse(missing, f"Missing required fields: {missing}")

    def test_brand_id_nonempty_string(self):
        self.assertIsInstance(self.brand["brand_id"], str)
        self.assertTrue(self.brand["brand_id"].strip())

    def test_brand_name_nonempty_string(self):
        self.assertIsInstance(self.brand["brand_name"], str)
        self.assertTrue(self.brand["brand_name"].strip())

    def test_voice_nonempty_string(self):
        self.assertIsInstance(self.brand["voice"], str)
        self.assertTrue(self.brand["voice"].strip())

    def test_tone_is_nonempty_list_of_strings(self):
        tone = self.brand["tone"]
        self.assertIsInstance(tone, list)
        self.assertTrue(len(tone) >= 1, "tone must have at least one entry")
        for item in tone:
            self.assertIsInstance(item, str)

    def test_default_hashtags_is_list(self):
        self.assertIsInstance(self.brand["default_hashtags"], list)

    def test_logo_path_nonempty_string(self):
        self.assertIsInstance(self.brand["logo_path"], str)
        self.assertTrue(self.brand["logo_path"].strip())

    def test_forbidden_terms_is_list(self):
        self.assertIsInstance(self.brand["forbidden_terms"], list)

    def test_cta_phrases_is_list(self):
        self.assertIsInstance(self.brand["cta_phrases"], list)

    def test_no_unexpected_top_level_keys(self):
        allowed = _REQUIRED_FIELDS | {"_notes"}
        unexpected = self.brand.keys() - allowed
        self.assertFalse(unexpected, f"Unexpected top-level keys: {unexpected}")


class TestBrandHandles(unittest.TestCase):
    """handles dict uses canonical platform IDs."""

    def setUp(self):
        self.handles = _load_brand()["handles"]

    def test_handles_is_dict(self):
        self.assertIsInstance(self.handles, dict)

    def test_handles_nonempty(self):
        self.assertTrue(len(self.handles) >= 1)

    def test_handle_values_are_nonempty_strings(self):
        for platform, handle in self.handles.items():
            with self.subTest(platform=platform):
                self.assertIsInstance(handle, str)
                self.assertTrue(handle.strip(), f"Handle for {platform!r} is blank")

    def test_no_x_key(self):
        """'x' is an alias, not a canonical platform_id — must not be a handles key."""
        self.assertNotIn("x", self.handles, "'x' is an alias; use 'twitter' as the key")

    def test_keys_are_known_canonical_ids(self):
        for key in self.handles:
            with self.subTest(key=key):
                self.assertIn(
                    key,
                    _CANONICAL_PLATFORMS,
                    f"'{key}' is not a recognised canonical platform_id",
                )


class TestBrandColours(unittest.TestCase):
    """brand_colours values are valid CSS hex strings."""

    def setUp(self):
        self.colours = _load_brand()["brand_colours"]

    def test_colours_is_dict(self):
        self.assertIsInstance(self.colours, dict)

    def test_colour_values_are_hex(self):
        for name, value in self.colours.items():
            with self.subTest(colour=name):
                self.assertIsInstance(value, str)
                self.assertRegex(
                    value,
                    _HEX_COLOUR_RE,
                    f"brand_colours['{name}'] = {value!r} is not a valid hex colour",
                )


class TestBrandHashtags(unittest.TestCase):
    """default_hashtags entries start with '#'."""

    def test_hashtags_start_with_hash(self):
        hashtags = _load_brand()["default_hashtags"]
        for tag in hashtags:
            with self.subTest(tag=tag):
                self.assertIsInstance(tag, str)
                self.assertTrue(
                    tag.startswith("#"),
                    f"default_hashtag {tag!r} must start with '#'",
                )


class TestBrandBio(unittest.TestCase):
    """bio has 'short' and 'long' string fields."""

    def setUp(self):
        self.bio = _load_brand()["bio"]

    def test_bio_is_dict(self):
        self.assertIsInstance(self.bio, dict)

    def test_bio_has_short(self):
        self.assertIn("short", self.bio)
        self.assertIsInstance(self.bio["short"], str)

    def test_bio_has_long(self):
        self.assertIn("long", self.bio)
        self.assertIsInstance(self.bio["long"], str)

    def test_bio_no_extra_keys(self):
        extra = self.bio.keys() - {"short", "long"}
        self.assertFalse(extra, f"Unexpected bio keys: {extra}")


class TestBrandSchemaShape(unittest.TestCase):
    """brand.schema.json is valid and has expected top-level structure."""

    def setUp(self):
        self.schema = _load_schema()

    def test_is_dict(self):
        self.assertIsInstance(self.schema, dict)

    def test_has_title(self):
        self.assertEqual(self.schema.get("title"), "BrandPack")

    def test_has_type_object(self):
        self.assertEqual(self.schema.get("type"), "object")

    def test_has_required_array(self):
        self.assertIsInstance(self.schema.get("required"), list)

    def test_has_properties(self):
        self.assertIsInstance(self.schema.get("properties"), dict)

    def test_additional_properties_false(self):
        self.assertFalse(self.schema.get("additionalProperties"))


class TestBrandSchemaRequired(unittest.TestCase):
    """schema required[] covers all expected brand fields."""

    def setUp(self):
        self.schema_required = set(_load_schema().get("required", []))

    def test_all_required_fields_in_schema(self):
        missing = _REQUIRED_FIELDS - self.schema_required
        self.assertFalse(
            missing,
            f"Fields in _REQUIRED_FIELDS missing from schema required[]: {missing}",
        )

    def test_schema_required_matches_expected(self):
        extra = self.schema_required - _REQUIRED_FIELDS
        self.assertFalse(
            extra,
            f"Schema required[] has fields not in _REQUIRED_FIELDS: {extra}",
        )
