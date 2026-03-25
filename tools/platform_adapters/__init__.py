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

Capability contract (from contract):
    PUBLISH_POST, PUBLISH_THREAD, UPLOAD_ASSET, VALIDATE_POST, PREVIEW_POST
    ALL_CAPABILITIES                  → frozenset of all known capability strings
    AdapterDefinition                 → immutable dataclass for an adapter's contract
    validate_definition(defn)         → None (raises ValueError on bad shape)

Capability registry (from capability_registry):
    CapabilityError                   → raised when a capability is not declared
    get_definition(platform_id)       → AdapterDefinition (raises ValueError if unknown)
    list_platforms()                  → sorted list of registered platform IDs
    list_capabilities(platform_id)    → sorted list of declared capabilities
    supports_capability(platform_id, capability) → bool
    require_capability(platform_id, capability)  → None (raises CapabilityError)

Usage
-----
    from tools.platform_adapters import get_dispatch_adapter
    from tools.publish_post import publish_post

    adapter = get_dispatch_adapter()           # reads credentials from os.environ
    result = publish_post(data, _adapter=adapter)

    # Capability query before dispatching:
    from tools.platform_adapters import supports_capability, PUBLISH_THREAD
    if supports_capability("twitter", PUBLISH_THREAD):
        ...
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
from .contract import (
    PUBLISH_POST,
    PUBLISH_THREAD,
    UPLOAD_ASSET,
    VALIDATE_POST,
    PREVIEW_POST,
    ALL_CAPABILITIES,
    AdapterDefinition,
    validate_definition,
)
from .capability_registry import (
    CapabilityError,
    get_definition,
    list_platforms,
    list_capabilities,
    supports_capability,
    require_capability,
)

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
    # Adapter helpers
    "is_retryable",
    "classify_http_error",
    "validate_adapter_result",
    # Adapters
    "StubAdapter",
    "get_adapter",
    "get_dispatch_adapter",
    # Capability constants
    "PUBLISH_POST",
    "PUBLISH_THREAD",
    "UPLOAD_ASSET",
    "VALIDATE_POST",
    "PREVIEW_POST",
    "ALL_CAPABILITIES",
    # Contract type and validator
    "AdapterDefinition",
    "validate_definition",
    # Capability registry
    "CapabilityError",
    "get_definition",
    "list_platforms",
    "list_capabilities",
    "supports_capability",
    "require_capability",
]
