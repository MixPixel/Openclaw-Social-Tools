# Spec: validate-asset

## Purpose

`validate_asset` is a deterministic pre-upload validator that answers:

> "Is this asset allowed for this platform, and if not, why?"

It must be called before any upload or publish attempt. It does not make
network calls, does not upload anything, and does not modify state.

---

## Why It Exists

Without a centralised asset validator, individual tools would need to
repeat provenance checks, format checks, license checks, and edit-rule
enforcement independently. `validate_asset` is the single gate:

- Provenance and licensing rules come from **Step 3** (`config/asset_policy.json`).
- Platform upload capability and accepted media formats come from **Step 4**
  (`tools/platform_adapters/capability_registry`).
- Neither source is duplicated inside this tool.

---

## File Structure

```
tools/validate_asset/
    __init__.py          public exports
    validate_asset.py    validator, error codes, result shape validator
```

---

## Public API

### `validate_asset(asset, platform, *, policy_path=None) -> dict`

```python
from tools.validate_asset import validate_asset

result = validate_asset(
    {
        "asset_type":   "logo",
        "format":       "png",
        "alt_text":     "OpenClaw logo",
        "context":      "social_post",
    },
    "twitter",
)
```

**`asset` dict fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `asset_type` | str | yes | Type slug from `usage_policies` (e.g. `"logo"`, `"stock_photo"`) |
| `format` | str | yes* | Lowercase file extension without dot (e.g. `"jpeg"`, `"mp4"`) |
| `source_url` | str | no | Origin URL; checked against provenance rules |
| `license` | dict | no | License record; required when `require_license` is true |
| `alt_text` | str | no | Accessibility text; required when global `require_alt_text` is true |
| `context` | str | no | Publishing context (e.g. `"social_post"`); checked against `allowed_contexts` |
| `edit_applied` | str | no | Edit operation applied (e.g. `"resize"`, `"crop"`) |

*`format` is treated as required: a missing or empty value returns `FORMAT_NOT_ALLOWED`.

**`platform`** — canonical platform ID (e.g. `"twitter"`). Case and whitespace
are normalised before lookup.

**`policy_path`** — optional path to `asset_policy.json`; defaults to
`config/asset_policy.json` relative to the repo root. Used by tests for isolation.

### Result dict

```python
{
    "valid":      bool,       # True only if errors list is empty
    "platform":   str,        # normalised platform value used for validation
    "asset_type": str | None, # normalised asset_type if provided
    "errors":     list,       # list of error dicts; always present
    "warnings":   list,       # always present; currently always []
}
```

Error dicts always contain `"code"` (str) and `"message"` (str), plus
optional context fields that vary by error type.

### `validate_asset_result(result) -> None`

Shape-validator for the result dict. Raises `ValueError` if `valid`,
`platform`, `asset_type`, `errors`, or `warnings` are missing or have
wrong types. Adapters and tests may call this to verify result conformance.

---

## Error Codes

| Code | Cause | Hard stop? |
|---|---|---|
| `UNKNOWN_PLATFORM` | Platform not in capability registry | yes |
| `UPLOAD_NOT_SUPPORTED` | Platform does not declare `UPLOAD_ASSET` | yes |
| `UNKNOWN_ASSET_TYPE` | `asset_type` not in `usage_policies` | no |
| `FORMAT_NOT_ALLOWED` | `format` missing/empty or not in platform's `media_formats` | no |
| `CONTEXT_NOT_ALLOWED` | `context` not in `allowed_contexts` for asset type | no |
| `FORBIDDEN_SOURCE` | `source_url` matches a `forbidden_url_patterns` entry | no |
| `SOURCE_NOT_APPROVED` | `source_url` hostname not in `approved_source_domains` | no |
| `LICENSE_REQUIRED` | `require_license` true, license record missing or incomplete | no |
| `ATTRIBUTION_REQUIRED` | `require_attribution` true, attribution absent | no |
| `ALT_TEXT_REQUIRED` | Global `require_alt_text` true, `alt_text` absent/empty | no |
| `EDIT_NOT_PERMITTED` | `edit_applied` violates asset type's `edit_rule` | no |

