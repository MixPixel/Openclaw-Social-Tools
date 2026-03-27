"""Tests for the publish pipeline."""

import pytest
from unittest.mock import MagicMock

from openclaw.adapters.base import PostResult, SocialAdapter
from openclaw.pipeline import publish, _LINKEDIN_CHAR_LIMIT


def _stub_adapter(platform: str = "linkedin") -> SocialAdapter:
    adapter = MagicMock(spec=SocialAdapter)
    adapter.platform = platform
    adapter.post_text.return_value = PostResult(
        platform=platform, post_id="urn:li:share:1", url=None
    )
    return adapter


class TestPublish:
    def test_calls_adapter_with_stripped_text(self):
        adapter = _stub_adapter()
        publish(adapter, "  Hello  ")
        adapter.post_text.assert_called_once_with("Hello")

    def test_returns_post_result(self):
        adapter = _stub_adapter()
        result = publish(adapter, "Hello")
        assert isinstance(result, PostResult)

    def test_empty_text_raises(self):
        adapter = _stub_adapter()
        with pytest.raises(ValueError, match="empty"):
            publish(adapter, "")

    def test_whitespace_only_raises(self):
        adapter = _stub_adapter()
        with pytest.raises(ValueError, match="empty"):
            publish(adapter, "   ")

    def test_text_at_limit_is_accepted(self):
        adapter = _stub_adapter()
        publish(adapter, "x" * _LINKEDIN_CHAR_LIMIT)
        adapter.post_text.assert_called_once()

    def test_text_over_limit_raises(self):
        adapter = _stub_adapter()
        with pytest.raises(ValueError, match="3000"):
            publish(adapter, "x" * (_LINKEDIN_CHAR_LIMIT + 1))

    def test_non_linkedin_platform_skips_char_limit(self):
        adapter = _stub_adapter(platform="twitter")
        # Should not raise even for long text
        publish(adapter, "x" * (_LINKEDIN_CHAR_LIMIT + 100))
        adapter.post_text.assert_called_once()
