"""
Unit Tests for Multi-Platform Social Media Connectors & Manager
Includes validation, formatting, ZIP packaging, and live platform API publishing workflows.
"""

from unittest.mock import patch
import json
import subprocess
from pathlib import Path
import pytest

from autochop.core.social.base import PlatformPostPayload
from autochop.core.social.instagram import InstagramReelsConnector
from autochop.core.social.linkedin import LinkedInConnector
from autochop.core.social.manager import SocialPublishManager
from autochop.core.social.tiktok import TikTokConnector
from autochop.core.social.twitter import TwitterConnector
from autochop.core.social.youtube_shorts import YouTubeShortsConnector
from autochop.utils.ffmpeg_utils import verify_ffmpeg_installed
from autochop.utils.http_client import HttpResponse


@pytest.fixture
def synthetic_short_video(tmp_path, monkeypatch) -> Path:
    """Creates a vertical 9:16 video or mocks probing when FFmpeg is not available."""
    out = tmp_path / "test_vertical.mp4"
    try:
        ffmpeg_bin, _ = verify_ffmpeg_installed()
        cmd = [
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=360x640:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
            "-c:v", "libx264", "-c:a", "aac",
            str(out),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        out.write_bytes(b"\x00" * 4096)
        # Mock probe_media_info to return vertical specifications
        monkeypatch.setattr(
            "autochop.core.social.youtube_shorts.probe_media_info",
            lambda p: {"duration": 15.0, "width": 1080, "height": 1920},
        )
        monkeypatch.setattr(
            "autochop.core.social.tiktok.probe_media_info",
            lambda p: {"duration": 15.0, "width": 1080, "height": 1920},
        )
        monkeypatch.setattr(
            "autochop.core.social.instagram.probe_media_info",
            lambda p: {"duration": 15.0, "width": 1080, "height": 1920},
        )
        monkeypatch.setattr(
            "autochop.core.social.twitter.probe_media_info",
            lambda p: {"duration": 15.0, "width": 1080, "height": 1920},
        )
        monkeypatch.setattr(
            "autochop.core.social.linkedin.probe_media_info",
            lambda p: {"duration": 15.0, "width": 1080, "height": 1920},
        )
    return out


def test_youtube_shorts_payload_and_validation(synthetic_short_video):
    connector = YouTubeShortsConnector()
    valid, msg = connector.validate_video(synthetic_short_video)
    assert valid is True

    payload = connector.format_payload(
        title="Epic AI Video Editing Tool",
        transcript="This tool cuts all silences automatically.",
        hook="Stop wasting 3 hours on jump cuts.",
        tags=["AI", "Tech"],
    )
    assert "#Shorts" in payload.title
    assert len(payload.title) <= 100
    assert "Shorts" in payload.tags
    assert payload.is_within_char_limit


def test_tiktok_payload_and_validation(synthetic_short_video):
    connector = TikTokConnector()
    valid, msg = connector.validate_video(synthetic_short_video)
    assert valid is True

    payload = connector.format_payload(
        title="AutoChop TikTok",
        transcript="Speech transcript here.",
        hook="Watch this amazing automated jump cut!",
        tags=["creator", "editing"],
    )
    assert "fyp" in payload.tags
    assert payload.char_limit == 2200
    assert payload.is_within_char_limit


def test_instagram_reels_payload_and_validation(synthetic_short_video):
    connector = InstagramReelsConnector()
    valid, msg = connector.validate_video(synthetic_short_video)
    assert valid is True

    payload = connector.format_payload(
        title="Reels Magic",
        transcript="Transcript text.",
        hook="The secret to fast YouTube Shorts.",
        tags=["reels", "viral"],
    )
    assert "reels" in payload.tags
    assert payload.char_limit == 2200


def test_twitter_payload_char_limit(synthetic_short_video):
    connector = TwitterConnector()
    valid, msg = connector.validate_video(synthetic_short_video)
    assert valid is True

    long_hook = "A" * 350
    payload = connector.format_payload(
        title="Twitter Title",
        transcript="Transcript text.",
        hook=long_hook,
        tags=["AI", "Video", "Editing"],
    )
    assert len(payload.full_post_text) <= 280
    assert payload.is_within_char_limit


def test_linkedin_payload_formatting(synthetic_short_video):
    connector = LinkedInConnector()
    valid, msg = connector.validate_video(synthetic_short_video)
    assert valid is True

    payload = connector.format_payload(
        title="Automating Post-Production Workflows",
        transcript="Transcript text.",
        hook="How creators can reclaim 10 hours a week using automated audio-visual trimming.",
        tags=["Automation", "FutureOfWork"],
    )
    assert "Key Takeaways" in payload.body
    assert payload.is_within_char_limit


def test_social_publish_manager_export_zip(synthetic_short_video, tmp_path):
    manager = SocialPublishManager()
    assert len(manager.supported_platforms) >= 5

    payloads = manager.format_all_platforms(
        title="AutoChop AI Launch",
        transcript="We just launched our new video studio.",
        hook="The easiest way to cut dead air and burn captions.",
        tags=["AI", "Video"],
    )

    assert "YouTube Shorts" in payloads
    assert "TikTok" in payloads
    assert "Instagram Reels" in payloads
    assert "X (Twitter)" in payloads
    assert "LinkedIn" in payloads

    out_zip = tmp_path / "social_kit.zip"
    manager.export_platform_kits_zip(payloads, synthetic_short_video, out_zip)

    assert out_zip.exists()
    assert out_zip.stat().st_size > 0

    import zipfile
    with zipfile.ZipFile(out_zip, "r") as zf:
        names = zf.namelist()
        assert "youtube_shorts_copy.txt" in names
        assert "tiktok_caption.txt" in names
        assert "instagram_reels_caption.txt" in names
        assert "twitter_post.txt" in names
        assert "linkedin_post.txt" in names
        assert "README_POSTING_GUIDE.md" in names
        assert synthetic_short_video.name in names


# ---------------------------------------------------------------------------
# Live Platform API Publishing Tests (Mocked Network Calls)
# ---------------------------------------------------------------------------

def test_youtube_shorts_publish_missing_token(synthetic_short_video, monkeypatch):
    monkeypatch.delenv("YOUTUBE_OAUTH_TOKEN", raising=False)
    connector = YouTubeShortsConnector()
    payload = connector.format_payload("Test Video", "", "Hook", ["test"])
    result = connector.publish(payload, synthetic_short_video)
    assert result.success is False
    assert "YOUTUBE_OAUTH_TOKEN is required" in result.message


def test_youtube_shorts_publish_live_success(synthetic_short_video, monkeypatch):
    monkeypatch.setenv("YOUTUBE_OAUTH_TOKEN", "mock_yt_oauth_token_123")
    connector = YouTubeShortsConnector()
    payload = connector.format_payload("Epic Jump Cut #Shorts", "", "Check this out", ["ai", "video"])

    mock_init_resp = HttpResponse(
        status_code=200,
        headers={"Location": "https://upload.youtube.com/upload/session_id_456"},
        content=b"{}",
    )
    mock_upload_resp = HttpResponse(
        status_code=200,
        headers={},
        content=json.dumps({"id": "live_yt_video_999"}).encode("utf-8"),
    )

    with patch("autochop.core.social.youtube_shorts.http_post", return_value=mock_init_resp) as mock_post, \
         patch("autochop.core.social.youtube_shorts.http_put", return_value=mock_upload_resp) as mock_put:
        result = connector.publish(payload, synthetic_short_video)

        assert result.success is True
        assert result.post_id == "live_yt_video_999"
        assert result.post_url == "https://youtube.com/shorts/live_yt_video_999"
        assert mock_post.called
        assert mock_put.called
        assert "Bearer mock_yt_oauth_token_123" in mock_post.call_args[1]["headers"]["Authorization"]


def test_twitter_publish_missing_token(synthetic_short_video, monkeypatch):
    monkeypatch.delenv("TWITTER_API_KEY", raising=False)
    monkeypatch.delenv("TWITTER_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    connector = TwitterConnector()
    payload = connector.format_payload("Test", "", "Check this out", ["ai"])
    result = connector.publish(payload, synthetic_short_video)
    assert result.success is False
    assert "TWITTER_API_KEY or TWITTER_ACCESS_TOKEN is required" in result.message


def test_twitter_publish_live_success(synthetic_short_video, monkeypatch):
    monkeypatch.setenv("TWITTER_ACCESS_TOKEN", "mock_tw_token_123")
    connector = TwitterConnector()
    payload = connector.format_payload("AutoChop", "", "Quick update", ["editing"])

    mock_init_res = HttpResponse(
        status_code=200,
        headers={},
        content=json.dumps({"media_id_string": "media_789"}).encode("utf-8"),
    )
    mock_append_res = HttpResponse(status_code=204, headers={}, content=b"")
    mock_fin_res = HttpResponse(
        status_code=200,
        headers={},
        content=json.dumps({"media_id_string": "media_789"}).encode("utf-8"),
    )
    mock_tweet_res = HttpResponse(
        status_code=201,
        headers={},
        content=json.dumps({"data": {"id": "tweet_real_12345"}}).encode("utf-8"),
    )

    def mock_http_post(url, *args, **kwargs):
        if "media/upload.json" in url:
            cmd = kwargs.get("form_data", {}).get("command")
            if cmd == "INIT":
                return mock_init_res
            elif cmd == "APPEND":
                return mock_append_res
            elif cmd == "FINALIZE":
                return mock_fin_res
        elif "2/tweets" in url:
            return mock_tweet_res
        return HttpResponse(status_code=400, headers={}, content=b"Bad Request")

    with patch("autochop.core.social.twitter.http_post", side_effect=mock_http_post):
        result = connector.publish(payload, synthetic_short_video)
        assert result.success is True
        assert result.post_id == "tweet_real_12345"
        assert result.post_url == "https://x.com/i/status/tweet_real_12345"


def test_tiktok_publish_missing_token(synthetic_short_video, monkeypatch):
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    connector = TikTokConnector()
    payload = connector.format_payload("Test", "", "Hook", ["fyp"])
    result = connector.publish(payload, synthetic_short_video)
    assert result.success is False
    assert "TIKTOK_ACCESS_TOKEN is required" in result.message


def test_tiktok_publish_live_success(synthetic_short_video, monkeypatch):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "mock_tt_token_abc")
    connector = TikTokConnector()
    payload = connector.format_payload("Trending Short", "", "Best video tool", ["fyp"])

    mock_init = HttpResponse(
        status_code=200,
        headers={},
        content=json.dumps({
            "data": {
                "publish_id": "tt_publish_real_456",
                "upload_url": "https://open-upload.tiktok.com/video/chunk_1",
            }
        }).encode("utf-8"),
    )
    mock_put = HttpResponse(status_code=200, headers={}, content=b"")

    with patch("autochop.core.social.tiktok.http_post", return_value=mock_init), \
         patch("autochop.core.social.tiktok.http_put", return_value=mock_put):
        result = connector.publish(payload, synthetic_short_video)
        assert result.success is True
        assert result.post_id == "tt_publish_real_456"
        assert "tiktok.com" in result.post_url


def test_instagram_reels_publish_missing_token(synthetic_short_video, monkeypatch):
    monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    connector = InstagramReelsConnector()
    payload = connector.format_payload("Test Reel", "", "Hook", ["reels"])
    result = connector.publish(payload, synthetic_short_video)
    assert result.success is False
    assert "INSTAGRAM_ACCESS_TOKEN is required" in result.message


def test_instagram_reels_publish_live_success(synthetic_short_video, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "mock_ig_token_xyz")
    monkeypatch.setenv("INSTAGRAM_ACCOUNT_ID", "17841400000000000")
    connector = InstagramReelsConnector()
    payload = connector.format_payload("Epic Reel", "", "Viral hook", ["reels"])

    mock_container_res = HttpResponse(
        status_code=200,
        headers={},
        content=json.dumps({
            "id": "container_reel_111",
            "uri": "https://rupload.facebook.com/ig-reels/upload_session_222",
        }).encode("utf-8"),
    )
    mock_upload_binary = HttpResponse(status_code=200, headers={}, content=b"")
    mock_publish_res = HttpResponse(
        status_code=200,
        headers={},
        content=json.dumps({"id": "ig_media_real_333"}).encode("utf-8"),
    )

    def mock_http_post(url, *args, **kwargs):
        if "rupload.facebook.com" in url:
            return mock_upload_binary
        elif "media_publish" in url:
            return mock_publish_res
        elif "/media" in url:
            return mock_container_res
        return HttpResponse(status_code=400, headers={}, content=b"Bad Request")

    with patch("autochop.core.social.instagram.http_post", side_effect=mock_http_post):
        result = connector.publish(payload, synthetic_short_video)
        assert result.success is True
        assert result.post_id == "ig_media_real_333"
        assert "instagram.com/reel/ig_media_real_333/" in result.post_url


def test_linkedin_publish_missing_token(synthetic_short_video, monkeypatch):
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    connector = LinkedInConnector()
    payload = connector.format_payload("Test LinkedIn", "", "Professional insight", ["AI"])
    result = connector.publish(payload, synthetic_short_video)
    assert result.success is False
    assert "LINKEDIN_ACCESS_TOKEN is required" in result.message


def test_linkedin_publish_live_success(synthetic_short_video, monkeypatch):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "mock_li_token_456")
    monkeypatch.setenv("LINKEDIN_PERSON_URN", "urn:li:person:user123")
    connector = LinkedInConnector()
    payload = connector.format_payload("Automating Workflows", "", "Key insight", ["AI"])

    mock_init = HttpResponse(
        status_code=200,
        headers={},
        content=json.dumps({
            "value": {
                "video": "urn:li:video:vid999",
                "uploadInstructions": [{"uploadUrl": "https://api.linkedin.com/mediaUpload/chunk_1"}],
            }
        }).encode("utf-8"),
    )
    mock_put = HttpResponse(status_code=200, headers={}, content=b"")
    mock_post_res = HttpResponse(
        status_code=201,
        headers={"x-restli-id": "urn:li:share:share888"},
        content=b"{}",
    )

    with patch("autochop.core.social.linkedin.http_post") as mock_post, \
         patch("autochop.core.social.linkedin.http_put", return_value=mock_put):
        mock_post.side_effect = [mock_init, mock_post_res]
        result = connector.publish(payload, synthetic_short_video)
        assert result.success is True
        assert result.post_id == "urn:li:share:share888"
        assert "linkedin.com/feed/update/urn:li:share:share888/" in result.post_url


