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

upload_asset() is implemented as a structured stub. The real media upload API
call is isolated in _call_mastodon_upload_api() which raises NotImplementedError
until HTTP is wired up.
"""

import os

from .base import AUTH_ERROR, MEDIA_UPLOAD_FAILED, validate_adapter_result

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


# ---------------------------------------------------------------------------
# Media upload
# ---------------------------------------------------------------------------

def _call_mastodon_upload_api(asset: dict, credentials: dict) -> dict:
    """Dispatch to the Mastodon v2 media upload endpoint.

    When implemented this will:
      POST https://{MASTODON_INSTANCE_URL}/api/v2/media
      with multipart/form-data containing the asset file and optional
      description (alt_text).
      Returns {"success": True, "asset_ref": media_attachment_id}
      where media_attachment_id is included in the statuses POST.

    On HTTP failure, return:
      {"success": False, "error_code": <canonical code>, "message": <detail>}

    Not yet implemented — raises NotImplementedError until HTTP is wired up.
    """
    raise NotImplementedError(
        "Mastodon media upload API is not yet implemented. "
        "Target: POST https://{instance}/api/v2/media"
    )


def upload_asset(asset: dict, credentials: dict, *, _upload_api=None) -> dict:
    """Upload an asset to Mastodon via the v2 media upload endpoint.

    This is the module-level upload function consumed by the Step 6
    upload_asset orchestrator (tools/upload_asset/upload_asset.py).
    It must not duplicate any validation logic from Step 5 or orchestration
    logic from Step 6.

    Args:
        asset:       Asset descriptor dict (same fields as validate_asset).
        credentials: Dict containing REQUIRED_CREDENTIALS keys.
        _upload_api: Injectable callable replacing _call_mastodon_upload_api.
                     Signature: (asset: dict, credentials: dict) -> dict.
                     For tests only; omit in production.

    Returns:
        Success: {"success": True, "asset_ref": str | None}
                 asset_ref is the Mastodon media attachment ID.
        Failure: {"success": False, "error_code": str, "message": str}
    """
    missing = [k for k in REQUIRED_CREDENTIALS if not credentials.get(k)]
    if missing:
        return {
            "success":    False,
            "error_code": AUTH_ERROR,
            "message":    f"Missing credentials: {', '.join(missing)}",
        }

    api_fn = _upload_api if _upload_api is not None else _call_mastodon_upload_api
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
