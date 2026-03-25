"""publish_pipeline — end-to-end publish pipeline vertical slice.

Validates a post payload, uploads any attached media, resolves a platform
adapter, and delivers the post.  Returns one structured result.

Two injectable seams for test isolation:
  - _adapter   — replaces registry.get_adapter() for the post-publish step.
  - patch tools.publish_pipeline.publish_pipeline._upload_asset to control
    media upload behaviour in unit tests.

Public API
----------
  publish_to_platform(post, *, credentials=None, policy_path=None, _adapter=None) -> dict
      Validate → upload media → publish.

  validate_pipeline_result(result) -> None
      Shape-check a pipeline result dict.  Raises ValueError on any violation.

Post input shape
----------------
  Required:
    platform  (str)   Target platform: "twitter", "linkedin", etc.
    content   (str)   Post text / caption.

  Optional:
    media     (list)  Asset dicts forwarded to upload_asset.  Each item may
                      also carry validate_post media fields (type, format,
                      size_bytes) for pre-upload content validation.
    hashtags  (list)  Hashtag strings (forwarded to validate_post and adapter).
    mentions  (list)  Mention strings (forwarded to validate_post and adapter).
    links     (list)  URL strings (forwarded to validate_post and adapter).

Result shape
------------
  {
      "success":           bool,
      "platform":          str,           # normalised (e.g. "x" → "twitter")
      "post_id":           str | None,    # platform post ID on success
      "character_count":   int | None,    # from validate_post
      "validation_errors": list,          # post-level validation errors
      "media_results":     list,          # per-media upload outcomes
      "errors":            list,          # pipeline / adapter errors
      "warnings":          list,          # non-blocking observations
  }

  Each media_results entry:
      {
          "asset_type":        str | None,
          "asset_ref":         str | None,
          "success":           bool,
          "errors":            list,
          "validation_errors": list,
      }

Failure taxonomy
----------------
  validation_errors non-empty, adapter not contacted:
      validate_post returned valid=False (unknown platform, empty content,
      character limit exceeded, bad media format/count, etc.).

  media_results contains success=False, adapter not contacted:
      One or more media uploads failed.  errors contains MEDIA_UPLOAD_FAILED.

  errors non-empty, validation and uploads passed:
      UNKNOWN_PLATFORM    — platform unknown to registry.get_adapter
      ADAPTER_EXCEPTION   — adapter callable raised unexpectedly
      <adapter error_code> — adapter returned success=False with its own code
"""

from typing import Optional

from tools.validate_post import validate_post as _validate_post
from tools.upload_asset import upload_asset as _upload_asset
from tools.platform_adapters.registry import get_adapter as _get_adapter


# ---------------------------------------------------------------------------
# Result shape validator
# ---------------------------------------------------------------------------

_REQUIRED_RESULT_FIELDS = (
    "success", "platform", "post_id", "character_count",
    "validation_errors", "media_results", "errors", "warnings",
)


