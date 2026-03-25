"""asset_payload — canonical uploadable asset payload contract.

Defines the single runtime payload shape that platform adapters consume when
performing a real media upload.  Separates binary transport (file_path) from
the metadata descriptor fields used by validate_asset (asset_type, format,
alt_text, etc.).

Public API
----------
  validate_asset_payload(payload, *, check_exists=True) -> None
      Raise ValueError if the payload is structurally invalid or the
      referenced file does not exist.  Pass check_exists=False in unit tests
      that do not create real files.

  make_asset_payload(file_path, *, asset_type, format, **metadata) -> dict
      Construct a canonical payload dict from required fields plus optional
      metadata.  Validates the result before returning.

Payload shape
-------------
  Required:
    file_path  (str)  Absolute or relative path to the file on disk.
    asset_type (str)  Type slug matching usage_policies (e.g. "logo").
    format     (str)  Lowercase file extension without dot (e.g. "png").

  Optional metadata (same as validate_asset descriptor fields):
    alt_text      (str)   Accessibility / caption text.
    context       (str)   Publishing context (e.g. "social_post").
    source_url    (str)   Origin URL for provenance records.
    license       (dict)  License record.
    edit_applied  (str)   Edit operation applied (e.g. "resize").

Usage
-----
  from tools.asset_payload import make_asset_payload, validate_asset_payload

  payload = make_asset_payload(
      "/tmp/logo.png",
      asset_type="logo",
      format="png",
      alt_text="OpenClaw logo",
      context="social_post",
  )
  # Pass to adapter:
  result = adapter.upload_asset(payload, credentials)
"""

from .asset_payload import (
    make_asset_payload,
    validate_asset_payload,
    PAYLOAD_REQUIRED_FIELDS,
)

__all__ = [
    "make_asset_payload",
    "validate_asset_payload",
    "PAYLOAD_REQUIRED_FIELDS",
]
