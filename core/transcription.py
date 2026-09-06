"""
AutoChop AI Studio - Transcription & Subtitle Pipeline (Module 2)
Caches faster-whisper models, transcribes audio with word-level timestamps,
generates relative-timestamped SRT files, and burns styled ASS subtitles.
"""

from __future__ import annotations

import logging
import math
import shutil
from pathlib import Path
from typing import Any

from autochop.config import (
    DEFAULT_MIN_CUE_DURATION,
    DEFAULT_SUBTITLE_PRESET,
    DEFAULT_WHISPER_MODEL,
    SUBTITLE_PRESETS,
    SUBPROCESS_TIMEOUT_SEC,
)
from autochop.utils.ffmpeg_utils import (
    escape_filter_path,
    probe_media_info,
    run_ffmpeg,
    verify_ffmpeg_installed,
)

logger = logging.getLogger("autochop.transcription")

_LAST_SUBTITLE_WARNING: str | None = None


def get_subtitle_warning() -> str | None:
    """Returns the most recent subtitle burning warning or fallback notice."""
    return _LAST_SUBTITLE_WARNING


def clear_subtitle_warning() -> None:
    """Clears the subtitle burning warning tracker."""
    global _LAST_SUBTITLE_WARNING
    _LAST_SUBTITLE_WARNING = None


class WhisperModelCache:
    """
    Session-level singleton cache for loaded faster-whisper WhisperModel instances.
    Reuses the model across multiple requests to avoid expensive reloads.
    """
    _instances: dict[str, Any] = {}

    @classmethod
    def get_model(cls, model_size: str = DEFAULT_WHISPER_MODEL) -> Any:
        if model_size not in cls._instances:
            logger.info(f"Loading faster-whisper model '{model_size}' into cache...")
            try:
                import os
                from faster_whisper import WhisperModel
                # Use int8 compute_type and multithreading for 3x faster CPU execution
                cpu_threads = min(4, os.cpu_count() or 4)
                model = WhisperModel(
                    model_size,
                    device="auto",
                    compute_type="int8",
                    cpu_threads=cpu_threads,
                )
                cls._instances[model_size] = model
                logger.info(f"Successfully loaded and cached Whisper model '{model_size}' (int8, threads={cpu_threads}).")
            except Exception as exc:
                logger.error(f"Failed to load Whisper model '{model_size}': {exc}")
                raise RuntimeError(
                    f"Unable to load faster-whisper model '{model_size}'. "
                    f"Ensure ctranslate2 is compatible with your hardware.\nDetails: {exc}"
                ) from exc
        return cls._instances[model_size]

    @classmethod
    def clear(cls) -> None:
        cls._instances.clear()


def format_srt_time(seconds: float) -> str:
    """
    Converts seconds into SRT timestamp format: HH:MM:SS,mmm.
    Example: 65.432 -> '00:01:05,432'.
    """
    if seconds < 0:
        seconds = 0.0

    total_ms = int(round(seconds * 1000))
    hours = total_ms // 3600000
    remainder = total_ms % 3600000
    minutes = remainder // 60000
    remainder %= 60000
    secs = remainder // 1000
    millis = remainder % 1000

    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def transcribe_audio(
    audio_path: str | Path,
    model_size: str = DEFAULT_WHISPER_MODEL,
    vad_filter: bool = True,
    word_timestamps: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """
    Transcribes a WAV audio file using faster-whisper.
    Returns:
        (segments, full_text_transcript)
        Each segment dict contains:
            - "start": float
            - "end": float
            - "text": str
            - "words": list[{"word": str, "start": float, "end": float, "probability": float}]
    """
    p = Path(audio_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found for transcription: {audio_path}")

    model = WhisperModelCache.get_model(model_size)
    logger.info(f"Transcribing {p.name} with model '{model_size}' (vad={vad_filter}, words={word_timestamps})...")

    # condition_on_previous_text=False minimizes memory accumulation and prevents repetition hallucination
    segments_generator, info = model.transcribe(
        p.as_posix(),
        vad_filter=vad_filter,
        word_timestamps=word_timestamps,
        beam_size=5,
        condition_on_previous_text=False,
    )

    segments: list[dict[str, Any]] = []
    text_pieces: list[str] = []

    for seg in segments_generator:
        seg_text = seg.text.strip()
        if not seg_text:
            continue

        words_data = []
        if word_timestamps and hasattr(seg, "words") and seg.words:
            for w in seg.words:
                words_data.append({
                    "word": w.word,
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "probability": round(w.probability, 3),
                })

        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg_text,
            "words": words_data,
        })
        text_pieces.append(seg_text)

    full_text = " ".join(text_pieces).strip()
    logger.info(
        f"Transcription completed: {len(segments)} segments, "
        f"detected language '{info.language}' (p={info.language_probability:.2f})"
    )
    return segments, full_text


