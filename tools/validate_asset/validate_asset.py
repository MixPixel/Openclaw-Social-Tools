"""validate_asset — pre-upload asset validator.

Determines whether a given asset descriptor is valid for a target platform
before any upload or publish is attempted.

Two sources of truth are consumed without duplication:
  - config/asset_policy.json (Step 3) — per-asset-type edit rules, license
    requirements, attribution requirements, allowed contexts, and global
    provenance/alt-text rules.
  - tools/platform_adapters/capability_registry (Step 4) — which platforms
    support UPLOAD_ASSET, and which media formats each platform accepts.

Public API
----------
  validate_asset(asset, platform, *, policy_path=None) -> dict
      Return a structured validation result for the asset/platform pair.

  validate_asset_result(result) -> None
      Shape-check a validate_asset result dict.
      Raises ValueError if required fields are missing or have wrong types.

Error code constants
--------------------
  UNKNOWN_PLATFORM, UPLOAD_NOT_SUPPORTED, UNKNOWN_ASSET_TYPE,
  FORMAT_NOT_ALLOWED, CONTEXT_NOT_ALLOWED,
  FORBIDDEN_SOURCE, SOURCE_NOT_APPROVED,
  LICENSE_REQUIRED, ATTRIBUTION_REQUIRED,
  ALT_TEXT_REQUIRED, EDIT_NOT_PERMITTED

  ALL_ERROR_CODES — frozenset of all codes above
"""

import json
import re
import urllib.parse
from pathlib import Path
from typing import Optional

from tools.platform_adapters.capability_registry import (
    get_definition,
    list_platforms,
    supports_capability,
)
from tools.platform_adapters.contract import UPLOAD_ASSET

# ---------------------------------------------------------------------------
# Default policy path
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent       # tools/validate_asset/
_REPO_ROOT = _HERE.parent.parent              # repo root
_DEFAULT_POLICY_PATH = _REPO_ROOT / "config" / "asset_policy.json"

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

UNKNOWN_PLATFORM:     str = "UNKNOWN_PLATFORM"
UPLOAD_NOT_SUPPORTED: str = "UPLOAD_NOT_SUPPORTED"
UNKNOWN_ASSET_TYPE:   str = "UNKNOWN_ASSET_TYPE"
FORMAT_NOT_ALLOWED:   str = "FORMAT_NOT_ALLOWED"
CONTEXT_NOT_ALLOWED:  str = "CONTEXT_NOT_ALLOWED"
FORBIDDEN_SOURCE:     str = "FORBIDDEN_SOURCE"
SOURCE_NOT_APPROVED:  str = "SOURCE_NOT_APPROVED"
LICENSE_REQUIRED:     str = "LICENSE_REQUIRED"
ATTRIBUTION_REQUIRED: str = "ATTRIBUTION_REQUIRED"
ALT_TEXT_REQUIRED:    str = "ALT_TEXT_REQUIRED"
EDIT_NOT_PERMITTED:   str = "EDIT_NOT_PERMITTED"

ALL_ERROR_CODES: frozenset[str] = frozenset({
    UNKNOWN_PLATFORM,
    UPLOAD_NOT_SUPPORTED,
    UNKNOWN_ASSET_TYPE,
    FORMAT_NOT_ALLOWED,
    CONTEXT_NOT_ALLOWED,
    FORBIDDEN_SOURCE,
    SOURCE_NOT_APPROVED,
    LICENSE_REQUIRED,
    ATTRIBUTION_REQUIRED,
    ALT_TEXT_REQUIRED,
    EDIT_NOT_PERMITTED,
})

# ---------------------------------------------------------------------------
# Edit-rule permission table
#   None  → all edits allowed
#   frozenset → only these edit_applied values are permitted (empty = none)
# ---------------------------------------------------------------------------

_EDIT_RULE_ALLOWED: dict[str, Optional[frozenset[str]]] = {
    "locked":        frozenset(),
    "resizable_only": frozenset({"resize"}),
    "croppable_only": frozenset({"crop"}),
    "editable":      None,
    "reference_only": frozenset(),
}

# ---------------------------------------------------------------------------
# Policy file cache
# ---------------------------------------------------------------------------

_policy_cache: dict[str, dict] = {}


def _clear_policy_cache() -> None:
    """Clear the policy file cache. Used by tests that inject a custom path."""
    _policy_cache.clear()


