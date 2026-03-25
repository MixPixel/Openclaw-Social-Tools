# Tool Spec: platform-adapters

## Purpose

Provides the platform adapter boundary between `publish_post` and the social media
platform APIs. Each adapter receives a queue entry, attempts delivery to one platform,
and returns a standardised result dict. Platform-specific HTTP logic, credential
management, and error normalisation live here — not in `publish_post`.

---

## Why It Exists

`publish_post` is deterministic: it reads the queue, applies delivery logic, and
updates state. It must not contain platform-specific code. The adapter layer is the
controlled boundary where side effects (real HTTP calls) occur. This separation means:

- `publish_post` can be tested without any network access
- Each platform adapter can be developed and tested independently
- Swapping or adding a platform requires no changes to `publish_post`
- Credentials never touch the deterministic tool layer

---

## Adapter Contract

All adapters share one callable signature:

```python
def adapter(entry: dict) -> dict:
    """
    entry:  Full queue record as written by schedule_post.
            Guaranteed fields: queue_id, post_id, platform, content,
            slot, media (list), actor, created_at.

    Returns on success:
    {
        "success":           True,
        "platform_post_id":  str | None,   # platform's ID for the created post
        "platform_response": dict | None,  # raw response body, for debugging
    }

    Returns on failure:
    {
        "success":           False,
        "error_code":        str,          # canonical code from base.py
        "message":           str,          # human-readable detail
        "retryable":         bool,         # advisory; derived from error_code
        "platform_response": dict | None,
    }
    """
```

`publish_post` catches any exception raised by an adapter and records it as
`error_code: ADAPTER_EXCEPTION`. Adapters should prefer returning a failure dict
over raising, except for `NotImplementedError` on skeletal methods.

### Result validation

`validate_adapter_result(result: dict)` in `base.py` checks the shape of any adapter
result. Raises `ValueError` if required fields are missing. Adapters call this before
returning; tests call it to verify mock conformance.

---

## Error Codes

Defined as string constants in `base.py`. All adapters normalise platform-specific
errors into these codes.

| Code | Meaning | Retryable |
|---|---|---|
| `AUTH_ERROR` | Credentials wrong, missing, or expired | No |
| `PERMISSION_ERROR` | Account lacks required scope or page access | No |
| `CONTENT_REJECTED` | Platform refused content (duplicate, policy, length) | No |
| `RATE_LIMITED` | Platform throttled the request | Yes |
| `MEDIA_UPLOAD_FAILED` | Media attachment could not be uploaded | No |
| `NETWORK_ERROR` | Connection failed before a response was received | Yes |
| `PLATFORM_UNAVAILABLE` | Platform returned 5xx | Yes |
| `TIMEOUT` | Request timed out | Yes |
| `UNKNOWN_ERROR` | Unclassified; conservative default | No |

`is_retryable(error_code: str) -> bool` derives the retryable flag from this table.

### HTTP status → error code mapping

`classify_http_error(status_code: int, body: str = "") -> str` provides the default
mapping. Individual adapters may override specific cases.

| HTTP status | Default code |
|---|---|
| 401, 403 | `AUTH_ERROR` |
| 429 | `RATE_LIMITED` |
| 400, 422 | `CONTENT_REJECTED` |
| 500–599 | `PLATFORM_UNAVAILABLE` |
| Other | `UNKNOWN_ERROR` |

---

## Credentials Model

Credentials are **never** in the queue entry and **never** hardcoded. They are resolved
at adapter construction time:

1. **Explicit dict** (tests, library use) — passed to `get_adapter()`:
   ```python
   adapter = get_adapter("twitter", credentials={"TWITTER_API_KEY": "key", ...})
   ```

2. **Environment variables** (production) — read via `os.environ` when `credentials=None`:
   ```python
   adapter = get_adapter("twitter")  # reads TWITTER_API_KEY etc. from env
   ```

If a required credential is absent from both sources, the adapter returns `AUTH_ERROR`
immediately without attempting any network call.

### Per-platform credential keys

| Platform | Required environment variables |
|---|---|
| `twitter` | `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET` |
| `linkedin` | `LINKEDIN_ACCESS_TOKEN` |
| `instagram` | `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID` |
| `facebook` | `FACEBOOK_PAGE_ACCESS_TOKEN`, `FACEBOOK_PAGE_ID` |
| `mastodon` | `MASTODON_ACCESS_TOKEN`, `MASTODON_INSTANCE_URL` |

Credentials are never written to disk, logged, or stored in any queue or state file.

---

## Registry and Factory

`registry.py` exports two functions:

### `get_adapter(platform, credentials=None)`

Returns the adapter callable for a single named platform. Raises `ValueError` for
unrecognised platform names — this is a **developer error** (a typo or unsupported
platform). Supported names: `twitter`, `linkedin`, `instagram`, `facebook`, `mastodon`,
`stub`.

