"""Tests for tools/validate_post/validate_post.py

Run from repo root:
    python -m unittest tests.test_validate_post
"""

import unittest

from tools.validate_post import validate_post


def _error_codes(result: dict) -> list[str]:
    return [e["code"] for e in result["errors"]]


def _warning_codes(result: dict) -> list[str]:
    return [w["code"] for w in result["warnings"]]


# ---------------------------------------------------------------------------
# Platform normalisation
# ---------------------------------------------------------------------------

class TestPlatformNormalisation(unittest.TestCase):

    def test_twitter_accepted(self):
        r = validate_post({"content": "Hello world", "platform": "twitter"})
        self.assertEqual(r["platform"], "twitter")

    def test_x_normalises_to_twitter(self):
        r = validate_post({"content": "Hello world", "platform": "x"})
        self.assertEqual(r["platform"], "twitter")
        self.assertTrue(r["valid"])

    def test_twitter_x_slash_normalises(self):
        r = validate_post({"content": "Hello world", "platform": "twitter/x"})
        self.assertEqual(r["platform"], "twitter")
        self.assertTrue(r["valid"])

    def test_x_twitter_slash_normalises(self):
        r = validate_post({"content": "Hello world", "platform": "x/twitter"})
        self.assertEqual(r["platform"], "twitter")
        self.assertTrue(r["valid"])

    def test_platform_case_insensitive(self):
        r = validate_post({"content": "Hello world", "platform": "Twitter"})
        self.assertEqual(r["platform"], "twitter")
        self.assertTrue(r["valid"])

    def test_unsupported_platform(self):
        r = validate_post({"content": "Hello world", "platform": "tiktok"})
        self.assertFalse(r["valid"])
        self.assertIn("UNSUPPORTED_PLATFORM", _error_codes(r))

    def test_missing_platform(self):
        r = validate_post({"content": "Hello world"})
        self.assertFalse(r["valid"])
        self.assertIn("MISSING_REQUIRED_FIELD", _error_codes(r))


# ---------------------------------------------------------------------------
# Content validation
# ---------------------------------------------------------------------------

class TestContentValidation(unittest.TestCase):

    def test_empty_string(self):
        r = validate_post({"content": "", "platform": "twitter"})
        self.assertFalse(r["valid"])
        self.assertIn("EMPTY_CONTENT", _error_codes(r))

    def test_whitespace_only(self):
        r = validate_post({"content": "   \n\t  ", "platform": "twitter"})
        self.assertFalse(r["valid"])
        self.assertIn("EMPTY_CONTENT", _error_codes(r))

    def test_missing_content_key(self):
        r = validate_post({"platform": "twitter"})
        self.assertFalse(r["valid"])
        self.assertIn("EMPTY_CONTENT", _error_codes(r))

    def test_valid_content_passes(self):
        r = validate_post({"content": "Hello world — this is a valid post.", "platform": "twitter"})
        self.assertTrue(r["valid"])
        self.assertEqual(r["errors"], [])


# ---------------------------------------------------------------------------
# Character limits
# ---------------------------------------------------------------------------