def _load_policy(policy_path: Optional[Path]) -> dict:
    """Load and cache asset_policy.json from the given path."""
    path = Path(policy_path).resolve() if policy_path else _DEFAULT_POLICY_PATH
    key = str(path)
    if key not in _policy_cache:
        try:
            with path.open(encoding="utf-8") as fh:
                _policy_cache[key] = json.load(fh)
        except FileNotFoundError:
            raise RuntimeError(f"Asset policy file not found: {path}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Asset policy file is not valid JSON ({path}): {exc}")
    return _policy_cache[key]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise(value: object) -> str:
    """Strip whitespace and lowercase a string input. Returns '' for non-str."""
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _domain_approved(hostname: str, approved_domains: list[str]) -> bool:
    """Return True if hostname matches any approved domain (exact or subdomain)."""
    hostname = hostname.lower().lstrip("www.")
    for domain in approved_domains:
        d = domain.lower()
        if hostname == d or hostname.endswith("." + d):
            return True
    return False


def _check_source_url(
    source_url: str,
    forbidden_patterns: list[str],
    approved_domains: list[str],
    errors: list[dict],
) -> None:
    """Append FORBIDDEN_SOURCE and/or SOURCE_NOT_APPROVED errors as appropriate."""
    # Forbidden pattern check (regex, case-insensitive)
    for pattern in forbidden_patterns:
        try:
            if re.search(pattern, source_url, re.IGNORECASE):
                errors.append({
                    "code":    FORBIDDEN_SOURCE,
                    "message": (
                        f"Source URL matches forbidden pattern '{pattern}'. "
                        "This asset source is not permitted."
                    ),
                    "pattern": pattern,
                })
                break  # one FORBIDDEN_SOURCE error is sufficient
        except re.error:
            continue  # malformed pattern in config — skip silently

    # Approved domain check
    parsed = urllib.parse.urlparse(source_url)
    hostname = parsed.hostname or ""
    if hostname and not _domain_approved(hostname, approved_domains):
        errors.append({
            "code":     SOURCE_NOT_APPROVED,
            "message":  (
                f"Source URL hostname '{hostname}' is not in the approved "
                "source domains list."
            ),
            "hostname": hostname,
        })


def _check_license(
    asset: dict,
    required_fields: list[str],
    errors: list[dict],
) -> None:
    """Append a LICENSE_REQUIRED error if the license record is incomplete."""
    license_record = asset.get("license")
    if not isinstance(license_record, dict):
        errors.append({
            "code":    LICENSE_REQUIRED,
            "message": (
                "This asset type requires a license record with fields: "
                f"{', '.join(required_fields)}. No license record provided."
            ),
            "required_fields": required_fields,
        })
        return

    missing = [f for f in required_fields if not license_record.get(f)]
    if missing:
        errors.append({
            "code":    LICENSE_REQUIRED,
            "message": (
                f"License record is missing required fields: {', '.join(missing)}."
            ),
            "missing_fields": missing,
        })


def _check_attribution(asset: dict, errors: list[dict]) -> None:
    """Append ATTRIBUTION_REQUIRED if attribution is absent or empty."""
    license_record = asset.get("license")
    attribution = (
        license_record.get("attribution") if isinstance(license_record, dict) else None
    )
    if not attribution or not str(attribution).strip():
        errors.append({
            "code":    ATTRIBUTION_REQUIRED,
            "message": (
                "This asset type requires an attribution string. "
                "Provide 'attribution' in the asset's license record."
            ),
        })


def _check_edit_rule(
    edit_applied: str,
    edit_rule: str,
    asset_type: str,
    errors: list[dict],
) -> None:
    """Append EDIT_NOT_PERMITTED if edit_applied violates the asset's edit_rule."""
    allowed = _EDIT_RULE_ALLOWED.get(edit_rule)
    if allowed is None:
        return  # editable — all edits permitted

    if edit_applied not in allowed:
        if allowed:
            permitted_str = f"Only permitted edit for '{asset_type}' is: {', '.join(sorted(allowed))}."
        else:
            permitted_str = f"Asset type '{asset_type}' has edit_rule '{edit_rule}': no edits are permitted."
        errors.append({
            "code":         EDIT_NOT_PERMITTED,
            "message":      (
                f"Edit '{edit_applied}' is not allowed for asset type "
                f"'{asset_type}' (edit_rule: '{edit_rule}'). {permitted_str}"
            ),
            "edit_applied": edit_applied,
            "edit_rule":    edit_rule,
        })


