"""validate_asset — pre-upload asset validator.

Public API
----------
  validate_asset(asset, platform, *, policy_path=None) -> dict
      Validate an asset descriptor against platform capabilities and asset policy.
      Returns a structured result dict with 'valid', 'errors', and 'warnings'.

  validate_asset_result(result) -> None
      Shape-check a validate_asset result dict.
      Raises ValueError if required fields are missing or have wrong types.

Error code constants:
  UNKNOWN_PLATFORM, UPLOAD_NOT_SUPPORTED, UNKNOWN_ASSET_TYPE,
  FORMAT_NOT_ALLOWED, CONTEXT_NOT_ALLOWED,
  FORBIDDEN_SOURCE, SOURCE_NOT_APPROVED,
  LICENSE_REQUIRED, ATTRIBUTION_REQUIRED,
  ALT_TEXT_REQUIRED, EDIT_NOT_PERMITTED,
  ALL_ERROR_CODES

Usage
-----
  from tools.validate_asset import validate_asset, FORMAT_NOT_ALLOWED

  result = validate_asset(
      {"asset_type": "logo", "format": "png", "alt_text": "OpenClaw logo"},
      "twitter",
  )
  if not result["valid"]:
      for err in result["errors"]:
          print(err["code"], err["message"])
"""

from .validate_asset import (
    validate_asset,
    validate_asset_result,
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
    ALL_ERROR_CODES,
    _clear_policy_cache,
)

__all__ = [
    "validate_asset",
    "validate_asset_result",
    "UNKNOWN_PLATFORM",
    "UPLOAD_NOT_SUPPORTED",
    "UNKNOWN_ASSET_TYPE",
    "FORMAT_NOT_ALLOWED",
    "CONTEXT_NOT_ALLOWED",
    "FORBIDDEN_SOURCE",
    "SOURCE_NOT_APPROVED",
    "LICENSE_REQUIRED",
    "ATTRIBUTION_REQUIRED",
    "ALT_TEXT_REQUIRED",
    "EDIT_NOT_PERMITTED",
    "ALL_ERROR_CODES",
]