def validate_pipeline_result(result: dict) -> None:
    """Verify that a publish_to_platform result dict has the required shape.

    Raises ValueError with a descriptive message if any required field is
    missing or has the wrong type.

    Required fields:
        success (bool), platform (str), post_id (str | None),
        character_count (int | None), validation_errors (list),
        media_results (list), errors (list), warnings (list)
    """
    if not isinstance(result, dict):
        raise ValueError(
            f"publish_to_platform result must be a dict, "
            f"got {type(result).__name__}."
        )
    for field in _REQUIRED_RESULT_FIELDS:
        if field not in result:
            raise ValueError(
                f"publish_to_platform result is missing required field '{field}'."
            )
    if not isinstance(result["success"], bool):
        raise ValueError(
            f"publish_to_platform result 'success' must be bool, "
            f"got {type(result['success']).__name__}."
        )
    for list_field in ("validation_errors", "media_results", "errors", "warnings"):
        if not isinstance(result[list_field], list):
            raise ValueError(
                f"publish_to_platform result '{list_field}' must be a list, "
                f"got {type(result[list_field]).__name__}."
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def publish_to_platform(
    post: dict,
    *,
    credentials: Optional[dict] = None,
    policy_path=None,
    _adapter=None,
) -> dict:
    """Validate, upload media, and publish a post to one platform.

    Runs in four stages:
        1. Validate post content and media metadata via validate_post.
        2. Upload each media item via upload_asset.  Skipped if no media.
        3. Resolve platform adapter via registry.get_adapter or injection.
        4. Deliver to the platform adapter.

    The adapter is never contacted when validation or any media upload fails.

    Args:
        post:         Post payload dict.  Required keys: platform (str),
                      content (str).  Optional: media (list), hashtags (list),
                      mentions (list), links (list).
        credentials:  Optional credentials dict for platform API calls.
                      None → adapters read from os.environ.
        policy_path:  Optional path to asset_policy.json for test isolation.
        _adapter:     Inject a callable (entry: dict) -> dict in place of the
                      registry adapter.  Useful in unit tests to isolate the
                      pipeline from real HTTP calls.

    Returns:
        A validated pipeline result dict.

    Raises:
        ValueError: if post is not a dict.
    """
    if not isinstance(post, dict):
        raise ValueError(
            f"publish_to_platform requires a dict, got {type(post).__name__}."
        )

    # Raw platform string; normalised form comes from validate_post.
    platform_out = str(post.get("platform") or "").strip().lower()
    content = post.get("content", "")

    def _result(
        success: bool,
        *,
        post_id: Optional[str] = None,
        character_count: Optional[int] = None,
        validation_errors: Optional[list] = None,
        media_results: Optional[list] = None,
        errors: Optional[list] = None,
        warnings: Optional[list] = None,
    ) -> dict:
        r = {
            "success":           success,
            "platform":          platform_out,
            "post_id":           post_id,
            "character_count":   character_count,
            "validation_errors": validation_errors if validation_errors is not None else [],
            "media_results":     media_results if media_results is not None else [],
            "errors":            errors if errors is not None else [],
            "warnings":          warnings if warnings is not None else [],
        }
        validate_pipeline_result(r)
        return r

    # ------------------------------------------------------------------
    # Stage 1 — validate post content
    # ------------------------------------------------------------------
    validate_input: dict = {
        "platform": post.get("platform"),
        "content":  content,
    }
    # media is deliberately excluded: validate_post expects {type, format, size_bytes}
    # but pipeline media items use the upload_asset schema {asset_type, format, ...}.
    # Media-level format and policy checks run inside upload_asset → validate_asset.
    for opt_key in ("hashtags", "mentions", "links"):
        if opt_key in post:
            validate_input[opt_key] = post[opt_key]

    try:
        vr = _validate_post(validate_input)
    except Exception as exc:  # noqa: BLE001
        return _result(
            False,
            errors=[{"code": "VALIDATION_ERROR", "message": str(exc)}],
        )

    # Adopt the normalised platform string from validate_post output.
    if vr.get("platform"):
        platform_out = vr["platform"]

    char_count = vr.get("character_count")

    if not vr["valid"]:
        return _result(
            False,
            character_count=char_count,
            validation_errors=vr["errors"],
            warnings=vr.get("warnings", []),
        )

    # ------------------------------------------------------------------
    # Stage 2 — upload media
    # ------------------------------------------------------------------
    raw_media = post.get("media") or []
    media_results: list[dict] = []

    for media_item in raw_media:
        ur = _upload_asset(
            media_item,
            platform_out,
            credentials=credentials,
            policy_path=policy_path,
        )
        media_results.append({
            "asset_type":        ur.get("asset_type"),
            "asset_ref":         ur.get("asset_ref"),
            "success":           bool(ur.get("success", False)),
            "errors":            ur.get("errors", []),
            "validation_errors": ur.get("validation_errors", []),
        })

    upload_failures = [m for m in media_results if not m["success"]]
    if upload_failures:
        return _result(
            False,
            character_count=char_count,
            media_results=media_results,
            errors=[{
                "code":    "MEDIA_UPLOAD_FAILED",
                "message": (
                    f"{len(upload_failures)} of {len(media_results)} "
                    "media upload(s) failed."
                ),
            }],
            warnings=vr.get("warnings", []),
        )

    # ------------------------------------------------------------------
    # Stage 3 — resolve adapter
    # ------------------------------------------------------------------
    if _adapter is not None:
        adapter = _adapter
    else:
        try:
            adapter = _get_adapter(platform_out, credentials)
        except ValueError as exc:
            return _result(
                False,
                character_count=char_count,
                media_results=media_results,
                errors=[{"code": "UNKNOWN_PLATFORM", "message": str(exc)}],
                warnings=vr.get("warnings", []),
            )

    # ------------------------------------------------------------------
    # Stage 4 — deliver to adapter
    # ------------------------------------------------------------------
    media_ids = [m["asset_ref"] for m in media_results if m.get("asset_ref")]
    entry: dict = {
        "platform":  platform_out,
        "content":   content,
        "media_ids": media_ids,
    }
    for extra_key in ("hashtags", "mentions", "links"):
        if extra_key in post:
            entry[extra_key] = post[extra_key]

    try:
        ar = adapter(entry)
    except Exception as exc:  # noqa: BLE001
        return _result(
            False,
            character_count=char_count,
            media_results=media_results,
            errors=[{"code": "ADAPTER_EXCEPTION", "message": str(exc)}],
            warnings=vr.get("warnings", []),
        )

    if ar.get("success"):
        return _result(
            True,
            post_id=ar.get("platform_post_id"),
            character_count=char_count,
            media_results=media_results,
            warnings=vr.get("warnings", []),
        )

    return _result(
        False,
        character_count=char_count,
        media_results=media_results,
        errors=[{
            "code":    str(ar.get("error_code") or "ADAPTER_ERROR"),
            "message": str(ar.get("message") or ""),
        }],
        warnings=vr.get("warnings", []),
    )
