# AI Video Editor — Tech Stack Research
## "Upload raw footage → Get professionally edited video in your style"

---

## The Full Problem Map

| Sub-Problem | What It Solves | Difficulty |
|---|---|---|
| Cut/Scene Detection | Find where edits happen in reference video | Easy |
| Zoom Detection | Detect zoom-in/out levels between frames | Medium |
| Transition Classification | Identify cut types (hard, jump, swipe, fade) | Medium |
| Caption Style Extraction | Read font, size, color, animation from reference | Medium |
| Color Grade Extraction | Pull LUT / color profile from reference | Easy-Medium |
| Transcription | Word-level timestamps from raw audio | Easy |
| Speech Energy Analysis | Detect emphasis, loud words, energy shifts | Easy-Medium |
| Silence Detection | Find pauses, dead air, filler | Easy |
| Face Tracking | Bounding box per frame for smart zoom/crop | Easy |
| Edit Decision Making | The brain — map style rules onto new footage | Hard |
| Caption Rendering | Animated word-by-word TikTok-style captions | Medium |
| Video Execution | Apply all edits via FFmpeg | Medium |
| Audio Mixing | Music ducking, SFX, voice levels | Easy-Medium |

---

## Vision Model Layer — Where & Why It's Irreplaceable

Traditional tools (PySceneDetect, WhisperX, MediaPipe, Librosa) handle MECHANICAL extraction — timestamps, coordinates, energy values, cut points. They answer "WHAT happened" and "WHEN."

The vision model answers "WHY" and "HOW" — the semantic understanding that no traditional tool can provide. Here's every place we need it:

### VM-1: Edit Intent Classification
**Input:** Keyframes extracted around each cut point (last frame of scene A, first frame of scene B)
**What it answers:** WHY was this cut made?
- Jump cut for pacing (same angle, time skip)
- Topic transition (new section/segment)
- B-roll insert (meme, screen recording, image overlay, stock footage)
- Reaction cut (cut to face for emphasis)
- Cutaway (product shot, demo, whiteboard)

**Why nothing else can do it:** PySceneDetect tells you "cut at 12.4s." It cannot distinguish a comedic jump cut from a topic transition. The edit INTENT determines how the brain applies similar cuts to new footage.

**Cost optimization:** Only send 2-3 frames per cut (not continuous video). At ~765 tokens per image (high detail), analyzing 50 cuts = ~115K tokens input = ~$0.29 on GPT-4o, ~$0.35 on Claude Sonnet.

### VM-2: Zoom Purpose Detection
**Input:** Frame pairs showing zoom change + corresponding transcript words
**What it answers:** WHAT triggered this zoom and what's the pattern?
- Zoom on emphasis word / punchline
- Zoom on emotional reaction / facial expression
- Zoom to focus on object being discussed
- Slow zoom for dramatic effect
- Quick zoom for comedic timing

**Why nothing else can do it:** MediaPipe detects that the face got bigger in frame. It cannot tell you the zoom was triggered by a punchline vs a topic shift. Librosa detects energy peaks. It cannot confirm the energy peak corresponds to the zoom moment. The vision model correlates visual zoom with speech content and facial expression simultaneously.

**Approach:** For each detected zoom region, send: pre-zoom frame + post-zoom frame + the transcript text being spoken at that moment. Ask the model to classify the trigger.

### VM-3: B-Roll / Overlay Identification
**Input:** Frames from each scene segment
**What it answers:** Is this the creator talking, or inserted content?
- Talking head (creator on camera)
- Screen recording / screencast
- Meme / image overlay
- Stock footage / cinematic b-roll
- Text card / title card
- Product shot / demo footage

**Why nothing else can do it:** OpenCV can detect if a frame looks "different" from the talking head frames, but it cannot classify WHAT it is. The vision model sees a meme and knows it's a meme. This classification determines how b-roll is used in the creator's style.

**Cost optimization:** Sample 1 frame per scene segment. Most are talking head — quickly classified. Only non-talking-head frames need deeper analysis.

