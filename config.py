"""
AutoChop AI Studio - Configuration & Constants
Defines application defaults, tunables, subtitle styles, and environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent
TEMP_DIR_ROOT = Path(os.getenv("AUTOCHOP_TEMP_DIR", Path(tempfile.gettempdir()) / "autochop"))

# Processing defaults
DEFAULT_SILENCE_THRESH_DB: float = float(os.getenv("AUTOCHOP_SILENCE_THRESH_DB", "-26.0"))
DEFAULT_MIN_SILENCE_SEC: float = float(os.getenv("AUTOCHOP_MIN_SILENCE_SEC", "0.4"))
DEFAULT_PADDING_SEC: float = float(os.getenv("AUTOCHOP_PADDING_SEC", "0.08"))
DEFAULT_MIN_GAP_SEC: float = float(os.getenv("AUTOCHOP_MIN_GAP_SEC", "0.05"))
DEFAULT_MIN_SEGMENT_SEC: float = float(os.getenv("AUTOCHOP_MIN_SEGMENT_SEC", "0.3"))
DEFAULT_MIN_CUE_DURATION: float = float(os.getenv("AUTOCHOP_MIN_CUE_DURATION", "0.3"))

# Performance & Encoding Defaults
DEFAULT_MAX_RESOLUTION: str = os.getenv("AUTOCHOP_MAX_RESOLUTION", "1080p (Fast - Recommended)")
SUPPORTED_RESOLUTIONS: list[str] = [
    "1080p (Fast - Recommended)",
    "720p (Ultra Fast)",
    "480p (Mobile Fast)",
    "1440p (2K)",
    "Source (Original)",
]
DEFAULT_FFMPEG_PRESET: str = os.getenv("AUTOCHOP_FFMPEG_PRESET", "veryfast")
DEFAULT_CRF: int = int(os.getenv("AUTOCHOP_CRF", "22"))
DEFAULT_AV_SYNC_TOLERANCE_FRAMES: float = 3.0

# Upload constraints (Audit Point 3 & 4: Configurable higher ceilings)
MAX_UPLOAD_SIZE_MB: int = int(os.getenv("AUTOCHOP_MAX_UPLOAD_SIZE_MB", "2048"))  # 2 GB
MAX_VIDEO_DURATION_SEC: float = float(os.getenv("AUTOCHOP_MAX_VIDEO_DURATION_SEC", "3600.0"))  # 60 mins
SUBPROCESS_TIMEOUT_SEC: int = int(os.getenv("AUTOCHOP_SUBPROCESS_TIMEOUT_SEC", "900"))  # 15 mins

# Whisper defaults (Audit Point 5: Expanded models)
DEFAULT_WHISPER_MODEL: str = os.getenv("AUTOCHOP_WHISPER_MODEL", "base")
SUPPORTED_WHISPER_MODELS: list[str] = ["tiny", "base", "small", "medium", "large-v3"]
DEFAULT_COMPUTE_TYPE: str = os.getenv("AUTOCHOP_COMPUTE_TYPE", "int8")

# Logging
LOG_LEVEL: str = os.getenv("AUTOCHOP_LOG_LEVEL", "INFO").upper()

# Subtitle Presets (ASS style definitions - Audit Point 7: Expanded presets)
SUBTITLE_PRESETS: dict[str, dict[str, str | int]] = {
    "TikTok Yellow Box": {
        "font": "Impact",
        "fallback_fonts": ["Arial Black", "Helvetica-Bold", "Arial"],
        "style": (
            "FontName=Impact,FontSize=24,Bold=1,"
            "PrimaryColour=&H0000FFFF,BackColour=&H90000000,"
            "BorderStyle=3,Outline=2,MarginV=60,Alignment=2"
        ),
    },
    "MrBeast Punchy Red": {
        "font": "Impact",
        "fallback_fonts": ["Arial Black", "Helvetica-Bold"],
        "style": (
            "FontName=Impact,FontSize=26,Bold=1,"
            "PrimaryColour=&H000000FF,OutlineColour=&H00FFFFFF,"
            "BorderStyle=1,Outline=3,Shadow=2,MarginV=55,Alignment=2"
        ),
    },
    "Neon Cyber Cyan": {
        "font": "Arial Black",
        "fallback_fonts": ["Helvetica-Bold", "Arial"],
        "style": (
            "FontName=Arial Black,FontSize=22,Bold=1,"
            "PrimaryColour=&H00FFFF00,OutlineColour=&H00000000,"
            "BorderStyle=1,Outline=2,Shadow=1,MarginV=50,Alignment=2"
        ),
    },
    "Classic Closed Caption (Boxed)": {
        "font": "Arial",
        "fallback_fonts": ["Helvetica", "DejaVu Sans"],
        "style": (
            "FontName=Arial,FontSize=20,Bold=0,"
            "PrimaryColour=&H00FFFFFF,BackColour=&H90000000,"
            "BorderStyle=3,Outline=0,MarginV=35,Alignment=2"
        ),
    },
    "Clean Minimalist": {
        "font": "Arial",
        "fallback_fonts": ["Helvetica", "Liberation Sans", "DejaVu Sans"],
        "style": (
            "FontName=Arial,FontSize=20,Bold=1,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            "BorderStyle=1,Outline=2,MarginV=30,Alignment=2"
        ),
    },
    "High-Contrast White": {
        "font": "Arial Black",
        "fallback_fonts": ["Impact", "Helvetica-Bold", "Arial"],
        "style": (
            "FontName=Arial Black,FontSize=22,"
            "PrimaryColour=&H00FFFFFF,BackColour=&H80000000,"
            "BorderStyle=3,Outline=1,MarginV=40,Alignment=2"
        ),
    },
}

DEFAULT_SUBTITLE_PRESET: str = "TikTok Yellow Box"

# LLM Providers & API Keys (Multi-Provider Support)
DEFAULT_OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
DEFAULT_GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
DEFAULT_ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
DEFAULT_GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
DEFAULT_XAI_API_KEY: str = os.getenv("XAI_API_KEY", "")
DEFAULT_NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
DEFAULT_OPENCODE_BASE_URL: str = os.getenv("OPENCODE_BASE_URL", os.getenv("OPENAI_BASE_URL", ""))
DEFAULT_OPENCODE_API_KEY: str = os.getenv("OPENCODE_API_KEY", "")
LLM_TIMEOUT_SEC: int = 30

SUPPORTED_METADATA_PROVIDERS: list[str] = [
    "Local Heuristic (No Key)",
    "Gemini",
    "OpenAI",
    "Anthropic (Claude)",
    "Groq (Ultra-Fast)",
    "Grok (xAI)",
    "NVIDIA NIM",
    "OpenCode / Custom Endpoint",
]
