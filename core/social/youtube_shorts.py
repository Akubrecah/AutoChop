"""
AutoChop AI Studio - YouTube Shorts Connector
Validates 60s vertical limits, formats #Shorts titles and descriptions,
and interfaces with YouTube Data API v3.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from autochop.core.social.base import BaseSocialConnector, PlatformPostPayload, PublishResult
from autochop.utils.ffmpeg_utils import probe_media_info
from autochop.utils.http_client import http_post, http_put

logger = logging.getLogger("autochop.social.youtube")


class YouTubeShortsConnector(BaseSocialConnector):
    """Connector for publishing to YouTube Shorts."""

    @property
    def platform_name(self) -> str:
        return "YouTube Shorts"

    @property
    def max_duration_sec(self) -> float:
        return 60.0  # YouTube Shorts hard limit is 60 seconds

    @property
    def required_aspect_ratio(self) -> str:
        return "9:16 (Vertical) or 1:1 (Square)"

    def validate_video(self, video_path: str | Path) -> tuple[bool, str]:
        path = Path(video_path).resolve()
        if not path.exists():
            return False, f"File does not exist: {path}"

        info = probe_media_info(path)
        duration = float(info.get("duration", 0.0) or 0.0)
        if duration > 60.5:
            return (
                False,
                f"YouTube Shorts must be 60 seconds or less. Current duration: {duration:.1f}s.",
            )

        # Check aspect ratio
        width = info.get("width")
        height = info.get("height")
        if width and height:
            ratio = width / height
            if ratio > 1.05:
                return (
                    False,
                    f"YouTube Shorts require vertical (9:16) or square (1:1) video. Current aspect ratio is {ratio:.2f}.",
                )

        return True, "Video meets YouTube Shorts specifications."

    def format_payload(
        self,
        title: str,
        transcript: str,
        hook: str,
        tags: list[str],
        **kwargs: Any,
    ) -> PlatformPostPayload:
        # YouTube Shorts requires/recommends #Shorts in title or description
        clean_title = (title or "AutoChop Short").strip()
        if "#Shorts" not in clean_title and "#shorts" not in clean_title:
            # Reserve 8 chars for " #Shorts"
            if len(clean_title) > 92:
                clean_title = clean_title[:89].strip() + "..."
            clean_title = f"{clean_title} #Shorts"
        else:
            if len(clean_title) > 100:
                clean_title = clean_title[:97].strip() + "..."

        # Format description body
        body_parts = []
        if hook:
            body_parts.append(hook.strip())
        body_parts.append("\nCreated with AutoChop AI Studio (https://github.com/Akubrecah/AutoChop)")
        body = "\n".join(body_parts)

        # Curate Shorts tags
        formatted_tags = ["Shorts", "Viral", "YouTubeShorts"]
        for t in tags:
            clean_t = t.replace("#", "").replace(" ", "")
            if clean_t and clean_t not in formatted_tags:
                formatted_tags.append(clean_t)

        privacy = kwargs.get("privacy", "public")

        return PlatformPostPayload(
            platform=self.platform_name,
            title=clean_title,
            body=body,
            tags=formatted_tags[:15],
            privacy=privacy,
            char_limit=5000,
            custom_fields={"category_id": "22"},  # People & Blogs
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
                message=f"Validation failed: {err}",
                error_details=err,
            )

        access_token = os.getenv("YOUTUBE_OAUTH_TOKEN")
        if not access_token:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=(
                    "Action required: YOUTUBE_OAUTH_TOKEN is required for direct YouTube publishing. "
                    "Please configure it in Settings."
                ),
                error_details="Missing YOUTUBE_OAUTH_TOKEN",
            )

        logger.info(f"Starting YouTube Data API v3 resumable upload for: {payload.title}")
        try:
            file_size = path.stat().st_size
            init_url = (
                "https://www.googleapis.com/upload/youtube/v3/videos"
                "?uploadType=resumable&part=snippet,status"
            )
            init_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(file_size),
            }
            init_body = {
                "snippet": {
                    "title": payload.title,
                    "description": payload.body,
                    "tags": payload.tags,
                    "categoryId": payload.custom_fields.get("category_id", "22"),
                },
                "status": {
                    "privacyStatus": payload.privacy.lower() if payload.privacy else "public",
                    "selfDeclaredMadeForKids": False,
                },
            }

            # Step 1: Initialize resumable upload session
            init_resp = http_post(init_url, headers=init_headers, json_data=init_body, timeout=30)
            if init_resp.status_code != 200:
                err_msg = init_resp.text
                try:
                    err_msg = init_resp.json().get("error", {}).get("message", err_msg)
                except Exception:
                    pass
                logger.error(f"YouTube upload session init failed ({init_resp.status_code}): {err_msg}")
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"YouTube session creation failed ({init_resp.status_code}): {err_msg}",
                    error_details=err_msg,
                )

            upload_url = init_resp.headers.get("Location") or init_resp.headers.get("location")
            if not upload_url:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message="YouTube did not return a resumable upload Location header.",
                    error_details="Missing Location header in YouTube init response",
                )

            # Step 2: Upload video binary data
            upload_headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(file_size),
            }
            with open(path, "rb") as f:
                upload_resp = http_put(upload_url, headers=upload_headers, data=f.read(), timeout=300)

            if upload_resp.status_code not in (200, 201):
                err_msg = upload_resp.text
                try:
                    err_msg = upload_resp.json().get("error", {}).get("message", err_msg)
                except Exception:
                    pass
                logger.error(f"YouTube video chunk upload failed ({upload_resp.status_code}): {err_msg}")
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"YouTube video upload failed ({upload_resp.status_code}): {err_msg}",
                    error_details=err_msg,
                )

            res_json = upload_resp.json()
            video_id = res_json.get("id")
            if not video_id:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message="YouTube upload succeeded but video ID was not found in response.",
                    error_details=str(res_json),
                )

            video_url = f"https://youtube.com/shorts/{video_id}"
            logger.info(f"Successfully published to YouTube Shorts: {video_url}")
            return PublishResult(
                success=True,
                platform=self.platform_name,
                message=f"Successfully published to YouTube Shorts: '{payload.title}'",
                post_id=video_id,
                post_url=video_url,
            )

        except Exception as exc:
            logger.error(f"YouTube upload error: {exc}")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=f"YouTube upload error: {exc}",
                error_details=str(exc),
            )
