"""
AutoChop AI Studio - Video Assembly & Stitching (Module 3)
Slices raw video into numbered takes, stitches takes into a master jump-cut cut,
verifies A/V sync drift, and generates a structured Markdown edit manifest.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from autochop.config import (
    DEFAULT_AV_SYNC_TOLERANCE_FRAMES,
    DEFAULT_CRF,
    DEFAULT_FFMPEG_PRESET,
    DEFAULT_MAX_RESOLUTION,
    DEFAULT_SUBTITLE_PRESET,
    SUBTITLE_PRESETS,
    SUBPROCESS_TIMEOUT_SEC,
)
from autochop.core.audio import get_video_duration
from autochop.utils.ffmpeg_utils import (
    escape_filter_path,
    probe_media_info,
    run_ffmpeg,
    verify_ffmpeg_installed,
)
from autochop.utils.file_utils import format_file_size

logger = logging.getLogger("autochop.assembly")


def slice_take(
    video_path: str | Path,
    start_sec: float,
    duration_sec: float,
    output_path: str | Path,
    max_resolution: str = DEFAULT_MAX_RESOLUTION,
    srt_path: str | Path | None = None,
    subtitle_preset: str = DEFAULT_SUBTITLE_PRESET,
    preset: str = DEFAULT_FFMPEG_PRESET,
    crf: int = DEFAULT_CRF,
) -> Path:
    """
    Slices a single take with frame-accurate seek and high-performance encoding:
    - Supports single-pass subtitle burning (avoids costly double re-encoding)
    - Applies resolution normalization (1080p/720p) to avoid multi-gigabyte CPU overload on Retina/4K footage
    - Uses multithreaded fast presets (-preset veryfast -threads 0)
    """
    ffmpeg_bin, _ = verify_ffmpeg_installed()
    src = Path(video_path).resolve()
    dst = Path(output_path).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Determine resolution scale filter (Audit Point 6)
    filter_chains: list[str] = []
    target_height = 0
    if "480p" in max_resolution:
        target_height = 480
        filter_chains.append("scale=-2:'min(480,ih)'")
    elif "720p" in max_resolution:
        target_height = 720
        filter_chains.append("scale=-2:'min(720,ih)'")
    elif "1080p" in max_resolution:
        target_height = 1080
        filter_chains.append("scale=-2:'min(1080,ih)'")
    elif "1440p" in max_resolution:
        target_height = 1440
        filter_chains.append("scale=-2:'min(1440,ih)'")

    # Probe media info for subtitles resolution
    effective_w, effective_h = 1920, 1080
    try:
        info = probe_media_info(src)
        src_w, src_h = info.get("width") or 1920, info.get("height") or 1080
        if target_height > 0 and src_h > target_height:
            effective_h = target_height
            effective_w = int(round((src_w / src_h) * target_height))
            if effective_w % 2 != 0:
                effective_w += 1
        else:
            effective_w, effective_h = src_w, src_h
    except Exception:
        pass

    # Check if subtitle burning is requested in this pass
    has_subtitles = False
    subtitle_filter_str = None
    if srt_path:
        srt_p = Path(srt_path).resolve()
        if srt_p.exists() and srt_p.stat().st_size > 0:
            has_subtitles = True
            preset_cfg = SUBTITLE_PRESETS.get(subtitle_preset, SUBTITLE_PRESETS[DEFAULT_SUBTITLE_PRESET])
            base_style = str(preset_cfg["style"])
            full_style = f"{base_style},PlayResX={effective_w},PlayResY={effective_h}"
            escaped_srt = escape_filter_path(srt_p)
            subtitle_filter_str = f"subtitles='{escaped_srt}':force_style='{full_style}'"
            filter_chains.append(subtitle_filter_str)

    vf_arg = ",".join(filter_chains) if filter_chains else None

    # If no subtitles and no scaling requested, try ultra-fast stream copy!
    if not has_subtitles and not vf_arg and "Source" in max_resolution:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss", f"{start_sec:.3f}",
            "-t", f"{duration_sec:.3f}",
            "-i", src.as_posix(),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            dst.as_posix(),
        ]
        try:
            run_ffmpeg(cmd, timeout=SUBPROCESS_TIMEOUT_SEC, check=True)
            return dst
        except Exception:
            # Fall back to re-encoding below
            pass

    def build_cmd(include_vf: str | None) -> list[str]:
        c = [
            ffmpeg_bin,
            "-y",
            "-ss", f"{start_sec:.3f}",
            "-t", f"{duration_sec:.3f}",
            "-i", src.as_posix(),
        ]
        if include_vf:
            c.extend(["-vf", include_vf])
        c.extend([
            "-c:v", "libx264",
            "-crf", str(crf),
            "-preset", preset,
            "-threads", "0",
            "-c:a", "aac",
            "-b:a", "192k",
            "-avoid_negative_ts", "make_zero",
            dst.as_posix(),
        ])
        return c

    cmd = build_cmd(vf_arg)
    try:
        run_ffmpeg(cmd, timeout=SUBPROCESS_TIMEOUT_SEC, check=True)
    except Exception as exc:
        if has_subtitles and subtitle_filter_str:
            # Subtitle burn failure fallback (Audit Points 8 & 17)
            logger.warning(
                f"Subtitle burning failed for slice {dst.name} ({exc}). "
                f"Retrying without subtitle overlay filter..."
            )
            clean_chains = [f for f in filter_chains if f != subtitle_filter_str]
            clean_vf = ",".join(clean_chains) if clean_chains else None
            fallback_cmd = build_cmd(clean_vf)
            run_ffmpeg(fallback_cmd, timeout=SUBPROCESS_TIMEOUT_SEC, check=True)
        else:
            raise

    return dst


def stitch_clips_concat_demuxer(
    clip_paths: list[Path | str],
    output_path: Path | str,
    list_file_path: Path | str,
) -> bool:
    """
    Concatenates clips using FFmpeg's concat demuxer (-f concat -safe 0 -i list.txt -c copy).
    Fast and lossless without quality degradation when clips share identical codec/resolution/fps.
    Returns True if successful, False otherwise.
    """
    ffmpeg_bin, _ = verify_ffmpeg_installed()
    out = Path(output_path).resolve()
    lst = Path(list_file_path).resolve()
    lst.parent.mkdir(parents=True, exist_ok=True)

    # Write concat list with absolute paths escaped
    lines = [f"file '{Path(cp).resolve().as_posix()}'" for cp in clip_paths]
    lst.write_text("\n".join(lines), encoding="utf-8")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", lst.as_posix(),
        "-c", "copy",
        out.as_posix(),
    ]

    logger.info(f"Attempting concat demuxer for {len(clip_paths)} clips...")
    try:
        run_ffmpeg(cmd, timeout=SUBPROCESS_TIMEOUT_SEC, check=True)
        return True
    except Exception as exc:
        logger.warning(f"Concat demuxer failed: {exc}. Falling back to filter_complex re-encoding.")
        return False


def stitch_clips_filter_complex(
    clip_paths: list[Path | str],
    output_path: Path | str,
) -> Path:
    """
    Concatenates clips using FFmpeg's filter_complex concat graph:
    [0:v][0:a][1:v][1:a]...concat=n=N:v=1:a=1[outv][outa]
    Guarantees successful stitching even if clips have minor stream differences.
    """
    ffmpeg_bin, _ = verify_ffmpeg_installed()
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [ffmpeg_bin, "-y"]
    # Add each input
    for cp in clip_paths:
        cmd.extend(["-i", Path(cp).resolve().as_posix()])

    n = len(clip_paths)
    inputs_str = "".join(f"[{i}:v][{i}:a]" for i in range(n))
    filter_graph = f"{inputs_str}concat=n={n}:v=1:a=1[outv][outa]"

    cmd.extend([
        "-filter_complex", filter_graph,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-crf", str(DEFAULT_CRF),
        "-preset", DEFAULT_FFMPEG_PRESET,
        "-threads", "0",
        "-c:a", "aac",
        "-b:a", "192k",
        out.as_posix(),
    ])

    logger.info(f"Stitching {n} clips via filter_complex concat...")
    run_ffmpeg(cmd, timeout=SUBPROCESS_TIMEOUT_SEC, check=True)
    return out


def assemble_master_video(
    take_paths: list[Path | str],
    output_master_path: Path | str,
    temp_dir: Path | str,
    av_sync_tolerance: float | None = None,
) -> Path:
    """
    Assembles individual takes into a final master jump-cut video.
    First tries the fast concat demuxer; if that fails or streams vary,
    falls back cleanly to filter_complex concat.
    Verifies A/V sync duration against the sum of individual takes with dynamic tolerance.
    """
    if not take_paths:
        raise ValueError("Cannot assemble master video: take_paths list is empty.")

    out = Path(output_master_path).resolve()
    t_dir = Path(temp_dir).resolve()
    t_dir.mkdir(parents=True, exist_ok=True)

    if len(take_paths) == 1:
        # Single take: copy directly
        import shutil
        shutil.copy2(Path(take_paths[0]), out)
        return out

    # Concatenation approach decision:
    # We prefer the FFmpeg concat demuxer (-f concat -safe 0 -i list.txt -c copy)
    # because all sliced takes originate from the identical source with identical encoder settings,
    # making copy-concatenation frame-accurate and an order of magnitude faster.
    # If the concat demuxer fails (e.g. slight timestamp discontinuity or varied caption burns),
    # we fall back to a re-encoding filter_complex concat graph.
    list_txt = t_dir / "concat_list.txt"
    success = stitch_clips_concat_demuxer(take_paths, out, list_txt)

    if not success or not out.exists() or out.stat().st_size == 0:
        stitch_clips_filter_complex(take_paths, out)

    # Dynamic A/V Sync & Duration Verification (Audit Point 9)
    try:
        summed_duration = sum(get_video_duration(p) for p in take_paths)
        master_duration = get_video_duration(out)
        diff = abs(summed_duration - master_duration)

        fps = 30.0
        try:
            p_info = probe_media_info(take_paths[0])
            if p_info.get("fps") and p_info["fps"] > 0:
                fps = p_info["fps"]
        except Exception:
            pass

        tolerance = av_sync_tolerance if av_sync_tolerance is not None else max(0.10, (DEFAULT_AV_SYNC_TOLERANCE_FRAMES / fps))

        logger.info(
            f"Assembly verification: Summed takes={summed_duration:.3f}s, "
            f"Master={master_duration:.3f}s (drift: {diff:.3f}s, tolerance: {tolerance:.3f}s @ {fps:.1f}fps)"
        )
        if diff > tolerance:
            logger.warning(
                f"A/V duration drift detected: final master differs from sum of takes by {diff:.3f}s "
                f"(tolerance: {tolerance:.3f}s, ~{DEFAULT_AV_SYNC_TOLERANCE_FRAMES} frames at {fps:.1f} fps). "
                f"Summed: {summed_duration:.2f}s vs master: {master_duration:.2f}s."
            )
    except Exception as exc:
        logger.warning(f"Could not verify master duration: {exc}")

    return out


def generate_edit_manifest(
    takes_metadata: list[dict[str, Any]],
    output_markdown_path: Path | str | None = None,
) -> str:
    """
    Generates a GitHub-flavored Markdown table summarizing all takes:
    Take # | Filename | Timecode Range | Duration | Spoken Preview | File Size
    """
    headers = ["Take", "Filename", "Timecode Range", "Duration", "Spoken Dialogue Preview", "Size"]
    separator = ["---", "---", "---", "---", "---", "---"]
    rows = [
        f"| {' | '.join(headers)} |",
        f"| {' | '.join(separator)} |",
    ]

    total_duration = 0.0
    total_size = 0

    for idx, item in enumerate(takes_metadata, 1):
        name = item.get("filename", f"take_{idx:03d}.mp4")
        start = item.get("start", 0.0)
        end = item.get("end", 0.0)
        dur = end - start
        total_duration += dur

        preview = item.get("transcript_preview", "").strip()
        # Clean preview for markdown table
        preview_clean = preview.replace("|", "/").replace("\n", " ")
        if len(preview_clean) > 80:
            preview_clean = preview_clean[:77] + "..."
        if not preview_clean:
            preview_clean = "*(no dialogue)*"

        size_bytes = item.get("size_bytes", 0)
        total_size += size_bytes
        size_str = format_file_size(size_bytes)

        timecode = f"{start:.2f}s – {end:.2f}s"
        dur_str = f"{dur:.2f}s"

        rows.append(f"| Take {idx:02d} | `{name}` | {timecode} | {dur_str} | {preview_clean} | {size_str} |")

    summary = (
        f"\n\n**Total Assembled Cuts:** {len(takes_metadata)} takes | "
        f"**Total Master Duration:** {total_duration:.2f}s | "
        f"**Total Takes Size:** {format_file_size(total_size)}"
    )

    manifest_md = "# 🎬 AutoChop Edit Manifest\n\n" + "\n".join(rows) + summary

    if output_markdown_path:
        out_p = Path(output_markdown_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(manifest_md, encoding="utf-8")

    return manifest_md
