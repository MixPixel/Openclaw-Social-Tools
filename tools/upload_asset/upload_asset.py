"""upload_asset — orchestrate pre-flight validation and platform asset upload.

Validates the asset for the target platform (via validate_asset from Step 5),
then dispatches to the platform adapter's upload_asset function.

Two sources of truth are consumed without duplication:
  - tools/validate_asset (Step 5) — all asset/platform/policy validation
  - tools/platform_adapters/capability_registry (Step 4) — module resolution

The adapter is never contacted when validation fails.

Public API
----------
  upload_asset(asset, platform, *, credentials=None, policy_path=None) -> dict
      Pre-flight validate then dispatch asset upload to the platform adapter.

  validate_upload_result(result) -> None
      Shape-check an upload_asset result dict.
      Raises ValueError if required fields are missing or have wrong types.

Result shape
------------
  {
      "success":           bool,
      "platform":          str,         # normalised platform value
      "asset_type":        str | None,  # normalised asset_type if provided
      "asset_ref":         str | None,  # remote media ID / URL from adapter
      "validation_errors": list,        # non-empty when pre-flight failed
      "errors":            list,        # non-empty when adapter failed
      "warnings":          list,        # always present; currently always []
  }

Failure taxonomy
----------------
  Pre-flight failures (validation_errors non-empty, adapter not contacted):
      Any validate_asset error code — UNKNOWN_PLATFORM, UPLOAD_NOT_SUPPORTED,
      FORMAT_NOT_ALLOWED, etc.

  Adapter failures (errors non-empty, validation passed):
      ADAPTER_LOAD_ERROR        adapter module could not be imported
      UPLOAD_NOT_IMPLEMENTED    adapter has no upload_asset() or raises
                                NotImplementedError
      ADAPTER_EXCEPTION         adapter upload_asset() raised unexpectedly
      <adapter error code>      adapter returned success=False with its own code
"""

import importlib
from typing import Optional

from tools.platform_adapters.capability_registry import get_definition
from tools.validate_asset import validate_asset as _validate_asset


# ---------------------------------------------------------------------------
# Result shape validator
# ---------------------------------------------------------------------------

_REQUIRED_RESULT_FIELDS = (
    "success", "platform", "asset_type", "asset_ref",
    "validation_errors", "errors", "warnings",
)


