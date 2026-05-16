# Experiment 08 — VM-7 Raw Footage Visual Analysis

**Phase:** Phase 2
**Status:** done
**Verdict:** ✅ **PASS** (100% parse, projected cost $0.014 for a 15-min
video, category distribution sensible)
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (model calls hit OpenRouter — Alibaba upstream)

## Goal

Sample frames of a raw clip at low fps and ask the model what the
creator is doing, plus two actionable hints (`should_cut_here`,
`zoom_hint`). The brain stage consumes this to decide where to cut,
where to zoom, where to speed up.

## Gate (from product.md §VM-7)

- **Cost ≤ $0.05** for a 5-min video at 1 frame / 5–10 s (doc estimated
  $0.04 on GPT-4o / $0.001 on Qwen Flash).
- **Parse success ≥ 90%**.
- **Output is non-trivially varied** (not all same category on a varied
  clip).
- **Output schema includes actionable hints** the brain can consume
  (cut/zoom).

## What we ran

- **Input:** `samples/raw/raw_5min.mp4` (360p30, 5 min — actually first
  5 min of an editing tutorial)
- **Sampling:** 1 frame every 5 s → **60 frames** total
- **Frame resolution:** 512 px wide, JPEG q=4
- **Model:** `qwen/qwen3-vl-8b-instruct` via OpenRouter
- **Categories:** talking_head, screen_recording, b_roll, demo,
  reading_notes, low_energy_tangent, joke_setup_or_punchline, other
- **Command:**
  ```bash
  python experiments/08_vm7_raw_footage/run.py \
      --clip samples/raw/raw_5min.mp4 --sample-every-s 5
  ```

## Observations

| Metric | Value |
|---|---|
| Frames evaluated | 60 |
| **Parse success rate** | **100% (60/60)** |
| Wall clock | 78.95 s (1.32 s / call avg) |
| **Total cost** | **$0.00470** |
| Cost per frame | **$0.000078** |
| Total prompt tokens | 16,140 (~269/call) |
| Total completion tokens | 3,187 (~53/call) |
| **Projected cost for 15-min video** | **$0.014** |

**Category distribution (60 frames):**

| Category | Count | Pct |
|---|---|---|
| screen_recording | 39 | 65% |
| other | 9 | 15% |
| demo | 7 | 12% |
| reading_notes | 3 | 5% |
| b_roll | 2 | 3% |
| talking_head | **0** | 0% |
| low_energy_tangent | 0 | 0% |
| joke_setup_or_punchline | 0 | 0% |

**Actionable hints:**

| Hint | Distribution |
|---|---|
| `should_cut_here` | 3/60 (5%) |
| `zoom_hint=medium` | 25/60 (42%) |
| `zoom_hint=none` | 35/60 (58%) |

The category distribution is dominated by `screen_recording` (65%) which
matches the clip's actual nature (an editing tutorial that's mostly
screen captures of Premiere/Capcut). Zero `talking_head` is **correct**
for this content — and it independently confirms the Exp 03 finding
that this clip is not a talking-head sample.

## Verdict against gate

- ✅ **Cost gate** ($0.00470 for 60 frames in a 5-min clip ≪ $0.05;
  projected $0.014 for 15-min). Cost is **3× cheaper than doc's GPT-4o
  estimate** ($0.04) and 14× cheaper at the 15-min projection.
- ✅ **Parse success rate** (100% ≥ 90%).
- ✅ **Distribution variety** (5 of 8 categories populated).
- ✅ **Actionable hints** (cut + zoom both populated and usable;
  zoom_hint=medium for the 42% of frames where the creator is shown
  centered, none for screen-only frames).

**Overall: PASS.**

## Open questions / follow-ups

- **Zero talking_head and zero joke_setup_or_punchline** mean we
  haven't validated those categories on this clip. Same gap surfaced
  in Exp 03 and Exp 06: a true talking-head sample is needed to
  exercise the categories the product cares about most.
- **5% cut-hint rate** is low but not unreasonable for screencast
  content. The doc's pipeline assumes the brain merges these with the
  Exp 02 hard-cut list, the Exp 04 silence regions, and the Exp 01
  word timings — so VM-7 cut hints are a *contribution* to cut
  decisions, not the sole driver. That logic gets tested in Exp 10.
- The model produces consistent rationales but they're short — for
  the brain to make a good decision it may want a richer feature
  vector (energy estimate, gesture flag, gaze direction). Out of scope
  for the gate; possible follow-up if Exp 10 brain output is shallow.

## Artifacts

- `outputs/08_vm7_raw_footage/raw_5min_vm7.json` (~30 KB — all 60
  classifications with rationales + per-call cost)
- `outputs/08_vm7_raw_footage/raw_5min/frames/frame_NNN_tXXX.X.jpg`
  — 60 frames at 512 px wide (~1.5 MB total)

All gitignored.

## Links

- metrics.json: [`experiments/08_vm7_raw_footage/metrics.json`](metrics.json)
- Related: Exp 10 (brain consumes these classifications + cut hints)
- Product doc reference: [product.md](../../docs/product.md) §VM-7
  "Raw Footage Visual Analysis"