def test_youtube_shorts_publish_api_error(synthetic_short_video, monkeypatch):
    monkeypatch.setenv("YOUTUBE_OAUTH_TOKEN", "invalid_expired_token")
    connector = YouTubeShortsConnector()
    payload = connector.format_payload("Video", "", "Hook", ["test"])

    err_resp = HttpResponse(
        status_code=401,
        headers={},
        content=json.dumps({"error": {"message": "Invalid Credentials"}}).encode("utf-8"),
    )
    with patch("autochop.core.social.youtube_shorts.http_post", return_value=err_resp):
        result = connector.publish(payload, synthetic_short_video)
        assert result.success is False
        assert "401" in result.message
        assert "Invalid Credentials" in result.error_details


def test_twitter_publish_api_error(synthetic_short_video, monkeypatch):
    monkeypatch.setenv("TWITTER_ACCESS_TOKEN", "bad_token")
    connector = TwitterConnector()
    payload = connector.format_payload("Title", "", "Hook", ["test"])

    err_resp = HttpResponse(
        status_code=403,
        headers={},
        content=json.dumps({"errors": [{"message": "Forbidden access"}]}).encode("utf-8"),
    )
    with patch("autochop.core.social.twitter.http_post", return_value=err_resp):
        result = connector.publish(payload, synthetic_short_video)
        assert result.success is False
        assert "403" in result.message


