"""
Unit tests for Module 4: Metadata & Chapter Studio
Verifies zero-key heuristic generation, YouTube chapter formatting requirements,
and schema validation with fallback safety.
"""

from autochop.core.metadata import (
    generate_heuristic_metadata,
    generate_metadata_with_fallback,
    validate_metadata_schema,
)


def test_heuristic_youtube_chapters_compliance():
    """
    Tests YouTube chapter compliance in zero-key heuristic mode:
    1. First chapter starts strictly at 00:00.
    2. Minimum of 3 chapters.
    3. Chapters spaced reasonably apart.
    """
    transcript = (
        "Welcome to the video. Today we are going to explore how video editing works. "
        "In this first segment we will examine silence detection using FFmpeg. "
        "Next, we move into speech transcription with faster whisper and subtitles. "
        "Finally, we stitch the cuts together and generate chapters for YouTube."
    )

    data = generate_heuristic_metadata(transcript, total_duration=90.0)

    # Compliance checks
    chapters = data.get("chapters", [])
    assert len(chapters) >= 3, f"Expected at least 3 chapters, got {len(chapters)}"
    assert chapters[0]["timestamp"] == "00:00", f"First chapter must be 00:00, got {chapters[0]['timestamp']}"

    # Titles check
    titles = data.get("titles", [])
    assert len(titles) == 3
    for t in titles:
        assert len(t) > 10

    # Description and tags
    assert len(data.get("description_hook", "")) > 10
    assert len(data.get("tags", "")) > 0


def test_validate_metadata_schema_fallbacks():
    """
    Tests validate_metadata_schema repairs incomplete or malformed LLM responses.
    """
    incomplete_data = {
        "titles": [],
        "chapters": [{"timestamp": "01:00", "title": "Late intro"}],
    }
    validated = validate_metadata_schema(incomplete_data)

    assert len(validated["titles"]) > 0
    assert len(validated["chapters"]) >= 3
    assert validated["chapters"][0]["timestamp"] == "00:00"
    assert validated["description_hook"] != ""


def test_generate_metadata_with_fallback_routing():
    """
    Verifies that selecting heuristic or providing no key routes safely to heuristic generator.
    """
    transcript = "This is a test transcript for AutoChop AI Studio."
    data, notice = generate_metadata_with_fallback(
        transcript=transcript,
        provider="Local Heuristic (No Key)",
        api_key=None,
    )
    assert data["mode"] == "heuristic"
    assert len(data["titles"]) == 3


def test_validate_api_key():
    """
    Verifies key format validation logic for providers (Audit Point 10).
    """
    from autochop.core.metadata import validate_api_key

    # Heuristic requires no key
    valid, err = validate_api_key("Local Heuristic (No Key)", None)
    assert valid is True
    assert err is None

    # Missing keys
    valid, err = validate_api_key("OpenAI", "")
    assert valid is False
    assert "required" in err

    # OpenAI invalid prefix
    valid, err = validate_api_key("OpenAI", "bad-key-12345678901234567890")
    assert valid is False
    assert "sk-" in err

    # OpenAI valid key format
    valid, err = validate_api_key("OpenAI", "sk-proj-1234567890abcdef1234567890")
    assert valid is True
    assert err is None

    # Gemini invalid format
    valid, err = validate_api_key("Gemini", "short")
    assert valid is False

    # Anthropic (Claude)
    valid, err = validate_api_key("Anthropic (Claude)", "sk-ant-api03-1234567890abcdef1234567890")
    assert valid is True
    valid, err = validate_api_key("Anthropic (Claude)", "bad-prefix-key")
    assert valid is False and "sk-ant-" in err

    # Groq
    valid, err = validate_api_key("Groq (Ultra-Fast)", "gsk_1234567890abcdef12345678901234567890")
    assert valid is True
    valid, err = validate_api_key("Groq (Ultra-Fast)", "wrong-prefix")
    assert valid is False and "gsk_" in err

    # Grok (xAI)
    valid, err = validate_api_key("Grok (xAI)", "xai-1234567890abcdef12345678901234567890")
    assert valid is True
    valid, err = validate_api_key("Grok (xAI)", "wrong-prefix")
    assert valid is False and "xai-" in err

    # NVIDIA NIM
    valid, err = validate_api_key("NVIDIA NIM", "nvapi-1234567890abcdef12345678901234567890")
    assert valid is True
    valid, err = validate_api_key("NVIDIA NIM", "wrong-prefix")
    assert valid is False and "nvapi-" in err

    # OpenCode / Custom Endpoint
    valid, err = validate_api_key("OpenCode / Custom Endpoint", "opencode-local")
    assert valid is True


def test_provider_connection_invalid_key():
    """
    Tests test_provider_connection rejects malformed keys early.
    """
    from autochop.core.metadata import test_provider_connection

    # Test heuristic is always ok
    success, msg = test_provider_connection("Local Heuristic (No Key)", None)
    assert success is True
    assert "no api key required" in msg.lower()

    # Invalid prefix should fail fast before network call
    success, msg = test_provider_connection("Anthropic (Claude)", "invalid-key")
    assert success is False
    assert "sk-ant-" in msg


def test_env_utils_persistence(tmp_path, monkeypatch):
    """
    Tests reading and writing API keys safely to .env file and environment sync.
    """
    import os
    from autochop.utils import env_utils

    env_file = tmp_path / ".env"
    monkeypatch.setattr(env_utils, "get_env_path", lambda: str(env_file))

    test_keys = {
        "OPENAI_API_KEY": "sk-test-openai",
        "GEMINI_API_KEY": "AIzaSyTestGeminiKey1234567890",
        "ANTHROPIC_API_KEY": "sk-ant-testkey1234567890",
        "GROQ_API_KEY": "gsk_testgroqkey1234567890",
        "XAI_API_KEY": "xai-testgrokkkey1234567890",
        "NVIDIA_API_KEY": "nvapi-testnvidiakey1234567890",
        "OPENCODE_API_KEY": "opencode-local-key",
        "OPENCODE_BASE_URL": "http://localhost:11434/v1",
        "OPENCODE_MODEL": "qwen2.5-coder:7b",
    }

    env_utils.save_keys_to_env(test_keys)
    assert env_file.exists()

    # Load back
    loaded = env_utils.load_all_keys()
    for k, v in test_keys.items():
        assert loaded.get(k) == v
        assert os.environ.get(k) == v

    # Check get_key_for_provider
    assert env_utils.get_key_for_provider("Anthropic (Claude)") == "sk-ant-testkey1234567890"
    assert env_utils.get_key_for_provider("Groq (Ultra-Fast)") == "gsk_testgroqkey1234567890"
    assert env_utils.get_key_for_provider("Grok (xAI)") == "xai-testgrokkkey1234567890"
    assert env_utils.get_key_for_provider("NVIDIA NIM") == "nvapi-testnvidiakey1234567890"
    assert env_utils.get_key_for_provider("OpenCode / Custom Endpoint") == "opencode-local-key"

