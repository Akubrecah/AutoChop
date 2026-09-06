"""
AutoChop AI Studio - Base Social Connector & Schemas
Defines standard interfaces and payload structures for social platform integration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PlatformPostPayload:
    """Standardized metadata payload tailored to a specific social platform."""
    platform: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    privacy: str = "public"  # "public", "unlisted", "private"
    char_limit: int = 2200
    custom_fields: dict[str, Any] = field(default_factory=dict)

    @property
    def full_post_text(self) -> str:
        """Returns formatted caption with tags included."""
        tags_str = " ".join(f"#{t.lstrip('#')}" for t in self.tags)
        if self.body and tags_str:
            return f"{self.body}\n\n{tags_str}".strip()
        return (self.body or tags_str).strip()

    @property
    def is_within_char_limit(self) -> bool:
        return len(self.full_post_text) <= self.char_limit


@dataclass
class PublishResult:
    """Result of an automated or manual social media publication attempt."""
    success: bool
    platform: str
    message: str
    post_id: str | None = None
    post_url: str | None = None
    error_details: str | None = None


class BaseSocialConnector(ABC):
    """Abstract base class for all social media platform connectors."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Returns the human-readable platform name (e.g. 'YouTube Shorts')."""
        pass

    @property
    @abstractmethod
    def max_duration_sec(self) -> float:
        """Maximum supported video duration in seconds."""
        pass

    @property
    @abstractmethod
    def required_aspect_ratio(self) -> str:
        """Required or recommended aspect ratio string (e.g. '9:16')."""
        pass

    @abstractmethod
    def validate_video(self, video_path: str | Path) -> tuple[bool, str]:
        """Checks if the video meets the platform's format, duration, and resolution rules."""
        pass

    @abstractmethod
    def format_payload(
        self,
        title: str,
        transcript: str,
        hook: str,
        tags: list[str],
        **kwargs: Any,
    ) -> PlatformPostPayload:
        """Tailors title, description, and hashtags to the platform's specific limits."""
        pass

    @abstractmethod
    def publish(
        self,
        payload: PlatformPostPayload,
        video_path: str | Path,
        **kwargs: Any,
    ) -> PublishResult:
        """Dispatches video and payload to the platform API or returns mock/ready-to-post status."""
        pass
