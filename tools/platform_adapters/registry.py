"""registry — adapter factory and platform dispatch.

Two public functions:

  get_adapter(platform, credentials=None)
    Return the adapter callable for a single named platform.
    Raises ValueError for unrecognised platform names — this is a developer
    error (a typo or a platform not yet supported).

  get_dispatch_adapter(credentials=None)
    Return a single callable that dispatches to the correct per-platform
    adapter based on entry["platform"]. Unknown platform values in a queue
    entry return a failure dict — they never raise, so publish_post always
    receives a clean result.
"""

import importlib

from .base import UNKNOWN_ERROR, validate_adapter_result
from .stub import StubAdapter

# ---------------------------------------------------------------------------
# Platform registry
# ---------------------------------------------------------------------------

_PLATFORM_TO_MODULE: dict[str, str] = {
    "twitter":   "tools.platform_adapters.twitter",
    "linkedin":  "tools.platform_adapters.linkedin",
    "instagram": "tools.platform_adapters.instagram",
    "facebook":  "tools.platform_adapters.facebook",
    "mastodon":  "tools.platform_adapters.mastodon",
}

_STUB_PLATFORM = "stub"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_adapter(platform: str, credentials: dict | None = None):
    """Return the adapter callable for a single named platform.

    Args:
        platform:    Canonical platform name: "twitter", "linkedin",
                     "instagram", "facebook", "mastodon", or "stub".
        credentials: Explicit credentials dict. None → read from os.environ
                     inside the platform module's get_adapter().

    Returns:
        A callable conforming to the adapter contract:
            (entry: dict) -> {"success": bool, ...}

    Raises:
        ValueError: if platform is not a recognised name. This is treated as
                    a developer error (wrong platform string passed by the
                    caller). Use get_dispatch_adapter() for runtime dispatch
                    where the platform value comes from user data.
    """
    if platform == _STUB_PLATFORM:
        return StubAdapter()

    if platform not in _PLATFORM_TO_MODULE:
        supported = ", ".join(sorted(_PLATFORM_TO_MODULE.keys()))
        raise ValueError(
            f"Unknown platform '{platform}'. "
            f"Supported: {supported}, {_STUB_PLATFORM}."
        )

    module = importlib.import_module(_PLATFORM_TO_MODULE[platform])
    return module.get_adapter(credentials)


def get_dispatch_adapter(credentials: dict | None = None):
    """Return a single callable that dispatches by entry["platform"].

    The returned callable is suitable for injecting into publish_post via
    _adapter when the queue contains entries for multiple platforms:

        adapter = get_dispatch_adapter(credentials={...})
        result = publish_post(data, _adapter=adapter)

    Unknown platform values in a queue entry produce a failure result dict
    (error_code: UNKNOWN_ERROR). They never raise an exception, so
    publish_post always receives a clean result regardless of queue content.

    Args:
        credentials: Passed through to each per-platform get_adapter().
                     None → each platform module reads from os.environ.

    Returns:
        A callable: (entry: dict) -> {"success": bool, ...}
    """
    def _dispatch(entry: dict) -> dict:
        platform = str(entry.get("platform") or "")

        if not platform:
            result = {
                "success":           False,
                "error_code":        UNKNOWN_ERROR,
                "message":           "Queue entry has no 'platform' field.",
                "retryable":         False,
                "platform_response": None,
            }
            validate_adapter_result(result)
            return result

        try:
            adapter = get_adapter(platform, credentials)
        except ValueError:
            result = {
                "success":           False,
                "error_code":        UNKNOWN_ERROR,
                "message":           f"Unknown platform: {platform}",
                "retryable":         False,
                "platform_response": None,
            }
            validate_adapter_result(result)
            return result

        return adapter(entry)

    return _dispatch
