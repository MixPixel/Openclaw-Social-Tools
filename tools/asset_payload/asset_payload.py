"""asset_payload — canonical uploadable asset payload contract.

The existing asset descriptor (used by validate_asset and the upload_asset
orchestrator) carries only metadata: asset_type, format, alt_text, etc.
It deliberately contains no binary content.

This module defines the upload-time extension: a canonical payload dict that
adds the one required transport field — file_path — to the descriptor.

Platform adapters receive this payload when performing a real HTTP upload.
They read file_path, open the file, and POST the binary content to the
platform API.  The metadata fields are available alongside the binary content
for constructing API request parameters (e.g. alt_text → media description,
format → Content-Type header).

Design choices
--------------
  Transport mode: local file path only.
    A single mandatory transport mode avoids the complexity of handling
    file_path OR bytes OR remote URL within each adapter.  Local files are
    the natural representation for a CLI/server-side tool.  If a remote URL
    is the source, it must be downloaded to a local path before upload.

  Required fields: file_path, asset_type, format.
    asset_type and format are already mandatory in the metadata descriptor;
    keeping them required in the payload ensures adapters never receive an
    underspecified payload.

  validate_asset_payload raises ValueError.
    The existing shape-guard pattern in this repo (validate_adapter_result,
    validate_upload_result) uses ValueError for structural violations.
    The payload validator follows the same convention: it is a developer-
    facing guard, not a user-facing reporter.

  check_exists parameter.
    File existence is part of structural validity at upload time, but unit
    tests that do not create real files must be able to check the other
    constraints.  check_exists=False skips the os.path.exists check only.

Public API
----------
  PAYLOAD_REQUIRED_FIELDS: tuple[str, ...]
      ("asset_type", "format", "file_path")

  validate_asset_payload(payload, *, check_exists=True) -> None
      Raise ValueError with a descriptive message if the payload is
      structurally invalid or the file does not exist.

  make_asset_payload(file_path, *, asset_type, format, **metadata) -> dict
      Construct and validate a canonical payload dict.
"""

import os
from typing import Any


# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

PAYLOAD_REQUIRED_FIELDS: tuple[str, ...] = ("asset_type", "format", "file_path")

# Optional metadata fields accepted by the payload.  Not exhaustive — the
# payload dict may carry any additional keys that a specific adapter needs.
PAYLOAD_OPTIONAL_FIELDS: tuple[str, ...] = (
    "alt_text",
    "context",
    "source_url",
    "license",
    "edit_applied",
)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_asset_payload(payload: Any, *, check_exists: bool = True) -> None:
    """Verify that a payload dict satisfies the asset payload contract.

    Raises ValueError with a descriptive message for any of:
      - payload is not a dict
      - any required field (asset_type, format, file_path) is missing
      - file_path is not a non-empty string
      - asset_type is not a non-empty string
      - format is not a non-empty string
      - file at file_path does not exist (when check_exists=True)

    Args:
        payload:      The dict to validate.
        check_exists: When True (default), verify os.path.exists(file_path).
                      Pass False in unit tests that do not create real files.

    Returns:
        None.  Raises on any violation.
    """
    if not isinstance(payload, dict):
        raise ValueError(
            f"Asset payload must be a dict, got {type(payload).__name__}."
        )

    for field in PAYLOAD_REQUIRED_FIELDS:
        if field not in payload:
            raise ValueError(
                f"Asset payload is missing required field '{field}'."
            )

    for str_field in ("asset_type", "format", "file_path"):
        value = payload[str_field]
        if not isinstance(value, str):
            raise ValueError(
                f"Asset payload field '{str_field}' must be a str, "
                f"got {type(value).__name__}."
            )
        if not value.strip():
            raise ValueError(
                f"Asset payload field '{str_field}' must not be empty."
            )

    if check_exists and not os.path.exists(payload["file_path"]):
        raise ValueError(
            f"Asset payload file_path does not exist: '{payload['file_path']}'."
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_asset_payload(
    file_path: str,
    *,
    asset_type: str,
    format: str,
    check_exists: bool = True,
    **metadata,
) -> dict:
    """Construct a canonical asset payload dict.

    Builds the payload from required transport and descriptor fields, merges
    any additional metadata, then validates the result before returning.

    Args:
        file_path:    Path to the file on disk (absolute or relative).
        asset_type:   Asset type slug (e.g. "logo", "product_photo").
        format:       Lowercase file extension without dot (e.g. "png", "mp4").
        check_exists: Passed through to validate_asset_payload.
                      Default True; pass False in tests without real files.
        **metadata:   Optional descriptor fields: alt_text, context,
                      source_url, license, edit_applied, or any adapter-
                      specific keys.

    Returns:
        A validated payload dict.

    Raises:
        ValueError: if the constructed payload fails validation.
    """
    payload = {
        "file_path":  file_path,
        "asset_type": asset_type,
        "format":     format,
        **metadata,
    }
    validate_asset_payload(payload, check_exists=check_exists)
    return payload
