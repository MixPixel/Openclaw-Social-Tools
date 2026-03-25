"""linkedin — platform adapter skeleton for LinkedIn.

Auth mechanism:  OAuth 2.0 Bearer token (access token obtained via auth code flow).
Posting API:     POST https://api.linkedin.com/v2/ugcPosts
                 (UGC Posts API; supports text, articles, and media)
Media upload:    Multi-step: register upload → binary upload → attach asset URN.
                 Must be completed before ugcPosts call.

Real HTTP delivery is not yet implemented. _build_payload and _parse_response
raise NotImplementedError. PlatformAdapter.__call__ raises NotImplementedError
after passing the credential check (publish_post catches this as ADAPTER_EXCEPTION).

upload_asset() is implemented as a structured stub. The real media upload API
call is isolated in _call_linkedin_upload_api() which raises NotImplementedError
until HTTP is wired up.
"""

import os

from .base import AUTH_ERROR, MEDIA_UPLOAD_FAILED, validate_adapter_result

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


# ---------------------------------------------------------------------------
# Media upload
# ---------------------------------------------------------------------------

def _call_linkedin_upload_api(asset: dict, credentials: dict) -> dict:
    """Dispatch to the LinkedIn media upload API (multi-step).

    When implemented this will:
      1. POST https://api.linkedin.com/v2/assets?action=registerUpload
         with a registerUploadRequest body to obtain an uploadUrl and asset URN.
      2. PUT the binary asset content to the returned uploadUrl.
      3. Return {"success": True, "asset_ref": asset_urn}
         where asset_urn is used in ugcPosts media references.

    On HTTP failure, return:
      {"success": False, "error_code": <canonical code>, "message": <detail>}

    Not yet implemented — raises NotImplementedError until HTTP is wired up.
    """
    raise NotImplementedError(
        "LinkedIn media upload API is not yet implemented. "
        "Target: POST https://api.linkedin.com/v2/assets?action=registerUpload"
    )


def upload_asset(asset: dict, credentials: dict, *, _upload_api=None) -> dict:
    """Upload an asset to LinkedIn via the media upload API.

    This is the module-level upload function consumed by the Step 6
    upload_asset orchestrator (tools/upload_asset/upload_asset.py).
    It must not duplicate any validation logic from Step 5 or orchestration
    logic from Step 6.

    Args:
        asset:       Asset descriptor dict (same fields as validate_asset).
        credentials: Dict containing REQUIRED_CREDENTIALS keys.
        _upload_api: Injectable callable replacing _call_linkedin_upload_api.
                     Signature: (asset: dict, credentials: dict) -> dict.
                     For tests only; omit in production.

    Returns:
        Success: {"success": True, "asset_ref": str | None}
                 asset_ref is the LinkedIn asset URN for use in ugcPosts.
        Failure: {"success": False, "error_code": str, "message": str}
    """
    missing = [k for k in REQUIRED_CREDENTIALS if not credentials.get(k)]
    if missing:
        return {
            "success":    False,
            "error_code": AUTH_ERROR,
            "message":    f"Missing credentials: {', '.join(missing)}",
        }

    api_fn = _upload_api if _upload_api is not None else _call_linkedin_upload_api
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
