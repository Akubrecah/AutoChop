"""
AutoChop AI Studio - Environment & API Key Management Utility
Provides secure read/write persistence for API keys and configuration in .env.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, set_key

logger = logging.getLogger("autochop.env_utils")

ENV_FILE_PATH = Path(__file__).resolve().parent.parent / ".env"


def get_env_path() -> Path:
    """Returns resolved path to the project's .env file, creating it if absent."""
    if not ENV_FILE_PATH.exists():
        example_path = ENV_FILE_PATH.parent / ".env.example"
        if example_path.exists():
            import shutil
            shutil.copy2(example_path, ENV_FILE_PATH)
        else:
            ENV_FILE_PATH.touch()
    return ENV_FILE_PATH


def load_all_keys() -> dict[str, str]:
    """Reads all current environment variables from .env and os.environ."""
    env_p = get_env_path()
    file_values = dotenv_values(env_p)

    keys = [
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GROQ_API_KEY",
        "XAI_API_KEY",
        "NVIDIA_API_KEY",
        "OPENCODE_BASE_URL",
        "OPENCODE_API_KEY",
        "OPENCODE_MODEL",
    ]

    result: dict[str, str] = {}
    for k in keys:
        # Prioritize os.environ if set, else .env file
        val = os.getenv(k, file_values.get(k, "") or "")
        result[k] = val.strip()

    return result


def save_keys_to_env(new_values: dict[str, str], overwrite_empty: bool = False) -> None:
    """
    Saves updated keys directly to .env and synchronizes os.environ in real-time.
    If overwrite_empty is False, empty string values will not erase existing configured keys.
    """
    env_p = get_env_path()
    current = load_all_keys()

    for k, v in new_values.items():
        clean_v = str(v).strip()
        if not clean_v and not overwrite_empty and current.get(k):
            # Skip erasing existing key if user didn't enter a new one
            continue
        set_key(env_p, k, clean_v)
        os.environ[k] = clean_v
        logger.info(f"Updated key {k} in .env and runtime environment.")


def save_single_key(key_name: str, value: str) -> None:
    """Saves a single environment variable to .env and memory immediately."""
    env_p = get_env_path()
    clean_v = str(value).strip()
    set_key(env_p, key_name, clean_v)
    os.environ[key_name] = clean_v
    logger.info(f"Persisted single key {key_name} to .env and os.environ.")


def save_key_for_provider(provider: str, api_key: str) -> bool:
    """Maps provider name to corresponding environment key and persists it."""
    clean_p = provider.strip()
    key_map = {
        "OpenAI": "OPENAI_API_KEY",
        "Gemini": "GEMINI_API_KEY",
        "Anthropic (Claude)": "ANTHROPIC_API_KEY",
        "Groq (Ultra-Fast)": "GROQ_API_KEY",
        "Grok (xAI)": "XAI_API_KEY",
        "NVIDIA NIM": "NVIDIA_API_KEY",
        "OpenCode / Custom Endpoint": "OPENCODE_API_KEY",
    }
    env_var = key_map.get(clean_p)
    if env_var and api_key:
        save_single_key(env_var, api_key)
        return True
    return False


def get_key_for_provider(provider: str) -> str:
    """Returns the configured API key for the given provider string."""
    clean_p = provider.strip()
    keys = load_all_keys()

    if clean_p == "OpenAI":
        return keys.get("OPENAI_API_KEY", "")
    elif clean_p == "Gemini":
        return keys.get("GEMINI_API_KEY", "")
    elif clean_p == "Anthropic (Claude)":
        return keys.get("ANTHROPIC_API_KEY", "")
    elif clean_p == "Groq (Ultra-Fast)":
        return keys.get("GROQ_API_KEY", "")
    elif clean_p == "Grok (xAI)":
        return keys.get("XAI_API_KEY", "")
    elif clean_p == "NVIDIA NIM":
        return keys.get("NVIDIA_API_KEY", "")
    elif clean_p == "OpenCode / Custom Endpoint":
        return keys.get("OPENCODE_API_KEY", "")
    return ""

