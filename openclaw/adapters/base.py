from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PostResult:
    platform: str
    post_id: str
    url: str | None = None


class SocialAdapter(ABC):
    """Minimal contract every platform adapter must satisfy."""

    platform: str

    @abstractmethod
    def post_text(self, text: str) -> PostResult: ...
