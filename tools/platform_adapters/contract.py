"""contract — capability constants and AdapterDefinition contract type.

This module is the single source of truth for:
  - ALL_CAPABILITIES   — frozenset of every known capability name
  - Capability constants — one string per capability
  - AdapterDefinition  — immutable dataclass describing an adapter's contract
  - validate_definition() — raises ValueError if a definition is malformed

Capability constants
--------------------
  PUBLISH_POST    Post a single status/post to a platform.
  PUBLISH_THREAD  Post a thread (sequence of connected, linked posts).
  UPLOAD_ASSET    Upload a media asset independently of posting (e.g. chunked
                  video upload that returns a media_id for later attachment).
  VALIDATE_POST   Validate post content against platform-specific rules without
                  publishing.
  PREVIEW_POST    Generate a visual or text preview without publishing.

Not all platforms support all capabilities.  Capabilities are declared per
adapter in capability_registry.py.  Unknown capabilities are rejected by
validate_definition().
"""

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Capability constants
# ---------------------------------------------------------------------------

PUBLISH_POST:   str = "publish_post"    # post a single status/post
PUBLISH_THREAD: str = "publish_thread"  # post a thread (chained posts)
UPLOAD_ASSET:   str = "upload_asset"    # standalone media upload
VALIDATE_POST:  str = "validate_post"   # content validation without publishing
PREVIEW_POST:   str = "preview_post"    # preview generation without publishing

ALL_CAPABILITIES: frozenset[str] = frozenset({
    PUBLISH_POST,
    PUBLISH_THREAD,
    UPLOAD_ASSET,
    VALIDATE_POST,
    PREVIEW_POST,
})


# ---------------------------------------------------------------------------
# AdapterDefinition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdapterDefinition:
    """Immutable contract record for a single platform adapter.

    Fields
    ------
    platform_id
        Canonical platform identifier (e.g. "twitter").  Must match the key
        used in capability_registry.py and the platform_id in
        config/platforms/<platform>.json.

    display_name
        Human-readable name for error messages and tooling output.

    capabilities
        Frozenset of capability strings this adapter declares.  All values
        must be members of ALL_CAPABILITIES.

    required_credential_keys
        Tuple of environment variable names required by the adapter.  Must
        match REQUIRED_CREDENTIALS in the corresponding platform module.

    module_path
        Fully qualified Python import path for the adapter module
        (e.g. "tools.platform_adapters.twitter").  Used by registry.py to
        dynamically import and instantiate the adapter.

    media_formats
        Frozenset of lowercase file extensions (without dot) that the
        platform accepts.  Empty frozenset means no media support declared.
    """

    platform_id:              str
    display_name:             str
    capabilities:             frozenset[str]
    required_credential_keys: tuple[str, ...]
    module_path:              str
    media_formats:            frozenset[str] = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_definition(defn: "AdapterDefinition") -> None:
    """Verify that an AdapterDefinition is well-formed.

    Checks:
      - defn is an AdapterDefinition instance
      - platform_id and display_name are non-empty strings
      - capabilities is a frozenset containing only known capability strings
      - required_credential_keys is a tuple
      - module_path is a non-empty string
      - media_formats is a frozenset

    Args:
        defn: The AdapterDefinition to validate.

    Raises:
        ValueError: with a descriptive message on any violation.
    """
    if not isinstance(defn, AdapterDefinition):
        raise ValueError(
            f"Expected AdapterDefinition, got {type(defn).__name__}."
        )
    if not isinstance(defn.platform_id, str) or not defn.platform_id.strip():
        raise ValueError(
            "AdapterDefinition.platform_id must be a non-empty string."
        )
    if not isinstance(defn.display_name, str) or not defn.display_name.strip():
        raise ValueError(
            f"AdapterDefinition('{defn.platform_id}').display_name must be a "
            "non-empty string."
        )
    if not isinstance(defn.capabilities, frozenset):
        raise ValueError(
            f"AdapterDefinition('{defn.platform_id}').capabilities must be a "
            f"frozenset, got {type(defn.capabilities).__name__}."
        )
    unknown_caps = defn.capabilities - ALL_CAPABILITIES
    if unknown_caps:
        raise ValueError(
            f"AdapterDefinition('{defn.platform_id}') declares unknown "
            f"capabilities: {sorted(unknown_caps)}. "
            f"Known: {sorted(ALL_CAPABILITIES)}."
        )
    if not isinstance(defn.required_credential_keys, tuple):
        raise ValueError(
            f"AdapterDefinition('{defn.platform_id}').required_credential_keys "
            f"must be a tuple, got {type(defn.required_credential_keys).__name__}."
        )
    if not isinstance(defn.module_path, str) or not defn.module_path.strip():
        raise ValueError(
            f"AdapterDefinition('{defn.platform_id}').module_path must be a "
            "non-empty string."
        )
    if not isinstance(defn.media_formats, frozenset):
        raise ValueError(
            f"AdapterDefinition('{defn.platform_id}').media_formats must be a "
            f"frozenset, got {type(defn.media_formats).__name__}."
        )
