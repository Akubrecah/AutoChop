"""
Integration tests for AutoChop AI Studio
Uses FFmpeg to programmatically synthesize a test video with known audio beeps
and silence pauses, then executes the full pipeline end-to-end.
"""

from pathlib import Path
import pytest

from autochop.core.assembly import (
    assemble_master_video,
    generate_edit_manifest,
    slice_take,
)
from autochop.core.audio import (
    calculate_active_segments,
    detect_silence,
    extract_audio,
    get_video_duration,
)
from autochop.core.metadata import generate_heuristic_metadata
from autochop.core.transcription import burn_subtitles, write_srt
from autochop.utils.ffmpeg_utils import is_ffmpeg_available, run_ffmpeg, verify_ffmpeg_installed
from autochop.utils.file_utils import create_export_zip


def create_synthetic_test_video(output_path: Path) -> Path:
    """
    Synthesizes a 6-second test MP4 video with FFmpeg:
    - 0.0s - 2.0s: 440Hz audible sine beep
    - 2.0s - 3.5s: dead silence (1.5s pause)
    - 3.5s - 5.5s: 660Hz audible sine beep
    - 5.5s - 6.0s: dead silence (0.5s pause)
    """
    ffmpeg_bin, _ = verify_ffmpeg_installed()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Audio filter generates tone -> silence -> tone -> silence
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", "color=c=blue:s=320x240:d=6:r=25",
        "-f", "lavfi",
        "-i", "sine=f=440:d=6",
        "-filter_complex", "[1:a]volume=enable='between(t,2,3.5)+between(t,5.5,6)':volume=0[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "aac",
        output_path.as_posix(),
    ]

    run_ffmpeg(cmd, timeout=30, check=True)
    return output_path


@pytest.mark.skipif(
    not is_ffmpeg_available(),
    reason="FFmpeg/FFprobe binaries must be installed and in PATH to run synthetic media integration tests",
)
def test_full_pipeline_synthetic_video(tmp_path: Path):
    """
    Executes the full AutoChop pipeline against the synthetic test video.
    """
    # 1. Synthesize media
    raw_video = tmp_path / "raw_synthetic.mp4"
    create_synthetic_test_video(raw_video)
    assert raw_video.exists()

    # 2. Get duration
    dur = get_video_duration(raw_video)
    assert pytest.approx(dur, abs=0.2) == 6.0

    # 3. Extract audio
    wav_path = tmp_path / "audio.wav"
    extract_audio(raw_video, wav_path)
    assert wav_path.exists()
    assert wav_path.stat().st_size > 0

    # 4. Silence detection
    silences = detect_silence(wav_path, noise_threshold="-25dB", min_duration=0.5, total_duration=dur)
    assert len(silences) >= 1

    # 5. Active speech segments
    active_segs = calculate_active_segments(
        silences,
        total_duration=dur,
        padding=0.1,
        min_gap=0.2,
        min_length=0.3,
    )
    assert len(active_segs) == 2, f"Expected 2 takes, got {len(active_segs)}: {active_segs}"

    # 6. Slicing takes & writing SRTs
    takes_dir = tmp_path / "takes"
    srt_dir = tmp_path / "subtitles"
    takes_dir.mkdir(exist_ok=True)
    srt_dir.mkdir(exist_ok=True)

    take_paths = []
    srt_paths = []
    takes_meta = []

    for idx, (s, e) in enumerate(active_segs, 1):
        t_path = takes_dir / f"take_{idx:03d}.mp4"
        slice_take(raw_video, s, e - s, t_path)
        assert t_path.exists()

        s_path = srt_dir / f"take_{idx:03d}.srt"
        fake_transcript = [{"start": s + 0.1, "end": e - 0.1, "text": f"Simulated Dialogue {idx}"}]
        write_srt(s_path, clip_start=s, clip_transcript=fake_transcript)
        assert s_path.exists()

        # Burn subtitles
        burned_path = takes_dir / f"take_{idx:03d}_burned.mp4"
        burn_subtitles(t_path, s_path, burned_path, style_preset="TikTok Yellow Box")
        assert burned_path.exists()

        take_paths.append(burned_path)
        srt_paths.append(s_path)
        takes_meta.append({
            "index": idx,
            "filename": burned_path.name,
            "start": s,
            "end": e,
            "size_bytes": burned_path.stat().st_size,
            "transcript_preview": f"Simulated Dialogue {idx}",
        })

    # 7. Assemble master video
    master_path = tmp_path / "master.mp4"
    assemble_master_video(take_paths, master_path, temp_dir=tmp_path)
    assert master_path.exists()
    assert master_path.stat().st_size > 0

    # 8. Manifest
    manifest_file = tmp_path / "manifest.md"
    manifest_md = generate_edit_manifest(takes_meta, output_markdown_path=manifest_file)
    assert manifest_file.exists()
    assert "Take 01" in manifest_md
    assert "Take 02" in manifest_md

    # 9. ZIP bundle
    zip_path = tmp_path / "bundle.zip"
    create_export_zip(
        zip_output_path=zip_path,
        take_paths=take_paths,
        srt_paths=srt_paths,
        manifest_path=manifest_file,
        master_path=master_path,
    )
    assert zip_path.exists()
    assert zip_path.stat().st_size > 0

    # 10. Metadata generator
    full_transcript = "Simulated Dialogue 1. Next we discuss simulated dialogue 2."
    meta = generate_heuristic_metadata(full_transcript, total_duration=dur)
    assert len(meta["titles"]) == 3
    assert len(meta["chapters"]) >= 3
    assert meta["chapters"][0]["timestamp"] == "00:00"
