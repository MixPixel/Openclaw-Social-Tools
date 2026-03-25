"""linkedin — platform adapter skeleton for LinkedIn.

Auth mechanism:  OAuth 2.0 Bearer token (access token obtained via auth code flow).
Posting API:     POST https://api.linkedin.com/v2/ugcPosts
                 (UGC Posts API; supports text, articles, and media)
Media upload:    Multi-step: register upload → binary upload → attach asset URN.
                 Must be completed before ugcPosts call.

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
    "LINKEDIN_ACCESS_TOKEN",
)


# ---------------------------------------------------------------------------
# Payload builder (not yet implemented)
# ---------------------------------------------------------------------------

def _build_payload(entry: dict) -> dict:
    """Build the LinkedIn UGC Post request body from a queue entry.

    Would produce:
        {
            "author": "urn:li:person:<person_id>",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": entry["content"]},
                    "shareMediaCategory": "NONE"  # or "IMAGE"/"VIDEO" if media
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
        }

    Person URN requires an additional /v2/me call to resolve the member ID.
    """
    raise NotImplementedError("LinkedInAdapter._build_payload is not yet implemented.")


def _parse_response(status_code: int, body: str) -> dict:
    """Normalise a LinkedIn API response into the standard adapter result dict.

    Success (201):
        Response header X-RestLi-Id contains the post URN (the post ID).

    Failure: classify_http_error(status_code, body) maps to canonical code.
    LinkedIn-specific overrides:
        422 with "DUPLICATE_SHARE" → CONTENT_REJECTED
        403                        → PERMISSION_ERROR
    """
    raise NotImplementedError("LinkedInAdapter._parse_response is not yet implemented.")


# ---------------------------------------------------------------------------
# Adapter class
# ---------------------------------------------------------------------------

class LinkedInAdapter:
    """Adapter for LinkedIn.

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
            "LinkedInAdapter: real HTTP delivery is not yet implemented."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_adapter(credentials: dict | None = None) -> LinkedInAdapter:
    """Return a LinkedInAdapter, resolving credentials from env if not provided."""
    if credentials is None:
        credentials = {k: os.environ.get(k, "") for k in REQUIRED_CREDENTIALS}
    return LinkedInAdapter(credentials)