def write_srt(
    srt_path: str | Path,
    clip_start: float,
    clip_transcript: list[dict[str, Any]],
    min_cue_duration: float = DEFAULT_MIN_CUE_DURATION,
) -> Path:
    """
    Writes a standard .srt file re-basing absolute timestamps relative to the clip start (00:00:00,000).
    Defensively skips zero-duration or invalid cues and adjusts overlaps.
    """
    out = Path(srt_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    cue_index = 1
    last_end = 0.0

    for seg in clip_transcript:
        raw_start = seg.get("start", 0.0)
        raw_end = seg.get("end", 0.0)
        text = seg.get("text", "").strip()
        if not text:
            continue

        # Re-base to clip origin
        rel_start = max(0.0, raw_start - clip_start)
        rel_end = max(rel_start + min_cue_duration, raw_end - clip_start)

        # Avoid inverted or zero cues
        if rel_end <= rel_start:
            rel_end = rel_start + min_cue_duration

        # Prevent overlapping with previous cue
        if rel_start < last_end:
            rel_start = last_end
            if rel_end <= rel_start:
                rel_end = rel_start + min_cue_duration

        start_str = format_srt_time(rel_start)
        end_str = format_srt_time(rel_end)

        lines.append(f"{cue_index}\n{start_str} --> {end_str}\n{text}\n")
        cue_index += 1
        last_end = rel_end

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def burn_subtitles(
    video_path: str | Path,
    srt_path: str | Path,
    output_path: str | Path,
    style_preset: str = DEFAULT_SUBTITLE_PRESET,
) -> bool:
    """
    Burns styled ASS subtitles onto the target video segment using FFmpeg subtitles filter.
    Injects PlayResX and PlayResY based on actual source dimensions for resolution-independent font scale.
    Falls back gracefully (keeps unburned video) if subtitle burning encounters host font errors.
    Returns True if subtitles were burned, False if fallback was used.
    """
    global _LAST_SUBTITLE_WARNING
    src = Path(video_path).resolve()
    srt = Path(srt_path).resolve()
    dst = Path(output_path).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not srt.exists() or srt.stat().st_size == 0:
        _LAST_SUBTITLE_WARNING = f"Subtitles for {src.name} were empty; generated clean unburned video."
        logger.warning(f"Empty or missing SRT file {srt}; copying unburned video to {dst}")
        shutil.copy2(src, dst)
        return False

    ffmpeg_bin, _ = verify_ffmpeg_installed()
    preset_cfg = SUBTITLE_PRESETS.get(style_preset, SUBTITLE_PRESETS[DEFAULT_SUBTITLE_PRESET])

    # Probe source resolution to set PlayResX / PlayResY for consistent font scale
    try:
        info = probe_media_info(src)
        res_x = info.get("width") or 1920
        res_y = info.get("height") or 1080
    except Exception as exc:
        logger.warning(f"Could not probe video resolution for {src}: {exc}. Defaulting to 1920x1080.")
        res_x, res_y = 1920, 1080

    base_style = str(preset_cfg["style"])
    # Append PlayResX and PlayResY to force_style
    full_force_style = f"{base_style},PlayResX={res_x},PlayResY={res_y}"
    escaped_srt = escape_filter_path(srt)

    subtitles_filter = f"subtitles='{escaped_srt}':force_style='{full_force_style}'"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", src.as_posix(),
        "-vf", subtitles_filter,
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "fast",
        "-c:a", "copy",
        dst.as_posix(),
    ]

    logger.info(f"Burning subtitles onto {src.name} with preset '{style_preset}'...")
    try:
        run_ffmpeg(cmd, timeout=SUBPROCESS_TIMEOUT_SEC, check=True)
        return True
    except Exception as exc:
        _LAST_SUBTITLE_WARNING = (
            f"Subtitle burning encountered a host font/filter issue on {src.name} ({exc}). "
            "Clean unburned video was generated without captions."
        )
        logger.warning(
            f"Subtitle burning failed for {src.name} (likely missing font or filter issue): {exc}\n"
            f"Falling back to clean unburned video."
        )
        if dst.exists():
            dst.unlink()
        shutil.copy2(src, dst)
        return False
