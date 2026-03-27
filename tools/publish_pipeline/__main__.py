"""CLI entry point for publish_to_platform.

Usage:
    echo '{"content": "Hello!"}' | python -m tools.publish_pipeline --platform twitter

    # credentials loaded from .env in the working directory automatically
    cat post.json | python -m tools.publish_pipeline --platform twitter

    # explicit .env file path
    cat post.json | python -m tools.publish_pipeline --platform twitter --env-file ~/secrets/twitter.env

    # post same content to multiple platforms
    for platform in twitter linkedin mastodon; do
        cat post.json | python -m tools.publish_pipeline --platform "$platform"
    done

Reads a JSON post payload from stdin.  Credentials are loaded from a .env
file (default: .env in the working directory) and then from environment
variables.  Real environment variables always win over .env values.

.env file format:
    TWITTER_API_KEY=abc123
    TWITTER_API_SECRET=xyz789   # inline comments are stripped
    # full-line comments and blank lines are ignored
    TWITTER_ACCESS_TOKEN="token with spaces"   # quoted values are unquoted

Required credentials per platform:
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
import os
import sys

from .publish_pipeline import publish_to_platform


# ---------------------------------------------------------------------------
# .env parser
# ---------------------------------------------------------------------------

def _load_env_file(path: str) -> dict[str, str]:
    """Parse a .env file into a dict of KEY=value pairs.

    Rules:
      - Blank lines and lines whose first non-whitespace character is '#' are
        skipped.
      - Lines without '=' are skipped.
      - Keys and values are stripped of leading/trailing whitespace.
      - Values wrapped in matching single or double quotes are unquoted.
      - Inline comments (text after an unquoted ' #') are NOT stripped — keeps
        the parser simple and avoids surprising values with '#' in them.
      - Returns an empty dict silently if the file does not exist.

    Raises:
      OSError: if the file exists but cannot be read (e.g. permission denied).
               Raised only when the caller explicitly requested a specific path
               via --env-file; the default .env fallback swallows FileNotFoundError.
    """
    result: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key:
                result[key] = value
    return result


def _apply_env_file(path: str, *, required: bool = False) -> None:
    """Load a .env file and populate os.environ for keys not already set.

    Args:
        path:     Path to the .env file.
        required: If True, raise OSError when the file does not exist.
                  If False (default), silently skip a missing file.
    """
    try:
        pairs = _load_env_file(path)
    except FileNotFoundError:
        if required:
            raise
        return
    for key, value in pairs.items():
        if key not in os.environ:
            os.environ[key] = value


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

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
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        dest="env_file",
        help=(
            "Path to a .env file containing platform credentials. "
            "Defaults to '.env' in the current working directory if present. "
            "Real environment variables always override values from the file."
        ),
    )
    args = parser.parse_args()

    # Load credentials: .env file first, real env vars win.
    if args.env_file:
        try:
            _apply_env_file(args.env_file, required=True)
        except OSError as exc:
            result = {
                "success":           False,
                "platform":          "",
                "post_id":           None,
                "character_count":   None,
                "validation_errors": [],
                "media_results":     [],
                "errors":            [{"code": "ENV_FILE_ERROR",
                                       "message": f"Cannot read env file '{args.env_file}': {exc}"}],
                "warnings":          [],
            }
            print(json.dumps(result, indent=2))
            sys.exit(1)
    else:
        _apply_env_file(".env")  # silent no-op if absent

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
