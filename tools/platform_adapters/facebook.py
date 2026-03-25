"""facebook — platform adapter skeleton for Facebook Pages.

Auth mechanism:  Page Access Token (long-lived) obtained via Facebook Login
                 OAuth flow with pages_manage_posts and pages_read_engagement
                 permissions.
Posting API:     POST /{page-id}/feed  (text + link posts)
                 POST /{page-id}/photos (photo posts; requires photo upload)
                 POST /{page-id}/videos (video posts; resumable upload API)
Content limit:   63,206 characters; validate_post enforces this upstream.

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
    "FACEBOOK_PAGE_ACCESS_TOKEN",
    "FACEBOOK_PAGE_ID",
)


# ---------------------------------------------------------------------------
# Payload builder (not yet implemented)
# ---------------------------------------------------------------------------

def _build_payload(entry: dict) -> dict:
    """Build the Facebook Graph API feed post request from a queue entry.

    Text post payload:
        {
            "message":      entry["content"],
            "access_token": <page_access_token>
        }

    Photo post payload (POST /{page-id}/photos):
        {
            "url":          entry["media"][0]["url_or_path"],
            "caption":      entry["content"],
            "access_token": <page_access_token>
        }

    Post type is determined by presence of media items in the entry.
    """
    raise NotImplementedError("FacebookAdapter._build_payload is not yet implemented.")


def _parse_response(status_code: int, body: str) -> dict:
    """Normalise a Facebook Graph API response into the standard adapter result dict.

    Success (200):
        body JSON contains {"id": "<page-id>_<post-id>"}
        → platform_post_id = id

    Failure: Graph API sometimes returns 200 with an error body; real
    implementation must check for "error" key before treating as success.
    classify_http_error(status_code) used as fallback for HTTP-level errors.
    """
    raise NotImplementedError("FacebookAdapter._parse_response is not yet implemented.")


# ---------------------------------------------------------------------------
# Adapter class
# ---------------------------------------------------------------------------

class FacebookAdapter:
    """Adapter for Facebook Pages.

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
            "FacebookAdapter: real HTTP delivery is not yet implemented."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_adapter(credentials: dict | None = None) -> FacebookAdapter:
    """Return a FacebookAdapter, resolving credentials from env if not provided."""
    if credentials is None:
        credentials = {k: os.environ.get(k, "") for k in REQUIRED_CREDENTIALS}
    return FacebookAdapter(credentials)
