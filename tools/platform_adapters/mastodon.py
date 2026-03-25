"""mastodon — platform adapter skeleton for Mastodon.

Auth mechanism:  OAuth 2.0 Bearer token. Each Mastodon instance has its own
                 domain; the instance URL must be supplied alongside the token.
                 Applications are registered per-instance.
Posting API:     POST https://{instance}/api/v1/statuses
                 (simplest REST API of the five supported platforms)
Media upload:    POST https://{instance}/api/v2/media
                 Returns a media attachment object; id attached to status.
Content limit:   500 characters (default; instance admins may raise it).
                 validate_post enforces the 500-character default upstream.

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
    "MASTODON_ACCESS_TOKEN",
    "MASTODON_INSTANCE_URL",
)


# ---------------------------------------------------------------------------
# Payload builder (not yet implemented)
# ---------------------------------------------------------------------------

def _build_payload(entry: dict) -> dict:
    """Build the Mastodon POST /api/v1/statuses request from a queue entry.

    Payload:
        {
            "status":     entry["content"],
            "media_ids":  [<uploaded_media_id>, ...]  # if media present
        }

    Headers:
        Authorization: Bearer <MASTODON_ACCESS_TOKEN>
        Content-Type:  application/json

    The base URL is https://{MASTODON_INSTANCE_URL}/api/v1/statuses.
    """
    raise NotImplementedError("MastodonAdapter._build_payload is not yet implemented.")


def _parse_response(status_code: int, body: str) -> dict:
    """Normalise a Mastodon API response into the standard adapter result dict.

    Success (200):
        body JSON contains {"id": "<status_id>", "url": "...", ...}
        → platform_post_id = id

    Failure: classify_http_error(status_code, body) maps to canonical code.
    Mastodon-specific overrides:
        422 → CONTENT_REJECTED (validation error, e.g. character limit exceeded)
        401 → AUTH_ERROR
    """
    raise NotImplementedError("MastodonAdapter._parse_response is not yet implemented.")


# ---------------------------------------------------------------------------
# Adapter class
# ---------------------------------------------------------------------------

class MastodonAdapter:
    """Adapter for Mastodon.

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
            "MastodonAdapter: real HTTP delivery is not yet implemented."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_adapter(credentials: dict | None = None) -> MastodonAdapter:
    """Return a MastodonAdapter, resolving credentials from env if not provided."""
    if credentials is None:
        credentials = {k: os.environ.get(k, "") for k in REQUIRED_CREDENTIALS}
    return MastodonAdapter(credentials)
