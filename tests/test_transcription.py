"""
Unit tests for Module 2: Transcription & Subtitle Pipeline
Verifies SRT timestamp formatting, relative timestamp re-basing,
and defensive cue handling.
"""

from pathlib import Path
import pytest
from autochop.core.transcription import format_srt_time, write_srt


def test_format_srt_time():
    """Verifies format_srt_time across various time boundaries."""
    assert format_srt_time(0.0) == "00:00:00,000"
    assert format_srt_time(1.234) == "00:00:01,234"
    assert format_srt_time(65.5) == "00:01:05,500"
    assert format_srt_time(3661.123) == "01:01:01,123"
    # Negative clamping
    assert format_srt_time(-5.0) == "00:00:00,000"


def test_write_srt_rebasing(tmp_path: Path):
    """
    Tests write_srt re-basing relative to clip_start (origin 00:00:00,000).
    """
    srt_file = tmp_path / "test.srt"
    clip_start = 10.0
    clip_transcript = [
        {"start": 10.5, "end": 12.0, "text": "Hello world!"},
        {"start": 12.2, "end": 14.5, "text": "This is AutoChop."},
    ]

    out = write_srt(srt_file, clip_start=clip_start, clip_transcript=clip_transcript)
    assert out.exists()

    content = out.read_text(encoding="utf-8")
    assert "1" in content
    # First cue should start at 10.5 - 10.0 = 0.5s -> 00:00:00,500
    assert "00:00:00,500 --> 00:00:02,000" in content
    assert "Hello world!" in content

    # Second cue should start at 12.2 - 10.0 = 2.2s -> 00:00:02,200
    assert "00:00:02,200 --> 00:00:04,500" in content
    assert "This is AutoChop." in content


def test_write_srt_zero_duration_and_overlaps(tmp_path: Path):
    """
    Tests defensive handling of zero-duration or overlapping cues.
    """
    srt_file = tmp_path / "overlap.srt"
    clip_start = 5.0
    clip_transcript = [
        {"start": 5.0, "end": 5.0, "text": "Instant cue"},  # 0 duration
        {"start": 5.1, "end": 6.0, "text": "Next cue"},     # overlaps minimum duration
    ]

    out = write_srt(srt_file, clip_start=clip_start, clip_transcript=clip_transcript, min_cue_duration=0.2)
    content = out.read_text(encoding="utf-8")

    # The first cue should have a minimum duration applied
    assert "00:00:00,000 --> 00:00:00,200" in content
    # Second cue should not start before first cue ends
    assert "Next cue" in content


def test_burn_subtitles_empty_fallback_warning(tmp_path: Path):
    """
    Tests that empty SRT file gracefully triggers unburned copy and records a clear warning.
    """
    from autochop.core.transcription import burn_subtitles, clear_subtitle_warning, get_subtitle_warning

    clear_subtitle_warning()
    fake_video = tmp_path / "fake.mp4"
    fake_video.write_bytes(b"dummy video data")
    empty_srt = tmp_path / "empty.srt"
    empty_srt.write_text("", encoding="utf-8")
    out_video = tmp_path / "out.mp4"

    burned = burn_subtitles(fake_video, empty_srt, out_video)
    assert burned is False
    assert out_video.exists()
    warning = get_subtitle_warning()
    assert warning is not None
    assert "were empty" in warning