class TestCharacterLimits(unittest.TestCase):

    def test_twitter_at_limit(self):
        content = "a" * 280
        r = validate_post({"content": content, "platform": "twitter"})
        self.assertTrue(r["valid"])
        self.assertEqual(r["character_count"], 280)
        self.assertNotIn("CHARACTER_LIMIT_EXCEEDED", _error_codes(r))

    def test_twitter_over_limit(self):
        content = "a" * 281
        r = validate_post({"content": content, "platform": "twitter"})
        self.assertFalse(r["valid"])
        self.assertIn("CHARACTER_LIMIT_EXCEEDED", _error_codes(r))
        err = next(e for e in r["errors"] if e["code"] == "CHARACTER_LIMIT_EXCEEDED")
        self.assertEqual(err["limit"], 280)
        self.assertEqual(err["actual"], 281)

    def test_twitter_url_costs_23_chars(self):
        # "x" * 10 + space + URL → only 10 + 1 + 23 = 34 chars counted
        short_text = "x" * 10 + " "
        url = "https://example.com/some/very/long/path/that/is/way/more/than/23/characters"
        content = short_text + url
        r = validate_post({"content": content, "platform": "twitter"})
        self.assertEqual(r["character_count"], 10 + 1 + 23)
        self.assertTrue(r["valid"])

    def test_mastodon_url_costs_23_chars(self):
        content = "Check this out: https://mastodon.social/very/long/path"
        r = validate_post({"content": content, "platform": "mastodon"})
        expected = len("Check this out: ") + 23
        self.assertEqual(r["character_count"], expected)

    def test_linkedin_url_counted_at_actual_length(self):
        url = "https://example.com"  # 19 chars
        content = "Read this: " + url
        r = validate_post({"content": content, "platform": "linkedin"})
        self.assertEqual(r["character_count"], len(content))

    def test_mastodon_at_limit(self):
        content = "a" * 500
        r = validate_post({"content": content, "platform": "mastodon"})
        self.assertTrue(r["valid"])

    def test_mastodon_over_limit(self):
        content = "a" * 501
        r = validate_post({"content": content, "platform": "mastodon"})
        self.assertFalse(r["valid"])
        self.assertIn("CHARACTER_LIMIT_EXCEEDED", _error_codes(r))

    def test_instagram_over_limit(self):
        content = "a" * 2201
        r = validate_post({"content": content, "platform": "instagram"})
        self.assertFalse(r["valid"])
        self.assertIn("CHARACTER_LIMIT_EXCEEDED", _error_codes(r))

    def test_linkedin_over_limit(self):
        content = "a" * 3001
        r = validate_post({"content": content, "platform": "linkedin"})
        self.assertFalse(r["valid"])
        self.assertIn("CHARACTER_LIMIT_EXCEEDED", _error_codes(r))

    def test_facebook_long_post_is_valid(self):
        content = "a" * 10000
        r = validate_post({"content": content, "platform": "facebook"})
        self.assertTrue(r["valid"])

    def test_long_content_warning_above_80_percent(self):
        # Twitter limit 280; 80% = 224. Use 225 chars.
        content = "a" * 225
        r = validate_post({"content": content, "platform": "twitter"})
        self.assertTrue(r["valid"])
        self.assertIn("LONG_CONTENT", _warning_codes(r))

    def test_no_long_content_warning_below_80_percent(self):
        content = "a" * 100  # well under 224
        r = validate_post({"content": content, "platform": "twitter"})
        self.assertNotIn("LONG_CONTENT", _warning_codes(r))

    def test_character_count_always_present(self):
        r = validate_post({"content": "Hi", "platform": "twitter"})
        self.assertIn("character_count", r)
        self.assertIsInstance(r["character_count"], int)


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure(unittest.TestCase):

    def test_errors_always_present(self):
        r = validate_post({"content": "Hello world", "platform": "twitter"})
        self.assertIn("errors", r)
        self.assertIsInstance(r["errors"], list)

    def test_warnings_always_present(self):
        r = validate_post({"content": "Hello world", "platform": "twitter"})
        self.assertIn("warnings", r)
        self.assertIsInstance(r["warnings"], list)

    def test_valid_false_when_errors_present(self):
        r = validate_post({"content": "a" * 300, "platform": "twitter"})
        self.assertFalse(r["valid"])
        self.assertTrue(len(r["errors"]) > 0)

    def test_valid_true_when_no_errors(self):
        r = validate_post({"content": "Hello world", "platform": "twitter"})
        self.assertTrue(r["valid"])
        self.assertEqual(r["errors"], [])


# ---------------------------------------------------------------------------
# Hashtags
# ---------------------------------------------------------------------------

