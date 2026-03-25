"""instagram — platform adapter skeleton for Instagram.

Auth mechanism:  OAuth 2.0 Bearer token via Facebook Graph API.
                 Requires a Facebook Business account linked to an Instagram
                 Professional account.
Posting API:     Two-step process via Graph API:
                   Step 1: POST /{ig-user-id}/media
                           Creates a media container (image/video/carousel).
                   Step 2: POST /{ig-user-id}/media_publish
                           Publishes the container using the creation_id.
                 Text-only posts (Reels excluded) are not supported on Instagram;
                 at least one media item is required by the platform.
Content limit:   2,200 characters; validate_post enforces this upstream.

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
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID",
)


# ---------------------------------------------------------------------------
# Payload builder (not yet implemented)
# ---------------------------------------------------------------------------

def _build_payload(entry: dict) -> dict:
    """Build the Instagram Graph API media container request from a queue entry.

    Step 1 payload (image example):
        {
            "image_url": entry["media"][0]["url_or_path"],
            "caption":   entry["content"],
            "access_token": <token>
        }

    Step 2 payload:
        {
            "creation_id": <id from step 1>,
            "access_token": <token>
        }

    Returns a representation of both steps. Real implementation must execute
    them sequentially.
    """
    raise NotImplementedError("InstagramAdapter._build_payload is not yet implemented.")


def _parse_response(status_code: int, body: str) -> dict:
    """Normalise an Instagram Graph API response into the standard adapter result dict.

    Step 2 success (200):
        body JSON contains {"id": "<media_id>"}
        → platform_post_id = id

    Failure: classify_http_error(status_code, body) maps to canonical code.
    Graph API uses 200 for most errors (error details in body JSON); real
    implementation must parse the body's "error" key before checking status.
    """
    raise NotImplementedError("InstagramAdapter._parse_response is not yet implemented.")


# ---------------------------------------------------------------------------
# Adapter class
# ---------------------------------------------------------------------------

class InstagramAdapter:
    """Adapter for Instagram (via Facebook Graph API).

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
            "InstagramAdapter: real HTTP delivery is not yet implemented."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_adapter(credentials: dict | None = None) -> InstagramAdapter:
    """Return an InstagramAdapter, resolving credentials from env if not provided."""
    if credentials is None:
        credentials = {k: os.environ.get(k, "") for k in REQUIRED_CREDENTIALS}
    return InstagramAdapter(credentials)
