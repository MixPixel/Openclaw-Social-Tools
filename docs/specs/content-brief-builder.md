# Tool Spec: content-brief-builder

## Purpose

Assembles a structured, JSON-serialisable brief from raw content intent inputs. The brief is designed to be passed directly to an LLM as a well-scoped prompt context, replacing loose freeform instructions.

---

## Why It Exists

Without a standard brief format, every call to the LLM carries different structure, varying field names, missing constraints, and redundant context. This wastes tokens and produces inconsistent output. The content-brief-builder enforces a canonical brief shape so the LLM always receives exactly what it needs — no more, no less.

This tool is deterministic: given the same inputs it always produces the same brief. No LLM involvement.

---

## Inputs

| Field | Type | Required | Description |
|---|---|---|---|
| `topic` | string | yes | The subject or angle of the post |
| `platform` | enum | yes | Target platform: `twitter`, `linkedin`, `instagram`, `facebook`, `mastodon` |
| `audience` | string | yes | Description of the intended audience |
| `tone` | enum | no | `professional`, `casual`, `humorous`, `educational`. Defaults to `casual` |
| `word_limit` | integer | no | Soft word limit for the draft. Defaults to platform standard |
| `reference_urls` | list[string] | no | URLs to cite or draw from |
| `constraints` | list[string] | no | Hard rules (e.g. "do not mention competitors", "must include a CTA") |
| `keywords` | list[string] | no | Words or phrases to include |
| `format_hint` | string | no | Structural guidance (e.g. "use a numbered list", "open with a question") |

---

## Outputs

A single structured `brief` object:

```json
{
  "platform": "linkedin",
  "audience": "senior product managers at SaaS companies",
  "tone": "professional",
  "topic": "Why async communication reduces meeting fatigue",
  "word_limit": 150,
  "constraints": ["include a CTA", "do not mention specific tools"],
  "keywords": ["async", "focus time", "deep work"],
  "format_hint": "open with a statistic",
  "reference_urls": [],
  "platform_rules": {
    "character_limit": 3000,
    "supports_images": true,
    "supports_hashtags": true,
    "hashtag_limit": null
  }
}
```

Note: `platform_rules` is injected automatically based on the `platform` field — the caller does not supply it.

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| Unknown `platform` value | Return error: `UNSUPPORTED_PLATFORM` |
| `word_limit` exceeds platform character limit | Return error: `WORD_LIMIT_EXCEEDS_PLATFORM_MAX` with the platform max |
| Conflicting constraints (e.g. "be funny" + tone = `professional`) | Include both; flag a `constraint_warning` in the output, do not block |
| Empty `topic` | Return error: `MISSING_REQUIRED_FIELD: topic` |
| `reference_urls` contains malformed URLs | Return error: `INVALID_URL` with the offending value |
| All optional fields omitted | Return brief with platform defaults applied |

---

## Implementation Status

**Not yet implemented.** The `tools/content_brief_builder/` directory exists but
contains no code. This spec describes the intended contract. All other tools in
the workflow (`validate-post` through `publish_pipeline`) are implemented and
working.

---

## Where It Fits in the Workflow

**Position: Step 1 — first tool called.**

```
[content-brief-builder]  →  (LLM drafts post)  →  [validate-post]  →  ...
```

The brief output is handed directly to the LLM. The tool does not call the LLM; it prepares the input for the caller to pass to whichever LLM they choose.
