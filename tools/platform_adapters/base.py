"""base — shared constants, helpers, and result validation for platform adapters.

This module is the single source of truth for:
  - canonical error code strings
  - the retryability table (which errors are worth retrying)
  - HTTP status → error code classification
  - adapter result shape validation
"""

# ---------------------------------------------------------------------------
# Canonical error codes
# ---------------------------------------------------------------------------

AUTH_ERROR          = "AUTH_ERROR"           # credentials wrong, missing, or expired
PERMISSION_ERROR    = "PERMISSION_ERROR"     # account lacks required scope/access
CONTENT_REJECTED    = "CONTENT_REJECTED"     # platform refused content (policy, duplicate)
RATE_LIMITED        = "RATE_LIMITED"         # platform throttled the request
MEDIA_UPLOAD_FAILED = "MEDIA_UPLOAD_FAILED"  # media attachment could not be uploaded
NETWORK_ERROR       = "NETWORK_ERROR"        # connection failed before response received
PLATFORM_UNAVAILABLE = "PLATFORM_UNAVAILABLE" # platform returned 5xx
TIMEOUT             = "TIMEOUT"              # request timed out
UNKNOWN_ERROR       = "UNKNOWN_ERROR"        # unclassified; conservative default

ALL_ERROR_CODES: frozenset[str] = frozenset({
    AUTH_ERROR,
    PERMISSION_ERROR,
    CONTENT_REJECTED,
    RATE_LIMITED,
    MEDIA_UPLOAD_FAILED,
    NETWORK_ERROR,
    PLATFORM_UNAVAILABLE,
    TIMEOUT,
    UNKNOWN_ERROR,
})

# ---------------------------------------------------------------------------
# Retryability table
# ---------------------------------------------------------------------------

_RETRYABLE: frozenset[str] = frozenset({
    RATE_LIMITED,
    NETWORK_ERROR,
    PLATFORM_UNAVAILABLE,
    TIMEOUT,
})

_NON_RETRYABLE: frozenset[str] = ALL_ERROR_CODES - _RETRYABLE


def is_retryable(error_code: str) -> bool:
    """Return True if the error is likely transient and worth retrying."""
    return error_code in _RETRYABLE


# ---------------------------------------------------------------------------
# HTTP status code → error code classification
# ---------------------------------------------------------------------------

def classify_http_error(status_code: int, body: str = "") -> str:
    """Map an HTTP status code to a canonical error code.

    Individual platform adapters may override specific cases (e.g. Twitter
    returns 403 for both auth failures and scope/permission issues). This
    provides a safe default mapping.

    Args:
        status_code: HTTP response status integer.
        body:        Raw response body string (unused in base; available to
                     platform adapters that override this function).

    Returns:
        One of the canonical error code strings.
    """
    if status_code in (401, 403):
        return AUTH_ERROR
    if status_code == 429:
        return RATE_LIMITED
    if status_code in (400, 422):
        return CONTENT_REJECTED
    if 500 <= status_code <= 599:
        return PLATFORM_UNAVAILABLE
    return UNKNOWN_ERROR


# ---------------------------------------------------------------------------
# Adapter result validation
# ---------------------------------------------------------------------------

def validate_adapter_result(result: dict) -> None:
    """Verify that an adapter result dict has the required shape.

    Raises ValueError with a descriptive message if any required field is
    missing. Adapters should call this before returning. Tests should call
    this to verify their mock adapters conform.

    Success shape:
        {"success": True, "platform_post_id": ..., "platform_response": ...}

    Failure shape:
        {"success": False, "error_code": ..., "message": ...}
        Optional: "retryable" (bool), "platform_response" (dict | None)
    """
    if not isinstance(result, dict):
        raise ValueError(
            f"Adapter result must be a dict, got {type(result).__name__}."
        )
    if "success" not in result:
        raise ValueError("Adapter result is missing required field 'success'.")

    if result["success"]:
        for field in ("platform_post_id", "platform_response"):
            if field not in result:
                raise ValueError(
                    f"Successful adapter result is missing required field '{field}'."
                )
    else:
        for field in ("error_code", "message"):
            if field not in result:
                raise ValueError(
                    f"Failed adapter result is missing required field '{field}'."
                )