class TestHashtags(unittest.TestCase):

    def test_hashtags_detected_in_content(self):
        r = validate_post({"content": "Post about #python and #ai", "platform": "twitter"})
        # 2 hashtags — below warn threshold of 3, no warning
        self.assertNotIn("HIGH_HASHTAG_COUNT", _warning_codes(r))

    def test_high_hashtag_count_twitter_warns_above_3(self):
        content = "Hello #a #b #c #d"
        r = validate_post({"content": content, "platform": "twitter"})
        self.assertIn("HIGH_HASHTAG_COUNT", _warning_codes(r))
        self.assertTrue(r["valid"])  # warning, not error

    def test_explicit_hashtags_are_additive(self):
        # 3 in content + 2 explicit = 5 total → above Twitter warn threshold (3)
        content = "Hello #a #b #c"
        r = validate_post({"content": content, "platform": "twitter", "hashtags": ["d", "e"]})
        self.assertIn("HIGH_HASHTAG_COUNT", _warning_codes(r))

    def test_hashtag_deduplication(self):
        # Same hashtag in content and explicit field — counts as one
        r = validate_post({
            "content": "Hello #python",
            "platform": "twitter",
            "hashtags": ["python"],
        })
        self.assertNotIn("HIGH_HASHTAG_COUNT", _warning_codes(r))

    def test_instagram_hashtag_limit_exceeded(self):
        tags = " ".join(f"#tag{i}" for i in range(31))
        r = validate_post({"content": "Post " + tags, "platform": "instagram"})
        self.assertFalse(r["valid"])
        self.assertIn("HASHTAG_LIMIT_EXCEEDED", _error_codes(r))

    def test_instagram_hashtag_at_limit(self):
        tags = " ".join(f"#tag{i}" for i in range(30))
        r = validate_post({"content": "Post " + tags, "platform": "instagram"})
        self.assertNotIn("HASHTAG_LIMIT_EXCEEDED", _error_codes(r))

    def test_instagram_high_hashtag_warning(self):
        tags = " ".join(f"#tag{i}" for i in range(11))
        r = validate_post({"content": "Post " + tags, "platform": "instagram"})
        # 11 hashtags: above warn threshold (10) but under hard limit (30) → warning only
        self.assertNotIn("HASHTAG_LIMIT_EXCEEDED", _error_codes(r))
        self.assertIn("HIGH_HASHTAG_COUNT", _warning_codes(r))
        self.assertTrue(r["valid"])

    def test_facebook_no_hashtag_warn(self):
        tags = " ".join(f"#tag{i}" for i in range(20))
        r = validate_post({"content": "Post " + tags, "platform": "facebook"})
        self.assertNotIn("HIGH_HASHTAG_COUNT", _warning_codes(r))
        self.assertNotIn("HASHTAG_LIMIT_EXCEEDED", _error_codes(r))


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

class TestLinks(unittest.TestCase):

    def test_http_link_is_valid(self):
        r = validate_post({"content": "Check out https://example.com for more.", "platform": "twitter"})
        self.assertNotIn("INVALID_LINK", _error_codes(r))

    def test_ftp_link_is_invalid(self):
        r = validate_post({
            "content": "Download here",
            "platform": "twitter",
            "links": ["ftp://example.com/file.zip"],
        })
        self.assertFalse(r["valid"])
        self.assertIn("INVALID_LINK", _error_codes(r))

    def test_instagram_link_triggers_warning(self):
        r = validate_post({
            "content": "Check out https://example.com for more.",
            "platform": "instagram",
        })
        self.assertIn("LINK_NOT_ALLOWED", _warning_codes(r))
        self.assertTrue(r["valid"])  # warning only, not an error

    def test_instagram_no_link_no_warning(self):
        r = validate_post({"content": "Beautiful sunset today. Sign up for more.", "platform": "instagram"})
        self.assertNotIn("LINK_NOT_ALLOWED", _warning_codes(r))

    def test_explicit_links_field_used(self):
        r = validate_post({
            "content": "Hello world",
            "platform": "twitter",
            "links": ["ftp://bad.example.com"],
        })
        self.assertFalse(r["valid"])
        self.assertIn("INVALID_LINK", _error_codes(r))

    def test_link_in_content_suppresses_no_cta(self):
        r = validate_post({"content": "Check https://example.com", "platform": "twitter"})
        self.assertNotIn("NO_CTA", _warning_codes(r))


# ---------------------------------------------------------------------------
# NO_CTA warning
# ---------------------------------------------------------------------------

class TestNoCta(unittest.TestCase):

    def test_no_cta_fires_when_no_link_or_phrase(self):
        r = validate_post({"content": "The weather is nice today.", "platform": "twitter"})
        self.assertIn("NO_CTA", _warning_codes(r))

    def test_no_cta_suppressed_by_cta_phrase(self):
        r = validate_post({"content": "Read more about this topic.", "platform": "twitter"})
        self.assertNotIn("NO_CTA", _warning_codes(r))

    def test_no_cta_suppressed_by_link(self):
        r = validate_post({"content": "See https://example.com", "platform": "twitter"})
        self.assertNotIn("NO_CTA", _warning_codes(r))

    def test_no_cta_is_never_an_error(self):
        # Even without a CTA, valid should be True (no other errors)
        r = validate_post({"content": "The weather is nice today.", "platform": "twitter"})
        self.assertTrue(r["valid"])
        self.assertIn("NO_CTA", _warning_codes(r))

    def test_cta_phrases_case_insensitive(self):
        r = validate_post({"content": "SIGN UP now for early access.", "platform": "twitter"})
        self.assertNotIn("NO_CTA", _warning_codes(r))


# ---------------------------------------------------------------------------
# Media validation
# ---------------------------------------------------------------------------

