"""Tests for Twitter adapter HTTP delivery layer (Step 10).

Coverage:
  TestOAuthSignature       — _oauth_authorization_header: format, determinism,
                             sensitivity to key material, correct percent-encoding
  TestBuildPayload         — _build_payload: text-only, media_ids, empty list
  TestParseResponse        — _parse_response: 201 success, all error status codes,
                             Twitter-specific 403 overrides, retryable flags,
                             JSON body extraction, malformed body fallback
  TestCallTwitterApi       — _call_twitter_api: Authorization header sent,
                             Content-Type header, payload serialised as JSON,
                             HTTPError unwrapped, network exception propagated
  TestTwitterAdapterCall   — TwitterAdapter.__call__: missing credentials,
                             success result mapped, error result mapped,
                             network exception → NETWORK_ERROR, result shape valid
  TestCallTwitterUploadApi — _call_twitter_upload_api: missing file_path,
                             unreadable file, success extracts media_id_string,
                             HTTP error mapped, form body is base64 encoded
  TestGetAdapter           — get_adapter: resolves env credentials,
                             accepts explicit credentials, _http_fn threaded
  TestIntegration          — end-to-end through publish_to_platform with
                             mocked HTTP function
"""

import base64
import io
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools.platform_adapters.twitter import (
    REQUIRED_CREDENTIALS,
    TwitterAdapter,
    _build_payload,
    _call_twitter_api,
    _call_twitter_upload_api,
    _oauth_authorization_header,
    _parse_response,
    get_adapter,
    upload_asset as twitter_upload_asset,
)
from tools.platform_adapters.base import (
    AUTH_ERROR,
    CONTENT_REJECTED,
    MEDIA_UPLOAD_FAILED,
    NETWORK_ERROR,
    PERMISSION_ERROR,
    PLATFORM_UNAVAILABLE,
    RATE_LIMITED,
    UNKNOWN_ERROR,
    validate_adapter_result,
)
from tools.publish_pipeline import publish_to_platform


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_FULL_CREDS = {
    "TWITTER_API_KEY":       "test_api_key",
    "TWITTER_API_SECRET":    "test_api_secret",
    "TWITTER_ACCESS_TOKEN":  "test_access_token",
    "TWITTER_ACCESS_SECRET": "test_access_secret",
}

_FIXED_TS    = "1700000000"
_FIXED_NONCE = "abc123nonce"


