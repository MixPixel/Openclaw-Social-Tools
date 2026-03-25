"""capability_registry — platform adapter definitions and capability query layer.

This module is the single registry of AdapterDefinition records — one entry per
supported platform.  It is the authoritative source for:

  - which platform IDs are supported
  - what capabilities each platform adapter declares
  - what credentials each adapter requires
  - which module implements each adapter

It is also the source that registry.py uses to resolve module_path when
constructing adapter callables, so the two are never out of sync.

Public API
----------

  get_definition(platform_id) -> AdapterDefinition
      Return the definition for a named platform.
      Raises ValueError for unknown platform IDs.

  list_platforms() -> list[str]
      Return a sorted list of all registered platform IDs.

  list_capabilities(platform_id) -> list[str]
      Return a sorted list of capabilities declared for a platform.
      Raises ValueError for unknown platforms.

  supports_capability(platform_id, capability) -> bool
      Return True if the platform declares the capability.
      Raises ValueError for unknown platforms.

  require_capability(platform_id, capability) -> None
      Assert that a platform supports a capability.
      Raises CapabilityError if the capability is not declared.
      Raises ValueError for unknown platforms.

CapabilityError vs ValueError
------------------------------
  ValueError       Unknown platform_id — developer / config error.
  CapabilityError  Known platform, but the requested capability is not
                   declared.  Callers that need to branch on capability
                   support should use supports_capability() instead.
"""

from .contract import (
    AdapterDefinition,
    ALL_CAPABILITIES,
    PUBLISH_POST,
    PUBLISH_THREAD,
    UPLOAD_ASSET,
    VALIDATE_POST,
    PREVIEW_POST,
    validate_definition,
)

# ---------------------------------------------------------------------------
# CapabilityError
# ---------------------------------------------------------------------------

class CapabilityError(Exception):
    """Raised when a requested capability is not declared by a platform adapter.

    Attributes match the ValueError pattern used elsewhere in the codebase:
    the string representation includes both the platform_id and the missing
    capability name, making it easy to surface in logs and test assertions.
    """


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, AdapterDefinition] = {}


def _register(defn: AdapterDefinition) -> None:
    """Validate and add a definition to the module-level registry.

    Called at import time for each platform.  Raises ValueError (via
    validate_definition) if the definition is malformed — this is a
    programming error and should surface immediately on import.
    """
    validate_definition(defn)
    _REGISTRY[defn.platform_id] = defn


# ---------------------------------------------------------------------------
# Platform definitions — one AdapterDefinition per canonical platform_id
#
# Capability notes:
#   PUBLISH_POST   — all five platforms support single-post publishing
#   UPLOAD_ASSET   — all five require media pre-upload before attaching
#   VALIDATE_POST  — validate_post.py implements client-side content rules for
#                    all five; declared here so callers can query capability
#   PUBLISH_THREAD — not yet implemented; omitted from all current adapters
#   PREVIEW_POST   — not yet implemented; omitted from all current adapters
# ---------------------------------------------------------------------------

_register(AdapterDefinition(
    platform_id="twitter",
    display_name="Twitter / X",
    capabilities=frozenset({PUBLISH_POST, UPLOAD_ASSET, VALIDATE_POST}),
    required_credential_keys=(
        "TWITTER_API_KEY",
        "TWITTER_API_SECRET",
        "TWITTER_ACCESS_TOKEN",
        "TWITTER_ACCESS_SECRET",
    ),
    module_path="tools.platform_adapters.twitter",
    media_formats=frozenset({
        "jpeg", "jpg", "png", "gif", "webp", "mp4", "mov",
    }),
))

_register(AdapterDefinition(
    platform_id="linkedin",
    display_name="LinkedIn",
    capabilities=frozenset({PUBLISH_POST, UPLOAD_ASSET, VALIDATE_POST}),
    required_credential_keys=(
        "LINKEDIN_ACCESS_TOKEN",
    ),
    module_path="tools.platform_adapters.linkedin",
    media_formats=frozenset({
        "jpeg", "jpg", "png", "gif", "mp4", "mov",
    }),
))

