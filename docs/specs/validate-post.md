# Tool Spec: validate-post

## Purpose

Checks a post draft against the hard rules of a target platform before it enters the approval workflow. Returns a pass/fail result with structured error codes so the LLM (or a human) can correct the draft efficiently.

---

## Why It Exists

Platform rules are exact and mechanical: character limits, forbidden content types, image count limits, link restrictions. Asking an LLM to enforce these is wasteful and unreliable. A deterministic validator catches every violation instantly, cheaply, and consistently.

By catching errors early — before approval, before scheduling — the tool prevents bad posts from travelling further down the pipeline and reduces the number of LLM revision calls needed.

---

## Inputs

| Field | Type | Required | Description |
|---|---|---|---|
| `content` | string | yes | The post body text |
| `platform` | enum | yes | Target platform: `twitter`, `linkedin`, `instagram`, `facebook`, `mastodon` |
| `media` | list[object] | no | Attached media. Each item: `{ type: "image"\|"video", size_bytes: int, format: string }` |
| `links` | list[string] | no | URLs included in the post |
| `hashtags` | list[string] | no | Hashtags included (without `#` prefix) |
| `mentions` | list[string] | no | Mentions included (without `@` prefix) |

---

## Outputs

### On pass

```json
{
  "valid": true,
  "platform": "twitter",
  "character_count": 242,
  "warnings": []
}
```

### On fail

```json
{
  "valid": false,
  "platform": "twitter",
  "character_count": 301,
  "errors": [
    {
      "code": "CHARACTER_LIMIT_EXCEEDED",
      "message": "Post is 301 characters; Twitter limit is 280.",
      "limit": 280,
      "actual": 301
    }
  ],
  "warnings": [
    {
      "code": "HIGH_HASHTAG_COUNT",
      "message": "5 hashtags detected. Engagement typically drops above 3 on Twitter."
    }
  ]
}
```

`warnings` are non-blocking. `errors` cause `valid: false`.

---

## Error Codes

| Code | Description |
|---|---|
| `CHARACTER_LIMIT_EXCEEDED` | Post body exceeds platform character limit |
| `EMPTY_CONTENT` | Post body is empty or whitespace only |
| `UNSUPPORTED_MEDIA_TYPE` | Attached media format not supported on this platform |
| `MEDIA_SIZE_EXCEEDED` | Media file exceeds platform size limit |
| `MEDIA_COUNT_EXCEEDED` | Too many media attachments for this platform |
| `INVALID_LINK` | A link is malformed or uses a disallowed protocol |
| `LINK_NOT_ALLOWED` | Platform does not support clickable links in this context (e.g. Instagram captions) |
| `HASHTAG_LIMIT_EXCEEDED` | More hashtags than the platform allows |
| `UNSUPPORTED_PLATFORM` | Platform value not recognised |

## Warning Codes

| Code | Description |
|---|---|
| `HIGH_HASHTAG_COUNT` | Hashtag count is within limits but above the recommended threshold |
| `LONG_CONTENT` | Content is within limits but above 80% of the character cap |
| `NO_CTA` | No call-to-action phrase detected (heuristic, not enforced) |

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| Unicode content (emoji, CJK characters) | Character count follows platform-specific rules (Twitter counts emoji as 2, LinkedIn as 1) |
| Multi-platform validation | Tool validates one platform per call; call it once per platform for cross-posting |
| Content is only whitespace | Returns `EMPTY_CONTENT` error |
| Links included in character count | Character count includes link text as the platform would count it (e.g. Twitter t.co wrapping = 23 chars per link) |
| Media list is empty array vs. omitted | Both treated as "no media" — no difference in behaviour |
| Hashtags in body vs. in `hashtags` field | Tool detects hashtags in `content` automatically; `hashtags` field is additive |

---

## Where It Fits in the Workflow

**Position: Step 3 — after LLM drafts, before approval.**

```
(LLM drafts post)  →  [validate-post]  ──── fail ──→  (LLM revises with error context)
                              │ pass
                              ▼
                  [approval-state-manager]
```

On failure, the error list should be passed back to the LLM as structured context to guide revision. Do not send the full validator output — extract only the `errors` array to keep token usage minimal.
