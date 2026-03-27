"""CLI entry point for publish_to_platform.

Usage:
    echo '{"platform": "twitter", "content": "Hello!"}' | python -m tools.publish_pipeline

    # platform from flag — JSON needs only content, hashtags, etc.
    echo '{"content": "Hello!"}' | python -m tools.publish_pipeline --platform twitter

    # post same content to multiple platforms
    for platform in twitter linkedin mastodon; do
        cat post.json | python -m tools.publish_pipeline --platform "$platform"
    done

    # with Twitter credentials in environment
    TWITTER_API_KEY=... TWITTER_API_SECRET=... \\
    TWITTER_ACCESS_TOKEN=... TWITTER_ACCESS_SECRET=... \\
    python -m tools.publish_pipeline --platform twitter < post.json

Reads a JSON post payload from stdin.  Credentials are resolved from
environment variables by each platform adapter (credentials=None path).

--platform overrides the 'platform' key in the JSON payload when both
are present.  If neither provides a platform the pipeline returns its
normal MISSING_REQUIRED_FIELD validation error.

Required env vars per platform:
  twitter:   TWITTER_API_KEY, TWITTER_API_SECRET,
             TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET
  linkedin:  LINKEDIN_ACCESS_TOKEN
  instagram: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID
  facebook:  FACEBOOK_PAGE_ACCESS_TOKEN, FACEBOOK_PAGE_ID
  mastodon:  MASTODON_ACCESS_TOKEN, MASTODON_INSTANCE_URL

Exit codes:
  0  success — post delivered, result["success"] is True
  1  failure — validation error, upload error, adapter error, or bad input
"""

import argparse
import json
import sys

from .publish_pipeline import publish_to_platform


def _main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tools.publish_pipeline",
        description="Publish a post payload to a social platform.",
    )
    parser.add_argument(
        "--platform",
        metavar="PLATFORM",
        help=(
            "Target platform: twitter, linkedin, instagram, facebook, mastodon. "
            "Overrides the 'platform' key in the JSON payload when both are present."
        ),
    )
    args = parser.parse_args()

    try:
        post = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        result = {
            "success":           False,
            "platform":          "",
            "post_id":           None,
            "character_count":   None,
            "validation_errors": [],
            "media_results":     [],
            "errors":            [{"code": "INVALID_INPUT", "message": f"Invalid JSON: {exc}"}],
            "warnings":          [],
        }
        print(json.dumps(result, indent=2))
        sys.exit(1)

    if args.platform:
        if isinstance(post, dict):
            post["platform"] = args.platform

    # credentials=None → each platform adapter reads its required keys from os.environ
    result = publish_to_platform(post)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    _main()