_register(AdapterDefinition(
    platform_id="instagram",
    display_name="Instagram",
    capabilities=frozenset({PUBLISH_POST, UPLOAD_ASSET, VALIDATE_POST}),
    required_credential_keys=(
        "INSTAGRAM_ACCESS_TOKEN",
        "INSTAGRAM_BUSINESS_ACCOUNT_ID",
    ),
    module_path="tools.platform_adapters.instagram",
    media_formats=frozenset({
        "jpeg", "jpg", "png", "mp4", "mov",
    }),
))

_register(AdapterDefinition(
    platform_id="facebook",
    display_name="Facebook",
    capabilities=frozenset({PUBLISH_POST, UPLOAD_ASSET, VALIDATE_POST}),
    required_credential_keys=(
        "FACEBOOK_PAGE_ACCESS_TOKEN",
        "FACEBOOK_PAGE_ID",
    ),
    module_path="tools.platform_adapters.facebook",
    media_formats=frozenset({
        "jpeg", "jpg", "png", "gif", "mp4", "mov",
    }),
))

_register(AdapterDefinition(
    platform_id="mastodon",
    display_name="Mastodon",
    capabilities=frozenset({PUBLISH_POST, UPLOAD_ASSET, VALIDATE_POST}),
    required_credential_keys=(
        "MASTODON_ACCESS_TOKEN",
        "MASTODON_INSTANCE_URL",
    ),
    module_path="tools.platform_adapters.mastodon",
    media_formats=frozenset({
        "jpeg", "jpg", "png", "gif", "webp", "mp4", "mov", "webm",
    }),
))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_definition(platform_id: str) -> AdapterDefinition:
    """Return the AdapterDefinition for the given canonical platform_id.

    Args:
        platform_id: Canonical platform ID (e.g. "twitter").

    Returns:
        The AdapterDefinition registered for that platform.

    Raises:
        ValueError: if platform_id is not registered.
    """
    defn = _REGISTRY.get(platform_id)
    if defn is None:
        known = ", ".join(sorted(_REGISTRY.keys()))
        raise ValueError(
            f"Unknown platform '{platform_id}'. "
            f"Registered platforms: {known}."
        )
    return defn


def list_platforms() -> list[str]:
    """Return a sorted list of all registered canonical platform IDs."""
    return sorted(_REGISTRY.keys())


def list_capabilities(platform_id: str) -> list[str]:
    """Return a sorted list of capabilities declared for a platform.

    Args:
        platform_id: Canonical platform ID.

    Returns:
        Sorted list of capability strings.

    Raises:
        ValueError: if platform_id is not registered.
    """
    return sorted(get_definition(platform_id).capabilities)


def supports_capability(platform_id: str, capability: str) -> bool:
    """Return True if the platform declares the named capability.

    Args:
        platform_id: Canonical platform ID.
        capability:  Capability constant (e.g. PUBLISH_POST).

    Returns:
        True if the platform's capabilities frozenset includes capability;
        False otherwise (including if capability is not a known capability).

    Raises:
        ValueError: if platform_id is not registered.
    """
    return capability in get_definition(platform_id).capabilities


def require_capability(platform_id: str, capability: str) -> None:
    """Assert that a platform supports a capability.

    A convenience guard for callers that must abort if a capability is absent.

    Args:
        platform_id: Canonical platform ID.
        capability:  Capability constant (e.g. PUBLISH_POST).

    Returns:
        None — succeeds silently when the capability is declared.

    Raises:
        ValueError:      if platform_id is not registered.
        CapabilityError: if the platform does not declare the capability.
    """
    defn = get_definition(platform_id)   # raises ValueError for unknown platform
    if capability not in defn.capabilities:
        declared = sorted(defn.capabilities)
        raise CapabilityError(
            f"Platform '{platform_id}' does not support capability '{capability}'. "
            f"Declared capabilities: {declared}."
        )