def test_tiktok_publish_api_error(synthetic_short_video, monkeypatch):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "bad_token")
    connector = TikTokConnector()
    payload = connector.format_payload("Title", "", "Hook", ["fyp"])

    err_resp = HttpResponse(
        status_code=400,
        headers={},
        content=json.dumps({"error": {"message": "Invalid parameter"}}).encode("utf-8"),
    )
    with patch("autochop.core.social.tiktok.http_post", return_value=err_resp):
        result = connector.publish(payload, synthetic_short_video)
        assert result.success is False
        assert "400" in result.message


def test_instagram_reels_publish_api_error(synthetic_short_video, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "bad_token")
    connector = InstagramReelsConnector()
    payload = connector.format_payload("Title", "", "Hook", ["reels"])

    err_resp = HttpResponse(
        status_code=400,
        headers={},
        content=json.dumps({"error": {"message": "Invalid OAuth access token"}}).encode("utf-8"),
    )
    with patch("autochop.core.social.instagram.http_get", return_value=HttpResponse(status_code=400, headers={}, content=b"")), \
         patch("autochop.core.social.instagram.http_post", return_value=err_resp):
        result = connector.publish(payload, synthetic_short_video)
        assert result.success is False
        assert "400" in result.message


def test_linkedin_publish_api_error(synthetic_short_video, monkeypatch):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "bad_token")
    connector = LinkedInConnector()
    payload = connector.format_payload("Title", "", "Hook", ["ai"])

    err_resp = HttpResponse(
        status_code=403,
        headers={},
        content=json.dumps({"message": "Not enough permissions to access /videos"}).encode("utf-8"),
    )
    with patch("autochop.core.social.linkedin.http_get", return_value=HttpResponse(status_code=403, headers={}, content=b"")), \
         patch("autochop.core.social.linkedin.http_post", return_value=err_resp):
        result = connector.publish(payload, synthetic_short_video)
        assert result.success is False
        assert "403" in result.message

