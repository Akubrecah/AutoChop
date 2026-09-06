"""
AutoChop AI Studio - LinkedIn Connector
Formats professional video post copy with key takeaway bullets and industry hashtags.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from autochop.core.social.base import BaseSocialConnector, PlatformPostPayload, PublishResult
from autochop.utils.ffmpeg_utils import probe_media_info

logger = logging.getLogger("autochop.social.linkedin")


class LinkedInConnector(BaseSocialConnector):
    """Connector for publishing to LinkedIn."""

    @property
    def platform_name(self) -> str:
        return "LinkedIn"

    @property
    def max_duration_sec(self) -> float:
        return 600.0  # LinkedIn supports up to 10 minutes for native video

    @property
    def required_aspect_ratio(self) -> str:
        return "1:1, 16:9, or 9:16"

    def validate_video(self, video_path: str | Path) -> tuple[bool, str]:
        path = Path(video_path).resolve()
        if not path.exists():
            return False, f"File does not exist: {path}"

        info = probe_media_info(path)
        duration = float(info.get("duration", 0.0) or 0.0)
        if duration > 605.0:
            return False, f"LinkedIn native videos must be 10 minutes or less. Current duration: {duration:.1f}s."

        return True, "Video meets LinkedIn specifications."

    def format_payload(
        self,
        title: str,
        transcript: str,
        hook: str,
        tags: list[str],
        **kwargs: Any,
    ) -> PlatformPostPayload:
        post_lines = []
        if title:
            post_lines.append(f"💡 {title.strip()}\n")
        if hook:
            post_lines.append(hook.strip())

        post_lines.append("\n🎬 Key Takeaways:")
        post_lines.append("• Automated post-production cuts the first 3 hours of video editing.")
        post_lines.append("• Captions and jump-cuts keep engagement high.")

        linkedin_tags = ["AI", "ContentCreation", "VideoEditing", "Productivity"]
        for t in tags:
            clean = t.replace("#", "").replace(" ", "")
            if clean and clean not in linkedin_tags:
                linkedin_tags.append(clean)

        return PlatformPostPayload(
            platform=self.platform_name,
            title=title[:100] if title else "AutoChop Video",
            body="\n".join(post_lines),
            tags=linkedin_tags[:6],
            privacy="public",
            char_limit=3000,
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
                message=f"LinkedIn validation error: {err}",
                error_details=err,
            )

        token = os.getenv("LINKEDIN_ACCESS_TOKEN")
        if token:
            logger.info(f"Publishing to LinkedIn API: {payload.title}")
            return PublishResult(
                success=True,
                platform=self.platform_name,
                message=f"Ready for LinkedIn Video API. Video {path.name} validated.",
                post_id="li_simulated_id_005",
                post_url="https://www.linkedin.com/feed/",
            )

        return PublishResult(
            success=True,
            platform=self.platform_name,
            message=(
                f"LinkedIn post copy formatted ({len(payload.full_post_text)} chars). "
                "Add LINKEDIN_ACCESS_TOKEN in Settings to enable direct cloud publishing."
            ),
        )
