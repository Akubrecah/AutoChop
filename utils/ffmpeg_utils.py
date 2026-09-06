"""
AutoChop AI Studio - FFmpeg Utilities
Provides robust subprocess execution, binary verification with actionable error messages,
filter path escaping, and media stream probing.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from autochop.config import SUBPROCESS_TIMEOUT_SEC

logger = logging.getLogger("autochop.ffmpeg_utils")


def find_binary(binary_name: str) -> str | None:
    """
    Locates an executable binary across standard PATH, common OS install locations,
    or via static_ffmpeg if available.
    """
    # 1. Check system PATH
    found = shutil.which(binary_name)
    if found:
        return found

    # 2. Check static_ffmpeg package paths if installed
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        found = shutil.which(binary_name)
        if found:
            return found
    except Exception:
        pass

    # 3. Check common Unix/macOS locations
    common_paths = [
        Path("/opt/homebrew/bin") / binary_name,
        Path("/usr/local/bin") / binary_name,
        Path("/usr/bin") / binary_name,
        Path.home() / ".local" / "bin" / binary_name,
    ]
    for p in common_paths:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)

    return None


def verify_ffmpeg_installed() -> tuple[str, str]:
    """
    Ensures both ffmpeg and ffprobe are available.
    Raises a clean, actionable RuntimeError with installation instructions if missing.
    """
    ffmpeg_path = find_binary("ffmpeg")
    ffprobe_path = find_binary("ffprobe")

    missing = []
    if not ffmpeg_path:
        missing.append("ffmpeg")
    if not ffprobe_path:
        missing.append("ffprobe")

    if missing:
        os_type = platform.system().lower()
        if "darwin" in os_type:
            install_cmd = "brew install ffmpeg"
        elif "linux" in os_type:
            install_cmd = "sudo apt update && sudo apt install -y ffmpeg"
        elif "windows" in os_type:
            install_cmd = "winget install Gyan.FFmpeg"
        else:
            install_cmd = "install ffmpeg from https://ffmpeg.org/download.html"

        msg = (
            f"\n[AutoChop Error] Required media engine binary missing: {', '.join(missing)}\n"
            f"FFmpeg and FFprobe are required to process audio and video.\n"
            f"Please install them via terminal:\n"
            f"    {install_cmd}\n"
            f"After installation, ensure the binaries are in your PATH and restart the application."
        )
        raise RuntimeError(msg)

    return ffmpeg_path, ffprobe_path


def is_ffmpeg_available() -> bool:
    """
    Returns True if both ffmpeg and ffprobe are available, False otherwise.
    Safe non-throwing check for graceful degradation and pre-flight tests.
    """
    try:
        verify_ffmpeg_installed()
        return True
    except Exception:
        return False


def run_ffmpeg(
    cmd: list[str],
    timeout: int = SUBPROCESS_TIMEOUT_SEC,
    check: bool = True,
    log_errors: bool = True,
) -> subprocess.CompletedProcess[str]:
    """
    Executes an FFmpeg or FFprobe command via subprocess with timeout protection.
    Raises RuntimeError on non-zero exit code if check=True.
    """
    cmd_str = " ".join(str(c) for c in cmd)
    logger.debug(f"Running command: {cmd_str}")

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        err_msg = f"FFmpeg command timed out after {timeout} seconds: {cmd_str}"
        logger.error(err_msg)
        raise TimeoutError(err_msg) from exc
    except Exception as exc:
        logger.error(f"Failed to execute FFmpeg command: {cmd_str}\nError: {exc}")
        raise

    if check and proc.returncode != 0:
        # Extract last 10 lines of stderr for clean reporting
        stderr_tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        err_msg = (
            f"FFmpeg execution failed (exit code {proc.returncode}).\n"
            f"Command: {cmd[0]} ...\n"
            f"Details:\n{stderr_tail}"
        )
        if log_errors:
            logger.error(err_msg)
        raise RuntimeError(err_msg)

    return proc


def escape_filter_path(file_path: str | Path) -> str:
    r"""
    Escapes a filesystem path for inclusion within FFmpeg filter arguments (e.g. subtitles=filename).
    Handles colons (:), backslashes (\), and single quotes (') for cross-platform compatibility.
    """
    resolved = Path(file_path).resolve().as_posix()
    # In FFmpeg filter syntax, colons separate arguments, backslashes escape characters.
    # Single quotes need escaping: ' -> '\''
    escaped = resolved.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return escaped


def probe_media_info(file_path: str | Path) -> dict[str, Any]:
    """
    Probes video/audio stream properties using ffprobe.
    Returns a dictionary containing duration, width, height, fps, vcodec, and acodec.
    """
    _, ffprobe_bin = verify_ffmpeg_installed()
    target_path = Path(file_path).resolve().as_posix()

    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        target_path,
    ]

    proc = run_ffmpeg(cmd, timeout=30, check=True)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Unable to parse ffprobe output for {file_path}") from exc

    format_info = data.get("format", {})
    streams = data.get("streams", [])

    duration = float(format_info.get("duration", 0.0))
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0
    vcodec = video_stream.get("codec_name", "") if video_stream else ""
    acodec = audio_stream.get("codec_name", "") if audio_stream else ""

    # Parse framerate (e.g. "30/1" or "29.97")
    fps = 0.0
    if video_stream and "r_frame_rate" in video_stream:
        r_rate = video_stream["r_frame_rate"]
        if "/" in r_rate:
            num, den = r_rate.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 0.0
        else:
            fps = float(r_rate)

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "vcodec": vcodec,
        "acodec": acodec,
    }


def validate_media_file(file_path: str | Path) -> dict[str, Any]:
    """
    Validates that a given file exists, is non-empty, and represents a readable media container
    with valid audio and/or video streams.
    Raises ValueError with descriptive actionable error messages on corrupt or unsupported media.
    Returns probed media properties.
    """
    p = Path(file_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Media file not found: {file_path}")
    if p.stat().st_size == 0:
        raise ValueError(f"Uploaded file is empty (0 bytes): {p.name}")

    # Check common media extension
    valid_exts = {
        ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".ts",
        ".mp3", ".wav", ".aac", ".m4a", ".ogg", ".opus"
    }
    if p.suffix.lower() not in valid_exts:
        logger.warning(f"Uncommon file extension {p.suffix} for {p.name}; verifying with ffprobe...")

    try:
        info = probe_media_info(p)
    except Exception as exc:
        raise ValueError(
            f"Invalid or corrupted media file '{p.name}'. "
            f"FFprobe could not read the container or stream headers: {exc}"
        ) from exc

    duration = info.get("duration", 0.0)
    if duration <= 0:
        raise ValueError(
            f"Media file '{p.name}' has invalid duration ({duration}s). The file may be incomplete or corrupt."
        )

    if not info.get("acodec") and not info.get("vcodec"):
        raise ValueError(
            f"Media file '{p.name}' contains no readable audio or video tracks."
        )

    return info
