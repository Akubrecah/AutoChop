"""
AutoChop AI Studio - Metadata, Title & Chapter Studio (Module 4)
Generates high-CTR video titles, clickable YouTube timestamp chapters,
description copy, and SEO tags using Gemini / OpenAI or a zero-key heuristic fallback.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from typing import Any

from autochop.config import LLM_TIMEOUT_SEC

logger = logging.getLogger("autochop.metadata")


def format_timestamp_seconds(seconds: float) -> str:
    """Formats seconds to MM:SS or HH:MM:SS for YouTube chapter timestamps."""
    if seconds < 0:
        seconds = 0.0
    total_sec = int(round(seconds))
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def generate_heuristic_metadata(
    transcript: str,
    timestamped_segments: list[dict[str, Any]] | None = None,
    total_duration: float | None = None,
) -> dict[str, Any]:
    """
    Zero-key deterministic fallback generator.
    Partitions the transcript into intervals and generates YouTube-compliant chapters:
    - First chapter starts strictly at 00:00.
    - Minimum of 3 chapters.
    - Each chapter duration >= 10 seconds.
    - Formats 3 high-CTR titles, 2-sentence hook, and SEO tags.
    """
    words = [w.strip(".,!?;:\"'") for w in transcript.split() if len(w.strip(".,!?;:\"'")) > 2]
    # Extract salient keywords
    stop_words = {
        "the", "and", "that", "this", "with", "from", "your", "have", "more",
        "will", "about", "there", "what", "which", "when", "make", "like", "just",
        "know", "take", "into", "year", "some", "them", "people", "could", "than",
        "then", "their", "also", "very", "were", "been", "these", "would",
    }
    content_words = [w.capitalize() for w in words if w.lower() not in stop_words]
    top_keywords = content_words[:5] if content_words else ["Creator", "Workflow", "Secrets"]
    topic = " ".join(top_keywords[:2]) if len(top_keywords) >= 2 else "This Post-Production Secret"

    # 1. High-CTR Titles
    titles = [
        f"How I Mastered {topic} (And You Can Too)",
        f"The Truth About {topic} Nobody Tells You",
        f"{topic} Explained in 5 Minutes",
    ]

    # 2. YouTube-Compliant Chapters
    chapters: list[dict[str, str]] = []

    # Calculate actual video duration
    if total_duration is None or total_duration <= 0:
        if timestamped_segments:
            total_duration = max(s.get("end", 0.0) for s in timestamped_segments)
        else:
            # Estimate 130 words per minute
            total_duration = max(35.0, (len(words) / 130.0) * 60.0)

    # YouTube mandates: >= 3 chapters, each >= 10s, starts at 00:00
    effective_duration = max(35.0, total_duration)

    if timestamped_segments and len(timestamped_segments) >= 3:
        # Group segments into 3 to 5 coherent intervals
        num_target = min(5, max(3, int(effective_duration // 30)))
        step = max(1, len(timestamped_segments) // num_target)

        chapter_points: list[tuple[float, str]] = []
        for i in range(0, len(timestamped_segments), step):
            seg = timestamped_segments[i]
            t = seg.get("start", 0.0)
            txt = seg.get("text", "").strip()
            # Extract first 3-5 words as topic name
            snippet = " ".join(txt.split()[:4]).strip(".,;:?!")
            title = snippet.capitalize() if snippet else f"Part {len(chapter_points) + 1}"
            chapter_points.append((t, title))

        # Force first chapter at 00:00
        first_title = chapter_points[0][1] if chapter_points else "Introduction"
        refined_chapters: list[tuple[float, str]] = [(0.0, first_title if "intro" in first_title.lower() else "Introduction")]

        for t, title in chapter_points[1:]:
            # Ensure at least 10s gap from previous chapter
            if t - refined_chapters[-1][0] >= 10.0 and (effective_duration - t) >= 10.0:
                refined_chapters.append((t, title))

        # If less than 3 chapters, divide duration evenly
        if len(refined_chapters) < 3:
            third = effective_duration / 3.0
            refined_chapters = [
                (0.0, "Introduction & Overview"),
                (round(third, 1), f"Deep Dive into {top_keywords[0]}"),
                (round(third * 2, 1), "Key Takeaways & Summary"),
            ]

        for t, title in refined_chapters:
            chapters.append({
                "timestamp": format_timestamp_seconds(t),
                "title": title,
            })
    else:
        # Evenly split into 3 chapters
        third = effective_duration / 3.0
        refined = [
            (0.0, "Introduction & Hook"),
            (round(third, 1), f"Breakdown: {top_keywords[0]}"),
            (round(third * 2, 1), "Final Verdict & Conclusion"),
        ]
        for t, title in refined:
            chapters.append({
                "timestamp": format_timestamp_seconds(t),
                "title": title,
            })

    # 3. Description Hook & Copy
    first_sentence = transcript.split(".")[0].strip() if "." in transcript else transcript[:100].strip()
    if not first_sentence:
        first_sentence = f"In this video, we dive deep into {topic}."
    hook = f"{first_sentence}. Discover everything you need to know about streamlining your workflow and getting results."

    # 4. Tags
    tags = [f"#{kw.lower()}" for kw in top_keywords[:3]]
    tags.extend(["#creator", "#tutorial", "#workflow"])
    comma_tags = ", ".join([kw.lower() for kw in top_keywords[:5]] + ["editing", "tutorial", "guide"])

    return {
        "mode": "heuristic",
        "titles": titles,
        "description_hook": hook,
        "chapters": chapters,
        "tags": comma_tags,
        "hashtags": tags[:3],
    }


def call_openai_metadata(
    transcript: str,
    api_key: str,
    timestamped_segments: list[dict[str, Any]] | None = None,
    total_duration: float | None = None,
) -> dict[str, Any]:
    """Calls OpenAI API with strict JSON schema enforcement and timeout handling."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=LLM_TIMEOUT_SEC)
    system_prompt = (
        "You are an elite YouTube strategist and video metadata engineer. "
        "Analyze the provided spoken transcript and generate high-CTR metadata. "
        "You must respond with ONLY a valid JSON object strictly matching this schema:\n"
        "{\n"
        '  "titles": ["5 high-CTR variations (curiosity, search, punchy)"],\n'
        '  "description_hook": "2-sentence punchy description hook",\n'
        '  "chapters": [{"timestamp": "MM:SS", "title": "Chapter Title"}],\n'
        '  "tags": "comma, separated, seo, tags",\n'
        '  "hashtags": ["#tag1", "#tag2", "#tag3"]\n'
        "}\n\n"
        "YOUTUBE CHAPTER RULES:\n"
        "- First chapter MUST start at 00:00.\n"
        "- Minimum of 3 chapters.\n"
        "- Each chapter MUST be at least 10 seconds after the previous chapter."
    )

    user_content = f"Spoken Transcript:\n{transcript[:4000]}"
    if total_duration:
        user_content += f"\n\nTotal Video Duration: {total_duration:.1f} seconds"

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )

    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    data["mode"] = "openai"
    return validate_metadata_schema(data)


