"""
AutoChop AI Studio - Gradio Web Application
Provides an intuitive, creator-focused web interface for automated dead-air removal,
transcription, take slicing, subtitle burning, and YouTube metadata generation.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import gradio as gr

from autochop.config import (
    DEFAULT_MIN_GAP_SEC,
    DEFAULT_MIN_SEGMENT_SEC,
    DEFAULT_MIN_SILENCE_SEC,
    DEFAULT_PADDING_SEC,
    DEFAULT_SILENCE_THRESH_DB,
    DEFAULT_SUBTITLE_PRESET,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_MAX_RESOLUTION,
    SUPPORTED_RESOLUTIONS,
    LOG_LEVEL,
    MAX_UPLOAD_SIZE_MB,
    MAX_VIDEO_DURATION_SEC,
    SUBTITLE_PRESETS,
    SUPPORTED_METADATA_PROVIDERS,
    SUPPORTED_WHISPER_MODELS,
    TEMP_DIR_ROOT,
)
from autochop.core.assembly import (
    assemble_master_video,
    generate_edit_manifest,
    slice_take,
)
from autochop.core.audio import (
    calculate_active_segments,
    calculate_segments_from_speech,
    detect_audio_volume,
    detect_silence,
    detect_silence_adaptive,
    extract_audio,
    get_video_duration,
)
from autochop.core.metadata import (
    generate_metadata_with_fallback,
    test_provider_connection,
    validate_api_key,
)
from autochop.utils.env_utils import (
    get_key_for_provider,
    load_all_keys,
    save_key_for_provider,
    save_keys_to_env,
    save_single_key,
)
from autochop.core.transcription import (
    burn_subtitles,
    clear_subtitle_warning,
    get_subtitle_warning,
    transcribe_audio,
    write_srt,
)
from autochop.utils.ffmpeg_utils import (
    is_ffmpeg_available,
    validate_media_file,
    verify_ffmpeg_installed,
)
from autochop.utils.file_utils import (
    create_export_zip,
    format_file_size,
    get_session_dir,
    sanitize_filename,
)

# Configure structured logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("autochop.app")

# Perform startup verification of FFmpeg/FFprobe binaries
try:
    verify_ffmpeg_installed()
    FFMPEG_AVAILABLE = True
    FFMPEG_STATUS_MSG = "✅ FFmpeg & FFprobe detected and operational."
except RuntimeError as exc:
    FFMPEG_AVAILABLE = False
    FFMPEG_STATUS_MSG = f"⚠️ {exc}"
    logger.error(FFMPEG_STATUS_MSG)


# Pipeline Controller for Tab 1
def process_video_cuts(
    video_input: str | None,
    silence_thresh: float,
    min_silence_dur: float,
    whisper_model: str,
    burn_captions: bool,
    subtitle_preset: str,
    max_resolution: str = DEFAULT_MAX_RESOLUTION,
    progress=gr.Progress(track_tqdm=True),
) -> tuple[
    str | None,           # Master video path
    dict[str, Any],       # Updated Dropdown for takes
    str | None,           # Take preview (first take)
    str,                  # Manifest Markdown
    str | None,           # Export ZIP path
    dict[str, Any],       # takes_map State
    str,                  # Plain transcript for Tab 2
    list[dict[str, Any]], # Timestamped segments State
    float,                # Total video duration State
]:
    """
    Executes the end-to-end video cutting, transcription, and assembly pipeline.
    """
    if not video_input:
        raise gr.Error("Please upload a raw video file before starting.")

    if not FFMPEG_AVAILABLE:
        raise gr.Error("FFmpeg/FFprobe is not installed or not in PATH. Please check installation instructions.")

    video_path = Path(video_input).resolve()
    if not video_path.exists():
        raise gr.Error(f"Input video file not found at: {video_path}")

    # Validate video container, format, and streams (Audit Point 19)
    try:
        media_info = validate_media_file(video_path)
    except Exception as exc:
        raise gr.Error(f"Video validation failed: {exc}")

    file_size_mb = video_path.stat().st_size / (1024 * 1024)
    if file_size_mb > MAX_UPLOAD_SIZE_MB:
        raise gr.Error(
            f"Uploaded file ({file_size_mb:.1f} MB) exceeds maximum allowed size of {MAX_UPLOAD_SIZE_MB} MB."
        )

    # Reset any previous subtitle warnings (Audit Point 8 & 17)
    clear_subtitle_warning()

    # Session-scoped working directory
    session_id = uuid.uuid4().hex[:10]
    session_dir = get_session_dir(session_id)
    logger.info(f"Initialized processing session: {session_id} in {session_dir}")

    try:
        # Step 1: Probe video duration (0% -> 10%)
        progress(0.05, desc="Analyzing video properties & duration...")
        try:
            total_duration = get_video_duration(video_path)
        except Exception as exc:
            raise gr.Error(f"Failed to read video properties: {exc}")

        if total_duration > MAX_VIDEO_DURATION_SEC:
            raise gr.Error(
                f"Video duration ({total_duration:.1f}s) exceeds maximum limit of {MAX_VIDEO_DURATION_SEC:.1f}s ({MAX_VIDEO_DURATION_SEC / 60:.0f} mins)."
            )

        # Step 2: Extract audio (10% -> 20%)
        progress(0.12, desc="Extracting 16kHz audio track...")
        audio_wav = session_dir / "extracted_audio.wav"
        try:
            extract_audio(video_path, audio_wav)
        except Exception as exc:
            raise gr.Error(f"Audio extraction failed: {exc}")

        # Step 3: Transcribe audio with Whisper (20% -> 42%)
        progress(0.24, desc=f"Transcribing spoken dialogue via Whisper ({whisper_model})...")
        try:
            all_segments, full_transcript = transcribe_audio(
                audio_wav,
                model_size=whisper_model,
                vad_filter=True,
                word_timestamps=True,
            )
        except Exception as exc:
            logger.warning(f"Whisper transcription failed ({exc}). Continuing without captions.")
            all_segments, full_transcript = [], ""

        # Step 4: Detect silence & calculate active speech takes (42% -> 58%)
        progress(0.44, desc="Detecting speech pauses and trimming dead air...")
        active_segments: list[tuple[float, float]] = []
        silence_method_note = ""

        # Attempt 1: Standard FFmpeg silencedetect at user's threshold
        try:
            silence_ranges = detect_silence(
                audio_wav,
                noise_threshold=silence_thresh,
                min_duration=min_silence_dur,
                total_duration=total_duration,
            )
            if silence_ranges:
                try:
                    active_segments = calculate_active_segments(
                        silence_ranges,
                        total_duration=total_duration,
                        padding=DEFAULT_PADDING_SEC,
                        min_gap=DEFAULT_MIN_GAP_SEC,
                        min_length=DEFAULT_MIN_SEGMENT_SEC,
                    )
                except ValueError:
                    active_segments = []
        except Exception as exc:
            logger.warning(f"Initial silencedetect error: {exc}")

        # Attempt 2: If 0 or 1 take resulted, retry with adaptive volume-aware threshold
        if len(active_segments) <= 1:
            try:
                adap_ranges, used_thresh = detect_silence_adaptive(
                    audio_wav,
                    base_threshold=silence_thresh,
                    min_duration=min_silence_dur,
                    total_duration=total_duration,
                )
                if adap_ranges:
                    try:
                        active_segments = calculate_active_segments(
                            adap_ranges,
                            total_duration=total_duration,
                            padding=DEFAULT_PADDING_SEC,
                            min_gap=DEFAULT_MIN_GAP_SEC,
                            min_length=DEFAULT_MIN_SEGMENT_SEC,
                        )
                        if len(active_segments) > 1:
                            silence_method_note = f"Adaptive silence detection triggered ({used_thresh:.0f}dB) to capture pauses above background noise."
                    except ValueError:
                        pass
            except Exception as exc:
                logger.warning(f"Adaptive silence detection error: {exc}")

        # Attempt 3: Derive speech cuts from Whisper neural Voice Activity Detection (VAD)
        vad_takes: list[tuple[float, float]] = []
        if all_segments:
            try:
                vad_takes = calculate_segments_from_speech(
                    speech_segments=all_segments,
                    total_duration=total_duration,
                    min_silence_dur=min_silence_dur,
                    padding=DEFAULT_PADDING_SEC,
                    min_segment_dur=DEFAULT_MIN_SEGMENT_SEC,
                )
            except Exception as exc:
                logger.warning(f"VAD speech segmentation error: {exc}")

        # Intelligently select the best cutting strategy:
        # If Whisper neural VAD detected more takes OR cut significantly more dead air than silencedetect:
        silence_active_dur = sum(e - s for s, e in active_segments) if active_segments else total_duration
        vad_active_dur = sum(e - s for s, e in vad_takes) if vad_takes else total_duration

        if vad_takes and (
            len(active_segments) <= 1
            or len(vad_takes) > len(active_segments)
            or (silence_active_dur - vad_active_dur) > 1.5
        ):
            active_segments = vad_takes
            silence_method_note = (
                f"Neural Voice Activity Detection (VAD) selected ({len(vad_takes)} speech takes, "
                f"cutting {total_duration - vad_active_dur:.1f}s dead air past ambient noise)."
            )
        elif not active_segments:
            active_segments = [(0.0, total_duration)]

        # Step 5: Slice individual takes and generate relative SRTs (58% -> 78%)
        progress(0.58, desc=f"Slicing {len(active_segments)} speech takes...")
        takes_dir = session_dir / "takes"
        srt_dir = session_dir / "subtitles"
        takes_dir.mkdir(parents=True, exist_ok=True)
        srt_dir.mkdir(parents=True, exist_ok=True)

        take_files: list[Path] = []
        srt_files: list[Path] = []
        takes_metadata: list[dict[str, Any]] = []
        takes_map: dict[str, str] = {}

        num_segments = len(active_segments)
        for idx, (start_sec, end_sec) in enumerate(active_segments, 1):
            dur_sec = end_sec - start_sec
            take_name = f"take_{idx:03d}.mp4"
            take_path = takes_dir / take_name
            srt_name = f"take_{idx:03d}.srt"
            srt_path = srt_dir / srt_name

            # 1. Match dialogue segments for this take
            take_transcript_segments = [
                seg for seg in all_segments
                if seg["start"] >= (start_sec - 0.2) and seg["end"] <= (end_sec + 0.2)
            ]
            preview_text = " ".join(seg["text"] for seg in take_transcript_segments).strip()

            # 2. Write relative-timestamped SRT
            write_srt(srt_path, clip_start=start_sec, clip_transcript=take_transcript_segments)

            # 3. High-performance single-pass slice + caption burn (avoids double re-encoding)
            active_srt_path = srt_path if (burn_captions and srt_path.exists() and srt_path.stat().st_size > 0) else None
            slice_take(
                video_path=video_path,
                start_sec=start_sec,
                duration_sec=dur_sec,
                output_path=take_path,
                max_resolution=max_resolution,
                srt_path=active_srt_path,
                subtitle_preset=subtitle_preset,
            )

            take_files.append(take_path)
            srt_files.append(srt_path)
            take_label = f"Take {idx:02d} ({start_sec:.1f}s - {end_sec:.1f}s)"
            takes_map[take_label] = str(take_path)

            takes_metadata.append({
                "index": idx,
                "filename": take_path.name,
                "start": start_sec,
                "end": end_sec,
                "size_bytes": take_path.stat().st_size if take_path.exists() else 0,
                "transcript_preview": preview_text,
            })

            # Sub-step progress
            progress(0.58 + (0.20 * (idx / num_segments)), desc=f"Processed take {idx}/{num_segments}...")

        # Step 6: Assemble master video (78% -> 90%)
        progress(0.80, desc="Stitching master jump-cut rough video...")
        master_path = session_dir / "master_rough_cut.mp4"
        assemble_master_video(take_files, master_path, temp_dir=session_dir)

        # Step 7: Generate Edit Manifest & Export ZIP (90% -> 100%)
        progress(0.92, desc="Compiling edit manifest and downloadable ZIP archive...")
        manifest_path = session_dir / "manifest.md"
        manifest_md = generate_edit_manifest(takes_metadata, output_markdown_path=manifest_path)

        # Calculate dead-air trim statistics
        cut_duration = max(0.0, total_duration - sum(e - s for s, e in active_segments))
        cut_pct = (cut_duration / total_duration) * 100.0 if total_duration > 0 else 0.0

        if len(active_segments) > 1 and cut_duration > 0.05:
            trim_banner = (
                f"### ✂️ Trimming Summary: Removed {cut_duration:.1f}s of dead air ({cut_pct:.1f}% reduction) into {len(active_segments)} takes!\n"
            )
            if silence_method_note:
                trim_banner += f"> ℹ️ *{silence_method_note}*\n\n"
            manifest_md = trim_banner + manifest_md
            gr.Info(f"✂️ Trimmed {cut_duration:.1f}s of dead air into {len(active_segments)} takes ({cut_pct:.1f}% condensed)!")
        else:
            trim_banner = (
                f"### ℹ️ Notice: No pauses >= {min_silence_dur:.1f}s detected (audio was continuous). Master video is 100% uncut.\n"
                f"> 💡 **Tip:** To cut dead air more aggressively, adjust 'Silence Noise Threshold' to -22dB or -20dB and set 'Minimum Silence Duration' to 0.3s in the left settings.\n\n"
            )
            manifest_md = trim_banner + manifest_md

        zip_path = session_dir / "autochop_bundle.zip"
        create_export_zip(
            zip_output_path=zip_path,
            take_paths=take_files,
            srt_paths=srt_files,
            manifest_path=manifest_path,
            master_path=master_path,
        )

        progress(1.0, desc="Done! Master cut & takes ready.")

        # Prepare take dropdown
        dropdown_choices = list(takes_map.keys())
        first_preview = takes_map[dropdown_choices[0]] if dropdown_choices else None
        dropdown_update = gr.update(
            choices=dropdown_choices,
            value=dropdown_choices[0] if dropdown_choices else None,
            interactive=True,
        )

        # Notify user if any subtitle burning fallback occurred (Audit Points 8 & 17)
        sub_warn = get_subtitle_warning()
        if sub_warn:
            gr.Warning(f"Subtitle Fallback: {sub_warn}")
            manifest_md += f"\n\n> [!WARNING]\n> **Subtitle Notice:** {sub_warn}"

        return (
            str(master_path),
            dropdown_update,
            first_preview,
            manifest_md,
            str(zip_path),
            takes_map,
            full_transcript,
            all_segments,
            total_duration,
        )

    except gr.Error:
        raise
    except Exception as exc:
        logger.error(f"Pipeline error in session {session_id}: {exc}", exc_info=True)
        raise gr.Error(f"An unexpected error occurred during processing: {exc}")


def update_take_preview(selected_label: str, takes_map: dict[str, str]) -> str | None:
    """Updates the take inspector video preview when user chooses another take."""
    if not takes_map or not selected_label:
        return None
    return takes_map.get(selected_label)


# Controller for Tab 2: Title & Chapter Generator
def process_metadata_generation(
    transcript: str,
    provider: str,
    api_key: str,
    timestamped_segments: list[dict[str, Any]] | None,
    total_duration: float | None,
    custom_url: str | None = None,
    custom_model: str | None = None,
) -> tuple[str, str, str, str, str]:
    """
    Generates video metadata using selected provider or heuristic fallback.
    Returns:
        (status_notice, titles_text, hook_text, chapters_text, tags_text)
    """
    if not transcript or not transcript.strip():
        raise gr.Error("Please enter or generate a transcript first.")

    # Use saved key if textbox is empty
    active_key = api_key.strip() if api_key else get_key_for_provider(provider)

    # Validate API key if provider is not heuristic
    if provider not in ("Local Heuristic (No Key)", "OpenCode / Custom Endpoint"):
        is_valid, key_err = validate_api_key(provider, active_key)
        if not is_valid:
            raise gr.Error(key_err)
        # Automatically persist valid active key to .env so user never loses it!
        if active_key:
            save_key_for_provider(provider, active_key)

    try:
        data, notice = generate_metadata_with_fallback(
            transcript=transcript,
            provider=provider,
            api_key=active_key,
            timestamped_segments=timestamped_segments,
            total_duration=total_duration,
            custom_base_url=custom_url,
            custom_model=custom_model,
        )
    except Exception as exc:
        raise gr.Error(f"Metadata generation failed: {exc}")

    # Format Titles
    titles = data.get("titles", [])
    titles_md = "### 🎯 High-CTR Title Options\n\n" + "\n".join(f"{i}. **{t}**" for i, t in enumerate(titles, 1))

    # Format Description Hook
    hook = data.get("description_hook", "")
    hook_md = f"### ✍️ Video Description Hook\n\n{hook}"

    # Format Chapters
    chapters = data.get("chapters", [])
    chapters_lines = [f"`{c.get('timestamp', '00:00')}` {c.get('title', 'Chapter')}" for c in chapters]
    chapters_raw = "\n".join(f"{c.get('timestamp', '00:00')} {c.get('title', 'Chapter')}" for c in chapters)
    chapters_md = "### 📌 Clickable YouTube Chapters\n\n" + "\n".join(f"- {line}" for line in chapters_lines)

    # Format Tags
    tags = data.get("tags", "")
    hashtags = data.get("hashtags", [])
    hashtags_str = " ".join(hashtags)
    tags_md = f"### 🏷️ SEO Tags & Hashtags\n\n**Hashtags:** `{hashtags_str}`\n\n**Tags:** `{tags}`"

    notice_md = f"> [!NOTE]\n> {notice}" if notice else ""

    return notice_md, titles_md, hook_md, chapters_md, tags_md


def update_api_key_visibility(provider: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Toggles API key field & custom endpoint visibility based on provider selection."""
    clean_p = provider.strip()
    is_custom = (clean_p == "OpenCode / Custom Endpoint")
    is_heuristic = (clean_p == "Local Heuristic (No Key)")

    saved_key = get_key_for_provider(clean_p)

    if is_heuristic:
        return (
            gr.update(visible=False, value=""),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    key_update = gr.update(
        visible=True,
        value=saved_key,
        placeholder=f"Enter {clean_p} API Key (pre-loaded from .env if set)...",
    )
    btn_save_update = gr.update(visible=True)
    url_update = gr.update(visible=is_custom)
    model_update = gr.update(visible=is_custom)
    return key_update, btn_save_update, url_update, model_update


def handle_save_tab2_key(provider: str, key_val: str) -> str:
    """Saves the API key entered in Tab 2 directly to .env with live activation."""
    clean_p = provider.strip()
    if clean_p in ("Local Heuristic (No Key)", ""):
        return "ℹ️ Heuristic mode requires no API key."
    val = key_val.strip() if key_val else ""
    if not val:
        gr.Warning(f"Please enter an API key for {clean_p} first.")
        return f"⚠️ Please enter an API key for {clean_p}."
    is_valid, err = validate_api_key(clean_p, val)
    if not is_valid:
        gr.Warning(err or "Invalid key format.")
        return f"❌ {err}"
    save_key_for_provider(clean_p, val)
    gr.Info(f"✅ Saved {clean_p} API key to .env and active in memory!")
    return f"✅ Saved **{clean_p}** key to `.env` and active in memory!"


def handle_save_single_key(provider_name: str, key_env_var: str, key_val: str) -> str:
    """Saves an individual provider key from Tab 3 directly to .env."""
    val = key_val.strip() if key_val else ""
    if not val:
        gr.Warning(f"Please enter a key for {provider_name} before saving.")
        return f"⚠️ No key entered for {provider_name}."
    save_single_key(key_env_var, val)
    gr.Info(f"✅ Saved {provider_name} API key to .env & active in memory!")
    return f"✅ Saved **{provider_name}** key to `.env`!"


def handle_save_settings(
    openai_k: str,
    gemini_k: str,
    anthropic_k: str,
    groq_k: str,
    xai_k: str,
    nvidia_k: str,
    opencode_url: str,
    opencode_k: str,
    opencode_model: str,
) -> str:
    """Persists updated keys and endpoints to .env file and reloads into memory."""
    try:
        save_keys_to_env({
            "OPENAI_API_KEY": openai_k,
            "GEMINI_API_KEY": gemini_k,
            "ANTHROPIC_API_KEY": anthropic_k,
            "GROQ_API_KEY": groq_k,
            "XAI_API_KEY": xai_k,
            "NVIDIA_API_KEY": nvidia_k,
            "OPENCODE_BASE_URL": opencode_url,
            "OPENCODE_API_KEY": opencode_k,
            "OPENCODE_MODEL": opencode_model,
        }, overwrite_empty=False)
        gr.Info("✅ All provided API keys and endpoints were saved to .env!")
        return "✅ **Success!** All configured API keys and custom endpoints were saved to `.env` and loaded into active memory."
    except Exception as exc:
        return f"❌ Failed to save keys: {exc}"


def handle_test_key(provider: str, key_val: str, extra_param: str | None = None) -> str:
    """Executes a live verification check against the target provider."""
    ok, msg = test_provider_connection(provider, key_val, base_url=extra_param)
    return msg


def reset_video_state() -> tuple:
    """Resets UI output components and session state when user clears or uploads new video (Audit Point 16)."""
    return (
        None,                                                  # out_master_video
        gr.update(choices=[], value=None, interactive=False),  # dropdown_takes
        None,                                                  # out_take_preview
        "*Upload a video and click 'Cut, Transcribe & Burn' to generate your edit manifest.*",  # out_manifest
        None,                                                  # out_zip_file
        {},                                                    # state_takes_map
        "",                                                    # txt_transcript
        [],                                                    # state_segments
        0.0,                                                   # state_duration
    )


# Clipboard copy helpers
def get_raw_titles(titles_md: str) -> str:
    lines = [line.replace("**", "").strip() for line in titles_md.splitlines() if line and line[0].isdigit()]
    return "\n".join(lines)


def get_raw_hook(hook_md: str) -> str:
    parts = hook_md.split("\n\n", 1)
    return parts[1].strip() if len(parts) > 1 else hook_md


def get_raw_chapters(chapters_md: str) -> str:
    lines = []
    for line in chapters_md.splitlines():
        if line.startswith("- `"):
            # Extract `MM:SS` Title
            clean = line.replace("- `", "").replace("`", "").strip()
            lines.append(clean)
    return "\n".join(lines)


def get_raw_tags(tags_md: str) -> str:
    tags_line = ""
    for line in tags_md.splitlines():
        if "**Tags:**" in line:
            tags_line = line.split("`")[1] if "`" in line else line
    return tags_line


# Build Gradio UI
CUSTOM_CSS = """
.container { max-width: 1280px; margin: 0 auto; }
.hero-header { text-align: center; margin-bottom: 20px; }
.hero-header h1 { font-size: 2.2rem; font-weight: 800; margin-bottom: 6px; }
.hero-header p { font-size: 1.05rem; opacity: 0.8; }
.status-box { padding: 10px 14px; border-radius: 8px; margin-bottom: 12px; font-weight: 500; }
"""

def build_app() -> gr.Blocks:
    """Constructs and returns the Gradio Blocks application."""
    with gr.Blocks(title="AutoChop AI Studio (v2)") as demo:
        # App State
        state_takes_map = gr.State({})
        state_transcript = gr.State("")
        state_segments = gr.State([])
        state_duration = gr.State(0.0)

        # Header
        with gr.Column(elem_classes=["hero-header"]):
            gr.Markdown(
                "# ⚡ AutoChop AI Studio\n"
                "Automated post-production studio: dead-air stripping, faster-whisper transcription, "
                "styled social captions, jump-cut assembly & YouTube chapter studio."
            )
            if not FFMPEG_AVAILABLE:
                gr.Markdown(f"> [!WARNING]\n> {FFMPEG_STATUS_MSG}")

        # Tabs
        with gr.Tabs():
            # TAB 1: Cuts & Captions
            with gr.TabItem("✂️ Video Cuts & Captions"):
                with gr.Row():
                    # Left Column: Inputs & Tunables
                    with gr.Column(scale=5):
                        input_video = gr.Video(
                            label="Upload Raw Video Footage",
                            sources=["upload"],
                            interactive=True,
                        )

                        with gr.Accordion("⚙️ Processing Settings", open=True):
                            slider_silence_thresh = gr.Slider(
                                minimum=-50.0,
                                maximum=-15.0,
                                value=DEFAULT_SILENCE_THRESH_DB,
                                step=1.0,
                                label="Silence Detection Threshold (dB)",
                                info="Audio below this level is classified as dead air (default: -30dB).",
                            )
                            slider_min_silence = gr.Slider(
                                minimum=0.2,
                                maximum=2.0,
                                value=DEFAULT_MIN_SILENCE_SEC,
                                step=0.1,
                                label="Minimum Silence Duration (seconds)",
                                info="Pauses shorter than this will be kept (default: 0.5s).",
                            )
                            dropdown_whisper = gr.Dropdown(
                                choices=SUPPORTED_WHISPER_MODELS,
                                value=DEFAULT_WHISPER_MODEL,
                                label="Whisper Transcription Model",
                                info="Model size. tiny/base/small run quickly on CPU; medium/large-v3 require 4GB+ RAM and take longer.",
                            )
                            checkbox_burn = gr.Checkbox(
                                value=True,
                                label="Burn Social Media Captions Onto Takes",
                                info="Hardcode styled ASS subtitles onto each slice.",
                            )
                            dropdown_preset = gr.Dropdown(
                                choices=list(SUBTITLE_PRESETS.keys()),
                                value=DEFAULT_SUBTITLE_PRESET,
                                label="Caption Style Preset",
                                info="High-contrast ASS subtitle typography preset.",
                            )
                            dropdown_resolution = gr.Dropdown(
                                choices=SUPPORTED_RESOLUTIONS,
                                value=DEFAULT_MAX_RESOLUTION,
                                label="Max Output Resolution",
                                info="Auto-downscale high-res/4K screen recordings for 4x faster processing.",
                            )

                        btn_process = gr.Button(
                            "🎬 Cut, Transcribe & Burn",
                            variant="primary",
                            size="lg",
                        )

                    # Right Column: Outputs
                    with gr.Column(scale=6):
                        out_master_video = gr.Video(
                            label="Master Jump-Cut Rough Video",
                            interactive=False,
                        )

                        with gr.Accordion("🔎 Take Inspector (Preview Individual Takes)", open=False):
                            dropdown_takes = gr.Dropdown(
                                label="Select Take to Preview",
                                choices=[],
                                interactive=False,
                            )
                            out_take_preview = gr.Video(
                                label="Take Preview Player",
                                interactive=False,
                            )

                        out_manifest = gr.Markdown(
                            value="*Upload a video and click 'Cut, Transcribe & Burn' to generate your edit manifest.*",
                            label="Edit Manifest",
                        )

                        out_zip_file = gr.File(
                            label="📦 Download Complete Project Bundle (.zip)",
                            interactive=False,
                        )

            # TAB 2: Metadata & Title Studio
            with gr.TabItem("🚀 Title & Chapter Studio"):
                with gr.Row():
                    # Left Column: Provider & Transcript
                    with gr.Column(scale=5):
                        radio_provider = gr.Radio(
                            choices=SUPPORTED_METADATA_PROVIDERS,
                            value="Local Heuristic (No Key)",
                            label="Metadata Generator Engine",
                            info="Choose an AI provider (OpenAI, Gemini, Claude, Groq, Grok, NVIDIA, OpenCode) or local heuristic.",
                        )
                        with gr.Row():
                            txt_api_key = gr.Textbox(
                                type="password",
                                label="API Key",
                                placeholder="Enter API Key...",
                                visible=False,
                                scale=8,
                            )
                            btn_save_tab2_key = gr.Button(
                                "💾 Save Key",
                                size="sm",
                                visible=False,
                                scale=3,
                            )
                        status_save_tab2 = gr.Markdown()
                        txt_custom_url = gr.Textbox(
                            label="Custom Endpoint Base URL",
                            value="http://localhost:11434/v1",
                            placeholder="http://localhost:11434/v1",
                            visible=False,
                        )
                        txt_custom_model = gr.Textbox(
                            label="Custom Model Name",
                            value="llama3.3",
                            placeholder="llama3.3",
                            visible=False,
                        )
                        txt_transcript = gr.Textbox(
                            lines=12,
                            label="Spoken Transcript",
                            placeholder="Auto-populated from Tab 1, or paste a transcript manually...",
                            interactive=True,
                        )
                        btn_generate_meta = gr.Button(
                            "✨ Generate Titles, Description & Chapters",
                            variant="primary",
                            size="lg",
                        )

                    # Right Column: Metadata Cards & Copy Actions
                    with gr.Column(scale=6):
                        out_notice = gr.Markdown()
                        out_titles_card = gr.Markdown()
                        btn_copy_titles = gr.Button("📋 Copy Titles to Clipboard", size="sm")

                        out_hook_card = gr.Markdown()
                        btn_copy_hook = gr.Button("📋 Copy Description to Clipboard", size="sm")

                        out_chapters_card = gr.Markdown()
                        btn_copy_chapters = gr.Button("📋 Copy YouTube Chapters to Clipboard", size="sm")

                        out_tags_card = gr.Markdown()
                        btn_copy_tags = gr.Button("📋 Copy SEO Tags to Clipboard", size="sm")

            # TAB 3: API Keys & Provider Settings
            with gr.TabItem("🔑 API Keys & Settings"):
                initial_keys = load_all_keys()
                gr.Markdown(
                    "## 🔑 Master API Key & Provider Configuration\n"
                    "Configure and save your API keys below. All keys are securely stored in your local `.env` file "
                    "and loaded into memory for real-time inference across tabs. You can save individually or all at once."
                )

                with gr.Row():
                    with gr.Column(scale=6):
                        gr.Markdown("### 🌟 Leading Cloud Providers")
                        set_openai = gr.Textbox(
                            label="OpenAI API Key (sk-...)",
                            type="password",
                            value=initial_keys.get("OPENAI_API_KEY", ""),
                            placeholder="sk-proj-...",
                        )
                        with gr.Row():
                            btn_test_openai = gr.Button("🧪 Test", size="sm")
                            btn_save_openai = gr.Button("💾 Save", size="sm", variant="secondary")
                        status_test_openai = gr.Markdown()

                        set_gemini = gr.Textbox(
                            label="Google Gemini API Key (AIzaSy...)",
                            type="password",
                            value=initial_keys.get("GEMINI_API_KEY", ""),
                            placeholder="AIzaSy...",
                        )
                        with gr.Row():
                            btn_test_gemini = gr.Button("🧪 Test", size="sm")
                            btn_save_gemini = gr.Button("💾 Save", size="sm", variant="secondary")
                        status_test_gemini = gr.Markdown()

                        set_anthropic = gr.Textbox(
                            label="Anthropic Claude API Key (sk-ant-...)",
                            type="password",
                            value=initial_keys.get("ANTHROPIC_API_KEY", ""),
                            placeholder="sk-ant-...",
                        )
                        with gr.Row():
                            btn_test_anthropic = gr.Button("🧪 Test", size="sm")
                            btn_save_anthropic = gr.Button("💾 Save", size="sm", variant="secondary")
                        status_test_anthropic = gr.Markdown()

                    with gr.Column(scale=6):
                        gr.Markdown("### ⚡ Fast Inference & Open Weights")
                        set_groq = gr.Textbox(
                            label="GroqCloud API Key (gsk_...)",
                            type="password",
                            value=initial_keys.get("GROQ_API_KEY", ""),
                            placeholder="gsk_...",
                        )
                        with gr.Row():
                            btn_test_groq = gr.Button("🧪 Test", size="sm")
                            btn_save_groq = gr.Button("💾 Save", size="sm", variant="secondary")
                        status_test_groq = gr.Markdown()

                        set_xai = gr.Textbox(
                            label="xAI Grok API Key (xai-...)",
                            type="password",
                            value=initial_keys.get("XAI_API_KEY", ""),
                            placeholder="xai-...",
                        )
                        with gr.Row():
                            btn_test_xai = gr.Button("🧪 Test", size="sm")
                            btn_save_xai = gr.Button("💾 Save", size="sm", variant="secondary")
                        status_test_xai = gr.Markdown()

                        set_nvidia = gr.Textbox(
                            label="NVIDIA NIM API Key (nvapi-...)",
                            type="password",
                            value=initial_keys.get("NVIDIA_API_KEY", ""),
                            placeholder="nvapi-...",
                        )
                        with gr.Row():
                            btn_test_nvidia = gr.Button("🧪 Test", size="sm")
                            btn_save_nvidia = gr.Button("💾 Save", size="sm", variant="secondary")
                        status_test_nvidia = gr.Markdown()

                with gr.Accordion("💻 OpenCode / Ollama / Local Custom OpenAI-Compatible Endpoints", open=False):
                    with gr.Row():
                        set_opencode_url = gr.Textbox(
                            label="Custom Base URL",
                            value=initial_keys.get("OPENCODE_BASE_URL", "http://localhost:11434/v1"),
                            placeholder="http://localhost:11434/v1",
                        )
                        set_opencode_key = gr.Textbox(
                            label="API Key (Optional for local)",
                            type="password",
                            value=initial_keys.get("OPENCODE_API_KEY", ""),
                            placeholder="Optional key...",
                        )
                        set_opencode_model = gr.Textbox(
                            label="Model Name",
                            value=initial_keys.get("OPENCODE_MODEL", "llama3.3"),
                            placeholder="llama3.3",
                        )
                    with gr.Row():
                        btn_test_opencode = gr.Button("🧪 Test Custom Endpoint", size="sm")
                        btn_save_opencode = gr.Button("💾 Save Custom Endpoint", size="sm", variant="secondary")
                    status_test_opencode = gr.Markdown()

                btn_save_all = gr.Button("💾 Save All Keys to .env", variant="primary", size="lg")
                status_save_all = gr.Markdown()

        # Event Wiring: Tab 1 Process
        btn_process.click(
            fn=process_video_cuts,
            inputs=[
                input_video,
                slider_silence_thresh,
                slider_min_silence,
                dropdown_whisper,
                checkbox_burn,
                dropdown_preset,
                dropdown_resolution,
            ],
            outputs=[
                out_master_video,
                dropdown_takes,
                out_take_preview,
                out_manifest,
                out_zip_file,
                state_takes_map,
                txt_transcript,
                state_segments,
                state_duration,
            ],
        )

        # Event Wiring: Video Re-upload & Clear state reset (Audit Point 16)
        reset_outputs = [
            out_master_video,
            dropdown_takes,
            out_take_preview,
            out_manifest,
            out_zip_file,
            state_takes_map,
            txt_transcript,
            state_segments,
            state_duration,
        ]
        input_video.clear(fn=reset_video_state, inputs=[], outputs=reset_outputs)
        input_video.upload(fn=reset_video_state, inputs=[], outputs=reset_outputs)

        # Event Wiring: Take Inspector Dropdown
        dropdown_takes.change(
            fn=update_take_preview,
            inputs=[dropdown_takes, state_takes_map],
            outputs=[out_take_preview],
        )

        # Event Wiring: Provider API Key Visibility Toggle
        radio_provider.change(
            fn=update_api_key_visibility,
            inputs=[radio_provider],
            outputs=[txt_api_key, btn_save_tab2_key, txt_custom_url, txt_custom_model],
        )

        # Event Wiring: Save key directly from Tab 2
        btn_save_tab2_key.click(
            fn=handle_save_tab2_key,
            inputs=[radio_provider, txt_api_key],
            outputs=[status_save_tab2],
        )

        # Event Wiring: Tab 2 Metadata Generation
        btn_generate_meta.click(
            fn=process_metadata_generation,
            inputs=[
                txt_transcript,
                radio_provider,
                txt_api_key,
                state_segments,
                state_duration,
                txt_custom_url,
                txt_custom_model,
            ],
            outputs=[
                out_notice,
                out_titles_card,
                out_hook_card,
                out_chapters_card,
                out_tags_card,
            ],
        )

        # Event Wiring: Tab 3 Settings & Key Testing / Saving
        btn_save_all.click(
            fn=handle_save_settings,
            inputs=[
                set_openai,
                set_gemini,
                set_anthropic,
                set_groq,
                set_xai,
                set_nvidia,
                set_opencode_url,
                set_opencode_key,
                set_opencode_model,
            ],
            outputs=[status_save_all],
        )

        btn_test_openai.click(
            fn=lambda k: handle_test_key("OpenAI", k),
            inputs=[set_openai],
            outputs=[status_test_openai],
        )
        btn_save_openai.click(
            fn=lambda k: handle_save_single_key("OpenAI", "OPENAI_API_KEY", k),
            inputs=[set_openai],
            outputs=[status_test_openai],
        )

        btn_test_gemini.click(
            fn=lambda k: handle_test_key("Gemini", k),
            inputs=[set_gemini],
            outputs=[status_test_gemini],
        )
        btn_save_gemini.click(
            fn=lambda k: handle_save_single_key("Gemini", "GEMINI_API_KEY", k),
            inputs=[set_gemini],
            outputs=[status_test_gemini],
        )

        btn_test_anthropic.click(
            fn=lambda k: handle_test_key("Anthropic (Claude)", k),
            inputs=[set_anthropic],
            outputs=[status_test_anthropic],
        )
        btn_save_anthropic.click(
            fn=lambda k: handle_save_single_key("Anthropic (Claude)", "ANTHROPIC_API_KEY", k),
            inputs=[set_anthropic],
            outputs=[status_test_anthropic],
        )

        btn_test_groq.click(
            fn=lambda k: handle_test_key("Groq (Ultra-Fast)", k),
            inputs=[set_groq],
            outputs=[status_test_groq],
        )
        btn_save_groq.click(
            fn=lambda k: handle_save_single_key("Groq", "GROQ_API_KEY", k),
            inputs=[set_groq],
            outputs=[status_test_groq],
        )

        btn_test_xai.click(
            fn=lambda k: handle_test_key("Grok (xAI)", k),
            inputs=[set_xai],
            outputs=[status_test_xai],
        )
        btn_save_xai.click(
            fn=lambda k: handle_save_single_key("xAI Grok", "XAI_API_KEY", k),
            inputs=[set_xai],
            outputs=[status_test_xai],
        )

        btn_test_nvidia.click(
            fn=lambda k: handle_test_key("NVIDIA NIM", k),
            inputs=[set_nvidia],
            outputs=[status_test_nvidia],
        )
        btn_save_nvidia.click(
            fn=lambda k: handle_save_single_key("NVIDIA NIM", "NVIDIA_API_KEY", k),
            inputs=[set_nvidia],
            outputs=[status_test_nvidia],
        )

        btn_test_opencode.click(
            fn=lambda k, u: handle_test_key("OpenCode / Custom Endpoint", k, u),
            inputs=[set_opencode_key, set_opencode_url],
            outputs=[status_test_opencode],
        )
        btn_save_opencode.click(
            fn=lambda u, k, m: handle_save_settings("", "", "", "", "", "", u, k, m),
            inputs=[set_opencode_url, set_opencode_key, set_opencode_model],
            outputs=[status_test_opencode],
        )

        # Copy to clipboard buttons using Gradio JavaScript API
        btn_copy_titles.click(
            fn=get_raw_titles,
            inputs=[out_titles_card],
            outputs=[],
            js="(text) => { navigator.clipboard.writeText(text); alert('Titles copied to clipboard!'); }",
        )
        btn_copy_hook.click(
            fn=get_raw_hook,
            inputs=[out_hook_card],
            outputs=[],
            js="(text) => { navigator.clipboard.writeText(text); alert('Description copied to clipboard!'); }",
        )
        btn_copy_chapters.click(
            fn=get_raw_chapters,
            inputs=[out_chapters_card],
            outputs=[],
            js="(text) => { navigator.clipboard.writeText(text); alert('YouTube chapters copied to clipboard!'); }",
        )
        btn_copy_tags.click(
            fn=get_raw_tags,
            inputs=[out_tags_card],
            outputs=[],
            js="(text) => { navigator.clipboard.writeText(text); alert('SEO tags copied to clipboard!'); }",
        )

    return demo


def main():
    """Application entry point."""
    port = int(os.getenv("PORT", "7860"))
    demo = build_app()
    allowed_dirs = [
        str(TEMP_DIR_ROOT.resolve()),
        str(Path.home() / ".autochop"),
        str(Path.cwd().resolve()),
        str(Path(tempfile.gettempdir()).resolve()),
    ]
    demo.queue(default_concurrency_limit=5).launch(
        server_name="0.0.0.0",
        server_port=port,
        share=False,
        theme=gr.themes.Default(),
        css=CUSTOM_CSS,
        allowed_paths=allowed_dirs,
    )


if __name__ == "__main__":
    main()

