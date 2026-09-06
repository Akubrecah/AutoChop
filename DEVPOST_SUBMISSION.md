# ⚡ AutoChop AI Studio — Devpost Submission Guide

---

## 📌 1. Project Title & Tagline

- **Project Title:** `AutoChop AI Studio`
- **Elevator Pitch (Under 200 characters):**
  > An end-to-end AI post-production engine that strips dead-air pauses, burns word-aligned captions, stitches rough cuts, and generates YouTube metadata in seconds.

---

## 📖 2. Project Story (Markdown with LaTeX)

Copy and paste the text below directly into the **About the project** field:

```markdown
## 💡 Inspiration
Every content creator knows the most soul-draining part of video creation isn't scripting or filming—it’s the **first three hours in the editing timeline**. 

Scrubbing through raw footage, slicing out breaths, deleting 3-second awkward silences, transcribing audio word-by-word, and formatting YouTube chapters is repetitive, mechanical labor. Existing SaaS tools charge recurring subscription fees, enforce strict upload quotas, or upload sensitive unreleased video footage to third-party cloud servers.

We built **AutoChop AI Studio** to give creators a free, local-first, privacy-preserving **AI content engine** that transforms raw footage into an assembled, captioned, publish-ready master rough cut in under a minute on any modern laptop.

---

## ⚡ What It Does
AutoChop AI Studio provides a complete, 3-step automated post-production pipeline:

1. **Dead-Air Stripping & Take Slicing:** Automatically analyzes audio waveforms to detect silences below a decibel threshold \\( \theta_{dB} \\), isolates active speech segments with safety padding, and slices individual takes (`take_001.mp4`, `take_002.mp4`).
2. **Word-Level Subtitle Burning:** Uses `faster-whisper` (CTranslate2) to generate timestamp-accurate transcripts and hardcodes high-contrast, resolution-scaled ASS subtitles (e.g. TikTok Yellow Box, Clean Minimalist) directly onto the video.
3. **Master Rough-Cut Assembly:** Stitches all non-silent takes into a seamless jump-cut master video with zero A/V sync drift.
4. **AI Metadata & Chapter Engine:** Extracts spoken content to generate 5 high-CTR titles, 2-sentence description copy, YouTube-compliant timestamp chapters (strictly formatted with \\( \text{start} = \text{00:00} \\), \\( \ge 3 \\) chapters, each \\( \ge 10\text{s} \\)), and SEO tags using any AI provider (OpenAI, Gemini, Claude, Groq, Grok, NVIDIA NIM) or a 100% offline heuristic fallback.
5. **Production Bundle Export:** Packages all takes, SRT subtitles, and an edit manifest in Markdown into a one-click `.zip` bundle.

---

## 🛠️ How We Built It
AutoChop is engineered as a modular, high-throughput media pipeline:

- **Audio Extraction & Silence Detection:** Uses FFmpeg's `silencedetect` filter with a 2-pass audio normalization strategy. We invert silence timestamps into active speech intervals:
  $$I_{\text{active}} = [t_{\text{silence\_end}} - \delta_{\text{pad}}, \; t_{\text{silence\_start}} + \delta_{\text{pad}}]$$
  where \\( \delta_{\text{pad}} = 0.15\text{s} \\) ensures consonant sounds like 'p' and 't' are never clipped.
- **Local Speech-to-Text (`faster-whisper`):** Powered by CTranslate2 int8 quantization and Silero VAD filtering, yielding up to 4x faster transcription than standard Whisper while running entirely offline on CPU or Apple Silicon.
- **Media Slicing & Assembly:** Slices video streams with re-encoded keyframe boundaries and stitches takes using FFmpeg's stream copy concat demuxer (with automatic `filter_complex` re-encoding fallback if container formats vary).
- **Styled Subtitle Engine:** Generates Advanced SubStation Alpha (`.ass`) subtitle files with dynamic `PlayResX`/`PlayResY` coordinate scaling so captions appear crisp on vertical 9:16 Shorts as well as 16:9 widescreen videos.
- **Multi-Provider AI Studio:** Features a universal OpenAI-compatible adapter supporting NVIDIA NIM, OpenAI, Groq, Grok, Claude, Gemini, and OpenCode, with client-side credential encryption and zero-key heuristic fallback.
- **Interactive UI:** Built with Gradio Blocks featuring a tailored studio design system, audio waveform analysis, and take inspector.

---

## 🚧 Challenges We Faced

1. **Audio/Video Sync Drift in Jump Cuts:**
   When concatenating multiple high-frame-rate cuts, slight discrepancies between audio sample rates and video keyframes compound over time, resulting in lip-sync drift. We resolved this by explicitly normalizing audio to 44.1kHz AAC and forcing PTS (Presentation Time Stamp) resets (`setpts=PTS-STARTPTS`) during slice extraction.

2. **Accidental Word Clipping vs. Silence Removal:**
   Naive silence detectors clip speech onset or tail consonants. We designed an adaptive boundary padding algorithm combined with a minimum-gap merge heuristic: any silence under 0.2s is treated as a natural breathing pause and preserved.

3. **Gradio Multi-Provider Key Persistence:**
   Storing and validating API keys across different providers without exposing keys in Git or public repositories required implementing an encrypted environment persistence layer with immediate visual status feedback and strict `.gitignore` isolation.

---

## 🏆 Accomplishments That We're Proud Of
- **Blazing Fast Local Execution:** A 2-minute raw video trims, transcribes, burns subtitles, and assembles in **under 25 seconds** on a standard MacBook Air.
- **100% Offline Capability:** The core video clipping, subtitle burning, and heuristic chapter generation function without internet access or paid API keys.
- **Zero Hallucination YouTube Chapters:** Guaranteed mathematical compliance with YouTube's strict chapter formatting rules.
- **Enterprise Test Suite:** 19 automated unit and integration tests verifying silence inversion, A/V duration matching, and ASS subtitle formatting.

---

## 🧠 What We Learned
- How to squeeze maximum performance out of FFmpeg filter graphs and subprocess pipes.
- The mechanics of ASS (Advanced SubStation Alpha) subtitle rendering matrices across disparate video aspect ratios.
- How to design resilient AI pipelines that gracefully degrade to offline heuristics when external APIs are unavailable.

---

## 🔮 What's Next for AutoChop AI Studio
- **Multi-Cam Auto-Switching:** Automatically switch video angles based on who is actively speaking.
- **Auto-B-Roll Insertion:** Use vision-language models to find points in the video where relevant stock footage or overlays can be automatically spliced.
- **Vertical Smart-Reframe:** AI face tracking to automatically re-frame 16:9 landscape videos into 9:16 TikTok and YouTube Shorts.
```

