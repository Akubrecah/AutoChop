"""
Unit & Integration Tests for Vertical Shorts Engine (Module 5)
"""

import subprocess
from pathlib import Path
import pytest

from autochop.core.shorts import (
    create_vertical_short,
    srt_to_vertical_ass,
    VERTICAL_SUBTITLE_STYLES,
)
from autochop.utils.ffmpeg_utils import probe_media_info, verify_ffmpeg_installed


@pytest.fixture
def synthetic_horizontal_video(tmp_path) -> Path:
    """Creates a 3-second 640x360 synthetic horizontal video with audio."""
    ffmpeg_bin, _ = verify_ffmpeg_installed()
    out = tmp_path / "test_horizontal.mp4"
    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=640x360:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
        "-c:v", "libx264", "-c:a", "aac",
        str(out),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out


@pytest.fixture
def sample_srt(tmp_path) -> Path:
    """Creates a sample SRT file for subtitle conversion."""
    srt = tmp_path / "sample.srt"
    srt.write_text(
        "1\n00:00:00,500 --> 00:00:02,000\nHello and welcome to AutoChop Shorts!\n\n"
        "2\n00:00:02,100 --> 00:00:02,900\nFast and automated vertical clips.\n",
        encoding="utf-8",
    )
    return srt


def test_srt_to_vertical_ass_safe_zone(sample_srt, tmp_path):
    """Verifies that vertical ASS contains 1080x1920 coordinates and safe-zone MarginV."""
    out_ass = tmp_path / "test_vertical.ass"
    res = srt_to_vertical_ass(
        sample_srt,
        out_ass,
        style_preset="TikTok Yellow (Vertical Safe-Zone)",
        play_res_x=1080,
        play_res_y=1920,
    )
    assert res.exists()
    content = res.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "MarginV=420" in content
    assert "Hello and welcome to AutoChop Shorts!" in content


def test_create_vertical_short_blurred_bg(synthetic_horizontal_video, sample_srt, tmp_path):
    """Verifies blurred background reframing produces 1080x1920 vertical video with subtitles."""
    out_short = tmp_path / "short_blur.mp4"
    res = create_vertical_short(
        input_video_path=synthetic_horizontal_video,
        output_path=out_short,
        mode="blur_bg",
        max_duration_sec=60.0,
        srt_path=sample_srt,
    )
    assert Path(res["output_path"]).exists()
    assert res["width"] == 1080
    assert res["height"] == 1920

    info = probe_media_info(out_short)
    assert info.get("width") == 1080
    assert info.get("height") == 1920
    assert info.get("duration") is not None and info["duration"] > 2.0


def test_create_vertical_short_center_crop(synthetic_horizontal_video, tmp_path):
    """Verifies center crop mode produces 1080x1920 vertical video."""
    out_short = tmp_path / "short_crop.mp4"
    res = create_vertical_short(
        input_video_path=synthetic_horizontal_video,
        output_path=out_short,
        mode="center_crop",
        max_duration_sec=60.0,
    )
    assert Path(res["output_path"]).exists()
    info = probe_media_info(out_short)
    assert info.get("width") == 1080
    assert info.get("height") == 1920


def test_create_vertical_short_letterbox(synthetic_horizontal_video, tmp_path):
    """Verifies letterbox fit mode produces 1080x1920 vertical video."""
    out_short = tmp_path / "short_letterbox.mp4"
    res = create_vertical_short(
        input_video_path=synthetic_horizontal_video,
        output_path=out_short,
        mode="letterbox",
        max_duration_sec=60.0,
    )
    assert Path(res["output_path"]).exists()
    info = probe_media_info(out_short)
    assert info.get("width") == 1080
    assert info.get("height") == 1920


def test_create_vertical_short_duration_limit(synthetic_horizontal_video, tmp_path):
    """Verifies duration cut-off limits video duration to max_duration_sec."""
    out_short = tmp_path / "short_1sec.mp4"
    res = create_vertical_short(
        input_video_path=synthetic_horizontal_video,
        output_path=out_short,
        mode="blur_bg",
        max_duration_sec=1.5,
    )
    assert Path(res["output_path"]).exists()
    info = probe_media_info(out_short)
    assert info.get("duration") is not None and info["duration"] <= 2.2
