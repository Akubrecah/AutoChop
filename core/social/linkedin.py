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
from autochop.utils.http_client import http_get, http_post, http_put

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
        if not token:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=(
                    "Action required: LINKEDIN_ACCESS_TOKEN is required for direct LinkedIn publishing. "
                    "Please configure it in Settings."
                ),
                error_details="Missing LINKEDIN_ACCESS_TOKEN",
            )

        logger.info(f"Initiating LinkedIn Video & Post publishing: {payload.title}")
        try:
            headers_base = {
                "Authorization": f"Bearer {token}",
                "LinkedIn-Version": "202401",
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json",
            }

            # Resolve author person URN if not explicitly configured in environment
            author_urn = os.getenv("LINKEDIN_PERSON_URN") or os.getenv("LINKEDIN_AUTHOR_URN")
            if not author_urn:
                userinfo_res = http_get(
                    "https://api.linkedin.com/v2/userinfo",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
                if userinfo_res.status_code == 200:
                    sub = userinfo_res.json().get("sub")
                    if sub:
                        author_urn = f"urn:li:person:{sub}"
                if not author_urn:
                    author_urn = "urn:li:person:me"

            file_size = path.stat().st_size

            # Step 1: Initialize Video Upload
            init_url = "https://api.linkedin.com/rest/videos?action=initializeUpload"
            init_payload = {
                "initializeUploadRequest": {
                    "owner": author_urn,
                    "fileSizeBytes": file_size,
                    "uploadCaptions": False,
                    "uploadThumbnail": False,
                }
            }
            init_res = http_post(init_url, headers=headers_base, json_data=init_payload, timeout=30)
            if init_res.status_code not in (200, 201):
                err_msg = init_res.text
                try:
                    err_msg = init_res.json().get("message", err_msg)
                except Exception:
                    pass
                logger.error(f"LinkedIn video upload init failed ({init_res.status_code}): {err_msg}")
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"LinkedIn upload initialization failed ({init_res.status_code}): {err_msg}",
                    error_details=err_msg,
                )

            val = init_res.json().get("value", {})
            video_urn = val.get("video")
            upload_instructions = val.get("uploadInstructions", [])
            upload_url = upload_instructions[0].get("uploadUrl") if upload_instructions else None

            if not video_urn or not upload_url:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message="LinkedIn init did not return video URN or uploadUrl.",
                    error_details=str(val),
                )

            # Step 2: Upload Video Bytes
            upload_headers = {"Content-Type": "application/octet-stream"}
            with open(path, "rb") as f:
                up_res = http_put(upload_url, headers=upload_headers, data=f.read(), timeout=300)

            if up_res.status_code not in (200, 201):
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"LinkedIn binary upload failed ({up_res.status_code}): {up_res.text}",
                    error_details=up_res.text,
                )

            # Step 3: Create Post referencing video URN
            post_endpoint = "https://api.linkedin.com/rest/posts"
            post_payload = {
                "author": author_urn,
                "commentary": payload.full_post_text[:3000],
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "content": {
                    "media": {
                        "id": video_urn,
                        "title": payload.title[:400] if payload.title else "AutoChop Video",
                    }
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }
            post_res = http_post(post_endpoint, headers=headers_base, json_data=post_payload, timeout=30)
            if post_res.status_code not in (200, 201):
                err_msg = post_res.text
                try:
                    err_msg = post_res.json().get("message", err_msg)
                except Exception:
                    pass
                logger.error(f"LinkedIn post creation failed ({post_res.status_code}): {err_msg}")
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"LinkedIn post creation failed ({post_res.status_code}): {err_msg}",
                    error_details=err_msg,
                )

            post_urn = post_res.headers.get("x-restli-id") or post_res.headers.get("x-linkedin-id") or video_urn
            post_url = f"https://www.linkedin.com/feed/update/{post_urn}/" if "urn:li:" in post_urn else "https://www.linkedin.com/feed/"
            logger.info(f"Successfully published to LinkedIn: {post_url}")
            return PublishResult(
                success=True,
                platform=self.platform_name,
                message=f"Successfully published to LinkedIn ({post_urn})",
                post_id=post_urn,
                post_url=post_url,
            )

        except Exception as exc:
            logger.error(f"LinkedIn publishing error: {exc}")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=f"LinkedIn publishing error: {exc}",
                error_details=str(exc),
            )
