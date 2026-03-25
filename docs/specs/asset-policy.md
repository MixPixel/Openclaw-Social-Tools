# Spec: asset-policy

## Purpose

Defines two classes of rules for every asset used in social content:

1. **Provenance / licensing rules** — where assets may come from, what license
   metadata must be recorded, and which source URLs are forbidden.
2. **Usage / edit protection rules** — what operations are permitted on each
   asset type (resize, crop, full edit, or no edit at all).

All rules are stored in `config/asset_policy.json` and validated against
`config/asset_policy.schema.json`. The file is machine-readable so a future
`validate_image_asset` tool can enforce policy deterministically without
hardcoding rules in Python.

---

## Why It Exists

Without a central policy file:

- Different tools or team members apply inconsistent rules to logos, customer
  photos, and stock images.
- Licensing obligations get lost when assets move between campaigns.
- A rule change requires hunting through Python code rather than editing one
  JSON entry.

A single config file makes policy auditable, version-controlled, and
enforceable by tooling.

---

## File Location

```
config/
├── asset_policy.json          # Active asset policy
└── asset_policy.schema.json   # JSON Schema (draft-07)
```

---

## Schema

`config/asset_policy.schema.json` defines the full shape.

### Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | string | yes | Policy version (semver recommended). Increment on any rule change. |
| `approved_source_domains` | array[string] | yes | Hostnames assets may be sourced from. |
| `forbidden_url_patterns` | array[string] | yes | Regex patterns; a match on a source URL disqualifies the asset. |
| `required_license_fields` | array[string] | yes | Fields that must be present on a license record when `require_license` is true. |
| `require_alt_text` | boolean | yes | If true, every asset attached to a post must carry non-empty `alt_text`. |
| `usage_policies` | object | yes | Per-asset-type rules. Keys are asset type slugs. |
| `_notes` | string | no | Free-text caveats and TODOs. |

### `usage_policies` object

Keys are asset type slugs (e.g. `"logo"`, `"stock_photo"`). Values conform to
the `UsagePolicy` sub-schema. Any slug is valid; the conventional types are
listed below.

### `UsagePolicy` sub-schema

Each entry in `usage_policies` has these fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `edit_rule` | enum | yes | Permitted modification level — see table below. |
| `require_license` | boolean | yes | Whether a license record is required before use. |
| `require_attribution` | boolean | yes | Whether attribution must be present and published. |
| `allowed_contexts` | array[string] | yes | Publishing contexts where this asset type may be used. |
| `_notes` | string | no | Free-text caveats for this asset type. |

### `edit_rule` enum

| Value | Meaning |
|---|---|
| `locked` | No modifications of any kind. Use the asset exactly as supplied. |
| `resizable_only` | May change dimensions (scale up/down) only. |
| `croppable_only` | May crop to a different aspect ratio or region only. |
| `editable` | Any editing operation is permitted. |
| `reference_only` | May be displayed for reference/illustration; not for production publishing without further review. |

### `allowed_contexts` conventional values

| Value | Meaning |
|---|---|
| `social_post` | Attached to a social media post |
| `website` | Published on the brand website |
| `email` | Used in email marketing |
| `blog` | Published in blog/editorial content |
| `press` | Press kits, media packs, or PR materials |

Any string is accepted by the schema; add new contexts as needed.

---

## Asset Types Defined

| Asset type | `edit_rule` | `require_license` | `require_attribution` | Notes |
|---|---|---|---|---|
| `logo` | `locked` | false | false | No edits ever. Use only files from `assets/logo/`. |
| `product_photo` | `resizable_only` | false | false | PLACEHOLDER — confirm crop permission with brand team. |
| `website_screenshot` | `reference_only` | false | false | Illustration only; legal review for commercial use. |
| `generated_graphic` | `editable` | false | false | AI/tool-generated; confirm output ownership per tool. |
| `customer_photo` | `croppable_only` | true | true | Requires written customer permission. Crop to aspect ratio only. |
| `stock_photo` | `resizable_only` | true | true | PLACEHOLDER — confirm crop and attribution format per provider. |
| `icon` | `editable` | true | false | PLACEHOLDER — check attribution per icon set licence. |

---

## Provenance Rules

### `approved_source_domains`

Assets sourced from a URL are checked against this list. If the URL's hostname
does not match any entry (or a subdomain thereof), the asset is flagged.

Current approved domains (see `config/asset_policy.json`):
- `openclaw.io` / `assets.openclaw.io`
- `unsplash.com`
- PLACEHOLDER — add further approved sources

### `forbidden_url_patterns`

Regex patterns evaluated case-insensitively against the full source URL. A
match means the asset may not be used regardless of other rules.

Current patterns block:
- `shutterstock.com`
- `gettyimages.com`
- `istockphoto.com`
- PLACEHOLDER — add any other sources with uncleared licences

### `required_license_fields`

When a usage policy has `require_license: true`, the asset's license record
must contain all fields listed here:

- `license_type` — e.g. `"CC-BY-4.0"`, `"commercial"`, `"permission_granted"`
- `license_url` — URL to the licence text or permission document
- `attribution` — Attribution string to display if required

---

## `require_alt_text`

Currently set to `true`. Every asset attached to a social post must carry a
non-empty `alt_text` value. This rule applies regardless of asset type.

---

## Placeholders

The following values in `config/asset_policy.json` need real decisions before launch:

| Field | Status |
|---|---|
| `approved_source_domains` | PLACEHOLDER — confirm full approved list |
| `forbidden_url_patterns` | PLACEHOLDER — confirm full blocklist |
| `usage_policies.product_photo.edit_rule` | PLACEHOLDER — `"resizable_only"` assumed; confirm if cropping is also permitted |
| `usage_policies.stock_photo.edit_rule` | PLACEHOLDER — confirm allowed ops and attribution format per stock provider |
| `usage_policies.icon.require_attribution` | PLACEHOLDER — depends on icon set licence (MIT vs Pro) |

---

## Where It Fits in the Workflow

This layer is a **leaf dependency** — no dependencies itself.

Planned consumers (not yet built):

- `validate_image_asset` — reads `usage_policies` to check `edit_rule`, checks
  source URL against `approved_source_domains` and `forbidden_url_patterns`,
  verifies license record completeness when `require_license` is true, and
  checks `alt_text` presence when `require_alt_text` is true.

No Python loader is provided at this step. The loader will be added alongside
`validate_image_asset`.

---

## Adding a New Asset Type

1. Add a new key to `usage_policies` in `config/asset_policy.json`.
2. Choose `edit_rule`, set `require_license`, `require_attribution`, and
   `allowed_contexts` appropriate to the asset type.
3. No code changes required until `validate_image_asset` is built.
