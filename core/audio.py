"""
AutoChop AI Studio - Audio & Silence Engine (Module 1)
Extracts audio tracks, detects dead-air silence intervals using FFmpeg silencedetect,
and calculates padded, merged active speech segments.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from autochop.config import (
    DEFAULT_MIN_GAP_SEC,
    DEFAULT_MIN_SEGMENT_SEC,
    DEFAULT_MIN_SILENCE_SEC,
    DEFAULT_PADDING_SEC,
    DEFAULT_SILENCE_THRESH_DB,
    SUBPROCESS_TIMEOUT_SEC,
)
from autochop.utils.ffmpeg_utils import run_ffmpeg, validate_media_file, verify_ffmpeg_installed

logger = logging.getLogger("autochop.audio")


def get_video_duration(file_path: str | Path) -> float:
    """
    Validates the media file format and streams via ffprobe, returning duration in seconds.
    Raises ValueError if file has no readable duration or is empty/corrupt.
    """
    p = Path(file_path).resolve()
    info = validate_media_file(p)
    duration = float(info.get("duration", 0.0))
    if duration <= 0:
        raise ValueError(f"Duration must be greater than 0, got {duration} for: {file_path}")
    return duration


def extract_audio(video_path: str | Path, temp_audio_path: str | Path) -> None:
    """
    Extracts a 16kHz mono 16-bit PCM WAV from the input video for Whisper processing.
    Timeout-guarded to prevent hangs on malformed inputs.
    """
    ffmpeg_bin, _ = verify_ffmpeg_installed()
    src = Path(video_path).resolve().as_posix()
    dst = Path(temp_audio_path).resolve().as_posix()
    Path(dst).parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", src,
        "-vn",
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        dst,
    ]

    logger.info(f"Extracting 16kHz mono WAV from {src} to {dst}")
    run_ffmpeg(cmd, timeout=SUBPROCESS_TIMEOUT_SEC, check=True)

    if not Path(dst).exists() or Path(dst).stat().st_size == 0:
        raise RuntimeError(f"Failed to extract audio or resulting WAV is empty: {dst}")


def detect_silence(
    file_path: str | Path,
    noise_threshold: str | float = DEFAULT_SILENCE_THRESH_DB,
    min_duration: float = DEFAULT_MIN_SILENCE_SEC,
    total_duration: float | None = None,
) -> list[tuple[float, float]]:
    """
    Runs FFmpeg silencedetect filter and parses stderr to extract silence intervals.
    Returns a list of (start_seconds, end_seconds) tuples.
    """
    ffmpeg_bin, _ = verify_ffmpeg_installed()
    src = Path(file_path).resolve().as_posix()

    if total_duration is None:
        total_duration = get_video_duration(src)

    # Format noise threshold (e.g. -30dB or -30)
    thresh_str = f"{noise_threshold}dB" if not str(noise_threshold).endswith("dB") else str(noise_threshold)

    cmd = [
        ffmpeg_bin,
        "-i", src,
        "-af", f"silencedetect=noise={thresh_str}:d={min_duration}",
        "-f", "null",
        "-",
    ]

    logger.info(f"Running silencedetect on {src} (noise={thresh_str}, d={min_duration}s)")
    proc = run_ffmpeg(cmd, timeout=SUBPROCESS_TIMEOUT_SEC, check=False)

    # Parse stderr for silence_start and silence_end
    # Examples:
    # [silence_detect @ 0x...] silence_start: 12.345
    # [silence_detect @ 0x...] silence_end: 15.678 | silence_duration: 3.333
    start_pattern = re.compile(r"silence_start:\s*([0-9\.]+)")
    end_pattern = re.compile(r"silence_end:\s*([0-9\.]+)")

    silence_ranges: list[tuple[float, float]] = []
    current_start: float | None = None

    for line in proc.stderr.splitlines():
        start_match = start_pattern.search(line)
        if start_match:
            current_start = float(start_match.group(1))
            continue

        end_match = end_pattern.search(line)
        if end_match:
            end_time = float(end_match.group(1))
            if current_start is not None:
                silence_ranges.append((current_start, end_time))
                current_start = None
            else:
                # Silence started before or at t=0
                silence_ranges.append((0.0, end_time))

    # Trailing silence handling: silence_start without matching silence_end
    if current_start is not None:
        silence_ranges.append((current_start, total_duration))

    logger.info(f"Detected {len(silence_ranges)} silence ranges across {total_duration:.2f}s total duration.")
    return silence_ranges


def calculate_active_segments(
    silence_ranges: list[tuple[float, float]],
    total_duration: float,
    padding: float = DEFAULT_PADDING_SEC,
    min_gap: float = DEFAULT_MIN_GAP_SEC,
    min_length: float = DEFAULT_MIN_SEGMENT_SEC,
) -> list[tuple[float, float]]:
    """
    Inverts silence ranges to determine active speech slices.
    Applies boundary padding, merges intervals closer than min_gap,
    drops segments shorter than min_length, and clamps strictly to [0, total_duration].
    Raises ValueError if zero active segments remain.
    """
    if total_duration <= 0:
        raise ValueError(f"Total duration must be positive, got {total_duration}")

    # Sort silence intervals by start time
    sorted_silence = sorted(silence_ranges, key=lambda x: x[0])

    # Calculate cumulative non-overlapping silence duration across total_duration
    total_silence_dur = 0.0
    if sorted_silence:
        curr_s = max(0.0, sorted_silence[0][0])
        curr_e = min(total_duration, sorted_silence[0][1])
        for n_s, n_e in sorted_silence[1:]:
            n_s = max(0.0, n_s)
            n_e = min(total_duration, n_e)
            if n_s <= curr_e:
                curr_e = max(curr_e, n_e)
            else:
                total_silence_dur += max(0.0, curr_e - curr_s)
                curr_s, curr_e = n_s, n_e
        total_silence_dur += max(0.0, curr_e - curr_s)

    # Check for entirely silent or near-total silent file edge case (Audit Point 13)
    if total_silence_dur >= (total_duration - 0.1) or (total_duration > 1.0 and (total_silence_dur / total_duration) >= 0.98):
        raise ValueError(
            f"Audio file is entirely or almost entirely silent ({total_silence_dur:.1f}s of {total_duration:.1f}s is dead air). "
            "No spoken dialogue detected. Please verify microphone input or adjust silence threshold."
        )

    # 1. Invert silence intervals into active ranges
    active_ranges: list[tuple[float, float]] = []
    cursor = 0.0

    for s_start, s_end in sorted_silence:
        # Clamp silence markers
        s_start = max(0.0, min(s_start, total_duration))
        s_end = max(0.0, min(s_end, total_duration))

        if s_start > cursor:
            active_ranges.append((cursor, s_start))
        cursor = max(cursor, s_end)

    if cursor < total_duration:
        active_ranges.append((cursor, total_duration))

    if not active_ranges:
        raise ValueError(
            "No active speech segments detected. The audio may be completely silent, "
            "or the silence threshold (-dB) is set too high."
        )

    # 2. Add padding on boundaries and clamp to [0, total_duration]
    padded_ranges: list[tuple[float, float]] = []
    for start, end in active_ranges:
        p_start = max(0.0, start - padding)
        p_end = min(total_duration, end + padding)
        if p_end > p_start:
            padded_ranges.append((p_start, p_end))

    if not padded_ranges:
        raise ValueError("No active segments remain after boundary padding.")

    # 3. Merge segments separated by less than min_gap
    merged_ranges: list[tuple[float, float]] = []
    current_start, current_end = padded_ranges[0]

    for next_start, next_end in padded_ranges[1:]:
        if next_start - current_end <= min_gap:
            # Merge
            current_end = max(current_end, next_end)
        else:
            merged_ranges.append((current_start, current_end))
            current_start, current_end = next_start, next_end

    merged_ranges.append((current_start, current_end))

    # 4. Filter out short noise artifacts (< min_length)
    final_segments = [
        (round(s, 3), round(e, 3))
        for s, e in merged_ranges
        if (e - s) >= min_length
    ]

    if not final_segments:
        raise ValueError(
            f"All active segments were shorter than the minimum segment duration ({min_length}s). "
            "Try decreasing the minimum segment length or lowering the silence threshold."
        )

    logger.info(
        f"Calculated {len(final_segments)} active segments "
        f"(total active duration: {sum(e - s for s, e in final_segments):.2f}s)"
    )
    return final_segments


def detect_audio_volume(file_path: str | Path) -> dict[str, float]:
    """
    Runs FFmpeg volumedetect filter on audio to determine mean_volume and max_volume.
    Useful for adapting silence thresholds to real microphone recordings.
    """
    ffmpeg_bin, _ = verify_ffmpeg_installed()
    src = Path(file_path).resolve().as_posix()
    cmd = [ffmpeg_bin, "-y", "-i", src, "-af", "volumedetect", "-f", "null", "-"]

    mean_vol = -30.0
    max_vol = 0.0
    try:
        proc = run_ffmpeg(cmd, timeout=30, check=False)
        for line in proc.stderr.splitlines():
            if "mean_volume:" in line:
                m = re.search(r"mean_volume:\s*(-?[0-9\.]+)\s*dB", line)
                if m:
                    mean_vol = float(m.group(1))
            elif "max_volume:" in line:
                m = re.search(r"max_volume:\s*(-?[0-9\.]+)\s*dB", line)
                if m:
                    max_vol = float(m.group(1))
    except Exception as exc:
        logger.warning(f"Audio volume detection warning: {exc}")

    return {"mean_volume": mean_vol, "max_volume": max_vol}


def detect_silence_adaptive(
    file_path: str | Path,
    base_threshold: float = -26.0,
    min_duration: float = 0.4,
    total_duration: float | None = None,
) -> tuple[list[tuple[float, float]], float]:
    """
    Attempts silence detection at base_threshold. If zero silence ranges are found,
    intelligently tests more aggressive thresholds (-24dB, -20dB, -16dB) based on audio levels.
    Returns (silence_ranges, final_threshold_used).
    """
    silences = detect_silence(
        file_path=file_path,
        noise_threshold=base_threshold,
        min_duration=min_duration,
        total_duration=total_duration,
    )
    if silences:
        return silences, base_threshold

    # Fallback: probe volume
    vol = detect_audio_volume(file_path)
    mean_v = vol.get("mean_volume", -30.0)
    logger.info(f"Zero pauses at {base_threshold}dB. Mean volume: {mean_v}dB. Attempting adaptive pass...")

    # Candidates between base_threshold and (mean_volume - 4dB)
    candidates = [-24.0, -20.0, -16.0]
    for cand in candidates:
        if cand > base_threshold:
            ranges = detect_silence(
                file_path=file_path,
                noise_threshold=cand,
                min_duration=min_duration,
                total_duration=total_duration,
            )
            if ranges:
                logger.info(f"Adaptive silence detection succeeded at {cand}dB ({len(ranges)} pauses detected).")
                return ranges, cand

    return [], base_threshold


def calculate_segments_from_speech(
    speech_segments: list[dict[str, Any]],
    total_duration: float,
    min_silence_dur: float = 0.4,
    padding: float = DEFAULT_PADDING_SEC,
    min_segment_dur: float = DEFAULT_MIN_SEGMENT_SEC,
) -> list[tuple[float, float]]:
    """
    Derives active speech cuts directly from Whisper / Silero VAD speech timestamps.
    Used as an authoritative fallback when audio has loud ambient noise or FFmpeg silencedetect
    fails to find dead air.
    """
    if not speech_segments or total_duration <= 0:
        return [(0.0, total_duration)]

    valid_segs = sorted(
        [s for s in speech_segments if s.get("end", 0) > s.get("start", 0)],
        key=lambda x: x["start"],
    )
    if not valid_segs:
        return [(0.0, total_duration)]

    # Group adjacent speech slices separated by less than min_silence_dur
    grouped_cuts: list[tuple[float, float]] = []
    curr_start = valid_segs[0]["start"]
    curr_end = valid_segs[0]["end"]

    for seg in valid_segs[1:]:
        s = seg["start"]
        e = seg["end"]
        gap = s - curr_end
        if gap < min_silence_dur:
            # Small natural breath gap: keep together
            curr_end = max(curr_end, e)
        else:
            # Dead air pause >= min_silence_dur: finalize previous take
            grouped_cuts.append((curr_start, curr_end))
            curr_start = s
            curr_end = e

    grouped_cuts.append((curr_start, curr_end))

    # Apply boundary padding and clamp to video duration
    padded_cuts: list[tuple[float, float]] = []
    for s, e in grouped_cuts:
        ps = max(0.0, s - padding)
        pe = min(total_duration, e + padding)
        if pe - ps >= min_segment_dur:
            padded_cuts.append((round(ps, 3), round(pe, 3)))

    if not padded_cuts:
        return [(0.0, total_duration)]

    logger.info(
        f"Derived {len(padded_cuts)} active speech takes from Whisper VAD timestamps "
        f"(trimmed from {total_duration:.2f}s to {sum(e - s for s, e in padded_cuts):.2f}s)."
    )
    return padded_cuts

