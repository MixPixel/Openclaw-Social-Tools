# Spec: upload-asset

## Purpose

`upload_asset` is the first runtime action in the platform layer. It
orchestrates the full pre-upload sequence for a single asset:

1. **Pre-flight validation** via `validate_asset` (Step 5) — no network call
   is attempted when the asset or platform fails validation.
2. **Adapter resolution** via the capability registry (Step 4) — the correct
   platform module is located without any hardcoded mapping.
3. **Upload dispatch** to the platform adapter's `upload_asset()` function.
4. **Structured result** — every outcome, success or failure, returns the
   same dict shape.

---

## Why It Exists

`validate_asset` answers "is this allowed?" but never uploads anything.
`upload_asset` answers "did the upload succeed?" and is the first tool that
makes a real (or eventual real) call to a platform API.

It sits between the validation layer (Step 5) and the future publish pipeline,
ensuring:

- Validation is never bypassed — the adapter is not contacted until the asset
  passes all policy and capability checks.
- Adapter resolution has a single source of truth — `capability_registry`.
- Failures are structured and predictable regardless of whether they originate
  from validation, module loading, or adapter execution.

---

## File Structure

```
tools/upload_asset/
    __init__.py          public exports
    upload_asset.py      orchestrator, result shape validator
```

---

## Public API

### `upload_asset(asset, platform, *, credentials=None, policy_path=None) -> dict`

```python
from tools.upload_asset import upload_asset

result = upload_asset(
    {
        "asset_type": "logo",
        "format":     "png",
        "alt_text":   "OpenClaw logo",
        "context":    "social_post",
    },
    "twitter",
)
```

**`asset` dict fields** — identical to `validate_asset` inputs.

| Field | Type | Required |
|---|---|---|
| `asset_type` | str | yes |
| `format` | str | yes* |
| `source_url` | str | no |
| `license` | dict | no |
| `alt_text` | str | no |
| `context` | str | no |
| `edit_applied` | str | no |

**`platform`** — canonical platform ID; normalised before lookup.

**`credentials`** — optional `dict` passed to the adapter. `None` → each
platform adapter reads from `os.environ`.

**`policy_path`** — optional path to `asset_policy.json`; defaults to
`config/asset_policy.json`. Used by tests for isolation.

### Result dict

```python
{
    "success":           bool,
    "platform":          str,         # normalised platform value
    "asset_type":        str | None,  # normalised asset_type if provided
    "asset_ref":         str | None,  # remote media ID / URL from adapter
    "validation_errors": list,        # non-empty when pre-flight failed
    "errors":            list,        # non-empty when adapter failed
    "warnings":          list,        # always present; currently always []
}
```

`success` is `True` only when the adapter returns a successful upload result.

`validation_errors` and `errors` are mutually exclusive in normal flow:
- Validation failure → `validation_errors` non-empty, `errors` is `[]`,
  adapter not contacted.
- Adapter failure → `validation_errors` is `[]`, `errors` non-empty.
- Success → both are `[]`.

### `validate_upload_result(result) -> None`

Shape-validator for the result dict. Raises `ValueError` if `success`,
`platform`, `asset_type`, `asset_ref`, `validation_errors`, `errors`, or
`warnings` are missing or have wrong types.

---

## Execution Flow

```
1. Call validate_asset(asset, platform, policy_path=policy_path)
   ├── Normalise platform, asset_type from result
   └── If not valid → return {success: False, validation_errors: [...]}
       (adapter is never contacted)

2. Resolve adapter module
   get_definition(platform) → module_path
   importlib.import_module(module_path)
   └── ImportError → {success: False, errors: [ADAPTER_LOAD_ERROR]}

3. Locate upload_asset() function in module
   getattr(module, "upload_asset", None)
   └── None → {success: False, errors: [UPLOAD_NOT_IMPLEMENTED]}

4. Call module.upload_asset(asset, credentials)
   ├── NotImplementedError → {success: False, errors: [UPLOAD_NOT_IMPLEMENTED]}
   ├── Other exception    → {success: False, errors: [ADAPTER_EXCEPTION]}
   └── Returns result dict:
       ├── success=True  → {success: True, asset_ref: result["asset_ref"]}
       └── success=False → {success: False, errors: [{code, message}]}
```

---

## Failure Codes

### In `validation_errors` (from `validate_asset`)

| Code | Cause |
|---|---|
| `UNKNOWN_PLATFORM` | Platform not in capability registry |
| `UPLOAD_NOT_SUPPORTED` | Platform does not declare `UPLOAD_ASSET` |
| `UNKNOWN_ASSET_TYPE` | `asset_type` not in `usage_policies` |
| `FORMAT_NOT_ALLOWED` | Format missing or not in platform's media formats |
| `CONTEXT_NOT_ALLOWED` | Context not in asset type's `allowed_contexts` |
| `FORBIDDEN_SOURCE` | `source_url` matches a forbidden pattern |
| `SOURCE_NOT_APPROVED` | `source_url` hostname not in approved domains |
| `LICENSE_REQUIRED` | License record missing or incomplete |
| `ATTRIBUTION_REQUIRED` | Attribution absent |
| `ALT_TEXT_REQUIRED` | Global `require_alt_text` true, `alt_text` absent |
| `EDIT_NOT_PERMITTED` | `edit_applied` violates asset type's `edit_rule` |

### In `errors` (from adapter layer)

| Code | Cause |
|---|---|
| `ADAPTER_LOAD_ERROR` | Module import failed |
| `UPLOAD_NOT_IMPLEMENTED` | Adapter has no `upload_asset()` or raises `NotImplementedError` |
| `ADAPTER_EXCEPTION` | Adapter raised an unexpected exception |
| _(adapter code)_ | Any code returned by the adapter's `upload_asset()` on failure |

---

## Adapter Upload Interface

Platform adapter modules expose upload via a module-level function:

```python
# In tools/platform_adapters/<platform>.py
def upload_asset(asset: dict, credentials: dict) -> dict:
    """Upload an asset to the platform.

    Returns:
        {"success": True,  "asset_ref": str | None}          on success
        {"success": False, "error_code": str, "message": str} on failure
    """
```

The Twitter adapter fully implements this function. All other platform adapters
(LinkedIn, Instagram, Facebook, Mastodon) raise `NotImplementedError`, which
the orchestrator records as `UPLOAD_NOT_IMPLEMENTED`.

---

## Relationship to Other Layers

- **`validate_asset`:** Consumed as a mandatory pre-flight guard.
  `upload_asset` never duplicates any validation logic.
- **`capability_registry`:** Consumed for module resolution only;
  capability checking is delegated to `validate_asset`.
- **`publish_pipeline`:** `publish_to_platform` calls `upload_asset` for each
  media attachment in the post before dispatching to the delivery adapter.
