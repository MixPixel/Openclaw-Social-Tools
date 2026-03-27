"""Openclaw CLI entry point.

Commands:
  openclaw post "text"    – publish immediately to LinkedIn
  openclaw queue "text"   – add to the queue for later delivery
  openclaw run            – flush all pending queued posts
"""

import argparse
import sys

from .adapters.linkedin import LinkedInAdapter
from .pipeline import publish
from . import queue as q


def _read_text(args_text: str | None) -> str:
    if args_text:
        return args_text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    print("Error: provide post text as an argument or via stdin.", file=sys.stderr)
    sys.exit(1)


def cmd_post(args: argparse.Namespace) -> None:
    text = _read_text(args.text)
    adapter = LinkedInAdapter()
    result = publish(adapter, text)
    print(f"Posted to {result.platform}: {result.post_id}")
    if result.url:
        print(result.url)


def cmd_queue(args: argparse.Namespace) -> None:
    text = _read_text(args.text)
    job_id = q.enqueue("linkedin", text)
    print(f"Queued job {job_id}")


def cmd_run(_args: argparse.Namespace) -> None:
    adapter = LinkedInAdapter()
    jobs = q.list_pending()
    if not jobs:
        print("No pending jobs.")
        return
    for job in jobs:
        try:
            result = publish(adapter, job["text"])
            q.mark_done(job["id"], result.post_id)
            print(f"[done]   {job['id']} -> {result.post_id}")
        except Exception as exc:  # noqa: BLE001
            q.mark_failed(job["id"], str(exc))
            print(f"[failed] {job['id']}: {exc}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openclaw",
        description="Openclaw Social Tools – LinkedIn text posting",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_post = sub.add_parser("post", help="Post text to LinkedIn immediately")
    p_post.add_argument("text", nargs="?", help="Post text (or pipe via stdin)")
    p_post.set_defaults(func=cmd_post)

    p_queue = sub.add_parser("queue", help="Add a text post to the queue")
    p_queue.add_argument("text", nargs="?", help="Post text (or pipe via stdin)")
    p_queue.set_defaults(func=cmd_queue)

    p_run = sub.add_parser("run", help="Flush all pending queued posts")
    p_run.set_defaults(func=cmd_run)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