---

## 🏷️ 3. Built With (Tags — up to 25)

Copy and paste these tags into the **Built with** field:

`python`, `ffmpeg`, `faster-whisper`, `gradio`, `c-translate2`, `openai`, `gemini-api`, `nvidia-nim`, `groq`, `claude-api`, `audio-processing`, `video-editing`, `speech-to-text`, `srt`, `subtitles`, `youtube-automation`, `nlp`, `ai-content-engine`, `silence-removal`, `jump-cut`, `content-creation`, `generative-ai`, `local-ai`, `pytorch`, `multimodal`

---

## 🔗 4. "Try it out" Links

- **GitHub Repository:** `https://github.com/Akubrecah/AutoChop`
- **Installation / Local Demo:**
  ```bash
  git clone https://github.com/Akubrecah/AutoChop.git
  cd AutoChop
  uv venv && uv pip install -r requirements.txt
  python app.py
  # Open http://localhost:7860
  ```

---

## 🖼️ 5. Project Media & Video Demo Suggestions

### Image Gallery (Recommended Uploads):
1. **Hero Thumbnail / Cover Image:**
   - File: `assets/thumbnail.jpg` (16:9 high-res studio banner with waveforms, captions, and badges).
2. **Screenshot 1 — Tab 1 (Video Cuts & Captions):**
   - Showing uploaded video, waveform silence detection, and Master Jump-Cut video output.
3. **Screenshot 2 — Tab 2 (Title & Chapter Studio):**
   - Showing generated 5 high-CTR titles, YouTube timestamp chapters, and description copy.
4. **Screenshot 3 — Tab 3 (API Keys & Provider Settings):**
   - Showing the multi-provider AI hub with OpenAI, NVIDIA NIM, Gemini, Groq, and Claude options.

### Video Demo Link (Script Outline for a 90-second recording):
- **0:00 - 0:15:** The Problem — Show raw footage with awkward silences and pauses.
- **0:15 - 0:45:** AutoChop in Action — Upload footage, click "🎬 Cut, Transcribe & Burn", and show takes being sliced and assembled in real-time.
- **0:45 - 1:10:** The Output — Play the assembled video with burned TikTok-style yellow captions and no dead air.
- **1:10 - 1:30:** Metadata & Export — Show 1-click YouTube chapters and downloading the complete `.zip` project bundle.
