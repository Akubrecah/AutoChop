"""
Unit tests for Module 1: Audio & Silence Engine
Verifies silence inversion, boundary padding, small gap merging,
short noise rejection, and error handling for all-silent inputs.
"""

import pytest
from autochop.core.audio import calculate_active_segments


def test_calculate_active_segments_basic():
    """
    Tests basic silence inversion with typical speech pauses.
    Video is 10.0s long.
    Silence at [3.0, 4.0] and [7.0, 8.0].
    Spoken ranges before padding: [0.0, 3.0], [4.0, 7.0], [8.0, 10.0].
    """
    silences = [(3.0, 4.0), (7.0, 8.0)]
    total_dur = 10.0
    segments = calculate_active_segments(
        silence_ranges=silences,
        total_duration=total_dur,
        padding=0.1,
        min_gap=0.5,
        min_length=0.3,
    )

    assert len(segments) == 3
    # Segment 1: [0.0, 3.1]
    assert segments[0][0] == 0.0
    assert segments[0][1] == pytest.approx(3.1, abs=0.05)

    # Segment 2: [3.9, 7.1]
    assert segments[1][0] == pytest.approx(3.9, abs=0.05)
    assert segments[1][1] == pytest.approx(7.1, abs=0.05)

    # Segment 3: [7.9, 10.0]
    assert segments[2][0] == pytest.approx(7.9, abs=0.05)
    assert segments[2][1] == 10.0


def test_calculate_active_segments_gap_merging():
    """
    Tests that gaps between active segments smaller than min_gap are merged.
    """
    # Spoken segments [0.0, 2.0] and [2.15, 4.0]. Gap is 0.15s (< 0.2s min_gap).
    silences = [(2.0, 2.15)]
    total_dur = 5.0
    segments = calculate_active_segments(
        silence_ranges=silences,
        total_duration=total_dur,
        padding=0.05,
        min_gap=0.3,
        min_length=0.3,
    )

    # Segments should be merged into one continuous segment
    assert len(segments) == 1
    assert segments[0][0] == 0.0
    assert segments[0][1] == 5.0


def test_calculate_active_segments_noise_rejection():
    """
    Tests that accidental noise artifacts shorter than min_length are dropped.
    """
    # Speech at [0.0, 3.0], silence [3.0, 5.0], brief click artifact [5.0, 5.15], silence [5.15, 8.0]
    silences = [(3.0, 5.0), (5.15, 8.0)]
    total_dur = 8.0
    segments = calculate_active_segments(
        silence_ranges=silences,
        total_duration=total_dur,
        padding=0.0,
        min_gap=0.1,
        min_length=0.3,
    )

    # The 0.15s click at [5.0, 5.15] should be discarded
    assert len(segments) == 1
    assert segments[0] == (0.0, 3.0)


def test_calculate_active_segments_all_silent_raises_error():
    """
    Tests that an entirely silent audio file raises a descriptive ValueError.
    """
    silences = [(0.0, 10.0)]
    total_dur = 10.0
    with pytest.raises(ValueError, match="entirely silent|No active speech"):
        calculate_active_segments(
            silence_ranges=silences,
            total_duration=total_dur,
            padding=0.15,
            min_gap=0.2,
            min_length=0.3,
        )


def test_calculate_active_segments_boundary_clamping():
    """
    Tests that padding never exceeds [0.0, total_duration].
    """
    silences = [(5.0, 6.0)]
    total_dur = 10.0
    segments = calculate_active_segments(
        silence_ranges=silences,
        total_duration=total_dur,
        padding=1.0,  # large padding
        min_gap=0.2,
        min_length=0.3,
    )

    for start, end in segments:
        assert start >= 0.0
        assert end <= total_dur


def test_calculate_active_segments_multi_silence_all_silent_raises_error():
    """
    Tests that audio with multiple disjoint silences that sum to >98% total duration
    correctly raises a descriptive ValueError (Audit Point 13).
    """
    # 10s file with 3 silences summing to 9.9s dead air
    silences = [(0.0, 4.0), (4.05, 7.0), (7.05, 10.0)]
    total_dur = 10.0
    with pytest.raises(ValueError, match="entirely or almost entirely silent"):
        calculate_active_segments(
            silence_ranges=silences,
            total_duration=total_dur,
            padding=0.01,
            min_gap=0.02,
            min_length=0.3,
        )


def test_calculate_segments_from_speech():
    """
    Tests deriving active speech cuts directly from Whisper / VAD speech timestamps.
    Verifies that pauses >= min_silence_dur are trimmed while small breath gaps are kept.
    """
    from autochop.core.audio import calculate_segments_from_speech

    speech_segments = [
        {"start": 1.0, "end": 3.0, "text": "First phrase."},
        {"start": 3.2, "end": 4.5, "text": "Quick continuation."},  # gap = 0.2s (< 0.4s)
        {"start": 6.0, "end": 8.5, "text": "Second phrase after 1.5s dead air."},  # gap = 1.5s (>= 0.4s)
    ]
    total_dur = 10.0

    cuts = calculate_segments_from_speech(
        speech_segments=speech_segments,
        total_duration=total_dur,
        min_silence_dur=0.4,
        padding=0.08,
    )

    # We expect 2 takes: Take 1 covering 1.0-4.5s (with padding), Take 2 covering 6.0-8.5s (with padding)
    assert len(cuts) == 2

    # Take 1: starts around 1.0 - 0.08 = 0.92, ends around 4.5 + 0.08 = 4.58
    assert cuts[0][0] == pytest.approx(0.92, abs=0.05)
    assert cuts[0][1] == pytest.approx(4.58, abs=0.05)

    # Take 2: starts around 6.0 - 0.08 = 5.92, ends around 8.5 + 0.08 = 8.58
    assert cuts[1][0] == pytest.approx(5.92, abs=0.05)
    assert cuts[1][1] == pytest.approx(8.58, abs=0.05)

    # Verify dead air at beginning (0-0.92s) and pause (4.58-5.92s) and end (8.58-10.0s) was trimmed
    active_dur = sum(e - s for s, e in cuts)
    assert active_dur < total_dur

