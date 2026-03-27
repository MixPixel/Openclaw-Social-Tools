"""Tests for the LinkedIn adapter (HTTP mocked)."""

import pytest
import requests
from unittest.mock import MagicMock, patch

from openclaw.adapters.linkedin import LinkedInAdapter, _UGC_POSTS_URL
from openclaw.adapters.base import PostResult


TOKEN = "test-token"
URN = "urn:li:person:testUser"


def _make_adapter() -> LinkedInAdapter:
    return LinkedInAdapter(access_token=TOKEN, author_urn=URN)


def _mock_response(post_id: str = "urn:li:share:123456789", status: int = 201):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"x-restli-id": post_id}
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


class TestLinkedInAdapterInit:
    def test_uses_explicit_credentials(self):
        adapter = LinkedInAdapter(access_token="tok", author_urn="urn:li:person:x")
        assert adapter.access_token == "tok"
        assert adapter.author_urn == "urn:li:person:x"

    def test_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "env-tok")
        monkeypatch.setenv("LINKEDIN_AUTHOR_URN", "urn:li:person:env")
        adapter = LinkedInAdapter()
        assert adapter.access_token == "env-tok"
        assert adapter.author_urn == "urn:li:person:env"

    def test_missing_token_raises(self, monkeypatch):
        monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("LINKEDIN_AUTHOR_URN", raising=False)
        with pytest.raises(KeyError):
            LinkedInAdapter()


class TestLinkedInAdapterPostText:
    def test_happy_path_returns_post_result(self):
        adapter = _make_adapter()
        with patch("openclaw.adapters.linkedin.requests.post") as mock_post:
            mock_post.return_value = _mock_response("urn:li:share:999")
            result = adapter.post_text("Hello LinkedIn!")

        assert isinstance(result, PostResult)
        assert result.platform == "linkedin"
        assert result.post_id == "urn:li:share:999"
        assert result.url == "https://www.linkedin.com/feed/update/urn:li:share:999"

    def test_sends_correct_payload(self):
        adapter = _make_adapter()
        with patch("openclaw.adapters.linkedin.requests.post") as mock_post:
            mock_post.return_value = _mock_response()
            adapter.post_text("Test text")

        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["author"] == URN
        assert payload["lifecycleState"] == "PUBLISHED"
        content = payload["specificContent"]["com.linkedin.ugc.ShareContent"]
        assert content["shareCommentary"]["text"] == "Test text"
        assert content["shareMediaCategory"] == "NONE"

    def test_sends_correct_auth_header(self):
        adapter = _make_adapter()
        with patch("openclaw.adapters.linkedin.requests.post") as mock_post:
            mock_post.return_value = _mock_response()
            adapter.post_text("x")

        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert kwargs["headers"]["X-Restli-Protocol-Version"] == "2.0.0"

    def test_posts_to_correct_url(self):
        adapter = _make_adapter()
        with patch("openclaw.adapters.linkedin.requests.post") as mock_post:
            mock_post.return_value = _mock_response()
            adapter.post_text("x")

        args, _ = mock_post.call_args
        assert args[0] == _UGC_POSTS_URL

    def test_http_error_propagates(self):
        adapter = _make_adapter()
        with patch("openclaw.adapters.linkedin.requests.post") as mock_post:
            mock_post.return_value = _mock_response(status=401)
            with pytest.raises(requests.HTTPError):
                adapter.post_text("x")

    def test_missing_restli_id_gives_none_url(self):
        adapter = _make_adapter()
        resp = _mock_response()
        resp.headers = {}  # no x-restli-id
        with patch("openclaw.adapters.linkedin.requests.post", return_value=resp):
            result = adapter.post_text("x")

        assert result.post_id == ""
        assert result.url is None