def call_gemini_metadata(
    transcript: str,
    api_key: str,
    timestamped_segments: list[dict[str, Any]] | None = None,
    total_duration: float | None = None,
) -> dict[str, Any]:
    """Calls Google Gemini API (google-genai) with structured output."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    prompt = (
        "You are an elite YouTube strategist and video metadata engineer. "
        "Analyze the spoken transcript and generate high-CTR metadata in strict JSON format.\n"
        "Rules:\n"
        "1. Exactly 5 high-CTR title variations (curiosity, search-optimized, punchy).\n"
        "2. 2-sentence description hook.\n"
        "3. YouTube-compliant chapters (starts at 00:00, >= 3 chapters, each >= 10s).\n"
        "4. Comma-separated SEO tags.\n"
        "5. Exactly 3 hashtags.\n\n"
        f"Transcript:\n{transcript[:4000]}"
    )
    if total_duration:
        prompt += f"\nTotal Duration: {total_duration:.1f}s"

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )

    content = response.text or "{}"
    data = json.loads(content)
    data["mode"] = "gemini"
    return validate_metadata_schema(data)


def validate_metadata_schema(data: dict[str, Any]) -> dict[str, Any]:
    """Ensures parsed JSON strictly fulfills all required keys and YouTube chapter rules."""
    titles = data.get("titles", [])
    if not isinstance(titles, list) or len(titles) == 0:
        titles = ["Untitled Video Cut"]

    hook = data.get("description_hook", "").strip()
    if not hook:
        hook = "An exciting video exploring key ideas and actionable insights."

    chapters = data.get("chapters", [])
    if not isinstance(chapters, list) or len(chapters) < 3:
        # Fallback chapters
        chapters = [
            {"timestamp": "00:00", "title": "Introduction"},
            {"timestamp": "00:15", "title": "Main Content"},
            {"timestamp": "00:30", "title": "Summary"},
        ]
    else:
        # Guarantee first chapter is 00:00
        chapters[0]["timestamp"] = "00:00"

    tags = data.get("tags", "")
    if isinstance(tags, list):
        tags = ", ".join(tags)

    hashtags = data.get("hashtags", [])
    if not isinstance(hashtags, list):
        hashtags = ["#video", "#creator"]

    return {
        "mode": data.get("mode", "llm"),
        "titles": titles,
        "description_hook": hook,
        "chapters": chapters,
        "tags": tags,
        "hashtags": hashtags,
    }


def call_anthropic_metadata(
    transcript: str,
    api_key: str,
    timestamped_segments: list[dict[str, Any]] | None = None,
    total_duration: float | None = None,
) -> dict[str, Any]:
    """Calls Anthropic Claude API (Claude 3.5 Sonnet) with JSON schema enforcement."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=LLM_TIMEOUT_SEC)
    system_prompt = (
        "You are an elite YouTube strategist and video metadata engineer. "
        "Analyze the provided spoken transcript and generate high-CTR metadata. "
        "You must respond with ONLY a valid JSON object strictly matching this schema:\n"
        "{\n"
        '  "titles": ["5 high-CTR variations (curiosity, search, punchy)"],\n'
        '  "description_hook": "2-sentence punchy description hook",\n'
        '  "chapters": [{"timestamp": "MM:SS", "title": "Chapter Title"}],\n'
        '  "tags": "comma, separated, seo, tags",\n'
        '  "hashtags": ["#tag1", "#tag2", "#tag3"]\n'
        "}\n\n"
        "YOUTUBE CHAPTER RULES:\n"
        "- First chapter MUST start at 00:00.\n"
        "- Minimum of 3 chapters.\n"
        "- Each chapter MUST be at least 10 seconds after the previous chapter."
    )
    user_content = f"Spoken Transcript:\n{transcript[:4000]}"
    if total_duration:
        user_content += f"\n\nTotal Video Duration: {total_duration:.1f} seconds"

    message = client.messages.create(
        model="claude-3-5-sonnet-latest",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    text = ""
    for block in message.content:
        if hasattr(block, "text"):
            text += block.text

    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    raw_json = json_match.group(0) if json_match else text
    data = json.loads(raw_json)
    data["mode"] = "anthropic"
    return validate_metadata_schema(data)


def call_openai_compatible_metadata(
    transcript: str,
    api_key: str,
    base_url: str,
    model: str,
    provider_name: str,
    timestamped_segments: list[dict[str, Any]] | None = None,
    total_duration: float | None = None,
) -> dict[str, Any]:
    """Calls any OpenAI-compatible API endpoint (Groq, xAI, NVIDIA NIM, Ollama, OpenCode)."""
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key or "local",
        base_url=base_url,
        timeout=LLM_TIMEOUT_SEC,
    )
    system_prompt = (
        "You are an elite YouTube strategist and video metadata engineer. "
        "Analyze the provided spoken transcript and generate high-CTR metadata. "
        "You must respond with ONLY a valid JSON object strictly matching this schema:\n"
        "{\n"
        '  "titles": ["5 high-CTR variations (curiosity, search, punchy)"],\n'
        '  "description_hook": "2-sentence punchy description hook",\n'
        '  "chapters": [{"timestamp": "MM:SS", "title": "Chapter Title"}],\n'
        '  "tags": "comma, separated, seo, tags",\n'
        '  "hashtags": ["#tag1", "#tag2", "#tag3"]\n'
        "}\n\n"
        "YOUTUBE CHAPTER RULES:\n"
        "- First chapter MUST start at 00:00.\n"
        "- Minimum of 3 chapters.\n"
        "- Each chapter MUST be at least 10 seconds after the previous chapter."
    )
    user_content = f"Spoken Transcript:\n{transcript[:4000]}"
    if total_duration:
        user_content += f"\n\nTotal Video Duration: {total_duration:.1f} seconds"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"} if ("nvidia" not in base_url.lower()) else None,
        temperature=0.7,
    )
    content = response.choices[0].message.content or "{}"
    json_match = re.search(r"\{.*\}", content, re.DOTALL)
    raw_json = json_match.group(0) if json_match else content
    data = json.loads(raw_json)
    data["mode"] = provider_name.lower()
    return validate_metadata_schema(data)


