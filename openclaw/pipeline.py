"""Thin publish pipeline: validate then delegate to the adapter."""

from .adapters.base import PostResult, SocialAdapter

_LINKEDIN_CHAR_LIMIT = 3000


def publish(adapter: SocialAdapter, text: str) -> PostResult:
    """Validate *text* and post it via *adapter*.

    Raises:
        ValueError: if text is empty or exceeds the platform character limit.
    """
    text = text.strip()
    if not text:
        raise ValueError("Post text must not be empty.")
    if adapter.platform == "linkedin" and len(text) > _LINKEDIN_CHAR_LIMIT:
        raise ValueError(
            f"Post text exceeds LinkedIn's {_LINKEDIN_CHAR_LIMIT}-character limit "
            f"({len(text)} chars)."
        )
    return adapter.post_text(text)
