"""Tests for tools/platform_config.

Coverage:
  TestLoadPlatform         — happy path for each platform, alias resolution,
                             unknown name raises, case-insensitivity
  TestResolveAlias         — canonical IDs, all aliases, unknown raises
  TestLoadAllPlatforms     — returns all five, correct keys, no schema file
  TestListPlatforms        — sorted list, correct contents
  TestConfigShape          — each real config file has required fields and
                             correct types (schema conformance without jsonschema dep)
  TestCustomConfigDir      — config_dir injection, missing file, malformed JSON
  TestAliasCache           — cache cleared between injected-dir tests
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from tools.platform_config import (
    load_platform,
    load_all_platforms,
    list_platforms,
    resolve_alias,
)
from tools.platform_config.platform_config import _clear_alias_cache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KNOWN_PLATFORMS = ["facebook", "instagram", "linkedin", "mastodon", "twitter"]

_REQUIRED_TOP_LEVEL = {
    "platform_id", "display_name", "char_limit", "link_char_cost",
    "hashtag_limit", "hashtag_warn_above", "links_clickable", "aliases", "media",
}

_REQUIRED_MEDIA = {
    "max_images", "max_videos", "images_and_video_exclusive",
    "allowed_image_formats", "allowed_video_formats",
    "max_image_size_bytes", "max_video_size_bytes",
}


def _make_minimal_config(platform_id: str, aliases: list[str] | None = None) -> dict:
    """Return a minimal valid platform config dict for use in custom-dir tests."""
    return {
        "platform_id": platform_id,
        "display_name": platform_id.capitalize(),
        "char_limit": 500,
        "link_char_cost": None,
        "hashtag_limit": None,
        "hashtag_warn_above": None,
        "links_clickable": True,
        "aliases": aliases or [platform_id],
        "media": {
            "max_images": 4,
            "max_videos": 1,
            "images_and_video_exclusive": True,
            "allowed_image_formats": ["jpeg", "png"],
            "allowed_video_formats": ["mp4"],
            "max_image_size_bytes": 5_000_000,
            "max_video_size_bytes": 50_000_000,
        },
    }


class _TempConfigDir(unittest.TestCase):
    """Base class that provides a fresh temp config dir and clears the alias cache."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        _clear_alias_cache()

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        _clear_alias_cache()

    def _write(self, filename: str, data: dict) -> str:
        path = os.path.join(self._tmp, filename)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path


# ---------------------------------------------------------------------------
# TestLoadPlatform
# ---------------------------------------------------------------------------

class TestLoadPlatform(unittest.TestCase):

    def test_load_twitter_by_canonical(self):
        cfg = load_platform("twitter")
        self.assertEqual(cfg["platform_id"], "twitter")

    def test_load_linkedin(self):
        cfg = load_platform("linkedin")
        self.assertEqual(cfg["platform_id"], "linkedin")

    def test_load_instagram(self):
        cfg = load_platform("instagram")
        self.assertEqual(cfg["platform_id"], "instagram")

    def test_load_facebook(self):
        cfg = load_platform("facebook")
        self.assertEqual(cfg["platform_id"], "facebook")

    def test_load_mastodon(self):
        cfg = load_platform("mastodon")
        self.assertEqual(cfg["platform_id"], "mastodon")

    def test_alias_x_resolves_to_twitter(self):
        cfg = load_platform("x")
        self.assertEqual(cfg["platform_id"], "twitter")

    def test_alias_twitter_slash_x(self):
        cfg = load_platform("twitter/x")
        self.assertEqual(cfg["platform_id"], "twitter")

    def test_alias_x_slash_twitter(self):
        cfg = load_platform("x/twitter")
        self.assertEqual(cfg["platform_id"], "twitter")

    def test_case_insensitive(self):
        cfg = load_platform("TWITTER")
        self.assertEqual(cfg["platform_id"], "twitter")

    def test_case_insensitive_alias(self):
        cfg = load_platform("X")
        self.assertEqual(cfg["platform_id"], "twitter")

    def test_unknown_platform_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            load_platform("tiktok")
        self.assertIn("tiktok", str(ctx.exception))

    def test_unknown_platform_message_lists_known(self):
        with self.assertRaises(ValueError) as ctx:
            load_platform("tiktok")
        msg = str(ctx.exception)
        for pid in _KNOWN_PLATFORMS:
            self.assertIn(pid, msg)

    def test_returns_dict(self):
        self.assertIsInstance(load_platform("mastodon"), dict)


# ---------------------------------------------------------------------------
# TestResolveAlias
# ---------------------------------------------------------------------------