### VM-4: Caption Style Extraction
**Input:** 3-5 frames from reference video that contain visible captions/subtitles
**What it answers:** Exact caption styling specification
- Font family (or closest match: bold sans-serif, thin serif, etc.)
- Font size relative to frame
- Color (text color, highlight color, stroke/outline color)
- Position (bottom center, top, custom)
- Background (none, box, gradient, blur)
- Animation style (word-by-word highlight, pop-in, fade, karaoke, static)
- Words shown at once (1 word, 2-3 words, full sentence)
- Capitalization (ALL CAPS, Sentence case, lowercase)

**Why nothing else can do it:** OCR reads text but cannot describe visual styling. Only a vision model looks at a caption frame and outputs "bold white text, 48px, yellow highlight on active word, drop shadow, centered bottom third, 2-3 words per line, pop-in animation."

### VM-5: Color Grade / Visual Style Description
**Input:** 5-8 representative frames from reference video
**What it answers:** Overall visual style the LUT pipeline can act on
- Warm / cool / neutral temperature
- High / low contrast
- Saturated / desaturated
- Specific color cast (teal shadows, orange highlights)
- Film grain / clean digital
- Brightness level (dark moody / bright airy)

**Why nothing else can do it:** OpenCV histograms give raw color numbers. They cannot say "warm, slightly desaturated cinematic grade with teal shadows" in a way that maps to a known LUT. The vision model bridges pixel data to creative intent.

### VM-6: Overall Editing Pace & Style Summary
**Input:** Grid of 20-30 sampled frames (single composite image) + all structured data
**What it answers:** Holistic style profile in natural language
- "Fast-paced gaming commentary with jump cuts every 2-3s, heavy meme b-roll, zooms on reactions, bold captions"
- "Calm educational tutorial with 10-15s segments, minimal zooms, clean lower-third captions"

**Why this matters:** This becomes the system prompt for the Edit Decision Brain. It gives the LLM creative context beyond mechanical pattern matching.

### VM-7: Raw Footage Visual Analysis
**Input:** Sampled frames from NEW raw footage (1 per 5-10 seconds)
**What it answers:** Scene content understanding for intelligent editing
- "Creator demonstrating product at 45-60s" → don't cut during demo
- "Creator telling story with hand gestures" → zoom on key moments
- "Creator reading from notes / looking away" → candidate for cutting
- "Creator's expression signals incoming joke" → prepare zoom on punchline
- "Low energy tangent section" → candidate for speed-up or removal

**Why nothing else can do it:** Transcript tells WHAT is said. Librosa tells HOW LOUD. Neither knows the creator is demonstrating something or that body language signals a punchline. The vision model reads visual context that audio-only analysis completely misses.

**Cost optimization:** 15-min video = 90-180 frames at 1/5-10s. Low detail mode (85 tokens/image) = ~15K tokens = ~$0.04 on GPT-4o. Very cheap.

### Vision Model Cost Summary (per 15-min video)

| Analysis | Frames | Tokens (est.) | Cost (Sonnet 4.6) |
|---|---|---|---|
| VM-1: Edit intent (50 cuts × 2 frames) | 100 | ~76K | $0.23 |
| VM-2: Zoom purpose (15 zooms × 3 frames) | 45 | ~34K | $0.10 |
| VM-3: B-roll ID (50 scenes × 1 frame) | 50 | ~38K | $0.11 |
| VM-4: Caption style (5 frames) | 5 | ~4K | $0.01 |
| VM-5: Color grade (8 frames) | 8 | ~6K | $0.02 |
| VM-6: Style summary (1 composite grid) | 1 | ~1K | $0.003 |
| VM-7: Raw footage analysis (180 frames low detail) | 180 | ~15K | $0.05 |
| **Total vision model** | **~389** | **~174K** | **~$0.52** |

Add brain output ($0.15-0.30) = **~$0.70-0.85 per video** total API costs.

At $79/mo for 20 videos = $14-17/mo API costs per customer. **Gross margins 78-82%.**

### Vision Model Choice (via OpenRouter — May 2026)

Forget GPT-4o. Chinese and open-source vision models now dominate price/performance. All via OpenRouter unified API.

**Tier 1 — Bulk classification (VM-1, VM-3, VM-7): $0.04-0.10/MTok input**

