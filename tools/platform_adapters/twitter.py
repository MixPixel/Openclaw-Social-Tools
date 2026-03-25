"""twitter — platform adapter skeleton for Twitter / X.

Auth mechanism:  OAuth 1.0a (user context) using HMAC-SHA1 signatures.
                 Requires four credentials: API key/secret + access token/secret.
Posting API:     POST https://api.twitter.com/2/tweets
Media upload:    POST https://upload.twitter.com/1.1/media/upload.json
                 (chunked upload for video; simple upload for images)
                 Must be called before the tweet is created; media_id attached.

Real HTTP delivery is not yet implemented. _build_payload and _parse_response
raise NotImplementedError. PlatformAdapter.__call__ raises NotImplementedError
after passing the credential check (publish_post catches this as ADAPTER_EXCEPTION).

upload_asset() is implemented and tested with mock injection. The real media
upload API call is isolated in _call_twitter_upload_api() which raises
NotImplementedError until HTTP is wired up.
"""

import os

from .base import AUTH_ERROR, MEDIA_UPLOAD_FAILED, validate_adapter_result

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

REQUIRED_CREDENTIALS: tuple[str, ...] = (
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_SECRET",
)


# ---------------------------------------------------------------------------
# Payload builder (not yet implemented)
# ---------------------------------------------------------------------------

def _build_payload(entry: dict) -> dict:
    """Build the Twitter v2 POST /tweets request body from a queue entry.

    Would produce:
        {
            "text": entry["content"],
            "media": {"media_ids": [<uploaded_media_id>, ...]}  # if media present
        }

    Twitter character limits are enforced upstream by validate_post.
    OAuth 1.0a Authorization header is computed separately using hmac + hashlib.
    """
    raise NotImplementedError("TwitterAdapter._build_payload is not yet implemented.")


def _parse_response(status_code: int, body: str) -> dict:
    """Normalise a Twitter API response into the standard adapter result dict.

    Success (201):
        body JSON contains {"data": {"id": "<tweet_id>", "text": "..."}}
        → platform_post_id = data["id"]

    Failure: classify_http_error(status_code, body) maps to canonical code.
    Twitter-specific overrides:
        403 with "duplicate content" in body → CONTENT_REJECTED
        403 otherwise                        → PERMISSION_ERROR
    """
    raise NotImplementedError("TwitterAdapter._parse_response is not yet implemented.")


# ---------------------------------------------------------------------------
# Adapter class
# ---------------------------------------------------------------------------

class TwitterAdapter:
    """Adapter for Twitter / X.

    Credential check is performed before any network call. Missing credentials
    return a clean AUTH_ERROR result dict; they do not raise.

    Real delivery raises NotImplementedError until implemented.
    """

    def __init__(self, credentials: dict) -> None:
        self._creds = credentials

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
        raise NotImplementedError(
            "TwitterAdapter: real HTTP delivery is not yet implemented."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_adapter(credentials: dict | None = None) -> TwitterAdapter:
    """Return a TwitterAdapter, resolving credentials from env if not provided."""
    if credentials is None:
        credentials = {k: os.environ.get(k, "") for k in REQUIRED_CREDENTIALS}
    return TwitterAdapter(credentials)


# ---------------------------------------------------------------------------
# Media upload
# ---------------------------------------------------------------------------

def _call_twitter_upload_api(asset: dict, credentials: dict) -> dict:
    """Dispatch to the Twitter v1.1 media upload API.

    When implemented this will:
      1. Determine upload type from asset["format"]:
           images (jpeg, jpg, png, gif, webp) → simple upload
           video (mp4, mov)                   → chunked INIT/APPEND/FINALIZE
      2. POST to https://upload.twitter.com/1.1/media/upload.json
         with OAuth 1.0a Authorization header (hmac + hashlib, stdlib only).
      3. Parse the JSON response body → {"media_id_string": "...", ...}
      4. Return {"success": True, "asset_ref": media_id_string}

    On HTTP failure, return:
      {"success": False, "error_code": <canonical code>, "message": <detail>}

    Not yet implemented — raises NotImplementedError until HTTP is wired up.
    """
    raise NotImplementedError(
        "Twitter media upload API is not yet implemented. "
        "Target: POST https://upload.twitter.com/1.1/media/upload.json"
    )


def upload_asset(asset: dict, credentials: dict, *, _upload_api=None) -> dict:
    """Upload an asset to Twitter via the media upload API.

    This is the module-level upload function consumed by the Step 6
    upload_asset orchestrator (tools/upload_asset/upload_asset.py).
    It must not duplicate any validation logic from Step 5 or orchestration
    logic from Step 6.

    Args:
        asset:       Asset descriptor dict (same fields as validate_asset).
                     The adapter does not re-validate; Step 6 guarantees the
                     asset passed all policy/capability checks before calling.
        credentials: Dict containing REQUIRED_CREDENTIALS keys.
        _upload_api: Injectable callable replacing _call_twitter_upload_api.
                     Signature: (asset: dict, credentials: dict) -> dict.
                     For tests only; omit in production.

    Returns:
        Success: {"success": True, "asset_ref": str | None}
                 asset_ref is the Twitter media_id_string for use in tweets.
        Failure: {"success": False, "error_code": str, "message": str}
    """
    # Step 1: credential check — mirrors TwitterAdapter.__call__ pattern.
    missing = [k for k in REQUIRED_CREDENTIALS if not credentials.get(k)]
    if missing:
        return {
            "success":    False,
            "error_code": AUTH_ERROR,
            "message":    f"Missing credentials: {', '.join(missing)}",
        }

    # Step 2: dispatch to upload API (injectable seam for tests).
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
