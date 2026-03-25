# Tool Spec: platform-config

## Purpose

Provides per-platform configuration files and a thin Python loader that returns
a platform's rules as a dict. All platform-specific constants (character limits,
media rules, link costs, etc.) live here — not hardcoded in individual tools.

---

## Why It Exists

Platform rules change when platforms update their APIs. A centralised config layer
means:

- A rule change is a one-line edit to one JSON file, not a Python code change.
- Every tool that needs platform rules reads from the same source of truth.
- Each platform file can be validated against a shared JSON schema.
- New platforms are added by dropping a new JSON file; no Python changes required.

---

## Config Files

### Location

```
config/platforms/
├── platform.schema.json   # JSON Schema (draft-07) for all platform files
├── x.json                 # Twitter / X
├── linkedin.json
├── instagram.json
├── facebook.json
└── mastodon.json
```

### Schema

All platform files conform to `config/platforms/platform.schema.json`.

Top-level fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `platform_id` | string | yes | Canonical internal identifier (e.g. `"twitter"`) |
| `display_name` | string | yes | Human-readable name for error messages |
| `char_limit` | integer | yes | Max post character count after link substitution |
| `link_char_cost` | int \| null | yes | Fixed char cost per URL; null = actual length |
| `hashtag_limit` | int \| null | yes | Hard max hashtags; null = no limit enforced |
| `hashtag_warn_above` | int \| null | yes | Warning threshold; null = no warning |
| `links_clickable` | boolean | yes | Whether links render as hyperlinks |
| `aliases` | array[string] | yes | All input strings that map to this platform |
| `media` | object | yes | Media constraints — see below |
| `scheduling` | object | no | Platform-specific scheduling hints (reserved; PLACEHOLDER) |
| `_notes` | string | no | Free-text caveats and TODO items |

`media` object fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `max_images` | integer | yes | Max image attachments per post |
| `max_videos` | integer | yes | Max video attachments per post |
| `images_and_video_exclusive` | boolean | yes | True if images and video cannot be mixed |
| `allowed_image_formats` | array[string] | yes | Lowercase extensions without dot |
| `allowed_video_formats` | array[string] | yes | Lowercase extensions without dot |
| `max_image_size_bytes` | integer | yes | Maximum image file size |
| `max_video_size_bytes` | integer | yes | Maximum video file size |
| `min_image_width_px` | int \| null | no | Minimum image width; null = not enforced (PLACEHOLDER) |
| `min_image_height_px` | int \| null | no | Minimum image height; null = not enforced (PLACEHOLDER) |
| `max_image_width_px` | int \| null | no | Maximum image width; null = not enforced (PLACEHOLDER) |
| `max_image_height_px` | int \| null | no | Maximum image height; null = not enforced (PLACEHOLDER) |

### Example (mastodon.json excerpt)

```json
{
  "platform_id": "mastodon",
  "display_name": "Mastodon",
  "char_limit": 500,
  "link_char_cost": 23,
  "hashtag_limit": null,
  "hashtag_warn_above": 5,
  "links_clickable": true,
  "aliases": ["mastodon"],
  "media": {
    "max_images": 4,
    "max_videos": 1,
    "images_and_video_exclusive": true,
    "allowed_image_formats": ["jpeg", "jpg", "png", "gif", "webp"],
    "allowed_video_formats": ["mp4", "mov", "webm"],
    "max_image_size_bytes": 10485760,
    "max_video_size_bytes": 41943040
  }
}
```

---

## Loader

### Location

```
tools/platform_config/
├── __init__.py
└── platform_config.py
```

### Public API

#### `load_platform(name, config_dir=None) -> dict`

Return the full config dict for a named platform.

```python
from tools.platform_config import load_platform

cfg = load_platform("twitter")
cfg = load_platform("x")          # alias — same result
cfg = load_platform("twitter/x")  # alias — same result
```

- `name` is case-insensitive; aliases are resolved automatically.
- Raises `ValueError` for unrecognised names.
- Raises `RuntimeError` if the config file is missing or contains invalid JSON.

#### `resolve_alias(name, config_dir=None) -> str`

Return the canonical `platform_id` for a name or alias.

```python
from tools.platform_config import resolve_alias

resolve_alias("x")          # → "twitter"
resolve_alias("Twitter/X")  # → "twitter"
```

#### `load_all_platforms(config_dir=None) -> dict[str, dict]`

Return a `platform_id → config dict` mapping for all platforms in the config
directory. Skips `platform.schema.json` and silently skips malformed files.

#### `list_platforms(config_dir=None) -> list[str]`

Return a sorted list of canonical platform IDs available in the config directory.

```python
from tools.platform_config import list_platforms

list_platforms()  # → ["facebook", "instagram", "linkedin", "mastodon", "twitter"]
```

### Name resolution

The loader builds an alias index from the `aliases` array in every config file.
Resolution is case-insensitive. The index is cached per `config_dir` path after
the first call.

### `config_dir` injection

All four functions accept an optional `config_dir` argument. This is used by tests
to point the loader at a temporary directory of fixture files without touching the
real configs.

---

## Placeholders

The following fields are present in the schema and config files but carry `null`
values pending confirmation from platform API documentation:

| Platform | Field | Status |
|---|---|---|
| All | `media.min_image_width_px` | PLACEHOLDER — verify per platform |
| All | `media.min_image_height_px` | PLACEHOLDER — verify per platform |
| All | `media.max_image_width_px` | PLACEHOLDER — verify per platform |
| All | `media.max_image_height_px` | PLACEHOLDER — verify per platform |
| instagram | `media.max_image_height_px` | PLACEHOLDER — width known (1440 px), height TBC |
| All | `scheduling` | PLACEHOLDER — reserved for future per-platform scheduling rules |
| facebook | `hashtag_warn_above` | PLACEHOLDER — set if brand guidelines define a threshold |
| mastodon | `char_limit` | Server default (500); instance admins may raise this |

---

## Where It Fits in the Workflow

This layer is a **leaf dependency** — it has no dependencies itself. All downstream
tools that need platform rules should load them from here rather than hardcoding.

Current tools that still hardcode platform rules (and should be updated in a future
pass):

- `tools/validate_post/validate_post.py` — `PLATFORM_RULES` dict
- `tools/validate_post/validate_post.py` — `PLATFORM_ALIASES` dict

These are **not refactored in this step** to keep the change isolated and
non-breaking. Migration is tracked as a future task.

---

## Adding a New Platform

1. Create `config/platforms/<platform_id>.json` conforming to the schema.
2. Include `platform_id` in the `aliases` array.
3. Add any additional aliases users might type.
4. No Python changes required — the loader discovers files automatically.
