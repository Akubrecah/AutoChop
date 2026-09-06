"""
AutoChop AI Studio - Vertical Shorts Engine (Module 5)
Converts horizontal or standard video takes into 9:16 vertical video (1080x1920)
optimized for YouTube Shorts, TikTok, and Instagram Reels.
Supports Blurred Background, Smart Center Crop, Letterbox, and Mobile UI Safe-Zone Subtitles.
"""

from __future__ import annotations

import logging
import math
import shutil
from pathlib import Path
from typing import Any

from autochop.config import (
    DEFAULT_CRF,
    DEFAULT_FFMPEG_PRESET,
    SUBPROCESS_TIMEOUT_SEC,
)
from autochop.utils.ffmpeg_utils import (
    escape_filter_path,
    probe_media_info,
    run_ffmpeg,
    verify_ffmpeg_installed,
)

logger = logging.getLogger("autochop.shorts")


# Safe-zone vertical subtitle presets (calculated for 1080x1920 mobile viewport)
# MarginV=420 positions subtitles in the vertical center-lower safe zone,
# avoiding the bottom ~280px (TikTok/Reels caption, sound ticker, username)
# and right ~120px (like, comment, share action buttons).
VERTICAL_SUBTITLE_STYLES: dict[str, dict[str, Any]] = {
    "TikTok Yellow (Vertical Safe-Zone)": {
        "font": "Impact",
        "fallback_fonts": ["Arial Black", "Helvetica-Bold", "Arial"],
        "style": (
            "FontName=Impact,FontSize=44,Bold=1,"
            "PrimaryColour=&H0000FFFF&,SecondaryColour=&H00000000&,"
            "OutlineColour=&H00000000&,BackColour=&H80000000&,"
            "BorderStyle=3,Outline=4,Shadow=3,"
            "Alignment=2,MarginL=60,MarginR=140,MarginV=420"
        ),
    },
    "Clean White (Vertical Safe-Zone)": {
        "font": "Arial",
        "fallback_fonts": ["Helvetica", "DejaVu Sans"],
        "style": (
            "FontName=Arial,FontSize=40,Bold=1,"
            "PrimaryColour=&H00FFFFFF&,SecondaryColour=&H00000000&,"
            "OutlineColour=&H00000000&,BackColour=&HA0000000&,"
            "BorderStyle=3,Outline=3,Shadow=2,"
            "Alignment=2,MarginL=60,MarginR=140,MarginV=420"
        ),
    },
    "Minimalist Dark Box (Vertical Safe-Zone)": {
        "font": "Helvetica",
        "fallback_fonts": ["Arial", "DejaVu Sans"],
        "style": (
            "FontName=Helvetica,FontSize=38,Bold=1,"
            "PrimaryColour=&H00FFFFFF&,SecondaryColour=&H00000000&,"
            "OutlineColour=&H00111111&,BackColour=&HC0111111&,"
            "BorderStyle=3,Outline=2,Shadow=0,"
            "Alignment=2,MarginL=80,MarginR=140,MarginV=440"
        ),
    },
}


def srt_to_vertical_ass(
    srt_path: str | Path,
    ass_path: str | Path,
    style_preset: str = "TikTok Yellow (Vertical Safe-Zone)",
    play_res_x: int = 1080,
    play_res_y: int = 1920,
) -> Path:
    """
    Converts a standard .srt file into an ASS subtitle file formatted specifically
    for 9:16 vertical resolution with mobile UI safe-zone margins.
    """
    srt = Path(srt_path).resolve()
    out_ass = Path(ass_path).resolve()
    out_ass.parent.mkdir(parents=True, exist_ok=True)

    if not srt.exists():
        raise FileNotFoundError(f"SRT file not found: {srt}")

    preset = VERTICAL_SUBTITLE_STYLES.get(
        style_preset,
        VERTICAL_SUBTITLE_STYLES["TikTok Yellow (Vertical Safe-Zone)"],
    )

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{preset['style']},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    srt_content = srt.read_text(encoding="utf-8", errors="replace")
    dialogue_lines: list[str] = []

    # Parse SRT blocks
    blocks = srt_content.strip().split("\n\n")
    for block in blocks:
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            continue

        # Check for timestamp line
        time_line_idx = 1 if lines[0].isdigit() else 0
        if time_line_idx >= len(lines):
            continue

        time_line = lines[time_line_idx]
        if "-->" not in time_line:
            continue

        parts = time_line.split("-->")
        if len(parts) != 2:
            continue

        start_raw, end_raw = parts[0].strip(), parts[1].strip()
        # Convert SRT time (00:01:23,456) to ASS time (0:01:23.45)
        start_ass = _convert_srt_time_to_ass(start_raw)
        end_ass = _convert_srt_time_to_ass(end_raw)

        # Text content
        text_lines = lines[time_line_idx + 1 :]
        text_content = "\\N".join(text_lines).strip()
        if text_content:
            dialogue_lines.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{text_content}")

    out_ass.write_text(header + "\n".join(dialogue_lines) + "\n", encoding="utf-8")
    return out_ass


