# Experiment 06 — VM-1 Edit Intent Classification

**Phase:** Phase 2
**Status:** done
**Verdict:** ✅ **PASS** (well under cost gate, 100% parse rate, label
distribution sensible)
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (model calls hit OpenRouter — Alibaba upstream)

## Goal

For each cut produced by PySceneDetect (Exp 02), send the last frame
before + first frame after to a cheap vision model and ask it to
classify the **intent** of the cut (not just confirm one exists). The
five labels per `product.md` §VM-1: jump_cut, topic_transition,
b_roll_insert, reaction_cut, cutaway.

## Gate (from product.md §VM-1 + this experiment's plan)

- **Cost gate:** ≤ $0.05 per 50-cut classification (doc estimated $0.29
  on GPT-4o, $0.005 on the now-defunct Qwen Flash; using $0.05 as the
  conservative gate based on the doc's modern-Qwen estimate).
- **Parse success rate ≥ 90%** (model returns valid JSON with one of
  the five labels).
- **Label distribution is non-trivially varied** on a multi-cut clip
  (not all the same label).

## What we ran

- **Input:** `samples/reference/reference.mp4` (1080p60, 11.4 min,
  308 cuts from Exp 02). Sent first **30 cuts** as the experimental
  sample — enough to validate gates without burning budget.
- **Frame extraction:** ±0.1 s around each cut timestamp, scaled to
  512 px wide, JPEG q=4.
- **Model:** `qwen/qwen3-vl-8b-instruct` via OpenRouter
  ($0.080 in / $0.500 out per MTok, no separate image surcharge).
- **Prompt:** structured ask for `{label, confidence, rationale}` JSON.
- **Command:**
  ```bash
  python experiments/06_vm1_edit_intent/run.py \
      --scenes outputs/02_pyscenedetect/reference_content_scenes.json \
      --clip samples/reference/reference.mp4 \
      --n-cuts 30
  ```

## Observations

| Metric | Value |
|---|---|
| Cuts classified | 30 |
| **Parse success rate** | **100% (30/30)** — all returned valid JSON |
| Wall clock | 49.82 s (1.66 s / call avg) |
| **Total cost** | **$0.00366** |
| **Cost per cut** | **$0.000122** |
| Total prompt tokens (across all calls) | 14,340 (~478/call: 2 frames × ~200 tok + prompt) |
| Total completion tokens | 1,474 (~49/call) |
| Label distribution | cutaway 11 / topic_transition 8 / b_roll_insert 6 / jump_cut 5 / reaction_cut 0 |
| **Projected cost for 15-min video at this cut density (404 cuts)** | **$0.049** |

**Sample classifications** (one per label, with rationale verbatim):

- `cut 1 @ 2.98s` → **b_roll_insert** (0.95): "The cut transitions into
  a YouTube channel interface screen recording, fitting the definition
  of a b_roll_insert."
- `cut 2 @ 8.98s` → **topic_transition** (0.98): "The video shifts from
  a financial chart to historical footage, indicating a clear change in
  subject matter."
- `cut 3 @ 9.30s` → **cutaway** (0.98): "The cut transitions to a
  black-and-white historical document with circled text, serving as a
  supporting visual to explain the topic."
- `cut 10 @ 18.20s` → **jump_cut** (0.95): "The frames show a sudden,
  abrupt transition from a document close-up to a blank/blurry screen,
  indicating time skipped for pacing."

Spot-checking these against the source: all four are correct calls. The
absence of `reaction_cut` is consistent with the source genre (editing
tutorial, not a vlog) — no faces means no reactions.

## Verdict against gate

- ✅ **Cost gate** ($0.00366 for 30 cuts ≪ $0.05 for 50; projected
  $0.049 for a typical 15-min video — exceeds doc's $0.29 GPT-4o
  estimate by 6× on the savings side).
- ✅ **Parse success rate** (100% ≥ 90%).
- ✅ **Label distribution** (4 of 5 labels populated; the absent
  `reaction_cut` is correct for this content).

**Overall: PASS.**

## Open questions / follow-ups

- **Per-image token count is ~200**, not the doc's "765 tokens per image
  high-detail" or "85 tokens low-detail" — Qwen3-VL's image tokenization
  is more aggressive at low resolutions. This is why the cost is so low.
  Worth highlighting in FINDINGS: the 765-token assumption in
  product.md is a GPT-4o-era number; modern open-weight VLMs are 3–5×
  cheaper per image.
- **`reaction_cut` was 0 on this clip.** That's correct for screencast
  content but means we haven't validated the model can find that label
  when it exists. Need a talking-head clip to test (same gap as Exp 03).
- The classifications themselves look strong on spot-check, but a
  rigorous WER/F1 against ground-truth labels would require a
  human-labeled set — out of scope here.

## Artifacts

- `outputs/06_vm1_edit_intent/reference_vm1_classifications.json`
  (~20 KB — all 30 classifications with rationales + per-call cost)
- `outputs/06_vm1_edit_intent/reference/frames/cut_NNNN_a.jpg` and
  `_b.jpg` — 60 frames total (~360 KB combined at 512 px wide)

All gitignored.

## Links

- metrics.json: [`experiments/06_vm1_edit_intent/metrics.json`](metrics.json)
- Related: Exp 02 (provides the cut list), Exp 09 (compares native-video
  input vs frame-extraction), Exp 10 (brain consumes these labels)
- Product doc reference: [product.md](../../docs/product.md) §VM-1
  "Edit Intent Classification"
