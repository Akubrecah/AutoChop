"""
AutoChop AI Studio - TikTok Connector
Validates 9:16 vertical video and formats high-engagement captions and hashtags
for TikTok Content Posting API v2.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from autochop.core.social.base import BaseSocialConnector, PlatformPostPayload, PublishResult
from autochop.utils.ffmpeg_utils import probe_media_info
from autochop.utils.http_client import http_post, http_put

logger = logging.getLogger("autochop.social.tiktok")


class TikTokConnector(BaseSocialConnector):
    """Connector for publishing to TikTok."""

    @property
    def platform_name(self) -> str:
        return "TikTok"

    @property
    def max_duration_sec(self) -> float:
        return 600.0  # TikTok supports up to 10 mins, though 15s-60s performs best

    @property
    def required_aspect_ratio(self) -> str:
        return "9:16 (Strictly Recommended: 1080x1920)"

    def validate_video(self, video_path: str | Path) -> tuple[bool, str]:
        path = Path(video_path).resolve()
        if not path.exists():
            return False, f"File does not exist: {path}"

        info = probe_media_info(path)
        width = info.get("width")
        height = info.get("height")
        if width and height:
            ratio = width / height
            # 9/16 is approx 0.5625
            if ratio > 0.8:
                return (
                    False,
                    f"TikTok requires vertical video (9:16). Current ratio is {ratio:.2f}. "
                    "Use the AutoChop Shorts generator to reframe into 9:16.",
                )

        return True, "Video meets TikTok 9:16 specifications."

    def format_payload(
        self,
        title: str,
        transcript: str,
        hook: str,
        tags: list[str],
        **kwargs: Any,
    ) -> PlatformPostPayload:
        # TikTok combines caption and hashtags into a single 2200 character string
        main_text = (hook or title or "").strip()
        if len(main_text) > 1800:
            main_text = main_text[:1797].strip() + "..."

        tiktok_tags = ["fyp", "viral", "foryou", "trending"]
        for t in tags:
            clean = t.replace("#", "").replace(" ", "").lower()
            if clean and clean not in tiktok_tags:
                tiktok_tags.append(clean)

        return PlatformPostPayload(
            platform=self.platform_name,
            title=title[:100] if title else "AutoChop TikTok",
            body=main_text,
            tags=tiktok_tags[:10],
            privacy=kwargs.get("privacy", "public"),
            char_limit=2200,
            custom_fields={"disable_comments": False, "disable_duet": False, "disable_stitch": False},
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
                message=f"TikTok validation error: {err}",
                error_details=err,
            )

        token = os.getenv("TIKTOK_ACCESS_TOKEN")
        if not token:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=(
                    "Action required: TIKTOK_ACCESS_TOKEN is required for direct TikTok publishing. "
                    "Please configure it in Settings."
                ),
                error_details="Missing TIKTOK_ACCESS_TOKEN",
            )

        logger.info(f"Initiating TikTok Content Posting API v2 upload for: {payload.title}")
        try:
            file_size = path.stat().st_size
            init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
            init_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            }
            privacy_map = {
                "public": "PUBLIC_TO_EVERYONE",
                "private": "SELF_ONLY",
                "friends": "MUTUAL_FOLLOW_FRIENDS",
            }
            tiktok_privacy = privacy_map.get((payload.privacy or "public").lower(), "PUBLIC_TO_EVERYONE")

            init_body = {
                "post_info": {
                    "title": payload.full_post_text[:2200],
                    "privacy_level": tiktok_privacy,
                    "disable_duet": payload.custom_fields.get("disable_duet", False),
                    "disable_comment": payload.custom_fields.get("disable_comments", False),
                    "disable_stitch": payload.custom_fields.get("disable_stitch", False),
                    "video_cover_timestamp_ms": 1000,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": file_size,
                    "chunk_size": file_size,
                    "total_chunk_count": 1,
                },
            }

            # Step 1: Initialize publish request
            init_resp = http_post(init_url, headers=init_headers, json_data=init_body, timeout=30)
            if init_resp.status_code != 200:
                err_msg = init_resp.text
                try:
                    err_msg = init_resp.json().get("error", {}).get("message", err_msg)
                except Exception:
                    pass
                logger.error(f"TikTok post init failed ({init_resp.status_code}): {err_msg}")
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"TikTok post init failed ({init_resp.status_code}): {err_msg}",
                    error_details=err_msg,
                )

            data = init_resp.json().get("data", {})
            publish_id = data.get("publish_id")
            upload_url = data.get("upload_url")
            if not upload_url:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message="TikTok init did not return an upload_url.",
                    error_details=str(data),
                )

            # Step 2: Upload video binary data
            upload_headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(file_size),
                "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
            }
            with open(path, "rb") as f:
                upload_resp = http_put(upload_url, headers=upload_headers, data=f.read(), timeout=300)

            if upload_resp.status_code not in (200, 201):
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"TikTok binary upload failed ({upload_resp.status_code}): {upload_resp.text}",
                    error_details=upload_resp.text,
                )

            post_url = f"https://www.tiktok.com/@me"
            logger.info(f"Successfully published to TikTok API: publish_id={publish_id}")
            return PublishResult(
                success=True,
                platform=self.platform_name,
                message=f"Successfully submitted to TikTok Content Posting API (ID: {publish_id})",
                post_id=publish_id,
                post_url=post_url,
            )

        except Exception as exc:
            logger.error(f"TikTok upload error: {exc}")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=f"TikTok upload error: {exc}",
                error_details=str(exc),
            )