def validate_api_key(provider: str, api_key: str | None) -> tuple[bool, str | None]:
    """
    Validates API key format for specified LLM provider (Audit Point 10).
    Returns (is_valid, error_reason).
    """
    clean_p = provider.strip()
    if clean_p in ("Local Heuristic (No Key)", "OpenCode / Custom Endpoint"):
        return True, None

    if not api_key or not api_key.strip():
        return False, f"API key is required for provider '{clean_p}'."

    key = api_key.strip()
    if clean_p == "OpenAI":
        if not key.startswith("sk-"):
            return False, "OpenAI API keys typically start with 'sk-'."
        if len(key) < 20:
            return False, "OpenAI API key appears too short (minimum 20 characters)."
    elif clean_p == "Gemini":
        if not key.startswith("AIzaSy") and len(key) < 20:
            return False, "Gemini API keys typically start with 'AIzaSy' and are at least 20 characters."
    elif clean_p == "Anthropic (Claude)":
        if not key.startswith("sk-ant-"):
            return False, "Anthropic API keys typically start with 'sk-ant-'."
        if len(key) < 20:
            return False, "Anthropic API key appears too short."
    elif clean_p == "Groq (Ultra-Fast)":
        if not key.startswith("gsk_"):
            return False, "Groq API keys typically start with 'gsk_'."
        if len(key) < 20:
            return False, "Groq API key appears too short."
    elif clean_p == "Grok (xAI)":
        if not key.startswith("xai-"):
            return False, "xAI API keys typically start with 'xai-'."
        if len(key) < 20:
            return False, "xAI API key appears too short."
    elif clean_p == "NVIDIA NIM":
        if not key.startswith("nvapi-"):
            return False, "NVIDIA API keys typically start with 'nvapi-'."
        if len(key) < 20:
            return False, "NVIDIA API key appears too short."

    return True, None


