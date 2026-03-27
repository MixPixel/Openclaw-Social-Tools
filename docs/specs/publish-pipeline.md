# Spec: publish-pipeline

## Purpose

`publish_pipeline` is the first end-to-end vertical slice of the OpenClaw
posting workflow.  It threads together three previously built layers — content
validation (`validate_post`), asset upload (`upload_asset`), and platform
adapter dispatch (`registry.get_adapter`) — into a single callable that takes
a post payload and returns one structured result.

---

## Problem It Solves

Before this tool:
- `validate_post`, `upload_asset`, and the adapter registry were independent.
- No layer existed to sequence them for a complete "write post → publish" run.
- Callers had to wire validation → upload → dispatch themselves, with no
  standard result shape for the combined outcome.

After this tool:
- One function — `publish_to_platform` — encapsulates the full pipeline.
- All three layers are called in order; the adapter is never reached if an
  earlier stage fails.
- The result carries every relevant outcome (validation errors, per-media
  upload results, adapter response) in a single dict.

---

## File Structure

```
tools/publish_pipeline/
    __init__.py          public exports
    publish_pipeline.py  pipeline logic + result validator
```

---

## Public API

### `publish_to_platform(post, *, credentials=None, policy_path=None, _adapter=None) -> dict`

Runs four stages in order:

1. **Validate post** — calls `validate_post` with `content`, `platform`, and
   any optional `media`, `hashtags`, `mentions`, `links` fields from `post`.
   Returns immediately if `valid=False`.

2. **Upload media** — calls `upload_asset` for each item in `post["media"]`
   (if present).  Returns immediately if any upload fails.

3. **Resolve adapter** — calls `registry.get_adapter(platform, credentials)`
   unless `_adapter` is injected.

4. **Deliver** — calls the adapter with an entry dict containing `platform`,
   `content`, `media_ids` (list of `asset_ref` strings), plus any forwarded
   optional fields.  Maps the adapter result to the pipeline result shape.

### `validate_pipeline_result(result) -> None`

Shape guard.  Raises `ValueError` if any required field is missing or has the
wrong type.  Called internally before returning; tests may call it directly.

---

## Post Input Shape

```python
{
    # Required:
    "platform": str,   # "twitter", "linkedin", "instagram", "facebook", "mastodon"
    "content":  str,   # post body text / caption

    # Optional:
    "media":    list,  # see Media item shape below
    "hashtags": list,
    "mentions": list,
    "links":    list,
}
```

### Media item shape

Each entry in `media` is passed verbatim to `upload_asset`, which passes it
through `validate_asset` (policy/capability check) and then to the platform
adapter's `upload_asset()` function. The adapter reads the file at `file_path`.

```python
{
    # Transport — required by the platform adapter:
    "file_path":  str,   # absolute or relative path to image file on disk

    # Policy — required by validate_asset:
    "asset_type": str,   # e.g. "product_photo", "logo", "generated_graphic"
    "format":     str,   # lowercase extension without dot: "png", "jpeg", "gif", "webp"
    "alt_text":   str,   # required when asset policy sets require_alt_text: true
    "context":    str,   # publishing context, e.g. "social_post"

    # Optional policy fields:
    "source_url":   str,   # origin URL for provenance checking
    "license":      dict,  # license record; required for some asset types
    "edit_applied": str,   # edit operation applied, e.g. "resize"
}
```

`file_path` is not validated by `validate_asset`. It is read by the adapter at
upload time. A missing or unreadable `file_path` returns `MEDIA_UPLOAD_FAILED`.

---

## Result Shape

```python
{
    "success":           bool,
    "platform":          str,          # normalised (e.g. "x" → "twitter")
    "post_id":           str | None,   # platform post ID on success
    "character_count":   int | None,   # from validate_post
    "validation_errors": list,         # non-empty when Stage 1 fails
    "media_results":     list,         # per-media upload outcomes
    "errors":            list,         # pipeline / adapter errors
    "warnings":          list,         # always present; from validate_post
}
```

Each `media_results` entry:

```python
{
    "asset_type":        str | None,
    "asset_ref":         str | None,
    "success":           bool,
    "errors":            list,
    "validation_errors": list,
}
```

---

## Failure Taxonomy

| Stage | Indicator | Description |
|---|---|---|
| Stage 1 | `validation_errors` non-empty | `validate_post` returned `valid=False` |
| Stage 2 | `media_results[i]["success"] == False` + `errors[0]["code"] == "MEDIA_UPLOAD_FAILED"` | One or more uploads failed |
| Stage 3 | `errors[0]["code"] == "UNKNOWN_PLATFORM"` | `get_adapter` raised `ValueError` |
| Stage 4 | `errors[0]["code"] == "ADAPTER_EXCEPTION"` | Adapter raised unexpectedly |
| Stage 4 | `errors[0]["code"] == <adapter code>` | Adapter returned `success=False` |

---

## Injectable Seams

| Parameter | Default | Purpose |
|---|---|---|
| `_adapter` | `registry.get_adapter(platform, credentials)` | Replace adapter for unit tests |
| `tools.publish_pipeline.publish_pipeline._upload_asset` | `tools.upload_asset.upload_asset` | Patch upload step in unit tests |
| `policy_path` | `config/asset_policy.json` | Isolate asset policy in tests |

---

## Relationship to Other Layers

- **`validate_post`:** Content and media metadata validation. Called first;
  result propagated verbatim to `validation_errors` and `warnings`.
- **`upload_asset`:** Per-media binary upload. Called for each media item after
  content validation passes.
- **`registry.get_adapter`:** Resolves the platform-specific adapter callable.
  Called only after all uploads succeed.
- **`publish_post`:** Queue-based post delivery — a separate path that is not
  called by `publish_pipeline`. `publish_pipeline` calls the adapter directly,
  without a scheduling queue.

---

## What Is Not in This Contract

- Scheduling / queued delivery — use `publish_post` for that.
- Retry logic — callers inspect `retryable` flags if available.
- Multi-platform fan-out — call `publish_to_platform` once per target platform.
- Draft or preview modes.