class TestMedia(unittest.TestCase):

    def _img(self, fmt="jpeg", size=1 * 1024 * 1024):
        return {"type": "image", "format": fmt, "size_bytes": size}

    def _vid(self, fmt="mp4", size=10 * 1024 * 1024):
        return {"type": "video", "format": fmt, "size_bytes": size}

    def test_valid_single_image(self):
        r = validate_post({
            "content": "Look at this photo! Check it out.",
            "platform": "twitter",
            "media": [self._img()],
        })
        self.assertTrue(r["valid"])

    def test_twitter_max_4_images(self):
        r = validate_post({
            "content": "Photos! Check them out.",
            "platform": "twitter",
            "media": [self._img()] * 5,
        })
        self.assertFalse(r["valid"])
        self.assertIn("MEDIA_COUNT_EXCEEDED", _error_codes(r))

    def test_twitter_image_and_video_conflict(self):
        r = validate_post({
            "content": "Mixed media! Check it out.",
            "platform": "twitter",
            "media": [self._img(), self._vid()],
        })
        self.assertFalse(r["valid"])
        self.assertIn("MEDIA_TYPE_CONFLICT", _error_codes(r))

    def test_instagram_allows_mixed_media(self):
        # Instagram carousel allows images and video together
        r = validate_post({
            "content": "Carousel post! Sign up for more.",
            "platform": "instagram",
            "media": [self._img(), self._vid()],
        })
        self.assertNotIn("MEDIA_TYPE_CONFLICT", _error_codes(r))

    def test_unsupported_image_format(self):
        r = validate_post({
            "content": "Photo! Sign up.",
            "platform": "twitter",
            "media": [self._img(fmt="bmp")],
        })
        self.assertFalse(r["valid"])
        self.assertIn("UNSUPPORTED_MEDIA_TYPE", _error_codes(r))

    def test_unsupported_video_format(self):
        r = validate_post({
            "content": "Video! Check it out.",
            "platform": "twitter",
            "media": [self._vid(fmt="avi")],
        })
        self.assertFalse(r["valid"])
        self.assertIn("UNSUPPORTED_MEDIA_TYPE", _error_codes(r))

    def test_image_size_exceeded(self):
        big = 6 * 1024 * 1024  # 6 MB; Twitter limit 5 MB
        r = validate_post({
            "content": "Big photo! Sign up.",
            "platform": "twitter",
            "media": [self._img(size=big)],
        })
        self.assertFalse(r["valid"])
        self.assertIn("MEDIA_SIZE_EXCEEDED", _error_codes(r))

    def test_image_size_at_limit_is_valid(self):
        exact = 5 * 1024 * 1024  # exactly 5 MB
        r = validate_post({
            "content": "Photo! Sign up.",
            "platform": "twitter",
            "media": [self._img(size=exact)],
        })
        self.assertNotIn("MEDIA_SIZE_EXCEEDED", _error_codes(r))

    def test_unknown_media_type(self):
        r = validate_post({
            "content": "Something! Check it out.",
            "platform": "twitter",
            "media": [{"type": "audio", "format": "mp3", "size_bytes": 1000}],
        })
        self.assertFalse(r["valid"])
        self.assertIn("UNSUPPORTED_MEDIA_TYPE", _error_codes(r))

    def test_empty_media_list_is_fine(self):
        r = validate_post({"content": "No media. Sign up.", "platform": "twitter", "media": []})
        self.assertTrue(r["valid"])

    def test_media_format_with_dot_prefix(self):
        # Some callers may pass ".jpeg" — strip leading dot
        r = validate_post({
            "content": "Photo! Sign up.",
            "platform": "twitter",
            "media": [self._img(fmt=".jpeg")],
        })
        self.assertNotIn("UNSUPPORTED_MEDIA_TYPE", _error_codes(r))


# ---------------------------------------------------------------------------
# Valid posts for each supported platform
# ---------------------------------------------------------------------------

class TestValidPosts(unittest.TestCase):

    def _valid(self, platform: str):
        return validate_post({"content": f"Hello from {platform}! Sign up for more.", "platform": platform})

    def test_valid_twitter(self):
        self.assertTrue(self._valid("twitter")["valid"])

    def test_valid_x(self):
        self.assertTrue(self._valid("x")["valid"])

    def test_valid_linkedin(self):
        self.assertTrue(self._valid("linkedin")["valid"])

    def test_valid_instagram(self):
        self.assertTrue(self._valid("instagram")["valid"])

    def test_valid_facebook(self):
        self.assertTrue(self._valid("facebook")["valid"])

    def test_valid_mastodon(self):
        self.assertTrue(self._valid("mastodon")["valid"])


if __name__ == "__main__":
    unittest.main()