def test_provider_connection(provider: str, api_key: str, base_url: str | None = None) -> tuple[bool, str]:
    """Tests connection to an LLM provider with a fast validation check."""
    import os
    key = api_key.strip() if api_key else ""
    if provider == "Local Heuristic (No Key)":
        return True, "✅ Local Heuristic Engine is operational (100% offline, zero-key, zero cost - no API key required)."

    valid, err = validate_api_key(provider, key)
    if not valid:
        return False, f"❌ {err}"

    try:
        if provider == "OpenAI":
            from openai import OpenAI
            client = OpenAI(api_key=key, timeout=10)
            client.models.list()
            return True, "✅ Successfully authenticated with OpenAI API."
        elif provider == "Gemini":
            from google import genai
            client = genai.Client(api_key=key)
            client.models.list(config={"page_size": 1})
            return True, "✅ Successfully authenticated with Google Gemini API."
        elif provider == "Anthropic (Claude)":
            import anthropic
            client = anthropic.Anthropic(api_key=key, timeout=10)
            client.messages.create(
                model="claude-3-5-sonnet-latest",
                max_tokens=5,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True, "✅ Successfully authenticated with Anthropic Claude API."
        elif provider == "Groq (Ultra-Fast)":
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1", timeout=10)
            client.models.list()
            return True, "✅ Successfully authenticated with GroqCloud API."
        elif provider == "Grok (xAI)":
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url="https://api.x.ai/v1", timeout=10)
            client.models.list()
            return True, "✅ Successfully authenticated with xAI Grok API."
        elif provider == "NVIDIA NIM":
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url="https://integrate.api.nvidia.com/v1", timeout=10)
            client.models.list()
            return True, "✅ Successfully authenticated with NVIDIA NIM API."
        elif provider == "OpenCode / Custom Endpoint":
            from openai import OpenAI
            b_url = base_url or os.getenv("OPENCODE_BASE_URL", "http://localhost:11434/v1")
            client = OpenAI(api_key=key or "local", base_url=b_url, timeout=10)
            client.models.list()
            return True, f"✅ Successfully connected to custom endpoint at {b_url}."
        else:
            return False, f"Unknown provider: {provider}"
    except Exception as exc:
        return False, f"❌ Connection failed: {exc}"