| Model | Input $/MTok | Output $/MTok | Notes |
|---|---|---|---|
| **Qwen 3.5 Flash** | $0.065 | $0.26 | Cheapest multimodal, vision+video native, 1M ctx |
| **Qwen 3.5 9B** | $0.04 | $0.15 | Dirt cheap, good for frame classification |
| **Xiaomi MiMo V2 Flash** | $0.09 | $0.29 | #1 on OpenRouter by volume, open weights |
| **Gemini 2.5 Flash Lite** | $0.10 | $0.40 | Ultra-fast, 1M ctx, thinking optional |
| **Grok 4.1 Fast** | $0.20 | $0.50 | 2M context, strong agentic |

**Tier 2 — Quality analysis (VM-2, VM-4, VM-5): $0.30/MTok input**

| Model | Input $/MTok | Output $/MTok | Notes |
|---|---|---|---|
| **Qwen 3.5 Plus** | $0.30 | $1.80 | Strong multimodal, vision+video, 1M ctx |
| **Gemini 2.5 Flash** | $0.30 | $2.50 | Best mid-tier, 1M ctx |
| **Qwen 3.6 Plus** | $0.325 | $1.95 | Latest frontier-adjacent, free preview available |

**Tier 3 — Brain / EDL generation (VM-6 + Phase 3)**

| Model | Input $/MTok | Output $/MTok | Notes |
|---|---|---|---|
| **Gemini 3 Flash** | $0.50 | $3.00 | #1 on OpenRouter, near-Pro reasoning |
| **Claude Sonnet 4.6** | $3.00 | $15.00 | Best structured output, strongest instructions |
| **Qwen 3.6 Plus** | $0.325 | $1.95 | Frontier-adjacent, great value |

**Revised cost with hybrid strategy (Qwen Flash → Qwen Plus → Gemini 3 Flash):**

| Analysis | Model Tier | Cost |
|---|---|---|
| VM-1: Edit intent (100 frames) | Qwen 3.5 Flash | $0.005 |
| VM-2: Zoom purpose (45 frames) | Qwen 3.5 Plus | $0.010 |
| VM-3: B-roll ID (50 frames) | Qwen 3.5 Flash | $0.003 |
| VM-4: Caption style (5 frames) | Qwen 3.5 Plus | $0.001 |
| VM-5: Color grade (8 frames) | Qwen 3.5 Plus | $0.002 |
| VM-6: Style summary (composite) | Gemini 3 Flash | $0.001 |
| VM-7: Raw footage (180 frames) | Qwen 3.5 Flash | $0.001 |
| Brain EDL output | Gemini 3 Flash | $0.060 |
| **Total per video** | | **~$0.08** |

**$0.08 per video.** That's 6-10x cheaper than GPT-4o/Claude pricing.

At $79/mo for 20 videos = **$1.60/mo per customer. Gross margins: 98%.**

**Key: Native Video Input.** Qwen 3.5+, Gemini 3/2.5 Flash, and NVIDIA Nemotron Nano 3 Omni all accept raw video input — not just frames. Can send video clips directly instead of extracting frames. Simpler pipeline, model sees motion/timing context.

---

## Tech Stack — Best Tool for Each Problem

### 1. Cut / Scene Detection
**Winner: PySceneDetect**

- Python + OpenCV based, production-proven (Netflix, BBC use it)
- 94.7% accuracy on standard test sets
- Three detection algorithms:
  - `ContentDetector` → best for most videos (hard cuts, jump cuts)
  - `AdaptiveDetector` → handles camera motion well
  - `ThresholdDetector` → for fades and dissolves
- Outputs scene list with timestamps, can export to EDL format (industry standard)
- Can output to OTIO (OpenTimelineIO) for interop with professional editors
- Fast: processes video at near-realtime speed
- Free, open source (BSD-3)

```python
from scenedetect import detect, AdaptiveDetector, split_video_ffmpeg
scene_list = detect('video.mp4', AdaptiveDetector())
# Returns list of (start_time, end_time) tuples
```

**Alternative:** FFmpeg's native `blackframe` filter or x264's `--scenecut` — faster but less accurate. Good for pre-filtering.

---

### 2. Transcription (Word-Level Timestamps)
**Winner: WhisperX**

- Built on faster-whisper (CTranslate2 backend) — 70x realtime speed
- Accurate word-level timestamps via wav2vec2 forced alignment (far better than vanilla Whisper)
- Speaker diarization via pyannote-audio (useful for interviews/podcasts)
- VAD preprocessing reduces hallucination
- Needs <8GB GPU memory for large-v2
- Free, open source

