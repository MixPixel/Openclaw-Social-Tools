# publish-pipeline CLI

Publishes a post to a social platform. Reads a JSON payload from stdin,
delivers it via the platform adapter, and prints a JSON result to stdout.

**Only Twitter delivery is fully implemented.** LinkedIn, Instagram, Facebook,
and Mastodon adapters are stubbed and will return an error.

---

## Quickstart

Create a `.env` file with your Twitter credentials:

```
TWITTER_API_KEY=your_api_key
TWITTER_API_SECRET=your_api_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_SECRET=your_access_token_secret
```

Create a `post.json`:

```json
{
  "content": "Hello from OpenClaw!"
}
```

Run:

```bash
cat post.json | python -m tools.publish_pipeline --platform twitter
```

Exit code `0` on success, `1` on any failure. The result is always JSON.

---

## Credentials

Credentials are loaded in this order (first match wins):

1. Real environment variables (`export TWITTER_API_KEY=...`)
2. Values from a `.env` file

Real environment variables always override `.env` values.

| Platform  | Required env vars |
|-----------|-------------------|
| twitter   | `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET` |

---

## `.env` file format

```
# Comments and blank lines are ignored
TWITTER_API_KEY=abc123
TWITTER_API_SECRET=xyz789
TWITTER_ACCESS_TOKEN=token
TWITTER_ACCESS_SECRET=token_secret
```

Quoted values are unquoted: `KEY="value with spaces"` → `value with spaces`.
Lines without `=` are silently skipped.

---

## `post.json` format

```json
{
  "content": "Post text here"
}
```

`platform` can be in the JSON or supplied with `--platform`. The flag overrides
the JSON field when both are present.

Optional fields (passed through to the adapter):

```json
{
  "content": "Post text",
  "hashtags": ["opendata", "python"],
  "mentions": ["someone"],
  "links": ["https://example.com"]
}
```

---

## Command examples

```bash
# .env in working directory loaded automatically
cat post.json | python -m tools.publish_pipeline --platform twitter

# Explicit credentials file
cat post.json | python -m tools.publish_pipeline --platform twitter \
  --env-file ~/secrets/twitter.env

# Platform already in the JSON file
cat post.json | python -m tools.publish_pipeline

# Override the platform field in the JSON
cat post.json | python -m tools.publish_pipeline --platform twitter

# Inline post, no file
echo '{"content": "Hello!"}' | python -m tools.publish_pipeline --platform twitter
```

---

## Result shape

```json
{
  "success": true,
  "platform": "twitter",
  "post_id": "1234567890",
  "character_count": 20,
  "validation_errors": [],
  "media_results": [],
  "errors": [],
  "warnings": []
}
```

On failure `success` is `false` and `errors` contains an object with a `code`
and `message`. Common codes:

| Code | Meaning |
|------|---------|
| `AUTH_ERROR` | Missing or invalid credentials |
| `CONTENT_REJECTED` | Platform rejected the post content |
| `RATE_LIMITED` | Too many requests |
| `NETWORK_ERROR` | HTTP request failed |
| `INVALID_INPUT` | Stdin was not valid JSON |
| `ENV_FILE_ERROR` | `--env-file` path could not be read |

---

## Current limitations

- **Text posts only.** Media uploads via `file_path` are implemented in the
  adapter but there is no documented end-to-end example for image or video posts.
- **Twitter only.** Other platforms fail at the delivery stage with
  `NOT_IMPLEMENTED`.
- **No retry logic.** Check `retryable: true` in the error object and re-run
  manually for rate-limit or transient network errors.