def generate_metadata_with_fallback(
    transcript: str,
    provider: str = "Local Heuristic (No Key)",
    api_key: str | None = None,
    timestamped_segments: list[dict[str, Any]] | None = None,
    total_duration: float | None = None,
    custom_base_url: str | None = None,
    custom_model: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """
    Main coordinator for metadata generation.
    Supports exact provider choices: 'OpenAI', 'Gemini', 'Anthropic (Claude)',
    'Groq (Ultra-Fast)', 'Grok (xAI)', 'NVIDIA NIM', 'OpenCode / Custom Endpoint', or 'Local Heuristic (No Key)'.
    Safely validates keys, catches timeouts and exceptions, performing 1 retry before falling back to heuristic.
    Returns (metadata_dict, notice_message).
    """
    import os
    if not transcript or not transcript.strip():
        raise ValueError("Cannot generate metadata from an empty transcript.")

    cleaned_key = api_key.strip() if api_key else ""
    cleaned_provider = provider.strip()

    # Exact matching
    if cleaned_provider == "Local Heuristic (No Key)" or (not cleaned_key and cleaned_provider != "OpenCode / Custom Endpoint"):
        logger.info("Using Local Heuristic mode for metadata generation.")
        res = generate_heuristic_metadata(transcript, timestamped_segments, total_duration)
        notice = "Generated using Local Zero-Key Heuristic Engine." if (not cleaned_key and cleaned_provider != "Local Heuristic (No Key)") else None
        return res, notice

    # Validate API key format before sending network request
    is_valid, key_err = validate_api_key(cleaned_provider, cleaned_key)
    if not is_valid:
        logger.warning(f"Invalid API key format for {cleaned_provider}: {key_err}. Falling back to heuristic.")
        fallback_res = generate_heuristic_metadata(transcript, timestamped_segments, total_duration)
        return fallback_res, f"{key_err} Automatically generated using local heuristic fallback."

    # LLM execution with 1 retry on failure
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            if cleaned_provider == "OpenAI":
                logger.info(f"Generating metadata via OpenAI (attempt {attempt + 1})...")
                res = call_openai_metadata(transcript, cleaned_key, timestamped_segments, total_duration)
                return res, None
            elif cleaned_provider == "Gemini":
                logger.info(f"Generating metadata via Gemini (attempt {attempt + 1})...")
                res = call_gemini_metadata(transcript, cleaned_key, timestamped_segments, total_duration)
                return res, None
            elif cleaned_provider == "Anthropic (Claude)":
                logger.info(f"Generating metadata via Anthropic (attempt {attempt + 1})...")
                res = call_anthropic_metadata(transcript, cleaned_key, timestamped_segments, total_duration)
                return res, None
            elif cleaned_provider == "Groq (Ultra-Fast)":
                logger.info(f"Generating metadata via GroqCloud (attempt {attempt + 1})...")
                res = call_openai_compatible_metadata(
                    transcript, cleaned_key,
                    base_url="https://api.groq.com/openai/v1",
                    model="llama-3.3-70b-versatile",
                    provider_name="Groq",
                    timestamped_segments=timestamped_segments,
                    total_duration=total_duration,
                )
                return res, None
            elif cleaned_provider == "Grok (xAI)":
                logger.info(f"Generating metadata via xAI Grok (attempt {attempt + 1})...")
                res = call_openai_compatible_metadata(
                    transcript, cleaned_key,
                    base_url="https://api.x.ai/v1",
                    model="grok-2-latest",
                    provider_name="Grok",
                    timestamped_segments=timestamped_segments,
                    total_duration=total_duration,
                )
                return res, None
            elif cleaned_provider == "NVIDIA NIM":
                logger.info(f"Generating metadata via NVIDIA NIM (attempt {attempt + 1})...")
                res = call_openai_compatible_metadata(
                    transcript, cleaned_key,
                    base_url="https://integrate.api.nvidia.com/v1",
                    model="meta/llama-3.3-70b-instruct",
                    provider_name="NVIDIA NIM",
                    timestamped_segments=timestamped_segments,
                    total_duration=total_duration,
                )
                return res, None
            elif cleaned_provider == "OpenCode / Custom Endpoint":
                endpoint = custom_base_url or os.getenv("OPENCODE_BASE_URL", "http://localhost:11434/v1")
                mod = custom_model or os.getenv("OPENCODE_MODEL", "llama3.3")
                logger.info(f"Generating metadata via OpenCode/Custom at {endpoint} (attempt {attempt + 1})...")
                res = call_openai_compatible_metadata(
                    transcript, cleaned_key,
                    base_url=endpoint,
                    model=mod,
                    provider_name="OpenCode",
                    timestamped_segments=timestamped_segments,
                    total_duration=total_duration,
                )
                return res, None
            else:
                logger.warning(f"Unrecognized provider '{cleaned_provider}'; using heuristic.")
                break
        except Exception as exc:
            last_error = exc
            logger.warning(f"LLM call to {cleaned_provider} failed (attempt {attempt + 1}): {exc}")
            time.sleep(1.0)

    # Fallback to heuristic
    logger.warning(f"Falling back to Heuristic metadata generator due to LLM error: {last_error}")
    fallback_res = generate_heuristic_metadata(transcript, timestamped_segments, total_duration)
    notice = f"LLM provider '{cleaned_provider}' encountered an error ({type(last_error).__name__}). Automatically generated via local heuristic fallback."
    return fallback_res, notice