def _make_response(status: int, body: str):
    """Build a minimal mock HTTP response."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body.encode("utf-8")
    return resp


def _make_http_fn(status: int, body: str):
    """Return a callable that mimics urlopen returning a fixed response."""
    resp = _make_response(status, body)
    return lambda req: resp


def _make_http_error(code: int, body: str):
    """Return a callable that mimics urlopen raising an HTTPError."""
    import urllib.error
    def _raise(req):
        exc = urllib.error.HTTPError(
            url="http://x", code=code, msg="err",
            hdrs=None, fp=io.BytesIO(body.encode("utf-8")),
        )
        raise exc
    return _raise


_TWEET_SUCCESS_BODY = json.dumps({"data": {"id": "tweet-999", "text": "hello"}})
_UPLOAD_SUCCESS_BODY = json.dumps({"media_id": 12345, "media_id_string": "12345"})


# ---------------------------------------------------------------------------
# TestOAuthSignature
# ---------------------------------------------------------------------------

class TestOAuthSignature(unittest.TestCase):

    def _header(self, **kwargs):
        return _oauth_authorization_header(
            "POST", "https://api.twitter.com/2/tweets",
            _FULL_CREDS,
            _timestamp=_FIXED_TS,
            _nonce=_FIXED_NONCE,
            **kwargs,
        )

    def test_header_starts_with_oauth(self):
        self.assertTrue(self._header().startswith("OAuth "))

    def test_header_contains_consumer_key(self):
        self.assertIn("oauth_consumer_key", self._header())

    def test_header_contains_token(self):
        self.assertIn("oauth_token", self._header())

    def test_header_contains_signature(self):
        self.assertIn("oauth_signature", self._header())

    def test_header_contains_hmac_sha1(self):
        self.assertIn("HMAC-SHA1", self._header())

    def test_header_contains_fixed_timestamp(self):
        self.assertIn(_FIXED_TS, self._header())

    def test_header_contains_fixed_nonce(self):
        self.assertIn(_FIXED_NONCE, self._header())

    def test_deterministic_with_same_inputs(self):
        h1 = self._header()
        h2 = self._header()
        self.assertEqual(h1, h2)

    def test_different_api_secret_gives_different_signature(self):
        creds_a = {**_FULL_CREDS, "TWITTER_API_SECRET": "secret_a"}
        creds_b = {**_FULL_CREDS, "TWITTER_API_SECRET": "secret_b"}
        h_a = _oauth_authorization_header(
            "POST", "https://api.twitter.com/2/tweets", creds_a,
            _timestamp=_FIXED_TS, _nonce=_FIXED_NONCE,
        )
        h_b = _oauth_authorization_header(
            "POST", "https://api.twitter.com/2/tweets", creds_b,
            _timestamp=_FIXED_TS, _nonce=_FIXED_NONCE,
        )
        self.assertNotEqual(h_a, h_b)

    def test_different_access_secret_gives_different_signature(self):
        creds_a = {**_FULL_CREDS, "TWITTER_ACCESS_SECRET": "ts_a"}
        creds_b = {**_FULL_CREDS, "TWITTER_ACCESS_SECRET": "ts_b"}
        h_a = _oauth_authorization_header(
            "POST", "https://api.twitter.com/2/tweets", creds_a,
            _timestamp=_FIXED_TS, _nonce=_FIXED_NONCE,
        )
        h_b = _oauth_authorization_header(
            "POST", "https://api.twitter.com/2/tweets", creds_b,
            _timestamp=_FIXED_TS, _nonce=_FIXED_NONCE,
        )
        self.assertNotEqual(h_a, h_b)

    def test_different_url_gives_different_signature(self):
        h_a = _oauth_authorization_header(
            "POST", "https://api.twitter.com/2/tweets", _FULL_CREDS,
            _timestamp=_FIXED_TS, _nonce=_FIXED_NONCE,
        )
        h_b = _oauth_authorization_header(
            "POST", "https://upload.twitter.com/1.1/media/upload.json", _FULL_CREDS,
            _timestamp=_FIXED_TS, _nonce=_FIXED_NONCE,
        )
        self.assertNotEqual(h_a, h_b)

    def test_signature_value_is_base64(self):
        header = self._header()
        # Extract signature value: oauth_signature="<value>"
        import re
        match = re.search(r'oauth_signature="([^"]+)"', header)
        self.assertIsNotNone(match)
        sig_encoded = match.group(1)
        # Percent-decode then base64-decode — must not raise
        from urllib.parse import unquote
        sig_b64 = unquote(sig_encoded)
        decoded = base64.b64decode(sig_b64)
        self.assertEqual(len(decoded), 20)  # SHA1 = 20 bytes

    def test_extra_params_change_signature(self):
        h_without = self._header()
        h_with = _oauth_authorization_header(
            "POST", "https://api.twitter.com/2/tweets", _FULL_CREDS,
            extra_params={"media_data": "abc"},
            _timestamp=_FIXED_TS, _nonce=_FIXED_NONCE,
        )
        self.assertNotEqual(h_without, h_with)

    def test_without_injectable_timestamp_nonce_still_works(self):
        # Real timestamp / nonce — just check it doesn't raise and starts with OAuth
        header = _oauth_authorization_header(
            "POST", "https://api.twitter.com/2/tweets", _FULL_CREDS,
        )
        self.assertTrue(header.startswith("OAuth "))


# ---------------------------------------------------------------------------
# TestBuildPayload
# ---------------------------------------------------------------------------

class TestBuildPayload(unittest.TestCase):

    def test_text_only(self):
        payload = _build_payload({"content": "Hello world"})
        self.assertEqual(payload, {"text": "Hello world"})

    def test_with_media_ids(self):
        payload = _build_payload({"content": "Look", "media_ids": ["111", "222"]})
        self.assertEqual(payload["media"], {"media_ids": ["111", "222"]})

    def test_empty_media_ids_excluded(self):
        payload = _build_payload({"content": "Look", "media_ids": []})
        self.assertNotIn("media", payload)

    def test_none_media_ids_excluded(self):
        payload = _build_payload({"content": "Look", "media_ids": None})
        self.assertNotIn("media", payload)

    def test_falsy_media_ids_filtered(self):
        payload = _build_payload({"content": "Look", "media_ids": [None, "", "real-id"]})
        self.assertEqual(payload["media"]["media_ids"], ["real-id"])

    def test_missing_content_gives_empty_text(self):
        payload = _build_payload({})
        self.assertEqual(payload["text"], "")

    def test_content_preserved_exactly(self):
        text = "Hello, World! #test @user https://example.com"
        payload = _build_payload({"content": text})
        self.assertEqual(payload["text"], text)


# ---------------------------------------------------------------------------
# TestParseResponse
# ---------------------------------------------------------------------------

class TestParseResponse(unittest.TestCase):

    def test_201_success(self):
        result = _parse_response(201, _TWEET_SUCCESS_BODY)
        self.assertTrue(result["success"])

    def test_201_extracts_post_id(self):
        result = _parse_response(201, _TWEET_SUCCESS_BODY)
        self.assertEqual(result["platform_post_id"], "tweet-999")

    def test_201_platform_response_populated(self):
        result = _parse_response(201, _TWEET_SUCCESS_BODY)
        self.assertIsNotNone(result["platform_response"])

    def test_201_malformed_json_still_succeeds(self):
        result = _parse_response(201, "not-json")
        self.assertTrue(result["success"])
        self.assertIsNone(result["platform_post_id"])

    def test_401_is_auth_error(self):
        result = _parse_response(401, "{}")
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_403_permission_error(self):
        result = _parse_response(403, '{"detail": "Forbidden"}')
        self.assertEqual(result["error_code"], PERMISSION_ERROR)

    def test_403_duplicate_content_is_content_rejected(self):
        body = '{"detail": "You are not allowed to create a Tweet with duplicate content."}'
        result = _parse_response(403, body)
        self.assertEqual(result["error_code"], CONTENT_REJECTED)

    def test_429_is_rate_limited(self):
        result = _parse_response(429, "{}")
        self.assertEqual(result["error_code"], RATE_LIMITED)

    def test_400_is_content_rejected(self):
        result = _parse_response(400, '{"detail": "bad request"}')
        self.assertEqual(result["error_code"], CONTENT_REJECTED)

    def test_422_is_content_rejected(self):
        result = _parse_response(422, "{}")
        self.assertEqual(result["error_code"], CONTENT_REJECTED)

    def test_500_is_platform_unavailable(self):
        result = _parse_response(500, "internal error")
        self.assertEqual(result["error_code"], PLATFORM_UNAVAILABLE)

    def test_503_is_platform_unavailable(self):
        result = _parse_response(503, "")
        self.assertEqual(result["error_code"], PLATFORM_UNAVAILABLE)

    def test_418_is_unknown_error(self):
        result = _parse_response(418, "i'm a teapot")
        self.assertEqual(result["error_code"], UNKNOWN_ERROR)

    def test_error_detail_from_json_detail_field(self):
        body = '{"detail": "Tweet text is too long."}'
        result = _parse_response(400, body)
        self.assertIn("too long", result["message"])

    def test_error_detail_from_json_title_field(self):
        body = '{"title": "Bad Request"}'
        result = _parse_response(400, body)
        self.assertIn("Bad Request", result["message"])

    def test_error_detail_fallback_to_raw_body(self):
        result = _parse_response(500, "raw server error")
        self.assertIn("raw server error", result["message"])

    def test_retryable_rate_limited(self):
        result = _parse_response(429, "{}")
        self.assertTrue(result["retryable"])

    def test_retryable_platform_unavailable(self):
        result = _parse_response(503, "")
        self.assertTrue(result["retryable"])

    def test_not_retryable_auth_error(self):
        result = _parse_response(401, "{}")
        self.assertFalse(result["retryable"])

    def test_not_retryable_content_rejected(self):
        result = _parse_response(400, "{}")
        self.assertFalse(result["retryable"])

    def test_failure_has_no_platform_post_id(self):
        result = _parse_response(401, "{}")
        self.assertNotIn("platform_post_id", result)


# ---------------------------------------------------------------------------
# TestCallTwitterApi
# ---------------------------------------------------------------------------

class TestCallTwitterApi(unittest.TestCase):

    def test_sends_post_request(self):
        calls = []
        def fake_http(req):
            calls.append(req)
            return _make_response(201, _TWEET_SUCCESS_BODY)

        _call_twitter_api({"text": "hi"}, _FULL_CREDS, _http_fn=fake_http)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].method, "POST")

    def test_sends_to_correct_url(self):
        calls = []
        def fake_http(req):
            calls.append(req)
            return _make_response(201, _TWEET_SUCCESS_BODY)

        _call_twitter_api({"text": "hi"}, _FULL_CREDS, _http_fn=fake_http)
        self.assertIn("api.twitter.com/2/tweets", calls[0].full_url)

    def test_authorization_header_present(self):
        calls = []
        def fake_http(req):
            calls.append(req)
            return _make_response(201, _TWEET_SUCCESS_BODY)

        _call_twitter_api({"text": "hi"}, _FULL_CREDS, _http_fn=fake_http)
        auth = calls[0].get_header("Authorization")
        self.assertIsNotNone(auth)
        self.assertTrue(auth.startswith("OAuth "))

    def test_content_type_is_json(self):
        calls = []
        def fake_http(req):
            calls.append(req)
            return _make_response(201, _TWEET_SUCCESS_BODY)

        _call_twitter_api({"text": "hi"}, _FULL_CREDS, _http_fn=fake_http)
        ct = calls[0].get_header("Content-type")
        self.assertIn("application/json", ct)

    def test_body_is_json_serialised(self):
        received_body = []
        def fake_http(req):
            received_body.append(req.data)
            return _make_response(201, _TWEET_SUCCESS_BODY)

        payload = {"text": "hello", "media": {"media_ids": ["123"]}}
        _call_twitter_api(payload, _FULL_CREDS, _http_fn=fake_http)
        parsed = json.loads(received_body[0].decode("utf-8"))
        self.assertEqual(parsed, payload)

    def test_returns_status_and_body(self):
        status, body = _call_twitter_api(
            {"text": "hi"}, _FULL_CREDS,
            _http_fn=_make_http_fn(201, _TWEET_SUCCESS_BODY),
        )
        self.assertEqual(status, 201)
        self.assertIn("tweet-999", body)

    def test_http_error_unwrapped_to_status_and_body(self):
        status, body = _call_twitter_api(
            {"text": "hi"}, _FULL_CREDS,
            _http_fn=_make_http_error(401, '{"detail": "Unauthorized"}'),
        )
        self.assertEqual(status, 401)
        self.assertIn("Unauthorized", body)

    def test_network_exception_propagates(self):
        def bad_http(req):
            raise OSError("connection refused")

        with self.assertRaises(OSError):
            _call_twitter_api({"text": "hi"}, _FULL_CREDS, _http_fn=bad_http)


# ---------------------------------------------------------------------------
# TestTwitterAdapterCall
# ---------------------------------------------------------------------------

class TestTwitterAdapterCall(unittest.TestCase):

    def _adapter(self, http_fn=None):
        return TwitterAdapter(_FULL_CREDS, _http_fn=http_fn)

    def test_missing_all_credentials_returns_auth_error(self):
        adapter = TwitterAdapter({})
        result = adapter({"platform": "twitter", "content": "hi"})
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_missing_one_credential_returns_auth_error(self):
        creds = {**_FULL_CREDS}
        del creds["TWITTER_ACCESS_SECRET"]
        adapter = TwitterAdapter(creds)
        result = adapter({"platform": "twitter", "content": "hi"})
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_missing_credentials_does_not_call_http(self):
        calls = []
        def spy(req):
            calls.append(req)
            return _make_response(201, _TWEET_SUCCESS_BODY)

        TwitterAdapter({}, _http_fn=spy)({"content": "hi"})
        self.assertEqual(calls, [])

    def test_success_returns_success_true(self):
        adapter = self._adapter(_make_http_fn(201, _TWEET_SUCCESS_BODY))
        result = adapter({"content": "hi", "media_ids": []})
        self.assertTrue(result["success"])

    def test_success_maps_platform_post_id(self):
        adapter = self._adapter(_make_http_fn(201, _TWEET_SUCCESS_BODY))
        result = adapter({"content": "hi"})
        self.assertEqual(result["platform_post_id"], "tweet-999")

    def test_401_returns_auth_error(self):
        adapter = self._adapter(_make_http_error(401, '{"detail": "Bad token"}'))
        result = adapter({"content": "hi"})
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], AUTH_ERROR)

    def test_429_returns_rate_limited(self):
        adapter = self._adapter(_make_http_error(429, "{}"))
        result = adapter({"content": "hi"})
        self.assertEqual(result["error_code"], RATE_LIMITED)
        self.assertTrue(result["retryable"])

    def test_500_returns_platform_unavailable(self):
        adapter = self._adapter(_make_http_error(500, "oops"))
        result = adapter({"content": "hi"})
        self.assertEqual(result["error_code"], PLATFORM_UNAVAILABLE)

    def test_network_error_returns_network_error_code(self):
        def bad_http(req):
            raise OSError("timeout")

        adapter = self._adapter(bad_http)
        result = adapter({"content": "hi"})
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], NETWORK_ERROR)
        self.assertTrue(result["retryable"])

    def test_network_error_message_included(self):
        def bad_http(req):
            raise OSError("connection refused")

        result = self._adapter(bad_http)({"content": "hi"})
        self.assertIn("connection refused", result["message"])

    def test_result_shape_valid_on_success(self):
        adapter = self._adapter(_make_http_fn(201, _TWEET_SUCCESS_BODY))
        result = adapter({"content": "hi"})
        validate_adapter_result(result)  # must not raise

    def test_result_shape_valid_on_failure(self):
        adapter = self._adapter(_make_http_error(401, "{}"))
        result = adapter({"content": "hi"})
        validate_adapter_result(result)  # must not raise

    def test_media_ids_forwarded_to_payload(self):
        sent_bodies = []
        def spy(req):
            sent_bodies.append(json.loads(req.data.decode("utf-8")))
            return _make_response(201, _TWEET_SUCCESS_BODY)

        adapter = self._adapter(spy)
        adapter({"content": "look", "media_ids": ["mid-1", "mid-2"]})
        self.assertEqual(sent_bodies[0]["media"]["media_ids"], ["mid-1", "mid-2"])


# ---------------------------------------------------------------------------
# TestCallTwitterUploadApi
# ---------------------------------------------------------------------------

class TestCallTwitterUploadApi(unittest.TestCase):

    def _temp_file(self, content=b"fake image bytes"):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(content)
        tmp.close()
        return tmp.name

    def test_missing_file_path_returns_error(self):
        result = _call_twitter_upload_api({"asset_type": "logo"}, _FULL_CREDS)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], MEDIA_UPLOAD_FAILED)

    def test_nonexistent_file_returns_error(self):
        result = _call_twitter_upload_api(
            {"file_path": "/no/such/file.png"}, _FULL_CREDS,
            _http_fn=_make_http_fn(200, _UPLOAD_SUCCESS_BODY),
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], MEDIA_UPLOAD_FAILED)
        self.assertIn("/no/such/file.png", result["message"])

    def test_success_extracts_media_id_string(self):
        path = self._temp_file()
        try:
            result = _call_twitter_upload_api(
                {"file_path": path}, _FULL_CREDS,
                _http_fn=_make_http_fn(200, _UPLOAD_SUCCESS_BODY),
            )
            self.assertTrue(result["success"])
            self.assertEqual(result["asset_ref"], "12345")
        finally:
            os.unlink(path)

    def test_request_body_contains_base64_encoded_file(self):
        file_content = b"test image data"
        path = self._temp_file(file_content)
        sent_bodies = []

        def spy(req):
            sent_bodies.append(req.data)
            return _make_response(200, _UPLOAD_SUCCESS_BODY)

        try:
            _call_twitter_upload_api(
                {"file_path": path}, _FULL_CREDS, _http_fn=spy,
            )
        finally:
            os.unlink(path)

        self.assertEqual(len(sent_bodies), 1)
        # Body is URL-encoded form: media_data=<base64>
        params = dict(p.split("=", 1) for p in sent_bodies[0].decode("utf-8").split("&"))
        decoded = base64.b64decode(urllib.parse.unquote(params["media_data"]))
        self.assertEqual(decoded, file_content)

    def test_authorization_header_sent(self):
        path = self._temp_file()
        captured = []

        def spy(req):
            captured.append(req)
            return _make_response(200, _UPLOAD_SUCCESS_BODY)

        try:
            _call_twitter_upload_api({"file_path": path}, _FULL_CREDS, _http_fn=spy)
        finally:
            os.unlink(path)

        auth = captured[0].get_header("Authorization")
        self.assertTrue(auth.startswith("OAuth "))

    def test_http_401_returns_auth_error(self):
        path = self._temp_file()
        try:
            result = _call_twitter_upload_api(
                {"file_path": path}, _FULL_CREDS,
                _http_fn=_make_http_error(401, '{"error": "unauthorized"}'),
            )
            self.assertFalse(result["success"])
            self.assertEqual(result["error_code"], AUTH_ERROR)
        finally:
            os.unlink(path)

    def test_http_403_returns_permission_error(self):
        path = self._temp_file()
        try:
            result = _call_twitter_upload_api(
                {"file_path": path}, _FULL_CREDS,
                _http_fn=_make_http_error(403, "{}"),
            )
            self.assertFalse(result["success"])
            self.assertEqual(result["error_code"], PERMISSION_ERROR)
        finally:
            os.unlink(path)

    def test_http_500_returns_platform_unavailable(self):
        path = self._temp_file()
        try:
            result = _call_twitter_upload_api(
                {"file_path": path}, _FULL_CREDS,
                _http_fn=_make_http_error(500, "server error"),
            )
            self.assertFalse(result["success"])
            self.assertEqual(result["error_code"], PLATFORM_UNAVAILABLE)
        finally:
            os.unlink(path)

    def test_200_malformed_json_still_succeeds(self):
        path = self._temp_file()
        try:
            result = _call_twitter_upload_api(
                {"file_path": path}, _FULL_CREDS,
                _http_fn=_make_http_fn(200, "not-json"),
            )
            self.assertTrue(result["success"])
            self.assertIsNone(result["asset_ref"])
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# TestGetAdapter
# ---------------------------------------------------------------------------

class TestGetAdapter(unittest.TestCase):

    def test_returns_twitter_adapter_instance(self):
        adapter = get_adapter(_FULL_CREDS)
        self.assertIsInstance(adapter, TwitterAdapter)

    def test_explicit_credentials_stored(self):
        adapter = get_adapter(_FULL_CREDS)
        self.assertEqual(adapter._creds, _FULL_CREDS)

    def test_http_fn_threaded_to_adapter(self):
        fn = lambda req: None
        adapter = get_adapter(_FULL_CREDS, _http_fn=fn)
        self.assertIs(adapter._http_fn, fn)

    def test_none_credentials_reads_from_env(self):
        env = {k: f"env_{k}" for k in REQUIRED_CREDENTIALS}
        with patch.dict(os.environ, env, clear=False):
            adapter = get_adapter()
        for k in REQUIRED_CREDENTIALS:
            self.assertEqual(adapter._creds[k], f"env_{k}")


# ---------------------------------------------------------------------------
# TestIntegration
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    """End-to-end via publish_to_platform with mocked HTTP."""

    def _run(self, http_fn):
        adapter = TwitterAdapter(_FULL_CREDS, _http_fn=http_fn)
        return publish_to_platform(
            {"platform": "twitter", "content": "Hello from OpenClaw!"},
            _adapter=adapter,
        )

    def test_successful_tweet_pipeline_succeeds(self):
        result = self._run(_make_http_fn(201, _TWEET_SUCCESS_BODY))
        self.assertTrue(result["success"])

    def test_post_id_propagated_from_adapter(self):
        result = self._run(_make_http_fn(201, _TWEET_SUCCESS_BODY))
        self.assertEqual(result["post_id"], "tweet-999")

    def test_platform_is_twitter(self):
        result = self._run(_make_http_fn(201, _TWEET_SUCCESS_BODY))
        self.assertEqual(result["platform"], "twitter")

    def test_auth_error_propagated_through_pipeline(self):
        result = self._run(_make_http_error(401, '{"detail": "Bad token"}'))
        self.assertFalse(result["success"])
        self.assertTrue(any(
            e["code"] == AUTH_ERROR for e in result["errors"]
        ))

    def test_rate_limit_propagated_through_pipeline(self):
        result = self._run(_make_http_error(429, "{}"))
        self.assertFalse(result["success"])
        self.assertTrue(any(
            e["code"] == RATE_LIMITED for e in result["errors"]
        ))

    def test_network_error_propagated_through_pipeline(self):
        def bad_http(req):
            raise OSError("network failure")

        result = self._run(bad_http)
        self.assertFalse(result["success"])
        self.assertTrue(any(
            e["code"] == NETWORK_ERROR for e in result["errors"]
        ))

    def test_pipeline_result_shape_valid_on_success(self):
        from tools.publish_pipeline import validate_pipeline_result
        result = self._run(_make_http_fn(201, _TWEET_SUCCESS_BODY))
        validate_pipeline_result(result)  # must not raise

    def test_pipeline_result_shape_valid_on_failure(self):
        from tools.publish_pipeline import validate_pipeline_result
        result = self._run(_make_http_error(500, "server error"))
        validate_pipeline_result(result)  # must not raise


# avoid name collision in body-parsing test
import urllib.parse

if __name__ == "__main__":
    unittest.main()