class TestResolveAlias(unittest.TestCase):

    def test_canonical_twitter(self):
        self.assertEqual(resolve_alias("twitter"), "twitter")

    def test_alias_x(self):
        self.assertEqual(resolve_alias("x"), "twitter")

    def test_alias_twitter_x(self):
        self.assertEqual(resolve_alias("twitter/x"), "twitter")

    def test_all_canonical_ids(self):
        for pid in _KNOWN_PLATFORMS:
            with self.subTest(pid=pid):
                self.assertEqual(resolve_alias(pid), pid)

    def test_case_insensitive(self):
        self.assertEqual(resolve_alias("LinkedIn"), "linkedin")
        self.assertEqual(resolve_alias("INSTAGRAM"), "instagram")

    def test_unknown_raises_value_error(self):
        with self.assertRaises(ValueError):
            resolve_alias("snapchat")

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            resolve_alias("")


# ---------------------------------------------------------------------------
# TestLoadAllPlatforms
# ---------------------------------------------------------------------------

class TestLoadAllPlatforms(unittest.TestCase):

    def setUp(self):
        self._all = load_all_platforms()

    def test_returns_dict(self):
        self.assertIsInstance(self._all, dict)

    def test_contains_all_five_platforms(self):
        for pid in _KNOWN_PLATFORMS:
            self.assertIn(pid, self._all, msg=f"{pid} missing from load_all_platforms()")

    def test_does_not_contain_schema_file(self):
        self.assertNotIn("platform.schema", self._all)
        self.assertNotIn("platform", self._all)

    def test_values_are_dicts(self):
        for pid, cfg in self._all.items():
            self.assertIsInstance(cfg, dict, msg=f"{pid} value is not a dict")

    def test_each_value_has_platform_id(self):
        for pid, cfg in self._all.items():
            self.assertEqual(cfg["platform_id"], pid)


# ---------------------------------------------------------------------------
# TestListPlatforms
# ---------------------------------------------------------------------------

class TestListPlatforms(unittest.TestCase):

    def test_returns_list(self):
        self.assertIsInstance(list_platforms(), list)

    def test_contains_all_five(self):
        result = list_platforms()
        for pid in _KNOWN_PLATFORMS:
            self.assertIn(pid, result)

    def test_sorted(self):
        result = list_platforms()
        self.assertEqual(result, sorted(result))

    def test_no_duplicates(self):
        result = list_platforms()
        self.assertEqual(len(result), len(set(result)))


# ---------------------------------------------------------------------------
# TestConfigShape — lightweight schema conformance without jsonschema dep
# ---------------------------------------------------------------------------

class TestConfigShape(unittest.TestCase):

    def setUp(self):
        self._all = load_all_platforms()

    def test_required_top_level_fields_present(self):
        for pid, cfg in self._all.items():
            with self.subTest(platform=pid):
                for field in _REQUIRED_TOP_LEVEL:
                    self.assertIn(field, cfg,
                                  msg=f"{pid} missing required field '{field}'")

    def test_required_media_fields_present(self):
        for pid, cfg in self._all.items():
            with self.subTest(platform=pid):
                media = cfg.get("media", {})
                for field in _REQUIRED_MEDIA:
                    self.assertIn(field, media,
                                  msg=f"{pid}.media missing required field '{field}'")

    def test_char_limit_is_positive_int(self):
        for pid, cfg in self._all.items():
            with self.subTest(platform=pid):
                self.assertIsInstance(cfg["char_limit"], int)
                self.assertGreater(cfg["char_limit"], 0)

    def test_link_char_cost_is_int_or_null(self):
        for pid, cfg in self._all.items():
            with self.subTest(platform=pid):
                val = cfg["link_char_cost"]
                self.assertIn(type(val), (int, type(None)),
                              msg=f"{pid}.link_char_cost must be int or null")

    def test_links_clickable_is_bool(self):
        for pid, cfg in self._all.items():
            with self.subTest(platform=pid):
                self.assertIsInstance(cfg["links_clickable"], bool)

    def test_aliases_is_non_empty_list(self):
        for pid, cfg in self._all.items():
            with self.subTest(platform=pid):
                aliases = cfg["aliases"]
                self.assertIsInstance(aliases, list)
                self.assertGreater(len(aliases), 0,
                                   msg=f"{pid}.aliases must not be empty")

    def test_platform_id_in_aliases(self):
        for pid, cfg in self._all.items():
            with self.subTest(platform=pid):
                self.assertIn(pid, cfg["aliases"],
                              msg=f"{pid} must include its own platform_id in aliases")

    def test_media_counts_are_non_negative_ints(self):
        for pid, cfg in self._all.items():
            with self.subTest(platform=pid):
                media = cfg["media"]
                for field in ("max_images", "max_videos"):
                    self.assertIsInstance(media[field], int)
                    self.assertGreaterEqual(media[field], 0)

    def test_media_size_limits_are_positive_ints(self):
        for pid, cfg in self._all.items():
            with self.subTest(platform=pid):
                media = cfg["media"]
                for field in ("max_image_size_bytes", "max_video_size_bytes"):
                    self.assertIsInstance(media[field], int)
                    self.assertGreater(media[field], 0)

    def test_image_formats_are_lowercase_strings(self):
        for pid, cfg in self._all.items():
            with self.subTest(platform=pid):
                for fmt in cfg["media"]["allowed_image_formats"]:
                    self.assertEqual(fmt, fmt.lower(),
                                     msg=f"{pid}: format '{fmt}' must be lowercase")
                    self.assertFalse(fmt.startswith("."),
                                     msg=f"{pid}: format '{fmt}' must not start with '.'")

    def test_known_values_twitter(self):
        cfg = load_platform("twitter")
        self.assertEqual(cfg["char_limit"], 280)
        self.assertEqual(cfg["link_char_cost"], 23)
        self.assertEqual(cfg["media"]["max_images"], 4)
        self.assertTrue(cfg["media"]["images_and_video_exclusive"])

    def test_known_values_instagram(self):
        cfg = load_platform("instagram")
        self.assertEqual(cfg["char_limit"], 2200)
        self.assertFalse(cfg["links_clickable"])
        self.assertEqual(cfg["hashtag_limit"], 30)
        self.assertFalse(cfg["media"]["images_and_video_exclusive"])

    def test_known_values_mastodon(self):
        cfg = load_platform("mastodon")
        self.assertEqual(cfg["char_limit"], 500)
        self.assertEqual(cfg["link_char_cost"], 23)

    def test_known_values_facebook(self):
        cfg = load_platform("facebook")
        self.assertEqual(cfg["char_limit"], 63206)
        self.assertIsNone(cfg["hashtag_warn_above"])

    def test_known_values_linkedin(self):
        cfg = load_platform("linkedin")
        self.assertEqual(cfg["char_limit"], 3000)
        self.assertIsNone(cfg["link_char_cost"])