# ---------------------------------------------------------------------------
# Result shape validator
# ---------------------------------------------------------------------------

def validate_asset_result(result: dict) -> None:
    """Verify that a validate_asset result dict has the required shape.

    Raises ValueError with a descriptive message if any field is missing or
    has the wrong type.  Callers and tests should use this to verify result
    conformance.

    Required fields:
        valid (bool), platform (str), asset_type (str | None),
        errors (list), warnings (list)
    """
    if not isinstance(result, dict):
        raise ValueError(
            f"validate_asset result must be a dict, got {type(result).__name__}."
        )
    for field in ("valid", "platform", "errors", "warnings"):
        if field not in result:
            raise ValueError(
                f"validate_asset result is missing required field '{field}'."
            )
    if not isinstance(result["valid"], bool):
        raise ValueError(
            f"validate_asset result 'valid' must be a bool, "
            f"got {type(result['valid']).__name__}."
        )
    if not isinstance(result["errors"], list):
        raise ValueError(
            f"validate_asset result 'errors' must be a list, "
            f"got {type(result['errors']).__name__}."
        )
    if not isinstance(result["warnings"], list):
        raise ValueError(
            f"validate_asset result 'warnings' must be a list, "
            f"got {type(result['warnings']).__name__}."
        )
    if "asset_type" not in result:
        raise ValueError(
            "validate_asset result is missing required field 'asset_type'."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_asset(
    asset: dict,
    platform: str,
    *,
    policy_path: Optional[str | Path] = None,
) -> dict:
    """Validate an asset descriptor against platform capabilities and asset policy.

    Args:
        asset: Dict describing the asset to validate.  Fields:
            asset_type (str, required) — type slug from usage_policies
                e.g. "logo", "customer_photo", "generated_graphic"
            format (str, required for valid upload) — lowercase file extension
                without dot, e.g. "jpeg", "mp4".  Missing or empty format
                produces FORMAT_NOT_ALLOWED.
            source_url (str, optional) — origin URL for provenance checking
            license (dict, optional) — license record; required fields vary
                per asset type
            alt_text (str, optional) — accessibility text
            context (str, optional) — publishing context, e.g. "social_post"
            edit_applied (str, optional) — edit operation applied to the asset
                e.g. "resize", "crop"

        platform: Canonical platform ID (e.g. "twitter").  Case and whitespace
            are normalised before lookup.

        policy_path: Optional path to asset_policy.json.  Defaults to
            config/asset_policy.json relative to the repo root.  Provide a
            custom path in tests for isolation.

    Returns:
        {
            "valid":      bool,
            "platform":   str,       # normalised platform value
            "asset_type": str|None,  # normalised asset_type if provided
            "errors":     list,      # list of error dicts with "code", "message"
            "warnings":   list,      # always present; currently always []
        }

    Hard-stop errors (returned immediately, no further validation):
        UNKNOWN_PLATFORM      — platform not in capability registry
        UPLOAD_NOT_SUPPORTED  — platform does not declare UPLOAD_ASSET

    Accumulating errors (all checks run, all failures collected):
        UNKNOWN_ASSET_TYPE, FORMAT_NOT_ALLOWED, CONTEXT_NOT_ALLOWED,
        FORBIDDEN_SOURCE, SOURCE_NOT_APPROVED,
        LICENSE_REQUIRED, ATTRIBUTION_REQUIRED,
        ALT_TEXT_REQUIRED, EDIT_NOT_PERMITTED
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    # Normalise inputs
    platform_norm  = _normalise(platform)
    asset_type_raw = _normalise(asset.get("asset_type", "")) or None
    format_norm    = _normalise(asset.get("format", ""))
    context_norm   = _normalise(asset.get("context", ""))

    def _result(valid: bool) -> dict:
        r = {
            "valid":      valid,
            "platform":   platform_norm,
            "asset_type": asset_type_raw,
            "errors":     errors,
            "warnings":   warnings,
        }
        validate_asset_result(r)
        return r

    # ------------------------------------------------------------------
    # Stage 1 — hard-stop checks
    # ------------------------------------------------------------------

    # 1a. Platform must be registered
    try:
        defn = get_definition(platform_norm)
    except ValueError:
        errors.append({
            "code":    UNKNOWN_PLATFORM,
            "message": (
                f"Platform '{platform_norm}' is not registered. "
                f"Registered platforms: {', '.join(list_platforms())}."
            ),
        })
        return _result(False)

    # 1b. Platform must support UPLOAD_ASSET
    if not supports_capability(platform_norm, UPLOAD_ASSET):
        errors.append({
            "code":    UPLOAD_NOT_SUPPORTED,
            "message": (
                f"Platform '{defn.display_name}' does not support "
                f"the '{UPLOAD_ASSET}' capability."
            ),
        })
        return _result(False)

    # ------------------------------------------------------------------
    # Stage 2 — load policy, accumulate all remaining errors
    # ------------------------------------------------------------------

    policy = _load_policy(policy_path)
    usage_policies      = policy.get("usage_policies", {})
    required_lic_fields = policy.get("required_license_fields", [])
    approved_domains    = policy.get("approved_source_domains", [])
    forbidden_patterns  = policy.get("forbidden_url_patterns", [])
    require_alt_text    = policy.get("require_alt_text", False)

    # 2a. Asset type must be in usage_policies
    usage_policy: Optional[dict] = None
    if asset_type_raw is None:
        errors.append({
            "code":    UNKNOWN_ASSET_TYPE,
            "message": "Field 'asset_type' is required.",
        })
    elif asset_type_raw not in usage_policies:
        errors.append({
            "code":       UNKNOWN_ASSET_TYPE,
            "message":    (
                f"Asset type '{asset_type_raw}' is not defined in the asset policy. "
                f"Known types: {', '.join(sorted(usage_policies.keys()))}."
            ),
            "asset_type": asset_type_raw,
        })
    else:
        usage_policy = usage_policies[asset_type_raw]

    # 2b. Format check (required — missing/empty is an error)
    if not format_norm:
        errors.append({
            "code":    FORMAT_NOT_ALLOWED,
            "message": (
                "Field 'format' is required for upload validation. "
                f"Platform '{defn.display_name}' accepts: "
                f"{', '.join(sorted(defn.media_formats))}."
            ),
        })
    elif format_norm not in defn.media_formats:
        errors.append({
            "code":    FORMAT_NOT_ALLOWED,
            "message": (
                f"Format '{format_norm}' is not accepted by "
                f"'{defn.display_name}'. "
                f"Accepted formats: {', '.join(sorted(defn.media_formats))}."
            ),
            "format":           format_norm,
            "accepted_formats": sorted(defn.media_formats),
        })

    # 2c. Context check (only when asset type is known and context is provided)
    if usage_policy is not None and context_norm:
        allowed_contexts = usage_policy.get("allowed_contexts", [])
        if context_norm not in allowed_contexts:
            errors.append({
                "code":     CONTEXT_NOT_ALLOWED,
                "message":  (
                    f"Context '{context_norm}' is not permitted for asset type "
                    f"'{asset_type_raw}'. "
                    f"Allowed contexts: {', '.join(allowed_contexts) or 'none'}."
                ),
                "context":          context_norm,
                "allowed_contexts": allowed_contexts,
            })

    # 2d. Source URL provenance (if provided)
    source_url = asset.get("source_url", "")
    if isinstance(source_url, str) and source_url.strip():
        _check_source_url(source_url.strip(), forbidden_patterns, approved_domains, errors)

    # 2e. License check (when asset type known and require_license is true)
    if usage_policy is not None and usage_policy.get("require_license"):
        _check_license(asset, required_lic_fields, errors)

    # 2f. Attribution check (when asset type known and require_attribution is true)
    if usage_policy is not None and usage_policy.get("require_attribution"):
        _check_attribution(asset, errors)

    # 2g. Alt text check (global policy)
    if require_alt_text:
        alt_text = asset.get("alt_text", "")
        if not isinstance(alt_text, str) or not alt_text.strip():
            errors.append({
                "code":    ALT_TEXT_REQUIRED,
                "message": (
                    "The asset policy requires 'alt_text' on every asset "
                    "attached to a post. Provide a non-empty 'alt_text' value."
                ),
            })

    # 2h. Edit rule check (when asset type known and edit_applied is non-empty)
    if usage_policy is not None:
        edit_applied = _normalise(asset.get("edit_applied", ""))
        if edit_applied:
            edit_rule = usage_policy.get("edit_rule", "editable")
            _check_edit_rule(edit_applied, edit_rule, asset_type_raw, errors)

    return _result(len(errors) == 0)
