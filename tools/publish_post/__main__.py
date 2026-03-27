"""Scheduler runner — process due queue entries end to end.

Reads the queue store, finds all entries whose slot is <= now, and
delivers each one through the full publish pipeline (validate → upload
media → platform adapter → Twitter / etc.).  Writes results back to
the queue store, advances the approval state machine, and appends to
the publish history log.

Credentials are loaded from a .env file (default: .env in the working
directory) then from real environment variables.  Real env vars always
win over .env values.

Usage:
    # Process all due entries (credentials from .env or environment)
    python -m tools.publish_post

    # Preview — show what would run without delivering
    python -m tools.publish_post --dry-run

    # Re-attempt entries that previously failed
    python -m tools.publish_post --retry-failed

    # Explicit credentials file
    python -m tools.publish_post --env-file ~/secrets/twitter.env

    # Custom store paths
    python -m tools.publish_post --queue-file data/queue.json \\
                                  --approval-file data/approval_states.json \\
                                  --log-file data/publish_log.jsonl

Exit codes:
    0  success — publish_post ran without a system error (individual post
                 failures are reported in the JSON result, not the exit code)
    1  system error — queue store unreadable, bad --env-file path, etc.

Required credentials per platform:
  twitter:   TWITTER_API_KEY, TWITTER_API_SECRET,
             TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET
  linkedin:  LINKEDIN_ACCESS_TOKEN
  instagram: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID
  facebook:  FACEBOOK_PAGE_ACCESS_TOKEN, FACEBOOK_PAGE_ID
  mastodon:  MASTODON_ACCESS_TOKEN, MASTODON_INSTANCE_URL
"""

import argparse
import json
import os
import sys

from .publish_post import publish_post, get_pipeline_adapter


# ---------------------------------------------------------------------------
# .env helpers  (identical pattern to tools/publish_pipeline/__main__.py)
# ---------------------------------------------------------------------------

def _load_env_file(path: str) -> dict[str, str]:
    """Parse a .env file into a dict of KEY=value pairs.

    Blank lines and lines starting with '#' are skipped.  Lines without '='
    are skipped.  Keys and values are stripped.  Values wrapped in matching
    quotes are unquoted.

    Raises OSError if the file exists but cannot be read.
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
    """Load a .env file and set os.environ for keys not already set."""
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
        prog="python -m tools.publish_post",
        description=(
            "Process due queue entries through the full publish pipeline. "
            "Delivers each entry whose slot is <= now to its target platform."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help=(
            "Select due entries but do not deliver them.  Useful for "
            "previewing what would run.  No credentials are required."
        ),
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        default=False,
        dest="retry_failed",
        help="Re-attempt entries whose status is 'failed'.",
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        dest="env_file",
        help=(
            "Path to a .env file containing platform credentials.  "
            "Defaults to '.env' in the current working directory if present.  "
            "Real environment variables always override .env values."
        ),
    )
    parser.add_argument(
        "--queue-file",
        metavar="PATH",
        dest="queue_file",
        default="data/queue.json",
        help="Path to the queue store.  Defaults to data/queue.json.",
    )
    parser.add_argument(
        "--approval-file",
        metavar="PATH",
        dest="approval_file",
        default="data/approval_states.json",
        help=(
            "Path to the approval state store.  "
            "Defaults to data/approval_states.json."
        ),
    )
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        dest="log_file",
        default="data/publish_log.jsonl",
        help=(
            "Path to the publish history log (JSONL).  "
            "Defaults to data/publish_log.jsonl.  "
            "Pass an empty string to suppress logging."
        ),
    )
    args = parser.parse_args()

    # Load credentials: .env file first, real env vars always win.
    if args.env_file:
        try:
            _apply_env_file(args.env_file, required=True)
        except OSError as exc:
            result = {
                "success":    False,
                "error_code": "ENV_FILE_ERROR",
                "message":    f"Cannot read env file '{args.env_file}': {exc}",
            }
            print(json.dumps(result, indent=2))
            sys.exit(1)
    else:
        _apply_env_file(".env")  # silent no-op if absent

    data = {
        "queue_store_path":    args.queue_file,
        "approval_store_path": args.approval_file,
        "log_path":            args.log_file or None,
        "dry_run":             args.dry_run,
        "retry_failed":        args.retry_failed,
    }

    # credentials=None → each platform adapter reads from os.environ at call time
    result = publish_post(data, _adapter=get_pipeline_adapter())
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    _main()
