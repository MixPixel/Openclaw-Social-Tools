# Tool Spec: validate-post

## Purpose

Checks a post draft against the hard rules of a target platform before it enters the approval workflow. Returns a pass/fail result with structured error codes so the LLM (or a human) can correct the draft efficiently.

---

## Why It Exists

Platform rules are exact and mechanical: character limits, forbidden content types, image count limits, link restrictions. Asking an LLM to enforce these is wasteful and unreliable. A deterministic validator catches every violation instantly, cheaply, and consistently.

By catching errors early — before approval, before scheduling — the tool prevents bad posts from travelling further down the pipeline and reduces the number of LLM revision calls needed.

---

## Implementation

`tools/validate_post/validate_post.py` — stdlib only, no external dependencies.

---

## Inputs

| Field | Type | Required | Description |
|---|---|---|---|
| `content` | string | yes | The post body text |
| `platform` | string | yes | See accepted values below |
| `media` | list[object] | no | Attached media. Each item: `{ type: "image"\|"video", size_bytes: int, format: string }` |
| `links` | list[string] | no | URLs included in the post (supplements auto-detection from content) |
| `hashtags` | list[string] | no | Hashtags without `#` prefix (supplements auto-detection from content) |
| `mentions` | list[string] | no | Mentions without `@` prefix |

### Accepted platform values

The tool accepts the following values for `platform` (case-insensitive). All Twitter variants normalise to the canonical key `"twitter"`.

| Input | Canonical key |
|---|---|
| `"twitter"` | `"twitter"` |
| `"x"` | `"twitter"` |
| `"twitter/x"` | `"twitter"` |
| `"x/twitter"` | `"twitter"` |
| `"linkedin"` | `"linkedin"` |
| `"instagram"` | `"instagram"` |
| `"facebook"` | `"facebook"` |
| `"mastodon"` | `"mastodon"` |

---

## Outputs

Both `errors` and `warnings` are always present in the response (may be empty lists).

### On pass

```json
{
  "valid": true,
  "platform": "twitter",
  "character_count": 242,
  "errors": [],
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
      "message": "Post is 301 characters; Twitter / X limit is 280.",
      "limit": 280,
      "actual": 301
    }
  ],
  "warnings": [
    {
      "code": "HIGH_HASHTAG_COUNT",
      "message": "5 hashtags detected. Engagement typically drops above 3 on Twitter / X."
    }
  ]
}
```

`warnings` are non-blocking — they never set `valid` to `false`.
`errors` cause `valid: false`.

The `platform` field in the output is always the canonical key (e.g. `"twitter"` even if the input was `"x"` or `"twitter/x"`).

---

## Platform Rules

### Character limits

| Platform | Limit | Link cost |
|---|---|---|
| Twitter / X | 280 | 23 chars per URL (t.co shortening) |
| LinkedIn | 3,000 | Actual URL length |
| Instagram | 2,200 | Actual URL length |
| Facebook | 63,206 | Actual URL length |
| Mastodon | 500 | 23 chars per URL (same convention as Twitter) |

URLs in content are auto-detected. Links in the explicit `links` field are validated but do not additionally inflate the character count (they are expected to already be present in `content`).

**Emoji and Unicode:** Characters are counted as Unicode code points. Emoji count as 1 character each. The exception is URLs on Twitter / X and Mastodon, which are counted at their fixed t.co cost regardless of actual length.

### Media limits

| Platform | Max images | Max videos | Notes |
|---|---|---|---|
| Twitter / X | 4 | 1 | Cannot mix images and video |
| LinkedIn | 9 | 1 | Cannot mix images and video |
| Instagram | 10 | 10 | Mixed carousel is allowed |
| Facebook | 10 | 1 | Cannot mix images and video |
| Mastodon | 4 | 1 | Cannot mix images and video |

**Allowed image formats:** jpeg/jpg, png, gif, webp (Twitter, Mastodon); jpeg/jpg, png, gif (LinkedIn); jpeg/jpg, png (Instagram); jpeg/jpg, png, gif, bmp, tiff (Facebook).

**Allowed video formats:** mp4, mov (Twitter, Instagram, Mastodon); mp4, mov, avi, mkv (LinkedIn); mp4, mov, avi (Facebook); mp4, mov, webm (Mastodon).

