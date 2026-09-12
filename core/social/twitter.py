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
from autochop.utils.http_client import http_post

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

        token = (
            os.getenv("TWITTER_ACCESS_TOKEN")
            or os.getenv("TWITTER_BEARER_TOKEN")
            or os.getenv("TWITTER_API_KEY")
        )
        if not token:
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=(
                    "Action required: TWITTER_API_KEY or TWITTER_ACCESS_TOKEN is required for direct publishing to X. "
                    "Please configure it in Settings."
                ),
                error_details="Missing TWITTER_API_KEY",
            )

        logger.info(f"Starting X (Twitter) media upload and tweet creation: {payload.title}")
        try:
            headers = {"Authorization": f"Bearer {token}"}
            file_size = path.stat().st_size
            upload_endpoint = "https://upload.twitter.com/1.1/media/upload.json"

            # Step 1: INIT
            init_data = {
                "command": "INIT",
                "total_bytes": str(file_size),
                "media_type": "video/mp4",
                "media_category": "tweet_video",
            }
            init_res = http_post(upload_endpoint, headers=headers, form_data=init_data, timeout=30)
            if init_res.status_code not in (200, 202):
                err_msg = init_res.text
                try:
                    err_msg = init_res.json().get("errors", [{}])[0].get("message", err_msg)
                except Exception:
                    pass
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"X media INIT failed ({init_res.status_code}): {err_msg}",
                    error_details=err_msg,
                )

            media_id = init_res.json().get("media_id_string")
            if not media_id:
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message="X upload INIT did not return media_id_string.",
                    error_details=init_res.text,
                )

            # Step 2: APPEND chunks (4MB chunks)
            chunk_size = 4 * 1024 * 1024
            segment_index = 0
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    append_data = {
                        "command": "APPEND",
                        "media_id": media_id,
                        "segment_index": str(segment_index),
                    }
                    append_files = {"media": chunk}
                    append_res = http_post(
                        upload_endpoint,
                        headers=headers,
                        form_data=append_data,
                        files=append_files,
                        timeout=60,
                    )
                    if append_res.status_code not in (200, 204):
                        return PublishResult(
                            success=False,
                            platform=self.platform_name,
                            message=f"X media APPEND failed at chunk {segment_index} ({append_res.status_code}): {append_res.text}",
                            error_details=append_res.text,
                        )
                    segment_index += 1

            # Step 3: FINALIZE
            finalize_data = {"command": "FINALIZE", "media_id": media_id}
            fin_res = http_post(upload_endpoint, headers=headers, form_data=finalize_data, timeout=30)
            if fin_res.status_code not in (200, 201):
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"X media FINALIZE failed ({fin_res.status_code}): {fin_res.text}",
                    error_details=fin_res.text,
                )

            # Step 4: Publish Tweet via Twitter API v2
            tweet_endpoint = "https://api.twitter.com/2/tweets"
            tweet_payload = {
                "text": payload.full_post_text,
                "media": {"media_ids": [media_id]},
            }
            tweet_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            tweet_res = http_post(tweet_endpoint, headers=tweet_headers, json_data=tweet_payload, timeout=30)
            if tweet_res.status_code not in (200, 201):
                err_msg = tweet_res.text
                try:
                    err_msg = tweet_res.json().get("detail", err_msg)
                except Exception:
                    pass
                return PublishResult(
                    success=False,
                    platform=self.platform_name,
                    message=f"X Tweet creation failed ({tweet_res.status_code}): {err_msg}",
                    error_details=err_msg,
                )

            tweet_id = tweet_res.json().get("data", {}).get("id")
            post_url = f"https://x.com/i/status/{tweet_id}" if tweet_id else "https://x.com/"
            logger.info(f"Successfully published to X (Twitter): {post_url}")
            return PublishResult(
                success=True,
                platform=self.platform_name,
                message=f"Successfully published to X (Twitter): post ID {tweet_id}",
                post_id=tweet_id,
                post_url=post_url,
            )

        except Exception as exc:
            logger.error(f"X (Twitter) publishing error: {exc}")
            return PublishResult(
                success=False,
                platform=self.platform_name,
                message=f"X publishing error: {exc}",
                error_details=str(exc),
            )
