"""
AutoChop AI Studio - Instagram Reels Connector
Validates 90s vertical limits and formats engaging captions for Instagram Graph API.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from autochop.core.social.base import BaseSocialConnector, PlatformPostPayload, PublishResult
from autochop.utils.ffmpeg_utils import probe_media_info
from autochop.utils.http_client import http_get, http_post

logger = logging.getLogger("autochop.social.instagram")


class InstagramReelsConnector(BaseSocialConnector):
    """Connector for publishing to Instagram Reels."""

    @property
    def platform_name(self) -> str:
        return "Instagram Reels"

    @property
    def max_duration_sec(self) -> float:
        return 90.0  # Instagram Reels max duration is 90s

    @property
    def required_aspect_ratio(self) -> str:
        return "9:16 (Strict: 1080x1920)"

    def validate_video(self, video_path: str | Path) -> tuple[bool, str]:
        path = Path(video_path).resolve()
        if not path.exists():
            return False, f"File does not exist: {path}"

        info = probe_media_info(path)
        duration = float(info.get("duration", 0.0) or 0.0)
        if duration > 90.5:
            return False, f"Instagram Reels must be 90s or less. Current duration: {duration:.1f}s."

        width = info.get("width")
        height = info.get("height")
        if width and height:
            ratio = width / height
            if ratio > 0.8:
                return (
                    False,
                    f"Instagram Reels requires vertical video (9:16). Current ratio: {ratio:.2f}.",
                )

        return True, "Video meets Instagram Reels specifications."

    def format_payload(
        self,
        title: str,
        transcript: str,
        hook: str,
        tags: list[str],
        **kwargs: Any,
    ) -> PlatformPostPayload:
        body_text = (hook or title or "").strip()
        if len(body_text) > 1900:
            body_text = body_text[:1897].strip() + "..."

        reels_tags = ["reels", "reelsinstagram", "viral", "explorepage"]
        for t in tags:
            clean = t.replace("#", "").replace(" ", "").lower()
            if clean and clean not in reels_tags:
                reels_tags.append(clean)

        return PlatformPostPayload(
            platform=self.platform_name,
            title=title[:100] if title else "AutoChop Reel",
            body=body_text,
            tags=reels_tags[:20],
            privacy=kwargs.get("privacy", "public"),
            char_limit=2200,
            custom_fields={"share_to_feed": True},
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
                message=f"Instagram validation error: {err}",
                error_details=err,
            )

        token = os.getenv("INSTAGRAM_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN")
        if not token:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=(
                    "Action required: INSTAGRAM_ACCESS_TOKEN is required for direct Instagram Reels publishing. "
                    "Please configure it in Settings."
                ),
                error_details="Missing INSTAGRAM_ACCESS_TOKEN",
            )

        logger.info(f"Publishing to Instagram Graph API: {payload.title}")
        try:
            ig_user_id = os.getenv("INSTAGRAM_ACCOUNT_ID") or os.getenv("INSTAGRAM_USER_ID")
            # If account ID is not set explicitly, query /me
            if not ig_user_id:
                me_res = http_get(
                    "https://graph.facebook.com/v19.0/me",
                    params={"access_token": token, "fields": "id,name"},
                    timeout=15,
                )
                if me_res.status_code == 200:
                    ig_user_id = me_res.json().get("id")
                else:
                    ig_user_id = "me"

            file_size = path.stat().st_size
            container_endpoint = f"https://graph.facebook.com/v19.0/{ig_user_id}/media"

            # Step 1: Create Reel Container
            container_payload = {
                "access_token": token,
                "media_type": "REELS",
                "caption": payload.full_post_text[:2200],
                "upload_type": "resumable",
                "share_to_feed": str(payload.custom_fields.get("share_to_feed", True)).lower(),
            }
            c_resp = http_post(container_endpoint, form_data=container_payload, timeout=30)
            if c_resp.status_code != 200:
                err_msg = c_resp.text
                try:
                    err_msg = c_resp.json().get("error", {}).get("message", err_msg)
                except Exception:
                    pass
                logger.error(f"Instagram Reel container creation failed ({c_resp.status_code}): {err_msg}")
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"Instagram Reel container creation failed ({c_resp.status_code}): {err_msg}",
                    error_details=err_msg,
                )

            c_data = c_resp.json()
            container_id = c_data.get("id")
            upload_uri = c_data.get("uri")

            if not container_id:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message="Instagram did not return a container ID.",
                    error_details=str(c_data),
                )

            # Step 2: Upload Video Bytes if upload_uri is provided
            if upload_uri:
                upload_headers = {
                    "Authorization": f"OAuth {token}",
                    "offset": "0",
                    "file_size": str(file_size),
                    "Content-Type": "application/octet-stream",
                }
                with open(path, "rb") as f:
                    up_resp = http_post(upload_uri, headers=upload_headers, data=f.read(), timeout=300)

                if up_resp.status_code not in (200, 201):
                    return PublishResult(
                        success=False,
                        platform=self.platform_name,
                        message=f"Instagram video binary upload failed ({up_resp.status_code}): {up_resp.text}",
                        error_details=up_resp.text,
                    )

            # Step 3: Publish Media Container
            publish_endpoint = f"https://graph.facebook.com/v19.0/{ig_user_id}/media_publish"
            pub_data = {
                "access_token": token,
                "creation_id": container_id,
            }
            pub_resp = http_post(publish_endpoint, form_data=pub_data, timeout=45)
            if pub_resp.status_code != 200:
                err_msg = pub_resp.text
                try:
                    err_msg = pub_resp.json().get("error", {}).get("message", err_msg)
                except Exception:
                    pass
                logger.error(f"Instagram Reel media publish failed ({pub_resp.status_code}): {err_msg}")
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"Instagram Reel publish failed ({pub_resp.status_code}): {err_msg}",
                    error_details=err_msg,
                )

            media_id = pub_resp.json().get("id", container_id)
            post_url = f"https://www.instagram.com/reel/{media_id}/"
            logger.info(f"Successfully published to Instagram Reels: {post_url}")
            return PublishResult(
                success=True,
                platform=self.platform_name,
                message=f"Successfully published to Instagram Reels (ID: {media_id})",
                post_id=media_id,
                post_url=post_url,
            )

        except Exception as exc:
            logger.error(f"Instagram Reels upload error: {exc}")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=f"Instagram upload error: {exc}",
                error_details=str(exc),
            )
