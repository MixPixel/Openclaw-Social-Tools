"""validate_post — deterministic post validator for social media platforms.

Usage (CLI):
    echo '{"content": "Hello world", "platform": "twitter"}' | python -m tools.validate_post.validate_post
    # exits 0 on pass, 1 on fail or error

Usage (library):
    from tools.validate_post import validate_post
    result = validate_post({"content": "Hello world", "platform": "twitter"})
"""

import json
import re
import sys
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MB = 1024 * 1024
_GB = 1024 * _MB

# ---------------------------------------------------------------------------
# Platform rules
# ---------------------------------------------------------------------------

PLATFORM_RULES: dict[str, dict] = {
    "twitter": {
        "display_name": "Twitter / X",
        "char_limit": 280,
        "link_char_cost": 23,   # t.co shortening — each URL costs exactly 23 chars
        "hashtag_limit": None,
        "hashtag_warn_above": 3,
        "links_clickable": True,
        "media": {
            "max_images": 4,
            "max_videos": 1,
            "images_and_video_exclusive": True,
            "allowed_image_formats": {"jpeg", "jpg", "png", "gif", "webp"},
            "allowed_video_formats": {"mp4", "mov"},
            "max_image_size_bytes": 5 * _MB,
            "max_video_size_bytes": 512 * _MB,
        },
    },
    "linkedin": {
        "display_name": "LinkedIn",
        "char_limit": 3000,
        "link_char_cost": None,  # links counted at actual length
        "hashtag_limit": None,
        "hashtag_warn_above": 5,
        "links_clickable": True,
        "media": {
            "max_images": 9,
            "max_videos": 1,
            "images_and_video_exclusive": True,
            "allowed_image_formats": {"jpeg", "jpg", "png", "gif"},
            "allowed_video_formats": {"mp4", "mov", "avi", "mkv"},
            "max_image_size_bytes": 8 * _MB,
            "max_video_size_bytes": 200 * _MB,
        },
    },
    "instagram": {
        "display_name": "Instagram",
        "char_limit": 2200,
        "link_char_cost": None,
        "hashtag_limit": 30,
        "hashtag_warn_above": 10,
        "links_clickable": False,  # links in captions are not clickable
        "media": {
            "max_images": 10,
            "max_videos": 10,
            "images_and_video_exclusive": False,  # carousel allows mixed
            "allowed_image_formats": {"jpeg", "jpg", "png"},
            "allowed_video_formats": {"mp4", "mov"},
            "max_image_size_bytes": 8 * _MB,
            "max_video_size_bytes": 100 * _MB,
        },
    },
    "facebook": {
        "display_name": "Facebook",
        "char_limit": 63206,
        "link_char_cost": None,
        "hashtag_limit": None,
        "hashtag_warn_above": None,
        "links_clickable": True,
        "media": {
            "max_images": 10,
            "max_videos": 1,
            "images_and_video_exclusive": True,
            "allowed_image_formats": {"jpeg", "jpg", "png", "gif", "bmp", "tiff"},
            "allowed_video_formats": {"mp4", "mov", "avi"},
            "max_image_size_bytes": 10 * _MB,
            "max_video_size_bytes": 10 * _GB,
        },
    },
    "mastodon": {
        "display_name": "Mastodon",
        "char_limit": 500,
        "link_char_cost": 23,   # same shortening convention as Twitter
        "hashtag_limit": None,
        "hashtag_warn_above": 5,
        "links_clickable": True,
        "media": {
            "max_images": 4,
            "max_videos": 1,
            "images_and_video_exclusive": True,
            "allowed_image_formats": {"jpeg", "jpg", "png", "gif", "webp"},
            "allowed_video_formats": {"mp4", "mov", "webm"},
            "max_image_size_bytes": 10 * _MB,
            "max_video_size_bytes": 40 * _MB,
        },
    },
}

# Accepts "x", "twitter/x", "X/Twitter", etc. — all normalise to "twitter".
# Case-insensitive: normalise the key before lookup.
PLATFORM_ALIASES: dict[str, str] = {
    "twitter": "twitter",
    "x": "twitter",
    "twitter/x": "twitter",
    "x/twitter": "twitter",
    "linkedin": "linkedin",
    "instagram": "instagram",
    "facebook": "facebook",
    "mastodon": "mastodon",
}

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)
_CTA_PHRASES = frozenset({
    "apply", "book now", "buy", "check out", "click", "discover",
    "download", "enter", "find out", "get started", "join",
    "learn more", "link in bio", "order", "read more", "register",
    "shop", "sign up", "subscribe", "swipe", "tap", "try",
    "visit", "watch",
})

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_platform(raw: str) -> str | None:
    """Return canonical platform key, or None if not recognised."""
    return PLATFORM_ALIASES.get(raw.strip().lower())


