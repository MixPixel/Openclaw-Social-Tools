# Spec: asset-payload

## Purpose

The asset descriptor used by `validate_asset` (Step 5) and the `upload_asset`
orchestrator (Step 6) carries only metadata: `asset_type`, `format`,
`alt_text`, `context`, etc.  It deliberately contains no binary content.

`asset_payload` defines the upload-time extension: a canonical runtime payload
that adds the one required transport field — `file_path` — to the descriptor.
Platform adapters receive this payload when performing a real HTTP upload.

---

## Problem It Solves

Before this contract:
- The `asset` dict passed to `adapter.upload_asset(asset, credentials)` carried
  only metadata.
- Adapters had no defined way to receive the actual file bytes.
- Each adapter could invent its own transport convention, breaking uniformity.

After this contract:
- Every adapter receives a payload dict with a guaranteed `file_path` field.
- Adapters open `payload["file_path"]`, read the bytes, and POST to the
  platform API.
- No adapter needs to invent or negotiate a transport format.

---

## Transport Mode: Local File Path

A single required field — `file_path` (str) — is the canonical transport.

**Why local file path only (not bytes, base64, or remote URL)?**

This is a CLI/server-side library, not a web request handler.  Local files are
the natural representation.  They are:
- Testable without encoding overhead
- Consumable by every platform's HTTP upload API (open + read)
- Unambiguous — there is no "is this a path or a URL?" question

If the asset originates as a remote URL, it must be downloaded to a local path
before `upload_asset` is called.  That download step is explicitly out of scope
for the adapter layer.

Supporting multiple transport modes (file_path OR bytes OR URL) would require
every adapter to branch on the input type, adding complexity with no clear
benefit for the current use case.

---

## File Structure

```
tools/asset_payload/
    __init__.py          public exports
    asset_payload.py     contract, validator, factory
```

---

## Payload Shape

```python
{
    # Transport (required for upload):
    "file_path":  str,   # path to file on disk (absolute or relative)

    # Descriptor (required — same constraints as validate_asset input):
    "asset_type": str,   # type slug, e.g. "logo", "product_photo"
    "format":     str,   # lowercase extension without dot, e.g. "png", "mp4"

    # Optional metadata (same fields as validate_asset descriptor):
    "alt_text":     str,   # accessibility / caption text
    "context":      str,   # publishing context, e.g. "social_post"
    "source_url":   str,   # origin URL for provenance
    "license":      dict,  # license record
    "edit_applied": str,   # edit operation, e.g. "resize"

    # Adapters may include additional platform-specific keys.
}
```

### Required fields

| Field | Type | Notes |
|---|---|---|
| `file_path` | str | Must be non-empty; file must exist at upload time |
| `asset_type` | str | Must be non-empty |
| `format` | str | Must be non-empty |

### Optional fields

All other fields are optional at the payload contract level.  Individual
platform adapters and the asset policy layer (`validate_asset`) may impose
additional requirements on the metadata fields.

---

## Public API

### `validate_asset_payload(payload, *, check_exists=True) -> None`

Shape guard for the payload dict.  Raises `ValueError` with a descriptive
message for any violation:

- `payload` is not a dict
- Any required field (`asset_type`, `format`, `file_path`) is missing
- `file_path`, `asset_type`, or `format` is not a non-empty string
- File at `file_path` does not exist (only when `check_exists=True`)

`check_exists=False` skips the filesystem check.  Use in unit tests that do
not create real files on disk.

### `make_asset_payload(file_path, *, asset_type, format, check_exists=True, **metadata) -> dict`

Construct and validate a canonical payload dict.  Merges required fields with
optional metadata kwargs, then calls `validate_asset_payload` before returning.

```python
payload = make_asset_payload(
    "/tmp/logo.png",
    asset_type="logo",
    format="png",
    alt_text="OpenClaw logo",
    context="social_post",
)
```

### `PAYLOAD_REQUIRED_FIELDS: tuple[str, ...]`

```python
("asset_type", "format", "file_path")
```

---

## Relationship to Other Layers

- **Step 5 (`validate_asset`):** Validates the metadata descriptor (policy,
  capability, format, alt_text, etc.).  Does not require `file_path`.  Called
  before upload as a pre-flight guard.
- **Step 6 (`upload_asset` orchestrator):** Currently passes the metadata
  descriptor to adapters.  Step 10 will extend it to require and forward a
  full payload (including `file_path`) to adapters.
- **Platform adapters (`upload_asset()`):** In Step 10+, will call
  `validate_asset_payload(payload)` as their first action before the credential
  check, then open `payload["file_path"]` to read the binary content for the
  HTTP request.

---

## What Is Not in This Contract

- File integrity / checksum validation — out of scope for Step 9.
- MIME type detection from file content — adapters derive `Content-Type` from
  `payload["format"]`.
- Remote URL download — callers are responsible for fetching remote assets
  before building a payload.
- Base64 or in-memory bytes transport — not supported; use file_path.
