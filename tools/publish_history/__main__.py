"""CLI entry point for publish_history.

Reads publish log entries and prints them as a JSON array to stdout.

Usage:
    python -m tools.publish_history
    python -m tools.publish_history --limit 20
    python -m tools.publish_history --log-file logs/prod.jsonl
    python -m tools.publish_history --failed-only
    python -m tools.publish_history --failed-only --limit 5

Options:
    --limit N          Return only the last N entries.
    --log-file PATH    Path to the JSONL log file.
                       Defaults to data/publish_log.jsonl.
    --failed-only      Only entries where success is false.

Exit codes:
    0  always (read-only operation)
"""

import argparse
import json
import sys

from .publish_history import read_log, DEFAULT_LOG_PATH


def _main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m tools.publish_history",
        description="Print publish history log entries as a JSON array.",
    )
    parser.add_argument(
        "--limit",
        metavar="N",
        type=int,
        default=None,
        help="Return only the last N entries.",
    )
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        dest="log_file",
        default=DEFAULT_LOG_PATH,
        help=f"Path to the JSONL log file. Defaults to {DEFAULT_LOG_PATH}.",
    )
    parser.add_argument(
        "--failed-only",
        action="store_true",
        default=False,
        dest="failed_only",
        help="Only print entries where success is false.",
    )
    args = parser.parse_args()

    entries = read_log(log_path=args.log_file, limit=args.limit)

    if args.failed_only:
        entries = [e for e in entries if not e.get("success")]

    print(json.dumps(entries, indent=2))


if __name__ == "__main__":
    _main()
