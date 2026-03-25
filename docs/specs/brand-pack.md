# Spec: brand-pack

## Purpose

Stores brand identity data in a single machine-readable JSON file so that
all downstream tools and LLM prompts can read brand voice, handles, colours,
and content rules from one source of truth instead of repeating them inline.

---

## Why It Exists

Brand data changes rarely but affects every piece of content:

- Handles must appear consistently across platforms.
- Forbidden terms must be checked before posting.
- CTA phrases should be drawn from an approved list.
- Voice and tone inform LLM content-brief generation.

Centralising these in `config/brand.json` means a rebrand is a JSON edit,
not a code change.

---

## File Location

```
config/
├── brand.json           # Brand pack for the active brand
└── brand.schema.json    # JSON Schema (draft-07) for all brand pack files
```

### Multi-brand support

The schema is designed for single-brand use now but multi-brand later.
When a second brand is needed, migrate to:

```
config/brands/
├── openclaw.json
└── <other_brand_id>.json
```

Each file conforms to the same `brand.schema.json`. A future loader can
discover all brands from `config/brands/` automatically, identical to how
`tools/platform_config` discovers platform files.

---

## Schema

All brand pack files conform to `config/brand.schema.json`.

### Top-level fields

| Field             | Type             | Required | Description |
|---|---|---|---|
| `brand_id`        | string           | yes | Canonical slug (e.g. `"openclaw"`). Key for multi-brand lookup. |
| `brand_name`      | string           | yes | Human-readable name (e.g. `"OpenClaw"`). |
| `handles`         | object           | yes | Platform handle per canonical `platform_id`. See below. |
| `voice`           | string           | yes | Single-sentence overall brand voice description. |
| `tone`            | array[string]    | yes | Ordered tone adjectives, most important first. |
| `default_hashtags`| array[string]    | yes | Hashtags included by default; must start with `#`. |
| `bio`             | object           | yes | Brand bio in two lengths. See below. |
| `logo_path`       | string           | yes | Relative path from repo root to primary logo file. |
| `brand_colours`   | object           | yes | Hex colour palette. Conventional keys: `primary`, `secondary`, `accent`. |
| `forbidden_terms` | array[string]    | yes | Terms that must never appear in published posts (case-insensitive). |
| `cta_phrases`     | array[string]    | yes | Approved call-to-action phrases for post copy. |
| `_notes`          | string           | no  | Free-text notes and TODOs. |

### `handles` object

Keys are canonical `platform_id` values (e.g. `"twitter"`, `"linkedin"`).
The canonical ID for Twitter / X is **`"twitter"`** — not `"x"`.
This is consistent with `config/platforms/twitter.json` and the platform-config
loader.

```json
"handles": {
  "twitter":   "@OpenClaw",
  "linkedin":  "openclaw",
  "instagram": "@openclaw",
  "facebook":  "OpenClaw",
  "mastodon":  "@openclaw@mastodon.social"
}
```

### `bio` object

| Field   | Type   | Description |
|---|---|---|
| `short` | string | ≤160 characters — for Twitter/X, Instagram |
| `long`  | string | Extended — for LinkedIn, Facebook profiles |

### `brand_colours` object

Values must be CSS hex strings: `#RGB` or `#RRGGBB`.

```json
"brand_colours": {
  "primary":   "#1A1A2E",
  "secondary": "#16213E",
  "accent":    "#0F3460"
}
```

Additional keys (e.g. `"background"`, `"text"`) are allowed by the schema.

---

## Example (`config/brand.json` excerpt)

```json
{
  "brand_id": "openclaw",
  "brand_name": "OpenClaw",
  "handles": {
    "twitter": "@OpenClaw",
    "linkedin": "openclaw"
  },
  "voice": "knowledgeable and approachable — we make complex social-media workflows feel simple",
  "tone": ["informative", "concise", "friendly", "practical"],
  "default_hashtags": ["#OpenClaw", "#SocialTools"],
  "bio": {
    "short": "PLACEHOLDER — short bio ≤160 chars",
    "long":  "PLACEHOLDER — extended bio"
  },
  "logo_path": "assets/logo/openclaw_logo.png",
  "brand_colours": {
    "primary": "#1A1A2E",
    "secondary": "#16213E",
    "accent": "#0F3460"
  },
  "forbidden_terms": [],
  "cta_phrases": ["Learn more at openclaw.io"]
}
```

---

## Placeholders

The following fields in `config/brand.json` contain placeholder values and
must be filled in before launch:

| Field | Status |
|---|---|
| `bio.short` | PLACEHOLDER — write brand short bio ≤160 chars |
| `bio.long` | PLACEHOLDER — write extended brand bio |
| `handles.*` | PLACEHOLDER — confirm actual account names per platform |
| `brand_colours.*` | PLACEHOLDER — replace hex values with real brand palette |
| `cta_phrases[0]` | PLACEHOLDER — replace with primary CTA phrase |
| `forbidden_terms` | PLACEHOLDER — populate from brand-guidelines review |

---

## Canonical Platform ID Note

The canonical internal ID for Twitter / X throughout this codebase is
**`"twitter"`**. This was confirmed and enforced when `config/platforms/x.json`
was renamed to `config/platforms/twitter.json`. The `"x"` string is an alias
only (preserved in `twitter.json`'s `aliases` array).

Brand pack `handles` keys must use canonical platform IDs. Do not use `"x"` as
a key in `handles`.

---

## Where It Fits in the Workflow

The brand pack is a **leaf dependency** — no dependencies itself.

Planned consumers (not yet wired up):

- `content-brief-builder` — injects voice, tone, default_hashtags into LLM prompts.
- `validate_post` — checks forbidden_terms against post body (future guard).
- Publishing tools — look up the correct handle for each platform.

No Python loader is provided at this step. A thin loader (similar to
`tools/platform_config`) will be added when a tool first needs to read brand
data programmatically.