```python
import whisperx
model = whisperx.load_model("large-v2", device="cuda", compute_type="float16")
audio = whisperx.load_audio("video.mp4")
result = model.transcribe(audio, batch_size=16)

# Align for word-level timestamps
model_a, metadata = whisperx.load_align_model(language_code="en", device="cuda")
result = whisperx.align(result["segments"], model_a, metadata, audio, device="cuda")
# Each word now has precise start/end timestamps
```

**Why not faster-whisper alone?** It's faster but word timestamps are less accurate. WhisperX uses phoneme alignment on top which is critical for syncing captions and detecting emphasis timing.

**Why not vanilla Whisper?** Slower, no batching, inaccurate timestamps.

---

### 3. Face Detection & Tracking
**Winner: MediaPipe Face Detection / Face Mesh**

- Google's ultrafast face detection — sub-10ms on mobile, near-instant on desktop
- Returns face bounding box + 6 key landmarks (eyes, nose, mouth, ear points)
- Face Mesh variant gives 468 3D landmarks (useful for expression detection)
- Frame-to-frame tracking (doesn't re-detect every frame — tracks from previous)
- Works with OpenCV video capture pipeline
- Free, open source

```python
import mediapipe as mp
import cv2

mp_face = mp.solutions.face_detection
with mp_face.FaceDetection(min_detection_confidence=0.5) as face_detection:
    # Per frame: get face bounding box
    results = face_detection.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    # results.detections[0].location_data.relative_bounding_box
    # → xmin, ymin, width, height (normalized 0-1)
```

**Use case in our tool:**
- Extract face center coordinates per frame → feed to FFmpeg crop/scale for smart zoom
- Detect facial expressions (surprise, emphasis) via Face Mesh landmarks → trigger zoom-ins
- Track face position for smooth reframing (horizontal → vertical crop)

**Alternative:** YOLO face detection — heavier but more robust for multiple faces. Overkill for single-creator talking head videos.

---

### 4. Audio Analysis (Energy / Emphasis / Silence)
**Winner: Librosa + Silero VAD**

**Librosa** for energy and emphasis:
- RMS energy per frame → detect loud/quiet sections
- Onset detection → identify sudden energy bursts (emphasis words, claps, impacts)
- Spectral contrast → distinguish speech energy patterns
- Tempo/beat detection → useful if background music needs to sync with cuts

```python
import librosa
y, sr = librosa.load("audio.wav")
# RMS energy curve
rms = librosa.feature.rms(y=y)[0]
# Onset strength (energy bursts)
onset_env = librosa.onset.onset_strength(y=y, sr=sr)
onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
```

**Silero VAD** for silence detection:
- Best-in-class voice activity detection
- Already integrated in faster-whisper
- Detects speech vs non-speech segments with millisecond precision
- Lightweight, runs on CPU fast

```python
# Via faster-whisper integration
segments, _ = model.transcribe("audio.mp3", vad_filter=True)
# Automatically filters out silence > 2 seconds
```

**Combined workflow:**
1. Silero VAD → find all speech/silence boundaries
2. Librosa RMS → find energy peaks within speech (emphasis words)
3. Cross-reference with WhisperX word timestamps → know WHICH words are emphasized

---

### 5. Caption Rendering (Animated Word-by-Word)
**Two viable approaches:**

#### Option A: ASS/SSA Subtitles (simpler, FFmpeg-native)
- ASS format supports: custom fonts, colors, positioning, bold/italic, fade animations, karaoke effects (word-by-word highlight)
- FFmpeg renders ASS natively via libass: `ffmpeg -i input.mp4 -vf ass=subtitles.ass output.mp4`
- Generate .ass file programmatically from WhisperX word timestamps
- Supports: word highlight color change, fade-in per word, position control
- **Limitation:** Animation options are restricted to what ASS format supports — no bounce, scale, or custom motion

#### Option B: Remotion / Rendervid (richer animations, heavier)
- **Remotion** — React-based programmatic video, full CSS/SVG animation control
  - TikTok-style captions already implemented: `createTikTokStyleCaptions()` 
  - Word-by-word highlight, bounce, scale, custom everything
  - **License cost:** requires commercial license for company use
- **Rendervid** — free open-source Remotion alternative, AI-first design, MCP integration
  - Same React rendering approach, no license fees
  - JSON template based — easier for AI agent to control
  - Newer, less battle-tested

#### Option C: MoviePy + Pillow (Python-native, flexible)
- Render each caption frame as an image (Pillow/Cairo)
- Composite onto video via MoviePy or FFmpeg overlay
- Full control over animation (render frame-by-frame)
- Slower than ASS but more flexible than ASS, lighter than Remotion
- Good middle ground

**Recommendation:** Start with **ASS/SSA** for MVP (simplest, FFmpeg-native, no extra rendering pipeline). Upgrade to **Rendervid** when you need fancy animations.

---

### 6. Zoom Detection in Reference Video
**No off-the-shelf library exists for this.** This is custom work.

**Approach:**
1. Extract keyframes at each cut point (from PySceneDetect)
2. Within each scene segment, sample frames at regular intervals
3. Compare frame-to-frame crop area / resolution changes using OpenCV
4. If the apparent subject size changes but the scene content is the same → zoom was applied
5. Calculate zoom level as ratio of face bounding box size between frames

**Alternatively — use vision model:**
- Send pairs of frames (before/after suspected zoom) to Claude/GPT-4o
- Ask: "Is this a zoom-in, zoom-out, or no change? What's the approximate zoom level?"
- More expensive but more accurate for detecting subtle zooms

---

### 7. Transition Classification
**Approach: PySceneDetect + Vision Model**

1. PySceneDetect detects ALL cut points
2. For each cut, extract 3 frames: last frame of scene A, transition frame (if any), first frame of scene B
3. Simple heuristics first:
   - Brightness drops to black → fade to black
   - Gradual pixel change → dissolve/crossfade  
   - Instant change → hard cut / jump cut
4. For complex transitions (swipe, slide, morph) → send frame triplet to vision model for classification

---

### 8. Color Grade / LUT Extraction
**Winner: OpenCV + 3D LUT generation**

- Sample N frames from reference video
- Analyze color distribution (HSV histograms, average warmth, contrast, saturation)
- Generate an approximate 3D LUT (.cube file) that transforms neutral footage toward the reference look
- Apply via FFmpeg: `ffmpeg -i input.mp4 -vf lut3d=style.cube output.mp4`

**Alternative:** Use a vision model to describe the color grade in words ("warm, slightly desaturated, high contrast, teal shadows") then map to known preset LUTs.

---

### 9. The Brain — Edit Decision Making
**Winner: LLM Agent (Claude / GPT-4o) with structured output**

This is the core differentiator. All analysis feeds into the LLM which outputs a structured Edit Decision List (EDL).

**Input to the brain:**
```json
{
  "style_profile": {
    "avg_cut_interval_seconds": 3.2,
    "zoom_triggers": "emphasis_words",
    "zoom_level": 1.3,
    "caption_style": "word_by_word_highlight_yellow",
    "transition_type": "hard_cut",
    "color_lut": "warm_v2.cube",
    "music_ducking": true,
    "sfx_on_cuts": "whoosh"
  },
  "raw_footage": {
    "transcript": [...words with timestamps...],
    "energy_peaks": [...timestamps...],
    "silence_regions": [...],
    "face_positions": [...per frame...],
    "total_duration": 624.5
  }
}
```

**Output (structured EDL):**
```json
{
  "edits": [
    {"type": "cut", "at": 12.4, "transition": "hard_cut"},
    {"type": "remove_silence", "from": 15.2, "to": 16.8},
    {"type": "zoom_in", "from": 18.1, "to": 19.5, "level": 1.3, "center": "face"},
    {"type": "caption", "text": "this is important", "from": 18.1, "to": 19.5, "style": "highlight"},
    {"type": "speed_up", "from": 22.0, "to": 28.0, "rate": 1.5},
    {"type": "sfx", "at": 12.4, "sound": "whoosh"},
    ...
  ]
}
```

---

### 10. Video Execution — FFmpeg
**FFmpeg handles all final rendering:**

| Edit Type | FFmpeg Approach |
|---|---|
| Cuts/trims | `-ss` and `-t` flags, or `trim` filter |
| Zoom (static) | `crop` + `scale` filters |
| Zoom (animated) | Frame-by-frame `crop` with interpolated coordinates via `zoompan` filter |
| Speed change | `setpts=0.5*PTS` (2x speed) or `setpts=1.5*PTS` (1.5x) |
| Transitions (crossfade) | `xfade` filter |
| Color grading | `lut3d` filter with .cube LUT file |
| Audio ducking | `sidechaincompress` filter |
| Music mixing | `amix` or `amerge` filters |
| Caption overlay | `ass` filter (for ASS subtitles) or `overlay` (for image sequences) |
| SFX insertion | `adelay` + `amix` |
| Concatenation | `concat` demuxer or filter |

---

## Full Pipeline Summary

```
═══════════════════════════════════════════════════════════════
PHASE 1: MECHANICAL EXTRACTION (cheap, fast, parallel)
═══════════════════════════════════════════════════════════════

REFERENCE VIDEO IN ──┬── [PySceneDetect] ──→ Cut timestamps + scene list
                     ├── [WhisperX] ──→ Word-level transcript
                     ├── [MediaPipe] ──→ Face positions per frame  
                     ├── [Librosa] ──→ Energy curve, onset peaks
                     ├── [Silero VAD] ──→ Speech/silence boundaries
                     └── [OpenCV] ──→ Color histograms, frame extraction

RAW VIDEO IN ────────┬── [WhisperX] ──→ Word-level transcript
                     ├── [MediaPipe] ──→ Face positions per frame
                     ├── [Librosa + Silero VAD] ──→ Energy peaks, silences
                     └── [OpenCV] ──→ Keyframe extraction

═══════════════════════════════════════════════════════════════
PHASE 2: SEMANTIC UNDERSTANDING (vision model, per-frame analysis)
═══════════════════════════════════════════════════════════════

REFERENCE VIDEO keyframes + structured data from Phase 1
                     │
                     ├── [VM-1] Edit intent per cut → "jump cut for comedy" / "topic transition"
                     ├── [VM-2] Zoom purpose → "emphasis on punchline" / "reaction zoom"
                     ├── [VM-3] B-roll classification → "meme" / "screencast" / "stock footage"
                     ├── [VM-4] Caption style → font, color, animation, position spec
                     ├── [VM-5] Color grade description → "warm, desaturated, teal shadows"
                     └── [VM-6] Overall style summary → system prompt for the brain
                             │
                             ▼
                     STYLE PROFILE (JSON — extracted once, reused for all future videos)

RAW VIDEO keyframes + structured data from Phase 1
                     │
                     └── [VM-7] Content understanding → "demo section" / "joke incoming" / "tangent"
                             │
                             ▼
                     RAW FOOTAGE ANALYSIS (JSON)

═══════════════════════════════════════════════════════════════
PHASE 3: EDIT DECISION BRAIN (LLM agent, structured output)
═══════════════════════════════════════════════════════════════

     STYLE PROFILE + RAW FOOTAGE ANALYSIS + TRANSCRIPT + ENERGY DATA
                             │
                             ▼
                     [Claude Sonnet / GPT-4o — structured JSON output]
                             │
                             ▼
                     EDIT DECISION LIST (EDL)
                     - Cut at 12.4s (hard cut, pacing)
                     - Remove silence 15.2-16.8s
                     - Zoom 1.3x at 18.1-19.5s centered on face (punchline)
                     - Caption "this is key" highlighted yellow 18.1-19.5s
                     - Speed up 22-28s to 1.5x (low energy tangent)
                     - SFX whoosh at 12.4s
                     - Apply LUT warm_v2.cube globally

═══════════════════════════════════════════════════════════════
PHASE 4: EXECUTION (FFmpeg + ASS rendering)
═══════════════════════════════════════════════════════════════

                     EDL + Raw Video + Audio Assets
                             │
                             ├── [ASS Generator] ──→ Styled subtitle file from transcript + EDL
                             ├── [LUT Mapper] ──→ .cube file from color grade description
                             │
                             ▼
                     [FFmpeg Execution Engine]
                     - trim/concat per cut decisions
                     - crop+scale per zoom decisions  
                     - setpts per speed decisions
                     - ass filter for captions
                     - lut3d for color grade
                     - amix/sidechaincompress for audio
                             │
                             ▼
                     EDITED VIDEO OUT
```

---

## Revised Cost Estimates (per 15-min video — OpenRouter May 2026)

| Component | Cost | Where It Runs |
|---|---|---|
| WhisperX transcription (×2 videos) | $0.02-0.10 | Self-hosted GPU |
| MediaPipe face tracking (×2 videos) | Free | CPU |
| PySceneDetect | Free | CPU |
| Librosa + Silero VAD | Free | CPU |
| OpenCV frame extraction | Free | CPU |
| **Vision Model — Phase 2 (Qwen 3.5 Flash/Plus)** | **$0.02** | **OpenRouter API** |
| **LLM Brain — Phase 3 (Gemini 3 Flash)** | **$0.06** | **OpenRouter API** |
| FFmpeg rendering | CPU time only | CPU (2-5 min) |
| **Total per video** | **$0.10-0.18** | |

At $79/mo with avg 20 videos/mo = **$2-3.60/mo per customer. Gross margins: 95-97%.**

Models with native video input (Qwen 3.5+, Gemini 3/2.5 Flash) may reduce this further — send video clips directly instead of extracting/sending individual frames.

## Cost by Video Length — The Real Numbers

The previous estimates were for a hypothetical "15-min video." In reality, creators upload everything from 5-minute tutorials to 3-hour livestreams. Every layer of the pipeline scales differently with length.

### Token cost per image frame

Image token consumption varies by model and resolution, typically ranging from 1,000 to 2,500 tokens per image for common resolutions.

For our use case (720p/1080p video frames resized to ~512px for classification):
- **Low detail / resized frame:** ~250-500 tokens per image (Gemini ~258, Claude ~300-400)
- **High detail / full res frame:** ~1,000-1,500 tokens per image
- **Qwen vision models:** similar range, ~300-600 tokens per resized frame

We'll use **400 tokens per frame** as a working average (resized to 512-768px).

### What scales with video length

| Pipeline Component | How it scales | 5 min | 15 min | 30 min | 60 min | 2 hrs |
|---|---|---|---|---|---|---|
| **WhisperX transcription** | Linear with audio duration | 5 min | 15 min | 30 min | 60 min | 120 min |
| **PySceneDetect** | Linear with video duration | Fast | Fast | Fast | Fast | Fast |
| **MediaPipe face tracking** | Linear per frame (24-30fps) | 7.5K frames | 22.5K frames | 45K frames | 90K frames | 180K frames |
| **Librosa audio analysis** | Linear with audio | Trivial | Trivial | Trivial | Trivial | Trivial |
| **VM-1: Edit intent** | Scales with # of cuts | ~20 cuts | ~50 cuts | ~80 cuts | ~130 cuts | ~250 cuts |
| **VM-3: B-roll ID** | Scales with # of scenes | ~20 scenes | ~50 scenes | ~80 scenes | ~130 scenes | ~250 scenes |
| **VM-7: Raw footage analysis** | 1 frame per 5-10 sec | 30-60 frames | 90-180 frames | 180-360 frames | 360-720 frames | 720-1440 frames |
| **VM-2: Zoom purpose** | Scales with # of zooms | ~5 zooms | ~15 zooms | ~25 zooms | ~40 zooms | ~80 zooms |
| **Brain EDL generation** | Input grows with all data | Medium | Medium | Large | Large | Very large |
| **FFmpeg rendering** | ~0.3-0.5x realtime on CPU | 1.5-2.5 min | 5-8 min | 10-15 min | 20-30 min | 40-60 min |

### Vision model token consumption by video length

**Assumptions:**
- 400 tokens per resized frame
- 2 frames per cut for VM-1, 1 frame per scene for VM-3
- 1 frame per 5 sec for VM-7 raw footage analysis
- 3 frames per zoom for VM-2
- VM-4, VM-5, VM-6 are fixed cost (one-time style extraction, ~20 frames total)

| Video Length | VM-1 frames | VM-3 frames | VM-7 frames | VM-2 frames | Total frames | Total tokens |
|---|---|---|---|---|---|---|
| **5 min** | 40 | 20 | 60 | 15 | 135 | ~54K |
| **15 min** | 100 | 50 | 180 | 45 | 375 | ~150K |
| **30 min** | 160 | 80 | 360 | 75 | 675 | ~270K |
| **60 min** | 260 | 130 | 720 | 120 | 1,230 | ~492K |
| **2 hrs** | 500 | 250 | 1,440 | 240 | 2,430 | ~972K |

### Cost per video by length (Qwen 3.5 Flash @ $0.065/MTok input)

| Video Length | Vision Input Cost | Brain Output Cost (Gemini 3 Flash) | WhisperX (self-hosted) | Total API Cost |
|---|---|---|---|---|
| **5 min** | $0.004 | $0.03 | $0.01 | **$0.04** |
| **15 min** | $0.010 | $0.06 | $0.02 | **$0.09** |
| **30 min** | $0.018 | $0.09 | $0.04 | **$0.15** |
| **60 min** | $0.032 | $0.15 | $0.08 | **$0.26** |
| **2 hrs** | $0.063 | $0.30 | $0.15 | **$0.51** |

### The problem at scale: context window limits

A 60-min video produces ~492K image tokens. Add transcript (~15K tokens) + structured data (~5K) = **~512K tokens in one call.** That fits in Qwen 3.5 Flash's 1M context window — barely.

A 2-hour video at ~972K tokens is pushing the limit. **Need to chunk the analysis:**
- Process in 15-30 min segments
- Merge results before feeding to the brain
- Brain still needs to see the full picture → may need the 1M context or summarization

### Context window fit check

| Model | Context Window | Max video length in single call |
|---|---|---|
| Qwen 3.5 Flash | 1M tokens | ~2 hrs (tight) |
| Qwen 3.5 Plus | 1M tokens | ~2 hrs (tight) |
| Gemini 3 Flash | 1.05M tokens | ~2 hrs |
| Gemini 2.5 Flash | 1.05M tokens | ~2 hrs |
| Grok 4.1 Fast | 2M tokens | ~4 hrs |
| Claude Sonnet 4.6 | 1M tokens | ~2 hrs |

For videos under 60 min: single-call processing works. For 1-3 hr videos: chunk into segments + merge.

### Pricing tiers for the product

Based on real costs:

| Plan | Video Length Limit | Videos/mo | Price | Cost/customer/mo | Margin |
|---|---|---|---|---|---|
| Starter | Up to 15 min | 10 | $29/mo | $0.90 | 97% |
| Creator | Up to 30 min | 30 | $59/mo | $4.50 | 92% |
| Pro | Up to 60 min | Unlimited | $99/mo | ~$8-15 (est 30-60 vids) | 85-92% |
| Studio | Up to 3 hrs | Unlimited | $199/mo | ~$15-40 | 80-92% |

**Key insight:** Even the heaviest usage tier (Studio, unlimited 3-hr videos) maintains 80%+ margins. The Qwen/Gemini pricing makes this viable at every length.

### Processing time by video length

This matters for UX — how long does the user wait?

| Video Length | Phase 1 (parallel) | Phase 2 (vision API) | Phase 3 (brain) | Phase 4 (FFmpeg) | **Total** |
|---|---|---|---|---|---|
| **5 min** | ~30s | ~15s | ~10s | ~2 min | **~3 min** |
| **15 min** | ~1 min | ~30s | ~15s | ~5 min | **~7 min** |
| **30 min** | ~2 min | ~1 min | ~20s | ~10 min | **~14 min** |
| **60 min** | ~4 min | ~2 min | ~30s | ~20 min | **~27 min** |
| **2 hrs** | ~8 min | ~4 min | ~1 min | ~45 min | **~58 min** |

FFmpeg rendering is the bottleneck. Can be parallelized by splitting into segments and rendering in parallel on multiple cores/workers. GPU-accelerated FFmpeg (NVENC) can cut render time by 3-5x.

---

**Skip for MVP:**
- Style extraction from reference video (hardcode a "good YouTube editing style" instead)
- Transition classification
- Color grade extraction
- Music/SFX insertion

**Build for MVP:**
1. WhisperX transcription → word-level timestamps
2. Silero VAD → silence detection + removal
3. Librosa → energy peaks for zoom triggers
4. MediaPipe → face tracking for zoom centering
5. Hardcoded edit rules (cut every 4-5 sec of silence, zoom 1.3x on energy peaks, add captions)
6. ASS subtitle generation for captions
7. FFmpeg pipeline to execute all edits
8. Simple web UI: upload video → get edited video back

**That's enough to validate whether the output quality is good enough that creators would pay for it.**

Then layer in style extraction from reference videos as v2.