def _convert_srt_time_to_ass(srt_time: str) -> str:
    """Converts 00:01:23,456 -> 0:01:23.45 (centi-seconds)."""
    clean = srt_time.replace(",", ".").strip()
    try:
        parts = clean.split(":")
        if len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            s_float = float(parts[2])
            total_sec = h * 3600 + m * 60 + s_float
            h_out = int(total_sec // 3600)
            m_out = int((total_sec % 3600) // 60)
            s_out = total_sec % 60
            cs_out = int(round((s_out - int(s_out)) * 100))
            if cs_out >= 100:
                s_out += 1
                cs_out = 0
            return f"{h_out}:{m_out:02d}:{int(s_out):02d}.{cs_out:02d}"
    except Exception:
        pass
    return "0:00:00.00"


def create_vertical_short(
    input_video_path: str | Path,
    output_path: str | Path,
    mode: str = "blur_bg",
    max_duration_sec: float | None = 60.0,
    srt_path: str | Path | None = None,
    subtitle_preset: str = "TikTok Yellow (Vertical Safe-Zone)",
    target_width: int = 1080,
    target_height: int = 1920,
) -> dict[str, Any]:
    """
    Converts input video into a 9:16 vertical short (1080x1920).
    Modes:
      - 'blur_bg': Centered video over an ambient blurred background (standard podcast/vlog style).
      - 'center_crop': Direct tight 9:16 crop to center.
      - 'letterbox': Scaled to fit with clean top/bottom letterboxing.
    Optionally burns mobile safe-zone styled subtitles if srt_path is provided.
    Optionally trims to max_duration_sec (e.g. 60s for YouTube Shorts / TikTok).
    """
    ffmpeg_bin, _ = verify_ffmpeg_installed()
    src = Path(input_video_path).resolve()
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise FileNotFoundError(f"Input video not found: {src}")

    info = probe_media_info(src)
    orig_duration = float(info.get("duration", 0.0) or 0.0)

    # Determine duration cut
    trim_args: list[str] = []
    effective_duration = orig_duration
    if max_duration_sec and max_duration_sec > 0 and orig_duration > max_duration_sec:
        trim_args = ["-t", str(max_duration_sec)]
        effective_duration = max_duration_sec

    # Prepare subtitle filter if requested
    ass_filter = ""
    temp_ass_path: Path | None = None
    if srt_path and Path(srt_path).exists():
        temp_ass_path = out.parent / f"{out.stem}_temp_vertical.ass"
        try:
            srt_to_vertical_ass(
                srt_path=srt_path,
                ass_path=temp_ass_path,
                style_preset=subtitle_preset,
                play_res_x=target_width,
                play_res_y=target_height,
            )
            escaped_ass = escape_filter_path(temp_ass_path)
            ass_filter = f",ass={escaped_ass}"
        except Exception as exc:
            logger.warning(f"Could not convert SRT to vertical ASS: {exc}. Proceeding without subtitles.")

    # Construct filter_complex based on reframing mode
    w, h = target_width, target_height
    mode_lower = mode.lower().replace(" ", "_")

    if "crop" in mode_lower:
        # Center Crop: scale so height matches target, then crop center width
        vf = f"scale=-2:{h}:flags=lanczos,crop={w}:{h}:(in_w-{w})/2:0{ass_filter}"
        filter_args = ["-vf", vf]
    elif "letterbox" in mode_lower or "fit" in mode_lower:
        # Fit with Letterbox: scale to fit inside 1080x1920 and pad with black
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black{ass_filter}"
        )
        filter_args = ["-vf", vf]
    else:
        # Default: Blurred Background (Full 9:16 bleed with centered foreground)
        filter_complex = (
            f"[0:v]split=2[blur_src][fg_src];"
            f"[blur_src]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=20:5[bg];"
            f"[fg_src]scale={w}:-2:flags=lanczos[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2{ass_filter}[v_combined]"
        )
        filter_args = ["-filter_complex", filter_complex, "-map", "[v_combined]", "-map", "0:a?"]

    cmd = [
        ffmpeg_bin,
        "-y",
        *trim_args,
        "-i",
        str(src),
        *filter_args,
        "-c:v",
        "libx264",
        "-preset",
        DEFAULT_FFMPEG_PRESET,
        "-crf",
        str(DEFAULT_CRF),
        "-c:a",
        "aac",
        "-ar",
        "44100",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(out),
    ]

    logger.info(f"Generating vertical short ({mode}): {' '.join(cmd)}")
    result = run_ffmpeg(cmd, timeout=SUBPROCESS_TIMEOUT_SEC)

    # Clean up temp ASS file if created
    if temp_ass_path and temp_ass_path.exists():
        try:
            temp_ass_path.unlink()
        except Exception:
            pass

    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        error_msg = f"Failed to generate vertical short (exit {result.returncode}): {result.stderr[-400:]}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info(f"Successfully generated vertical short: {out} ({effective_duration:.2f}s, {w}x{h})")
    return {
        "output_path": str(out),
        "duration": effective_duration,
        "width": w,
        "height": h,
        "mode": mode,
    }