def validate_upload_result(result: dict) -> None:
    """Verify that an upload_asset result dict has the required shape.

    Raises ValueError with a descriptive message if any required field is
    missing or has the wrong type.  Called internally before returning; tests
    and callers may use this to verify result conformance.

    Required fields:
        success (bool), platform (str), asset_type (str | None),
        asset_ref (str | None), validation_errors (list),
        errors (list), warnings (list)
    """
    if not isinstance(result, dict):
        raise ValueError(
            f"upload_asset result must be a dict, got {type(result).__name__}."
        )
    for field in _REQUIRED_RESULT_FIELDS:
        if field not in result:
            raise ValueError(
                f"upload_asset result is missing required field '{field}'."
            )
    if not isinstance(result["success"], bool):
        raise ValueError(
            f"upload_asset result 'success' must be bool, "
            f"got {type(result['success']).__name__}."
        )
    for list_field in ("validation_errors", "errors", "warnings"):
        if not isinstance(result[list_field], list):
            raise ValueError(
                f"upload_asset result '{list_field}' must be a list, "
                f"got {type(result[list_field]).__name__}."
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def upload_asset(
    asset: dict,
    platform: str,
    *,
    credentials: Optional[dict] = None,
    policy_path=None,
) -> dict:
    """Validate and upload an asset to the target platform.

    Pre-flight validation (via validate_asset) runs first.  If validation
    fails, a structured result is returned immediately and the adapter is
    never contacted.

    Args:
        asset:       Asset descriptor dict.  Same fields as validate_asset:
                       asset_type (str, required), format (str, required),
                       source_url, license, alt_text, context, edit_applied.
        platform:    Canonical platform ID (e.g. "twitter").  Case and
                     whitespace are normalised before lookup.
        credentials: Optional credentials dict for the platform adapter.
                     None → each platform adapter reads from os.environ.
        policy_path: Optional path to asset_policy.json.  Defaults to
                     config/asset_policy.json relative to the repo root.
                     Provide a custom path in tests for isolation.

    Returns:
        {
            "success":           bool,
            "platform":          str,         # normalised
            "asset_type":        str | None,
            "asset_ref":         str | None,  # remote media ID / URL
            "validation_errors": list,        # non-empty when pre-flight failed
            "errors":            list,        # non-empty when adapter failed
            "warnings":          list,        # always present
        }
    """
    # ------------------------------------------------------------------
    # Stage 1 — pre-flight validation
    # ------------------------------------------------------------------
    validation = _validate_asset(asset, platform, policy_path=policy_path)

    platform_norm  = validation["platform"]
    asset_type_out = validation["asset_type"]

    def _result(
        success: bool,
        *,
        asset_ref: Optional[str] = None,
        validation_errors: Optional[list] = None,
        errors: Optional[list] = None,
        warnings: Optional[list] = None,
    ) -> dict:
        r = {
            "success":           success,
            "platform":          platform_norm,
            "asset_type":        asset_type_out,
            "asset_ref":         asset_ref,
            "validation_errors": validation_errors if validation_errors is not None else [],
            "errors":            errors if errors is not None else [],
            "warnings":          warnings if warnings is not None else [],
        }
        validate_upload_result(r)
        return r

    if not validation["valid"]:
        return _result(
            False,
            validation_errors=validation["errors"],
            warnings=validation.get("warnings", []),
        )

    # ------------------------------------------------------------------
    # Stage 2 — adapter resolution
    # ------------------------------------------------------------------
    # validate_asset confirmed the platform is registered and supports
    # UPLOAD_ASSET, so get_definition() cannot raise ValueError here.
    # An ImportError is still possible if the module has a syntax error or
    # a missing dependency — surface it as ADAPTER_LOAD_ERROR.
    try:
        defn   = get_definition(platform_norm)
        module = importlib.import_module(defn.module_path)
    except (ValueError, ImportError) as exc:
        return _result(
            False,
            errors=[{
                "code":    "ADAPTER_LOAD_ERROR",
                "message": f"Could not load adapter for '{platform_norm}': {exc}",
            }],
        )

    # ------------------------------------------------------------------
    # Stage 3 — upload dispatch
    # ------------------------------------------------------------------
    # Platform adapter modules expose upload_asset(asset, credentials) → dict
    # as a module-level function alongside get_adapter() for post dispatch.
    # Adapters that declare UPLOAD_ASSET but have not yet implemented the
    # function return UPLOAD_NOT_IMPLEMENTED rather than raising.
    upload_fn = getattr(module, "upload_asset", None)
    if upload_fn is None:
        return _result(
            False,
            errors=[{
                "code":    "UPLOAD_NOT_IMPLEMENTED",
                "message": (
                    f"Platform '{defn.display_name}' adapter does not yet implement "
                    "upload_asset(). The UPLOAD_ASSET capability is declared but "
                    "upload is not active."
                ),
            }],
        )

    try:
        adapter_result = upload_fn(asset, credentials or {})
    except NotImplementedError as exc:
        return _result(
            False,
            errors=[{
                "code":    "UPLOAD_NOT_IMPLEMENTED",
                "message": str(exc) or (
                    f"Platform '{defn.display_name}' upload_asset() "
                    "is not yet implemented."
                ),
            }],
        )
    except Exception as exc:  # noqa: BLE001
        return _result(
            False,
            errors=[{
                "code":    "ADAPTER_EXCEPTION",
                "message": str(exc),
            }],
        )

    # ------------------------------------------------------------------
    # Stage 4 — map adapter result to upload result
    # ------------------------------------------------------------------
    if adapter_result.get("success"):
        return _result(
            True,
            asset_ref=adapter_result.get("asset_ref"),
        )

    return _result(
        False,
        errors=[{
            "code":    str(adapter_result.get("error_code") or "ADAPTER_ERROR"),
            "message": str(adapter_result.get("message") or ""),
        }],
    )
