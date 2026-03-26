"""twitter — platform adapter for Twitter / X.

Auth mechanism:  OAuth 1.0a (user context) using HMAC-SHA1 signatures.
                 Signing uses only stdlib: hmac, hashlib, base64, urllib.parse.
Posting API:     POST https://api.twitter.com/2/tweets
Media upload:    POST https://upload.twitter.com/1.1/media/upload.json
                 Simple upload (base64) for images; chunked not yet implemented.

Injectable seams for tests (never pass in production):
  TwitterAdapter(_http_fn=fn)      — replaces urllib.request.urlopen for posts
  upload_asset(_upload_api=fn)     — replaces _call_twitter_upload_api entirely
  _call_twitter_upload_api(_http_fn=fn) — replaces urlopen for media upload
  _oauth_authorization_header(_timestamp=, _nonce=) — deterministic signing in tests
"""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Optional

from .base import (
    AUTH_ERROR,
    CONTENT_REJECTED,
    MEDIA_UPLOAD_FAILED,
    NETWORK_ERROR,
    PERMISSION_ERROR,
    PLATFORM_UNAVAILABLE,
    RATE_LIMITED,
    UNKNOWN_ERROR,
    is_retryable,
    validate_adapter_result,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_CREDENTIALS: tuple[str, ...] = (
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_SECRET",
)

_TWEETS_URL  = "https://api.twitter.com/2/tweets"
_UPLOAD_URL  = "https://upload.twitter.com/1.1/media/upload.json"

# Image formats that support simple (non-chunked) upload.
_SIMPLE_UPLOAD_FORMATS = frozenset({"jpeg", "jpg", "png", "gif", "webp"})


# ---------------------------------------------------------------------------
# OAuth 1.0a signing
# ---------------------------------------------------------------------------

def _percent_encode(value: str) -> str:
    """Percent-encode a string per RFC 3986 (unreserved chars only)."""
    return urllib.parse.quote(str(value), safe="")


def _oauth_authorization_header(
    method: str,
    url: str,
    credentials: dict,
    extra_params: Optional[dict] = None,
    *,
    _timestamp: Optional[str] = None,
    _nonce: Optional[str] = None,
) -> str:
    """Build an OAuth 1.0a Authorization header value.

    Args:
        method:       HTTP method (e.g. "POST").
        url:          Full request URL without query string.
        credentials:  Dict with REQUIRED_CREDENTIALS keys.
        extra_params: Additional request parameters to include in the
                      signature base string (e.g. form fields for upload).
        _timestamp:   Override unix timestamp — for deterministic tests only.
        _nonce:       Override nonce — for deterministic tests only.

    Returns:
        String suitable for use as an Authorization header value.
    """
    timestamp = _timestamp or str(int(time.time()))
    nonce = _nonce or uuid.uuid4().hex

    oauth_params: dict[str, str] = {
        "oauth_consumer_key":     credentials["TWITTER_API_KEY"],
        "oauth_nonce":            nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        timestamp,
        "oauth_token":            credentials["TWITTER_ACCESS_TOKEN"],
        "oauth_version":          "1.0",
    }

    # Signature base string includes oauth params + any extra request params.
    all_params: dict[str, str] = {**oauth_params, **(extra_params or {})}
    sorted_params = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}"
        for k, v in sorted(all_params.items())
    )
    base_string = "&".join([
        method.upper(),
        _percent_encode(url),
        _percent_encode(sorted_params),
    ])

    signing_key = "&".join([
        _percent_encode(credentials["TWITTER_API_SECRET"]),
        _percent_encode(credentials["TWITTER_ACCESS_SECRET"]),
    ])

    raw_signature = hmac.new(
        signing_key.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    oauth_params["oauth_signature"] = base64.b64encode(raw_signature).decode("utf-8")

    # Header value: OAuth key="value", ... sorted by key.
    parts = ", ".join(
        f'{_percent_encode(k)}="{_percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {parts}"


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------

def _build_payload(entry: dict) -> dict:
    """Build the Twitter v2 POST /tweets request body from a pipeline entry.

    Produces:
        {"text": content}
        {"text": content, "media": {"media_ids": ["id1", ...]}}  # if media present

    Twitter character limits are enforced upstream by validate_post.
    OAuth signing is handled separately by _oauth_authorization_header.
    """
    payload: dict = {"text": entry.get("content", "")}
    media_ids = [str(m) for m in (entry.get("media_ids") or []) if m]
    if media_ids:
        payload["media"] = {"media_ids": media_ids}
    return payload


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_response(status_code: int, body: str) -> dict:
    """Normalise a Twitter API HTTP response into a standard adapter result.

    Success (201):
        body JSON contains {"data": {"id": "<tweet_id>", "text": "..."}}
        → {"success": True, "platform_post_id": tweet_id, "platform_response": data}

    Failure: Twitter-specific status → error code mapping:
        401               → AUTH_ERROR
        403 + "duplicate" → CONTENT_REJECTED
        403               → PERMISSION_ERROR
        429               → RATE_LIMITED
        400 / 422         → CONTENT_REJECTED
        5xx               → PLATFORM_UNAVAILABLE
        other             → UNKNOWN_ERROR
    """
    if status_code == 201:
        try:
            data = json.loads(body).get("data", {})
            return {
                "success":           True,
                "platform_post_id":  str(data["id"]) if data.get("id") else None,
                "platform_response": data,
            }
        except (json.JSONDecodeError, AttributeError, KeyError):
            return {
                "success":           True,
                "platform_post_id":  None,
                "platform_response": None,
            }

    # Twitter-specific error classification.
    body_lower = body.lower()
    if status_code == 401:
        error_code = AUTH_ERROR
    elif status_code == 403 and "duplicate" in body_lower:
        error_code = CONTENT_REJECTED
    elif status_code == 403:
        error_code = PERMISSION_ERROR
    elif status_code == 429:
        error_code = RATE_LIMITED
    elif status_code in (400, 422):
        error_code = CONTENT_REJECTED
    elif 500 <= status_code <= 599:
        error_code = PLATFORM_UNAVAILABLE
    else:
        error_code = UNKNOWN_ERROR

    # Extract human-readable detail from JSON body when available.
    try:
        parsed = json.loads(body)
        detail = (
            parsed.get("detail")
            or parsed.get("title")
            or parsed.get("error")
            or body
        )
    except (json.JSONDecodeError, AttributeError):
        detail = body

    return {
        "success":           False,
        "error_code":        error_code,
        "message":           str(detail),
        "retryable":         is_retryable(error_code),
        "platform_response": None,
    }


# ---------------------------------------------------------------------------
# HTTP call (tweet posting)
# ---------------------------------------------------------------------------

def _call_twitter_api(
    payload: dict,
    credentials: dict,
    *,
    _http_fn=None,
) -> tuple[int, str]:
    """POST a JSON payload to the Twitter v2 /tweets endpoint.

    Args:
        payload:     Request body dict (from _build_payload).
        credentials: Dict with REQUIRED_CREDENTIALS keys.
        _http_fn:    Injectable replacement for urllib.request.urlopen.
                     Signature: (request) -> response-like object with
                     .status (int) and .read() -> bytes.
                     HTTPError is caught regardless.

    Returns:
        (status_code, body_str) tuple.

    Raises:
        OSError, urllib.error.URLError on network failure (caller handles).
    """
    body_bytes = json.dumps(payload).encode("utf-8")
    auth_header = _oauth_authorization_header("POST", _TWEETS_URL, credentials)

    req = urllib.request.Request(
        _TWEETS_URL,
        data=body_bytes,
        method="POST",
        headers={
            "Authorization": auth_header,
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        },
    )

    http_fn = _http_fn if _http_fn is not None else urllib.request.urlopen
    try:
        resp = http_fn(req)
        return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Adapter class
# ---------------------------------------------------------------------------

class TwitterAdapter:
    """Adapter for Twitter / X.

    Credential check runs before any network call.  Missing credentials return
    AUTH_ERROR without touching the network.

    Args:
        credentials: Dict with REQUIRED_CREDENTIALS keys.
        _http_fn:    Injectable replacement for urllib.request.urlopen.
                     For tests only — omit in production.
    """

    def __init__(self, credentials: dict, *, _http_fn=None) -> None:
        self._creds   = credentials
        self._http_fn = _http_fn

    def __call__(self, entry: dict) -> dict:
        missing = [k for k in REQUIRED_CREDENTIALS if not self._creds.get(k)]
        if missing:
            result = {
                "success":           False,
                "error_code":        AUTH_ERROR,
                "message":           f"Missing credentials: {', '.join(missing)}",
                "retryable":         False,
                "platform_response": None,
            }
            validate_adapter_result(result)
            return result

        payload = _build_payload(entry)
        try:
            status_code, body = _call_twitter_api(
                payload, self._creds, _http_fn=self._http_fn,
            )
        except Exception as exc:  # noqa: BLE001  (network / OS errors)
            result = {
                "success":           False,
                "error_code":        NETWORK_ERROR,
                "message":           str(exc),
                "retryable":         True,
                "platform_response": None,
            }
            validate_adapter_result(result)
            return result

        result = _parse_response(status_code, body)
        validate_adapter_result(result)
        return result


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_adapter(credentials: Optional[dict] = None, *, _http_fn=None) -> TwitterAdapter:
    """Return a TwitterAdapter, resolving credentials from env if not provided.

    Args:
        credentials: Explicit credentials dict.  None → read from os.environ.
        _http_fn:    Injectable HTTP function for test isolation.
    """
    if credentials is None:
        credentials = {k: os.environ.get(k, "") for k in REQUIRED_CREDENTIALS}
    return TwitterAdapter(credentials, _http_fn=_http_fn)


# ---------------------------------------------------------------------------
# Media upload
# ---------------------------------------------------------------------------

def _call_twitter_upload_api(
    asset: dict,
    credentials: dict,
    *,
    _http_fn=None,
) -> dict:
    """Upload a media asset to Twitter via the v1.1 media/upload endpoint.

    Uses simple (base64) upload — suitable for images (jpeg, jpg, png, gif,
    webp).  Chunked upload for video is not yet implemented.

    Args:
        asset:       Asset descriptor dict.  Must contain 'file_path' pointing
                     to a readable local file.
        credentials: Dict with REQUIRED_CREDENTIALS keys.
        _http_fn:    Injectable replacement for urllib.request.urlopen.

    Returns:
        Success: {"success": True, "asset_ref": "<media_id_string>"}
        Failure: {"success": False, "error_code": str, "message": str}
    """
    file_path = asset.get("file_path")
    if not file_path:
        return {
            "success":    False,
            "error_code": MEDIA_UPLOAD_FAILED,
            "message":    "asset must include 'file_path' for Twitter media upload.",
        }

    try:
        with open(file_path, "rb") as fh:
            media_data = fh.read()
    except OSError as exc:
        return {
            "success":    False,
            "error_code": MEDIA_UPLOAD_FAILED,
            "message":    f"Could not read file '{file_path}': {exc}",
        }

    media_b64 = base64.b64encode(media_data).decode("utf-8")
    form_params = {"media_data": media_b64}
    body_bytes = urllib.parse.urlencode(form_params).encode("utf-8")

    auth_header = _oauth_authorization_header("POST", _UPLOAD_URL, credentials)
    req = urllib.request.Request(
        _UPLOAD_URL,
        data=body_bytes,
        method="POST",
        headers={
            "Authorization": auth_header,
            "Content-Type":  "application/x-www-form-urlencoded",
        },
    )

    http_fn = _http_fn if _http_fn is not None else urllib.request.urlopen
    try:
        resp = http_fn(req)
        body = resp.read().decode("utf-8")
        status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        status = exc.code

    if status == 200:
        try:
            data = json.loads(body)
            media_id = data.get("media_id_string") or str(data.get("media_id", ""))
            return {"success": True, "asset_ref": media_id or None}
        except (json.JSONDecodeError, AttributeError):
            return {"success": True, "asset_ref": None}

    # Map HTTP error to canonical code.
    body_lower = body.lower()
    if status == 401:
        error_code = AUTH_ERROR
    elif status == 403:
        error_code = PERMISSION_ERROR
    elif status == 429:
        error_code = RATE_LIMITED
    elif 500 <= status <= 599:
        error_code = PLATFORM_UNAVAILABLE
    else:
        error_code = MEDIA_UPLOAD_FAILED

    try:
        parsed = json.loads(body)
        detail = parsed.get("error") or parsed.get("message") or body
    except (json.JSONDecodeError, AttributeError):
        detail = body

    return {
        "success":    False,
        "error_code": error_code,
        "message":    str(detail),
    }


def upload_asset(asset: dict, credentials: dict, *, _upload_api=None) -> dict:
    """Upload an asset to Twitter via the media upload API.

    This is the module-level upload function consumed by the upload_asset
    orchestrator (tools/upload_asset/upload_asset.py).  It does not re-validate
    the asset; the orchestrator guarantees policy and capability checks have
    already passed.

    Args:
        asset:       Asset descriptor dict.  Must include 'file_path'.
        credentials: Dict containing REQUIRED_CREDENTIALS keys.
        _upload_api: Injectable callable replacing _call_twitter_upload_api.
                     Signature: (asset, credentials) -> dict.
                     For tests only; omit in production.

    Returns:
        Success: {"success": True, "asset_ref": str | None}
        Failure: {"success": False, "error_code": str, "message": str}
    """
    missing = [k for k in REQUIRED_CREDENTIALS if not credentials.get(k)]
    if missing:
        return {
            "success":    False,
            "error_code": AUTH_ERROR,
            "message":    f"Missing credentials: {', '.join(missing)}",
        }

    api_fn = _upload_api if _upload_api is not None else _call_twitter_upload_api
    try:
        return api_fn(asset, credentials)
    except NotImplementedError as exc:
        return {
            "success":    False,
            "error_code": "UPLOAD_NOT_IMPLEMENTED",
            "message":    str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "success":    False,
            "error_code": MEDIA_UPLOAD_FAILED,
            "message":    str(exc),
        }
