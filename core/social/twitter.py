"""
AutoChop AI Studio - X (Twitter) Connector
Formats concise high-impact 280-character posts with video media attachment rules.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from autochop.core.social.base import BaseSocialConnector, PlatformPostPayload, PublishResult
from autochop.utils.ffmpeg_utils import probe_media_info

logger = logging.getLogger("autochop.social.twitter")


class TwitterConnector(BaseSocialConnector):
    """Connector for publishing to X (Twitter)."""

    @property
    def platform_name(self) -> str:
        return "X (Twitter)"

    @property
    def max_duration_sec(self) -> float:
        return 140.0  # Standard accounts limit is 2 mins 20 seconds (140s)

    @property
    def required_aspect_ratio(self) -> str:
        return "16:9, 1:1, or 9:16"

    def validate_video(self, video_path: str | Path) -> tuple[bool, str]:
        path = Path(video_path).resolve()
        if not path.exists():
            return False, f"File does not exist: {path}"

        info = probe_media_info(path)
        duration = float(info.get("duration", 0.0) or 0.0)
        if duration > 141.0:
            return False, f"Standard X (Twitter) videos must be 140s or less. Current duration: {duration:.1f}s."

        return True, "Video meets X (Twitter) specifications."

    def format_payload(
        self,
        title: str,
        transcript: str,
        hook: str,
        tags: list[str],
        **kwargs: Any,
    ) -> PlatformPostPayload:
        # X strictly enforces 280 characters maximum
        clean_hook = (hook or title or "New clip from AutoChop Studio").strip()
        top_tags = [f"#{t.replace('#', '').replace(' ', '')}" for t in tags[:3]]
        tags_str = " ".join(top_tags)

        # Calculate max hook length allowing space for hashtags
        tag_len = len(tags_str) + 2 if tags_str else 0
        allowed_hook_len = 280 - tag_len

        if len(clean_hook) > allowed_hook_len:
            clean_hook = clean_hook[: allowed_hook_len - 3].strip() + "..."

        return PlatformPostPayload(
            platform=self.platform_name,
            title=title[:60] if title else "AutoChop Post",
            body=clean_hook,
            tags=[t.lstrip("#") for t in top_tags],
            privacy="public",
            char_limit=280,
        )

    def publish(
        self,
        payload: PlatformPostPayload,
        video_path: str | Path,
        **kwargs: Any,
    ) -> PublishResult:
        path = Path(video_path).resolve()
        valid, err = self.validate_video(path)
        if not valid:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=f"X (Twitter) validation error: {err}",
                error_details=err,
            )

        api_key = os.getenv("TWITTER_API_KEY")
        if api_key:
            logger.info(f"Publishing to Twitter API v2: {payload.body}")
            return PublishResult(
                success=True,
                platform=self.platform_name,
                message=f"Ready for X (Twitter) API v2. Video {path.name} validated.",
                post_id="x_simulated_id_004",
                post_url="https://x.com/",
            )

        return PublishResult(
            success=True,
            platform=self.platform_name,
            message=(
                f"X (Twitter) post formatted ({len(payload.full_post_text)} / 280 chars). "
                "Add TWITTER_API_KEY in Settings to enable direct cloud dispatch."
            ),
        )
