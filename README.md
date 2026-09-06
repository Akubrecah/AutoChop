# ⚡ AutoChop AI Studio (v2)

<p align="center">
  <img src="assets/thumbnail.jpg" alt="AutoChop AI Studio Banner" width="100%" />
</p>

Production-quality automated video post-production studio built with Python, FFmpeg, faster-whisper, and Gradio.

AutoChop automates the most tedious aspects of a creator's workflow:
1. **Dead-Air & Silence Stripping:** Analyzes audio with FFmpeg's `silencedetect` filter, inverts silence into speech takes, adds boundary padding, merges small breath pauses, and discards accidental noise artifacts.
2. **Local Speech-to-Text:** Generates word-aligned transcripts and relative-timestamped `.srt` files locally with `faster-whisper` (CTranslate2-backed Whisper engine) with cached model reuse.
3. **Take Slicing & Assembly:** Slices numbered takes (`take_001.mp4`, `take_002.mp4`) and concatenates them into a master jump-cut rough cut using FFmpeg's ultra-fast copy concat demuxer (with automatic `filter_complex` fallback). Verifies A/V sync duration.
4. **Styled Social Captions:** Hardcodes high-contrast ASS subtitles directly onto video takes with resolution-adaptive `PlayResX`/`PlayResY` scaling and multiple creator presets (TikTok Yellow Box, Clean Minimalist, High-Contrast White).
5. **Metadata Studio:** Generates 5 high-CTR titles, 2-sentence description copy, YouTube-compliant timestamp chapters (starts at `00:00`, $\ge 3$ chapters, each $\ge 10$s), and SEO tags using Gemini, OpenAI, or a zero-key local heuristic fallback.
6. **Creator Bundle Export:** Generates an edit manifest in GitHub Markdown and packages all takes, SRTs, and the manifest into a downloadable `.zip` archive.

---

## 🏗️ Architecture

```
autochop/
├── app.py                  # Gradio UI interface (Tab 1: Cuts, Tab 2: Studio)
├── config.py               # Constants, tunables & ASS subtitle style presets
├── core/
│   ├── audio.py            # Module 1: duration, WAV extraction, silence detection
│   ├── transcription.py    # Module 2: faster-whisper, SRT generation, subtitle burning
│   ├── assembly.py         # Module 3: take slicing, concat demuxer/filter, manifest, zip
│   └── metadata.py         # Module 4: metadata & chapters (Gemini, OpenAI, Heuristic)
├── utils/
│   ├── ffmpeg_utils.py     # Binary verification, subprocess runner, path escaping
│   └── file_utils.py       # Session-scoped temp directories, cleanup, zip creator
├── requirements.txt
├── .env.example
└── tests/
    ├── test_audio.py
    ├── test_transcription.py
    ├── test_assembly.py
    ├── test_metadata.py
    └── test_integration.py
```

---

## 🚀 Quick Start

### 1. Prerequisites
- **Python 3.10+** (Python 3.11 recommended)
- **FFmpeg & FFprobe $\ge$ 5.0** (or bundled via `static-ffmpeg`)

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install -y ffmpeg

# Windows
winget install Gyan.FFmpeg
```

### 2. Environment Setup

Using `uv` (recommended) or standard `venv`:

```bash
cd autochop

# Create and activate virtual environment
uv venv .venv --python 3.11
source .venv/bin/activate

# Install dependencies
uv pip install -r requirements.txt
```

### 3. Launch the Studio

```bash
python -m autochop.app
# or
python app.py
```

Open your browser to `http://localhost:7860`.

---

## 🧪 Running Tests

Run the full unit and integration test suite:

```bash
pytest tests/ -v
```

The test suite includes:
- `test_audio.py`: Silence inversion, gap merging, short noise rejection, boundary clamping, and all-silent error handling.
- `test_transcription.py`: SRT timestamp formatting and relative timestamp re-basing.
- `test_assembly.py`: Edit manifest generation and table formatting.
- `test_metadata.py`: Zero-key heuristic generation and YouTube chapter requirements compliance.
- `test_integration.py`: Programmatically synthesizes an audio/video clip using FFmpeg and runs the complete pipeline end-to-end.

---

## 📜 Acknowledgements & Attributions

AutoChop AI Studio is built with respect for open-source engineering:
- **[FFmpeg](https://ffmpeg.org/)** — Industry-standard multimedia engine for audio filtering, stream demuxing, and keyframe-accurate video concatenation.
- **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** — CTranslate2 reimplementation of OpenAI's Whisper model for ultra-fast on-device automatic speech recognition.
- **[Gradio](https://github.com/gradio-app/gradio)** — Modern web framework for interactive machine learning applications.

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](file:///Users/Akubrecah/Desktop/HACKATHONS/autochop/LICENSE) file for details.