**Max image sizes:** Twitter 5 MB · LinkedIn 8 MB · Instagram 8 MB · Facebook 10 MB · Mastodon 10 MB.

**Max video sizes:** Twitter 512 MB · LinkedIn 200 MB · Instagram 100 MB · Facebook 10 GB · Mastodon 40 MB.

### Hashtag limits

| Platform | Hard limit | Warn above |
|---|---|---|
| Twitter / X | none | 3 |
| LinkedIn | none | 5 |
| Instagram | 30 | 10 |
| Facebook | none | none |
| Mastodon | none | 5 |

### Link rules

Instagram: links in captions are not clickable. A `LINK_NOT_ALLOWED` **warning** (non-blocking) is added if links are detected. The post is still `valid`.

---

## Error Codes

| Code | Description |
|---|---|
| `CHARACTER_LIMIT_EXCEEDED` | Post body exceeds platform character limit |
| `EMPTY_CONTENT` | Post body is empty or whitespace only |
| `MISSING_REQUIRED_FIELD` | A required field (`platform`) was omitted |
| `UNSUPPORTED_PLATFORM` | Platform value not recognised |
| `UNSUPPORTED_MEDIA_TYPE` | Attached media format not supported on this platform, or unknown type |
| `MEDIA_SIZE_EXCEEDED` | Media file exceeds platform size limit |
| `MEDIA_COUNT_EXCEEDED` | Too many media attachments for this platform |
| `MEDIA_TYPE_CONFLICT` | Images and video mixed in the same post where not allowed |
| `INVALID_LINK` | A link is malformed or uses a disallowed protocol (only `http` and `https` are allowed) |
| `HASHTAG_LIMIT_EXCEEDED` | More hashtags than the platform allows |

## Warning Codes

| Code | Description |
|---|---|
| `HIGH_HASHTAG_COUNT` | Hashtag count is within limits but above the recommended threshold |
| `LONG_CONTENT` | Content is within limits but above 80% of the character cap |
| `LINK_NOT_ALLOWED` | Link detected for Instagram (non-clickable in captions) |
| `NO_CTA` | No call-to-action phrase or link detected (heuristic, warning only, never an error) |

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| `"x"`, `"twitter/x"`, `"X"` as platform | All normalise to `"twitter"` (case-insensitive) |
| Unicode content (emoji, CJK characters) | Characters counted as Unicode code points; emoji = 1 each |
| Multi-platform validation | Tool validates one platform per call; call it once per platform for cross-posting |
| Content is only whitespace | Returns `EMPTY_CONTENT` error |
| Links on Twitter / Mastodon | Each URL in content replaced with 23-char placeholder before counting |
| Media list is empty array vs. omitted | Both treated as "no media" — identical behaviour |
| Hashtags in body vs. in `hashtags` field | Tool detects hashtags in `content` automatically; `hashtags` field is additive. Duplicates are deduplicated |
| Format with leading dot (e.g. `".jpeg"`) | Leading dot is stripped before format check |
| Image + video on Twitter | Returns `MEDIA_TYPE_CONFLICT` error |
| Image + video on Instagram | Allowed (carousel); no error |

---

## CLI Usage

```bash
# Pass JSON on stdin; exits 0 on pass, 1 on fail
echo '{"content": "Hello world! Sign up now.", "platform": "twitter"}' \
  | python -m tools.validate_post.validate_post

# With media
echo '{
  "content": "Check out this photo! Learn more.",
  "platform": "twitter",
  "media": [{"type": "image", "format": "jpeg", "size_bytes": 1048576}]
}' | python -m tools.validate_post.validate_post
```

## Library Usage

```python
from tools.validate_post import validate_post

result = validate_post({
    "content": "Hello world! Sign up now.",
    "platform": "x",   # or "twitter", "twitter/x" — all equivalent
})

if result["valid"]:
    print("Post is valid")
else:
    for error in result["errors"]:
        print(error["code"], error["message"])
```

---

## Where It Fits in the Workflow

**Position: Step 3 — after LLM drafts, before approval.**

```
(LLM drafts post)  →  [validate-post]  ──── fail ──→  (LLM revises with error context)
                              │ pass
                              ▼
                  [approval-state-manager]
```

On failure, pass only the `errors` array back to the LLM as structured context — not the full validator output. This keeps token usage minimal.