def _count_chars(content: str, link_char_cost: int | None) -> tuple[int, list[str]]:
    """Return (character_count, detected_urls).

    When link_char_cost is set, each URL in content is replaced with
    exactly that many placeholder characters before counting.
    """
    detected = _URL_RE.findall(content)
    if link_char_cost is not None:
        working = _URL_RE.sub("x" * link_char_cost, content)
    else:
        working = content
    return len(working), detected


def _extract_hashtags(content: str, explicit: list[str]) -> list[str]:
    """Return sorted deduplicated list of hashtags from content + explicit list."""
    in_content = _HASHTAG_RE.findall(content)
    combined = {t.lower() for t in in_content}
    combined.update(t.lower().lstrip("#") for t in explicit)
    return sorted(combined)


def _has_cta(content: str, links: list[str]) -> bool:
    """Return True if content contains a link or a recognised CTA phrase."""
    if links:
        return True
    lower = content.lower()
    return any(phrase in lower for phrase in _CTA_PHRASES)


def _validate_media(
    media: list[dict],
    rules: dict,
    errors: list[dict],
    _warnings: list[dict],
) -> None:
    mr = rules["media"]
    display = rules["display_name"]

    images = [m for m in media if str(m.get("type", "")).lower() == "image"]
    videos = [m for m in media if str(m.get("type", "")).lower() == "video"]

    # Mixed image + video where not allowed
    if images and videos and mr["images_and_video_exclusive"]:
        errors.append({
            "code": "MEDIA_TYPE_CONFLICT",
            "message": f"Cannot mix images and video in the same post on {display}.",
        })
    else:
        if len(images) > mr["max_images"]:
            errors.append({
                "code": "MEDIA_COUNT_EXCEEDED",
                "message": f"{len(images)} images attached; {display} allows up to {mr['max_images']}.",
                "limit": mr["max_images"],
                "actual": len(images),
            })
        if len(videos) > mr["max_videos"]:
            errors.append({
                "code": "MEDIA_COUNT_EXCEEDED",
                "message": f"{len(videos)} videos attached; {display} allows up to {mr['max_videos']}.",
                "limit": mr["max_videos"],
                "actual": len(videos),
            })

    # Per-item format and size checks
    for item in media:
        kind = str(item.get("type", "")).lower()
        fmt = str(item.get("format", "")).lower().lstrip(".")
        size = item.get("size_bytes", 0)

        if kind == "image":
            allowed_formats = mr["allowed_image_formats"]
            max_size = mr["max_image_size_bytes"]
        elif kind == "video":
            allowed_formats = mr["allowed_video_formats"]
            max_size = mr["max_video_size_bytes"]
        else:
            errors.append({
                "code": "UNSUPPORTED_MEDIA_TYPE",
                "message": f"Unknown media type '{kind}'. Use 'image' or 'video'.",
            })
            continue

        if fmt and fmt not in allowed_formats:
            errors.append({
                "code": "UNSUPPORTED_MEDIA_TYPE",
                "message": (
                    f"Format '{fmt}' is not supported for {kind}s on {display}. "
                    f"Allowed: {', '.join(sorted(allowed_formats))}."
                ),
                "format": fmt,
            })

        if size and size > max_size:
            errors.append({
                "code": "MEDIA_SIZE_EXCEEDED",
                "message": (
                    f"{kind.capitalize()} size {size:,} bytes exceeds the {display} "
                    f"limit of {max_size:,} bytes ({max_size // _MB} MB)."
                ),
                "limit": max_size,
                "actual": size,
            })


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_post(data: dict) -> dict:
    """Validate a social media post draft against platform rules.

    Args:
        data: dict with keys:
            content  (str, required)  — post body text
            platform (str, required)  — "twitter"/"x"/"twitter/x", "linkedin",
                                        "instagram", "facebook", "mastodon"
            media    (list, optional) — list of {type, size_bytes, format}
            links    (list, optional) — URLs in the post (supplements auto-detection)
            hashtags (list, optional) — hashtags without # (supplements auto-detection)
            mentions (list, optional) — mentions without @

    Returns:
        dict with keys:
            valid           (bool)
            platform        (str)   — canonical key, e.g. "twitter" for input "x"
            character_count (int)
            errors          (list)  — non-empty means valid=False
            warnings        (list)  — non-blocking observations
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    content: str = data.get("content") or ""
    platform_raw: str = data.get("platform") or ""

    # --- Required: platform ---
    if not platform_raw:
        return {
            "valid": False,
            "platform": "",
            "character_count": 0,
            "errors": [{"code": "MISSING_REQUIRED_FIELD", "message": "Field 'platform' is required."}],
            "warnings": [],
        }

    platform_key = _normalize_platform(platform_raw)
    if platform_key is None:
        supported = ", ".join(sorted(PLATFORM_ALIASES.keys()))
        return {
            "valid": False,
            "platform": platform_raw,
            "character_count": 0,
            "errors": [{
                "code": "UNSUPPORTED_PLATFORM",
                "message": f"Platform '{platform_raw}' is not supported. Supported: {supported}.",
            }],
            "warnings": [],
        }

    rules = PLATFORM_RULES[platform_key]

    # --- Required: content ---
    if not content.strip():
        return {
            "valid": False,
            "platform": platform_key,
            "character_count": 0,
            "errors": [{"code": "EMPTY_CONTENT", "message": "Post content is empty or whitespace only."}],
            "warnings": [],
        }

    # --- Character count ---
    char_count, detected_links = _count_chars(content, rules["link_char_cost"])

    if char_count > rules["char_limit"]:
        errors.append({
            "code": "CHARACTER_LIMIT_EXCEEDED",
            "message": (
                f"Post is {char_count} characters; "
                f"{rules['display_name']} limit is {rules['char_limit']}."
            ),
            "limit": rules["char_limit"],
            "actual": char_count,
        })
    elif char_count > rules["char_limit"] * 0.8:
        warnings.append({
            "code": "LONG_CONTENT",
            "message": (
                f"Post is {char_count} characters, above 80% of "
                f"{rules['display_name']}'s {rules['char_limit']}-character limit."
            ),
        })

    # --- Hashtags ---
    explicit_hashtags: list[str] = data.get("hashtags") or []
    all_hashtags = _extract_hashtags(content, explicit_hashtags)
    hashtag_count = len(all_hashtags)

    if rules["hashtag_limit"] and hashtag_count > rules["hashtag_limit"]:
        errors.append({
            "code": "HASHTAG_LIMIT_EXCEEDED",
            "message": (
                f"{hashtag_count} hashtags detected; "
                f"{rules['display_name']} limit is {rules['hashtag_limit']}."
            ),
            "limit": rules["hashtag_limit"],
            "actual": hashtag_count,
        })
    elif rules["hashtag_warn_above"] and hashtag_count > rules["hashtag_warn_above"]:
        warnings.append({
            "code": "HIGH_HASHTAG_COUNT",
            "message": (
                f"{hashtag_count} hashtags detected. Engagement typically drops "
                f"above {rules['hashtag_warn_above']} on {rules['display_name']}."
            ),
        })

    # --- Links ---
    explicit_links: list[str] = data.get("links") or []
    all_links = list({*detected_links, *explicit_links})

    for link in all_links:
        try:
            parsed = urlparse(link)
            if parsed.scheme not in ("http", "https"):
                errors.append({
                    "code": "INVALID_LINK",
                    "message": (
                        f"Link '{link}' uses disallowed protocol '{parsed.scheme}'. "
                        "Only http and https are permitted."
                    ),
                    "link": link,
                })
        except Exception:
            errors.append({
                "code": "INVALID_LINK",
                "message": f"Link '{link}' is malformed.",
                "link": link,
            })

    if not rules["links_clickable"] and all_links:
        warnings.append({
            "code": "LINK_NOT_ALLOWED",
            "message": (
                f"Links in {rules['display_name']} captions are not clickable. "
                "Consider using 'link in bio' instead."
            ),
        })

    # --- Media ---
    media: list[dict] = data.get("media") or []
    if media:
        _validate_media(media, rules, errors, warnings)

    # --- NO_CTA (warning only, never an error) ---
    if not _has_cta(content, all_links):
        warnings.append({
            "code": "NO_CTA",
            "message": "No call-to-action phrase or link detected. Consider adding one to improve engagement.",
        })

    return {
        "valid": len(errors) == 0,
        "platform": platform_key,
        "character_count": char_count,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        result = {
            "valid": False,
            "platform": "",
            "character_count": 0,
            "errors": [{"code": "INVALID_INPUT", "message": f"Invalid JSON: {exc}"}],
            "warnings": [],
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)

    result = validate_post(data)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    _main()
