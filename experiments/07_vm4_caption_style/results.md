# Experiment 07 — VM-4 Caption Style Extraction

**Phase:** Phase 2
**Status:** done
**Verdict:** ✅ **PASS** on gate metrics; ⚠️ caveat on label quality (model
conflates burnt-in graphic text with subtitle captions on this clip).
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (model calls hit OpenRouter — Alibaba upstream)

## Goal

For a reference video, sample frames at regular intervals and extract a
structured caption-style spec — the font/color/position/animation
description the brain stage needs to generate ASS subtitles for new raw
footage.

## Gate (from product.md §VM-4)

- **Cost ≤ $0.05** for the experiment (doc estimated $0.01 with
  Qwen Plus).
- **≥ 1 frame classified as having a caption** (else clip has no
  captions, or detection failed — both are useful signals to record).
- **Parse success rate ≥ 80%** (model returns valid JSON).
- Aggregate spec includes the **fields the brain needs to drive ASS
  rendering**: font_weight, color_text, position, background.

## What we ran

- **Input:** `samples/reference/reference.mp4` (1080p60, 11.4 min)
- **Sampling:** 12 evenly-spaced frames between 5% and 95% of the
  source duration (avoiding intro / outro).
- **Frame resolution:** 768 px wide, JPEG q=3
- **Model:** `qwen/qwen3-vl-32b-instruct` (Tier 2 quality VL)
- **Command:**
  ```bash
  python experiments/07_vm4_caption_style/run.py \
      --clip samples/reference/reference.mp4 --n-frames 12
  ```

## Observations

| Metric | Value |
|---|---|
| Frames evaluated | 12 |
| **Parse success rate** | **100% (12/12)** |
| Wall clock | 24.6 s (2.05 s / call avg) |
| Frames with caption (model said true) | 7 (58%) |
| **Total cost** | **$0.00097** |
| Cost per frame | $0.000081 |
| Total prompt tokens | ~5,200 (~430/call) |
| Total completion tokens | ~600 |

**Aggregated style descriptor** (mode across the 7 caption-positive frames):

| Field | Value |
|---|---|
| font_weight_mode | regular |
| font_style_mode | sans |
| color_text_mode | `#ffffff` |
| background_mode | box |
| position_mode | bottom |
| capitalization_mode | Sentence |

This is a usable spec that the brain stage can hand off to an ASS template:
white sans-serif regular, bottom-positioned, sentence case, with a box
background. Matches the visual character of the source's burnt-in
auto-captions.

**⚠️ Quality caveat I caught spot-checking the per-frame raw output:**
two of the "positive" hits — `frame 0 @ 34.23s` ("THE DOWNING STREET
ME_", `mono`, `middle`, `ALL_CAPS`) and `frame 2 @ 146.26s` ("THE DOWNI",
`sans`, `bottom`, `ALL_CAPS`) — are **graphic title text inside the
screencast content** (document titles overlaid in the video's own
graphics), not actual subtitle captions. The model can't tell the
difference from a single frame.

The mode-aggregation absorbs this somewhat (5 of the 7 positives agreed
on the bottom/sans/sentence template, dominating the modes), but on a
cleaner sample it could throw off the aggregate. This is a real product
risk worth flagging.

## Verdict against gate

- ✅ **Cost gate** ($0.00097 ≪ $0.05; even at full-spec 5-frame
  per-video, projected cost is $0.0004).
- ✅ **At least one positive frame** (7 of 12).
- ✅ **Parse rate** (100% ≥ 80%).
- ✅ **Aggregate spec includes required fields** (font_weight,
  color_text, position, background all populated).

**Overall: PASS, with two caveats.**

## Open questions / follow-ups

- **The model confuses on-screen graphic titles with caption overlays.**
  Mitigation ideas for the eventual product:
  - Add a "is this text part of the recorded scene or overlaid on
    top?" probe before the styling questions.
  - Use a Phase 1 OCR + position-stability heuristic to pre-filter
    caption regions (subtitles are usually bottom 20% and consistent
    across many frames; graphic text is typically transient and
    framed within content).
  - Send adjacent frame pairs and ask the model "is this text persistent
    across both frames?" — captions stay; graphic titles move with cuts.
- **No animation field measured.** product.md §VM-4 lists "Animation
  style (word-by-word highlight, pop-in, fade, karaoke, static)" as
  important, but per-frame snapshots can't capture motion. Would
  require either video-clip input (Exp 09) or a frame *triplet* with
  small temporal offsets. Note for FINDINGS.
- The **5 of 7 positives that agree on the bottom/sans/sentence
  template** suggest the auto-captioning style of the reference is
  fairly homogenous — good news for style transfer (the brain can
  learn from a smaller training sample than the doc estimated).

## Artifacts

- `outputs/07_vm4_caption_style/reference_vm4_caption_style.json`
  (~10 KB — full per-frame results + aggregated spec)
- `outputs/07_vm4_caption_style/reference/frames/frame_NN_tXX.X.jpg` —
  12 frames at 768 px

All gitignored.

## Links

- metrics.json: [`experiments/07_vm4_caption_style/metrics.json`](metrics.json)
- Related: Exp 13 (ASS caption rendering — consumes this spec)
- Product doc reference: [product.md](../../docs/product.md) §VM-4
  "Caption Style Extraction"
