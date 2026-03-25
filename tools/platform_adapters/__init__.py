"""platform_adapters — platform adapter boundary for publish_post.

Public API
----------

Error code constants (from base):
    AUTH_ERROR, PERMISSION_ERROR, CONTENT_REJECTED, RATE_LIMITED,
    MEDIA_UPLOAD_FAILED, NETWORK_ERROR, PLATFORM_UNAVAILABLE, TIMEOUT,
    UNKNOWN_ERROR

Helpers (from base):
    is_retryable(error_code)          → bool
    classify_http_error(status, body) → str
    validate_adapter_result(result)   → None (raises ValueError on bad shape)

Adapters:
    StubAdapter(...)                  → configurable no-network adapter
    get_adapter(platform, credentials=None)         → platform adapter callable
    get_dispatch_adapter(credentials=None)          → dispatch callable (all platforms)

Usage
-----
    from tools.platform_adapters import get_dispatch_adapter
    from tools.publish_post import publish_post

    adapter = get_dispatch_adapter()           # reads credentials from os.environ
    result = publish_post(data, _adapter=adapter)
"""

from .base import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    CONTENT_REJECTED,
    RATE_LIMITED,
    MEDIA_UPLOAD_FAILED,
    NETWORK_ERROR,
    PLATFORM_UNAVAILABLE,
    TIMEOUT,
    UNKNOWN_ERROR,
    ALL_ERROR_CODES,
    is_retryable,
    classify_http_error,
    validate_adapter_result,
)
from .stub import StubAdapter
from .registry import get_adapter, get_dispatch_adapter

__all__ = [
    # Error code constants
    "AUTH_ERROR",
    "PERMISSION_ERROR",
    "CONTENT_REJECTED",
    "RATE_LIMITED",
    "MEDIA_UPLOAD_FAILED",
    "NETWORK_ERROR",
    "PLATFORM_UNAVAILABLE",
    "TIMEOUT",
    "UNKNOWN_ERROR",
    "ALL_ERROR_CODES",
    # Helpers
    "is_retryable",
    "classify_http_error",
    "validate_adapter_result",
    # Adapters
    "StubAdapter",
    "get_adapter",
    "get_dispatch_adapter",
]
