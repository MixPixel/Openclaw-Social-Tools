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
"""

import os

from .base import AUTH_ERROR, validate_adapter_result

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
            return {
                "success":           False,
                "error_code":        AUTH_ERROR,
                "message":           f"Missing credentials: {', '.join(missing)}",
                "retryable":         False,
                "platform_response": None,
            }
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
