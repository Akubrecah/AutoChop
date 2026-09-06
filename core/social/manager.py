"""
AutoChop AI Studio - Multi-Platform Social Media Manager
Coordinates validation, formatting, publishing, and 1-click platform kit ZIP packaging.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Any

from autochop.core.social.base import BaseSocialConnector, PlatformPostPayload, PublishResult
from autochop.core.social.instagram import InstagramReelsConnector
from autochop.core.social.linkedin import LinkedInConnector
from autochop.core.social.tiktok import TikTokConnector
from autochop.core.social.twitter import TwitterConnector
from autochop.core.social.youtube_shorts import YouTubeShortsConnector

logger = logging.getLogger("autochop.social.manager")


class SocialPublishManager:
    """Central registry and coordinator for social media connectors."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseSocialConnector] = {
            "YouTube Shorts": YouTubeShortsConnector(),
            "TikTok": TikTokConnector(),
            "Instagram Reels": InstagramReelsConnector(),
            "X (Twitter)": TwitterConnector(),
            "LinkedIn": LinkedInConnector(),
        }

    @property
    def supported_platforms(self) -> list[str]:
        return list(self._connectors.keys())

    def get_connector(self, platform_name: str) -> BaseSocialConnector | None:
        return self._connectors.get(platform_name)

    def format_all_platforms(
        self,
        title: str,
        transcript: str,
        hook: str,
        tags: list[str],
        **kwargs: Any,
    ) -> dict[str, PlatformPostPayload]:
        """Generates platform-tailored metadata for all supported social networks."""
        results: dict[str, PlatformPostPayload] = {}
        for name, connector in self._connectors.items():
            try:
                payload = connector.format_payload(title, transcript, hook, tags, **kwargs)
                results[name] = payload
            except Exception as exc:
                logger.error(f"Error formatting payload for {name}: {exc}")
        return results

    def validate_for_platforms(
        self,
        platforms: list[str],
        video_path: str | Path,
    ) -> dict[str, tuple[bool, str]]:
        """Checks if the video meets the technical criteria for specified platforms."""
        results: dict[str, tuple[bool, str]] = {}
        for p in platforms:
            connector = self._connectors.get(p)
            if connector:
                results[p] = connector.validate_video(video_path)
            else:
                results[p] = (False, f"Unsupported platform: {p}")
        return results

    def publish_to_platforms(
        self,
        platforms: list[str],
        payloads: dict[str, PlatformPostPayload],
        video_path: str | Path,
        **kwargs: Any,
    ) -> list[PublishResult]:
        """Dispatches video to selected platforms."""
        results: list[PublishResult] = []
        for p in platforms:
            connector = self._connectors.get(p)
            payload = payloads.get(p)
            if not connector:
                results.append(
                    PublishResult(
                        success=False,
                        platform=p,
                        message=f"Unknown platform connector: {p}",
                    )
                )
                continue
            if not payload:
                # Format on the fly if not provided
                payload = connector.format_payload("AutoChop Short", "", "", [])

            try:
                res = connector.publish(payload, video_path, **kwargs)
                results.append(res)
            except Exception as exc:
                logger.error(f"Exception while publishing to {p}: {exc}")
                results.append(
                    PublishResult(
                        success=False,
                        platform=p,
                        message=f"Execution error: {exc}",
                        error_details=str(exc),
                    )
                )
        return results

    def export_platform_kits_zip(
        self,
        payloads: dict[str, PlatformPostPayload],
        video_path: str | Path,
        output_zip_path: str | Path,
    ) -> Path:
        """
        Creates a creator-ready ZIP package containing the vertical video and
        tailored text files with copy and hashtags for each social media platform.
        """
        video = Path(video_path).resolve()
        out_zip = Path(output_zip_path).resolve()
        out_zip.parent.mkdir(parents=True, exist_ok=True)

        guide_lines = [
            "# 📱 AutoChop Social Publishing Kit",
            "",
            "This bundle contains your vertical 9:16 video formatted and ready for posting,",
            "along with platform-tailored copy optimized for each app's algorithm.",
            "",
            "## 📁 Included Files:",
            f"- `{video.name}`: Your 9:16 vertical short with mobile safe-zone captions.",
        ]

        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 1. Add video
            if video.exists():
                zf.write(video, arcname=video.name)

            # 2. Add tailored text files for each platform
            filename_map = {
                "YouTube Shorts": "youtube_shorts_copy.txt",
                "TikTok": "tiktok_caption.txt",
                "Instagram Reels": "instagram_reels_caption.txt",
                "X (Twitter)": "twitter_post.txt",
                "LinkedIn": "linkedin_post.txt",
            }

            for plat_name, payload in payloads.items():
                fname = filename_map.get(plat_name, f"{plat_name.lower().replace(' ', '_')}_copy.txt")
                tag_str = " ".join(f"#{t.lstrip('#')}" for t in payload.tags)
                content = (
                    f"=== {plat_name.upper()} POSTING PACK ===\n\n"
                    f"TITLE / HEADLINE:\n{payload.title}\n\n"
                    f"CAPTION / POST BODY:\n{payload.body}\n\n"
                    f"HASHTAGS:\n{tag_str}\n\n"
                    f"FULL READY-TO-PASTE TEXT ({len(payload.full_post_text)} / {payload.char_limit} chars):\n"
                    f"----------------------------------------\n"
                    f"{payload.full_post_text}\n"
                    f"----------------------------------------\n"
                )
                zf.writestr(fname, content)
                guide_lines.append(f"- `{fname}`: Tailored copy for {plat_name}")

            guide_lines.extend(
                [
                    "",
                    "## 🚀 Quick Posting Instructions:",
                    "1. Transfer the `.mp4` video to your mobile device or open via desktop web.",
                    "2. Open the matching text file for your target platform.",
                    "3. Copy the 'FULL READY-TO-PASTE TEXT' section and paste directly into the app.",
                    "4. Hit Publish!",
                ]
            )
            zf.writestr("README_POSTING_GUIDE.md", "\n".join(guide_lines))

        logger.info(f"Successfully generated social publishing kit ZIP: {out_zip}")
        return out_zip