# ---------------------------------------------------------------------------
# TestCustomConfigDir
# ---------------------------------------------------------------------------

class TestCustomConfigDir(_TempConfigDir):

    def test_load_from_custom_dir(self):
        self._write("testplatform.json", _make_minimal_config("testplatform"))
        cfg = load_platform("testplatform", config_dir=self._tmp)
        self.assertEqual(cfg["platform_id"], "testplatform")

    def test_alias_in_custom_dir(self):
        self._write("tp.json", _make_minimal_config("tp", aliases=["tp", "test_p"]))
        cfg = load_platform("test_p", config_dir=self._tmp)
        self.assertEqual(cfg["platform_id"], "tp")

    def test_unknown_platform_in_custom_dir_raises(self):
        self._write("tp.json", _make_minimal_config("tp"))
        with self.assertRaises(ValueError):
            load_platform("other", config_dir=self._tmp)

    def test_malformed_json_raises_runtime_error_on_load(self):
        path = os.path.join(self._tmp, "broken.json")
        with open(path, "w") as fh:
            fh.write("{not valid json")
        # Malformed files are skipped when building the alias index,
        # so they should not appear in load_all_platforms.
        result = load_all_platforms(config_dir=self._tmp)
        self.assertNotIn("broken", result)

    def test_load_all_in_custom_dir(self):
        self._write("alpha.json", _make_minimal_config("alpha"))
        self._write("beta.json", _make_minimal_config("beta"))
        result = load_all_platforms(config_dir=self._tmp)
        self.assertIn("alpha", result)
        self.assertIn("beta", result)
        self.assertEqual(len(result), 2)

    def test_list_platforms_in_custom_dir(self):
        self._write("alpha.json", _make_minimal_config("alpha"))
        self._write("beta.json", _make_minimal_config("beta"))
        result = list_platforms(config_dir=self._tmp)
        self.assertEqual(result, ["alpha", "beta"])

    def test_schema_file_excluded_from_load_all(self):
        self._write("platform.schema.json", {"$schema": "..."})
        self._write("tp.json", _make_minimal_config("tp"))
        result = load_all_platforms(config_dir=self._tmp)
        self.assertNotIn("platform.schema", result)
        self.assertIn("tp", result)

    def test_path_object_accepted(self):
        self._write("tp.json", _make_minimal_config("tp"))
        from pathlib import Path
        cfg = load_platform("tp", config_dir=Path(self._tmp))
        self.assertEqual(cfg["platform_id"], "tp")


if __name__ == "__main__":
    unittest.main()