### `get_dispatch_adapter(credentials=None)`

Returns a single callable that dispatches to the correct platform adapter based on
`entry["platform"]`. This is the canonical way to inject an adapter into `publish_post`
when the queue may contain entries for multiple platforms.

```python
from tools.platform_adapters import get_dispatch_adapter
from tools.publish_post import publish_post

adapter = get_dispatch_adapter()
result = publish_post(data, _adapter=adapter)
```

Unlike `get_adapter`, the dispatch adapter **never raises** for unknown platforms — it
returns a failure dict with `error_code: UNKNOWN_ERROR`. This ensures `publish_post`
always receives a clean result regardless of queue content.

---

## StubAdapter

`stub.py` provides a configurable no-network adapter for tests and development.

```python
from tools.platform_adapters import StubAdapter

adapter = StubAdapter()                              # always succeeds
adapter = StubAdapter(success=False,
                      error_code="RATE_LIMITED",
                      message="too many requests")  # always fails
adapter = StubAdapter(raise_exception=True,
                      exception_message="timeout")  # simulates crash
```

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `success` | bool | `True` | Whether the adapter reports success |
| `platform_post_id` | str \| None | `"stub_pid"` | Returned on success |
| `error_code` | str | `"ADAPTER_ERROR"` | Returned on failure |
| `message` | str | `"stub failure"` | Failure message |
| `raise_exception` | bool | `False` | Raise instead of returning |
| `exception_message` | str | `"stub exception"` | Exception message |
| `platform_response` | dict \| None | `None` | Raw response field |

`StubAdapter` calls `validate_adapter_result` before returning, so misconfigured stubs
are caught at test time rather than silently producing bad results.

---

## Platform Modules

Each of the five platform modules (`twitter.py`, `linkedin.py`, `instagram.py`,
`facebook.py`, `mastodon.py`) has the same structure:

| Symbol | Description |
|---|---|
| `REQUIRED_CREDENTIALS` | Tuple of required env var names |
| `_build_payload(entry)` | Pure function: queue entry → platform request dict |
| `_parse_response(status, body)` | Pure function: HTTP response → adapter result dict |
| `PlatformAdapter` | Class: checks credentials, calls build/parse, makes HTTP call |
| `get_adapter(credentials)` | Factory: resolves credentials and returns adapter instance |

`_build_payload` and `_parse_response` are pure functions (no network, no state) so
they can be unit-tested independently. `PlatformAdapter.__call__` orchestrates them.

### Current implementation status

Real HTTP delivery is not yet implemented. `_build_payload` and `_parse_response`
raise `NotImplementedError`. When called, `PlatformAdapter.__call__` performs the
credential check (returning `AUTH_ERROR` cleanly if credentials are missing) then
raises `NotImplementedError` — which `publish_post` catches and records as
`ADAPTER_EXCEPTION`.

| Platform | Auth | Post endpoint | Media notes |
|---|---|---|---|
| Twitter / X | OAuth 1.0a (HMAC-SHA1) | `POST /2/tweets` | Separate upload endpoint; media_id attached to tweet |
| LinkedIn | OAuth 2.0 Bearer | `POST /v2/ugcPosts` | Multi-step upload: register → binary upload → attach URN |
| Instagram | Graph API Bearer | Two-step: create container, then publish | Text-only posts not supported; media required |
| Facebook | Page Access Token | `POST /{page-id}/feed` | Photo/video use separate endpoints |
| Mastodon | Bearer + instance URL | `POST /api/v1/statuses` | Simplest API; instance URL varies per deployment |

---

## File Structure

```
tools/platform_adapters/
    __init__.py     public exports
    base.py         error codes, retryability, HTTP classification, result validation
    stub.py         StubAdapter
    registry.py     get_adapter(), get_dispatch_adapter()
    twitter.py      Twitter / X skeleton
    linkedin.py     LinkedIn skeleton
    instagram.py    Instagram skeleton
    facebook.py     Facebook skeleton
    mastodon.py     Mastodon skeleton
```

---

## Integration with publish_post

`publish_post.py` is not modified. The `_stub_adapter` inline in that file remains as
the zero-dependency default for the CLI. The adapter layer is consumed from the outside:

```python
# Development / testing (no real delivery):
from tools.platform_adapters import StubAdapter
result = publish_post(data, _adapter=StubAdapter())

# Production (all platforms, credentials from env):
from tools.platform_adapters import get_dispatch_adapter
result = publish_post(data, _adapter=get_dispatch_adapter())

# Single platform, explicit credentials:
from tools.platform_adapters import get_adapter
adapter = get_adapter("mastodon", credentials={
    "MASTODON_ACCESS_TOKEN":  "my_token",
    "MASTODON_INSTANCE_URL":  "https://mastodon.social",
})
result = publish_post(data, _adapter=adapter)
```
