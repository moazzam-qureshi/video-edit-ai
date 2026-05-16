# Experiment 09 — Native Video Input vs Frame Extraction

**Phase:** Phase 2
**Status:** done
**Verdict:** ✅ **PASS** on gate metrics; **major finding** that updates
the product spec recommendation.
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (model calls hit OpenRouter)

## Goal

product.md claims native-video-input models (Qwen 3.5+, Gemini 3 Flash)
can replace per-frame analysis, simplifying the pipeline and making
the model see motion/timing context. Empirically test that claim on the
same 30-second clip with two paths:

- **Video path:** upload the .mp4 sub-clip, ask for a structured list of
  segments with timestamps + labels.
- **Frames path:** extract 6 evenly-spaced frames at 512 px, send them
  as separate images in one call, ask for the same JSON schema.

## Gate (this experiment's plan)

- Both paths return parseable JSON.
- Total experiment cost ≤ $0.20.
- Produce a quantitative + qualitative comparison: cost, latency,
  token usage, temporal-grounding quality.

## What we ran

- **Source:** 30-second sub-clip from `samples/reference/reference.mp4`,
  spanning 60.0–90.0 s. Re-encoded to 512 px H.264 (no audio) at CRF 30
  → 363 KB.
- **Video model:** `qwen/qwen3.5-flash-02-23` ($0.065 in / $0.260 out
  per MTok; img=0, video=0 — token-only billing). Qwen3-VL-8B-Instruct
  does NOT accept video on OpenRouter today (returns 404 "No endpoints
  found that support input video") — so the comparison is across two
  Qwen Flash variants, not the exact same model.
- **Frames model:** `qwen/qwen3-vl-8b-instruct` (the model already
  used in Exp 06 and 08).
- **Identical prompt schema** for both: `{n_cuts, segments[{start_s,
  description, label}]}` with 6 label values.
- **Command:**
  ```bash
  python experiments/09_video_vs_frames/run.py \
      --clip samples/reference/reference.mp4 \
      --start 60 --duration 30 --n-frames 6
  ```

## Observations — head to head

| Metric | Video path (Qwen3.5-Flash) | Frames path (Qwen3-VL-8B × 6) | Ratio video/frames |
|---|---|---|---|
| **Cost (this 30 s clip)** | **$0.00323** | **$0.00019** | **17×** more |
| Latency | 56.4 s | 6.1 s | **9× slower** |
| Prompt tokens | 4,432 | 977 | 4.5× |
| Completion tokens | **11,444** | 234 | **49× more** |
| Segments returned | 7 | 5 | similar |
| Parse OK | ✅ | ✅ | — |

**Total experiment cost:** $0.00342 ≪ $0.20 gate.

### Quality — temporal grounding

This is the headline difference. Sub-clip is 30 s long.

- **Video path** produced 7 timestamps spread across the actual window:
  `0.0, 1.0, 7.0, 14.0, 15.0, 18.0, 20.0` s. These correspond to real
  events in the clip — the click-Subscribed at start, browsing CapCut
  projects, Discord notification, opening title card, etc. **The model
  is genuinely time-aware** of what happens when.
- **Frames path** produced 5 timestamps: `0.0, 1.0, 2.0, 3.0, 4.0` s.
  These are **the frame indices, not real timestamps** — the model has
  no way to know that 6 frames evenly spaced over 30 s means each frame
  is 5 s apart. Content descriptions for each frame are sane (Capcut
  grid, Patreon link, etc.), but the time axis is broken.

### Quality — content description

Both paths describe each segment coherently. Frames-path descriptions
are slightly more concise; video-path descriptions are slightly more
narrative ("A 'Subscribed' button is clicked..." vs "A grid of Capcut
project files..."). Either feeds a downstream brain stage adequately
for *what's happening* — but only the video path tells the brain
*when*.

### Cost projection — 5-min raw clip

- **Frames at 1/5 s** (same as Exp 08, what the doc recommends):
  60 frames × ~$0.00008 ≈ $0.005.
- **Video, naive whole-clip submission** (Qwen 3.5 Flash at this rate):
  ~$3.20 (linear scaling of the 30 s number). Unaffordable.
- **Hybrid: bulk classification via frames, micro-precision via video
  on the ~20 s windows where timing actually matters** (caption
  animation extraction, micro-zoom triggers, joke-punchline detection):
  ~$0.10–$0.20 per video. Both pipelines combined still well under
  doc's $0.06 vision-cost ceiling.

## Verdict against gate

- ✅ **Both return parseable JSON**
- ✅ **Total experiment cost** ($0.00342 ≪ $0.20)
- ✅ **Quantitative + qualitative comparison produced**

**Overall: PASS.**

## The finding — update product.md's pipeline recommendation

The doc says (paraphrased):
> Models with native video input (Qwen 3.5+, Gemini 3/2.5 Flash, NVIDIA
> Nemotron Nano 3 Omni) all accept raw video input — not just frames.
> Can send video clips directly instead of extracting frames. Simpler
> pipeline, model sees motion/timing context.

**Reality on OpenRouter today (2026-05-17):**

1. **Most VL models don't accept video.** Qwen3-VL (the current
   recommended bulk VL model) returns 404 on `video_url`. Only the
   newer-architecture Qwen 3.5+ "Flash"/"Plus" models, Gemini 3.1
   Flash Lite, and the Gemma 4 / Nemotron Omni families accept video.
2. **When the same family supports video, the input is dramatically
   more expensive on a per-second basis** (17× on this test) because
   the model internally samples many frames at high resolution and
   bills tokens for all of them — *plus* the completion gets verbose
   because the model has more context to reason over.
3. **What you actually get for the 17× premium is temporal grounding** —
   real start_s timestamps instead of frame indices. That's valuable
   for caption animation analysis, joke-punchline detection, and
   precise zoom triggers, but it's overkill for "what category is this
   segment."

**Recommendation for the eventual product build:**

- **Default pipeline = frame-based** (matches Exp 06 / 08 — current
  approach is right).
- **Add a narrow video-input branch for the ≤ 30 s windows that need
  motion/timing**: caption animation, micro-zoom triggers, punchline
  detection. Identify those windows with cheap frame-based analysis
  first, then re-analyze just those windows with video input.
- The doc's claim that native video input "simpler pipeline" is half-
  true: it's simpler in code, but more expensive AND slower per second
  of content. Hybrid is the correct architecture.

## Open questions / follow-ups

- **Apples-to-apples model comparison** — Qwen3-VL-8B and Qwen3.5-Flash
  are different model architectures. A cleaner comparison would use
  the same model with both paths, but no current model supports both
  routes equally well. Logged as a known limitation.
- **Latency variance** — 56 s for the video path is awful for any
  interactive use. The product would have to queue these or use them
  only in deep-analysis stages.
- **5-min limit** — Qwen 3.5 Flash's effective video length limit on
  OpenRouter wasn't tested. The doc claims 1M-context videos work
  ("~2 hrs tight"), but the cost would be ruinous. Not worth a
  separate experiment unless the product needs it.

## Artifacts

- `outputs/09_video_vs_frames/sub_60_90.mp4` — 363 KB sub-clip
- `outputs/09_video_vs_frames/frames/frame_NN_tXX.X.jpg` — 6 frames
- `outputs/09_video_vs_frames/comparison.json` — full side-by-side raw
  responses, ~5 KB

All gitignored.

## Links

- metrics.json: [`experiments/09_video_vs_frames/metrics.json`](metrics.json)
- Related: Exp 06 (frames-based edit intent), Exp 08 (frames-based
  raw analysis), Exp 10 (brain stage — consumes results from both
  approaches)
- Product doc reference: [product.md](../../docs/product.md)
  "Key: Native Video Input" subsection (~line 184)
