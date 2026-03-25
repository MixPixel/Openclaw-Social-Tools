"""upload_asset — pre-flight validator and platform asset uploader.

Public API
----------
  upload_asset(asset, platform, *, credentials=None, policy_path=None) -> dict
      Validate and upload an asset to the target platform.
      Pre-flight validation runs first via validate_asset (Step 5).
      The adapter is only contacted when validation passes.
      Returns a structured result dict.

  validate_upload_result(result) -> None
      Shape-check an upload_asset result dict.
      Raises ValueError if required fields are missing or have wrong types.

Usage
-----
  from tools.upload_asset import upload_asset

  result = upload_asset(
      {"asset_type": "logo", "format": "png", "alt_text": "OpenClaw logo"},
      "twitter",
  )
  if result["success"]:
      print("uploaded, ref:", result["asset_ref"])
  elif result["validation_errors"]:
      print("validation failed:", result["validation_errors"])
  else:
      print("upload failed:", result["errors"])
"""

from .upload_asset import (
    upload_asset,
    validate_upload_result,
)

__all__ = [
    "upload_asset",
    "validate_upload_result",
]