Hard-stop errors cause immediate return; no further validation runs.
All other errors accumulate in a single pass.

---

## Validation Flow

```
1. Normalise: platform, asset_type, format, context → lowercase + strip
2. [HARD STOP] get_definition(platform) → UNKNOWN_PLATFORM if not registered
3. [HARD STOP] supports_capability(platform, UPLOAD_ASSET) → UPLOAD_NOT_SUPPORTED
4. Load asset_policy.json (cached per path)
5. Check asset_type in usage_policies → UNKNOWN_ASSET_TYPE
6. Check format present and in platform media_formats → FORMAT_NOT_ALLOWED
7. Check context in allowed_contexts (if provided & asset_type known) → CONTEXT_NOT_ALLOWED
8. Check source_url against forbidden patterns → FORBIDDEN_SOURCE
9. Check source_url domain against approved_source_domains → SOURCE_NOT_APPROVED
10. Check license record completeness (if require_license) → LICENSE_REQUIRED
11. Check attribution present (if require_attribution) → ATTRIBUTION_REQUIRED
12. Check alt_text present (if global require_alt_text) → ALT_TEXT_REQUIRED
13. Check edit_applied against edit_rule (if provided & asset_type known) → EDIT_NOT_PERMITTED
14. Return {valid: len(errors)==0, errors: [...], warnings: [], ...}
```

---

## Edit Rule Table

| `edit_rule` | Permitted `edit_applied` values |
|---|---|
| `locked` | _(none)_ |
| `resizable_only` | `"resize"` |
| `croppable_only` | `"crop"` |
| `editable` | any |
| `reference_only` | _(none)_ |

If `edit_applied` is absent or empty, the edit rule check is skipped.

---

## Normalisation Rules

All four fields are normalised (strip whitespace, lowercase) before any
check. Returned `"platform"` and `"asset_type"` reflect the normalised value.

---

## Sources of Truth (consumed, not duplicated)

| Concern | Source |
|---|---|
| Platform upload capability | `capability_registry.supports_capability(platform, UPLOAD_ASSET)` |
| Platform media formats | `capability_registry.get_definition(platform).media_formats` |
| Asset type rules | `config/asset_policy.json` → `usage_policies[asset_type]` |
| Provenance rules | `config/asset_policy.json` → `approved_source_domains`, `forbidden_url_patterns` |
| License field requirements | `config/asset_policy.json` → `required_license_fields` |
| Alt text requirement | `config/asset_policy.json` → `require_alt_text` |

---

## Usage Examples

### Fully valid asset

```python
result = validate_asset(
    {
        "asset_type":   "generated_graphic",
        "format":       "png",
        "alt_text":     "Infographic showing Q1 growth",
        "context":      "social_post",
    },
    "twitter",
)
# result["valid"] == True
# result["errors"] == []
```

### Format not accepted

```python
result = validate_asset(
    {"asset_type": "product_photo", "format": "tiff", "alt_text": "product"},
    "instagram",
)
# result["valid"] == False
# result["errors"][0]["code"] == "FORMAT_NOT_ALLOWED"
```

### Customer photo missing license

```python
result = validate_asset(
    {
        "asset_type": "customer_photo",
        "format":     "jpeg",
        "alt_text":   "Jane at our event",
        "context":    "social_post",
    },
    "twitter",
)
# result["valid"] == False
# errors include LICENSE_REQUIRED and ATTRIBUTION_REQUIRED
```

---

## Relationship to Other Layers

- **Step 3 (asset-policy):** Read-only consumer. No changes to
  `config/asset_policy.json` or its schema.
- **Step 4 (adapter-capability-registry):** Read-only consumer. Calls
  `get_definition()` and `supports_capability()` from
  `tools/platform_adapters/capability_registry.py`.
- **validate_post:** Sibling tool. `validate_asset` follows the same
  result-dict pattern (`valid`, `errors`, `warnings`) but validates asset
  metadata rather than post content.
- **Future `upload_asset` tool:** Will call `validate_asset` as a
  precondition before making any network call to a platform API.
