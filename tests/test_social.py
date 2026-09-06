"""
Unit Tests for Multi-Platform Social Media Connectors & Manager
"""

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


@pytest.fixture
def synthetic_short_video(tmp_path) -> Path:
    """Creates a 2-second vertical 9:16 (360x640) video."""
    ffmpeg_bin, _ = verify_ffmpeg_installed()
    out = tmp_path / "test_vertical.mp4"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=360x640:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
        "-c:v", "libx264", "-c:a", "aac",
        str(out),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    # X strictly limits to 280 characters
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

    # Test ZIP export
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
