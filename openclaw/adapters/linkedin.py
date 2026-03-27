"""LinkedIn text-post adapter using the UGC Posts v2 API.

Required env vars:
  LINKEDIN_ACCESS_TOKEN  – OAuth 2.0 bearer token (scope: w_member_social)
  LINKEDIN_AUTHOR_URN    – e.g. urn:li:person:AbCdEfGhIj  (your LinkedIn member ID)

The access token must be obtained externally via LinkedIn's OAuth 2.0 flow.
Tokens expire after 60 days by default; refresh before calling post_text.
"""

import os

import requests

from .base import PostResult, SocialAdapter

_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"


class LinkedInAdapter(SocialAdapter):
    platform = "linkedin"

    def __init__(
        self,
        access_token: str | None = None,
        author_urn: str | None = None,
    ) -> None:
        self.access_token = access_token or os.environ["LINKEDIN_ACCESS_TOKEN"]
        self.author_urn = author_urn or os.environ["LINKEDIN_AUTHOR_URN"]

    def post_text(self, text: str) -> PostResult:
        payload = {
            "author": self.author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }
        response = requests.post(
            _UGC_POSTS_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            timeout=15,
        )
        response.raise_for_status()
        post_id = response.headers.get("x-restli-id", "")
        url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else None
        return PostResult(platform="linkedin", post_id=post_id, url=url)
