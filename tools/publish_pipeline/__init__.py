"""publish_pipeline — end-to-end publish pipeline vertical slice.

Takes a post payload (content + optional media), validates it, uploads any
media attachments, resolves a platform adapter, and delivers the post.
Returns one structured result covering every stage.

Public API
----------
  publish_to_platform(post, *, credentials=None, policy_path=None, _adapter=None) -> dict
      Validate → upload media → publish post to one target platform.

  validate_pipeline_result(result) -> None
      Shape-check a publish_to_platform result dict.  Raises ValueError on
      any structural violation.

Usage
-----
  from tools.publish_pipeline import publish_to_platform

  result = publish_to_platform(
      {
          "platform": "twitter",
          "content":  "Hello from OpenClaw!",
      },
      credentials={"TWITTER_API_KEY": "...", ...},
  )
  if result["success"]:
      print("Posted:", result["post_id"])
  else:
      print("Failed:", result["errors"] or result["validation_errors"])
"""

from .publish_pipeline import (
    publish_to_platform,
    validate_pipeline_result,
)

__all__ = [
    "publish_to_platform",
    "validate_pipeline_result",
]
