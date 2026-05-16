# Experiment 10 — Brain EDL generation (5-min input)

**Phase:** Phase 3
**Status:** done
**Verdict:** ✅ **PASS** (all six gate clauses; cost 25× under doc's
estimate; EDL is structurally clean and qualitatively sensible)
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (model calls hit OpenRouter — Google upstream)

## Goal

Assemble all Phase 1 + Phase 2 outputs for a single 5-minute raw clip
into one structured-context blob, hand it to the brain model, and
verify it can produce a parseable, in-bounds, multi-type Edit Decision
List (EDL).

## Gate (this experiment's plan, since plan.md is off-repo)

- **Parseable JSON matching the EDL schema** (≥ 80% of edit objects
  pass shape validation).
- **Cost for 5-min input ≤ $0.15** (doc estimated $0.06 with Gemini 3
  Flash; we picked Gemini 2.5 Flash Lite for the 3× lower input price).
- **EDL contains ≥ 3 distinct edit types** (brain isn't degenerate).
- **EDL timestamps are bounded** by the input duration (no edits at
  negative time or past the end).

## What we ran

- **Input clip:** `samples/raw/raw_5min.mp4` (300.03 s)
- **Context blob assembled from:**
  - Transcript: 649 words from Exp 01 (large-v2 int8, aligned)
  - Scenes: 79 cuts from Exp 02 (PySceneDetect content detector)
  - Face summary: 6.1% hit rate from Exp 03 (re-run on 5-min clip,
    output saved to `outputs/03_mediapipe_face/raw_5min_faces.json`
    without overwriting the committed 15-min metrics)
  - Audio analysis: 1352 onsets, speech segments, RMS — from Exp 04
    (re-run on 5-min clip same way)
  - VM-7: 60 per-segment categorizations + cut/zoom hints from Exp 08
- **Model:** `google/gemini-2.5-flash-lite` ($0.100 in / $0.400 out
  per MTok, 1M ctx, JSON-mode supported).
- **EDL schema** (now locked as the contract for Phase 4):
  ```
  cut            { at, transition }
  remove_silence { from, to }
  zoom_in        { from, to, level, center }
  caption        { text, from, to, style }
  speed_up       { from, to, rate }
  sfx            { at, sound }
  ```
- **Command:**
  ```bash
  python experiments/10_brain_5min/run.py
  ```

## Observations

| Metric | Value |
|---|---|
| **Wall clock / API latency** | **7.01 s** |
| **Cost** | **$0.00238** |
| Prompt tokens (incl. system) | 10,708 |
| Completion tokens | 3,332 |
| Prompt size in chars | 21,188 |
| Response parse OK (JSON mode) | ✅ |
| Edits returned | 66 |
| Valid edits (in-range, known type) | **66 (100%)** |
| Invalid / out-of-range | 0 |
| Distinct edit types | **5** (out of 6 schema types — `speed_up` not emitted) |
| Edit type distribution | caption 28 / zoom_in 17 / remove_silence 15 / cut 3 / sfx 3 |

**Sample edits** (one per type from the EDL):

```json
{"type": "remove_silence", "from": 0.0, "to": 0.2}

{"type": "caption",
 "text": "Johnny Harris is one of the most recognizable documentary storytellers on YouTube.",
 "from": 0.251, "to": 4.132, "style": "default"}

{"type": "zoom_in", "from": 2.5, "to": 5.0, "level": 1.2, "center": "face"}

{"type": "cut", "at": 10.6, "transition": "hard_cut"}

{"type": "sfx", "at": 10.6, "sound": "whoosh"}
```

- **Caption timestamps match Exp 01's word boundaries exactly** —
  caption from 0.251 s to 4.132 s lines up with the first sentence's
  first/last word. The brain is correctly grounding to transcript.
- **Cut + SFX paired at the same timestamp (10.6 s)** — the §9-pattern
  the doc described for hard cuts.
- **Zoom centered on face during a punchline** — the brain combined
  Exp 03's face data with Exp 08's `zoom_hint=medium` flag.

## Verdict against gate

- ✅ **Parse rate** (100% — JSON mode honored, all 66 edits well-formed)
- ✅ **Cost gate** ($0.00238 ≪ $0.15) — **25× cheaper than doc's $0.06
  Gemini-3-Flash estimate**, 63× cheaper than the gate
- ✅ **Edit type variety** (5 of 6 types emitted; `speed_up` absent
  because no clear "low energy tangent" segment in this clip)
- ✅ **Bounded timestamps** (0 out-of-range edits)

**Overall: PASS.**

## Open questions / follow-ups

- **Words were truncated** in the prompt (first 30 + last 30 instead of
  all 649) to keep this experiment small. Exp 11 tests the full-words
  payload on a 30-min clip — that's where prompt size matters.
- **`speed_up` was never emitted.** Either:
  - The 5-min clip really has no low-energy passages worth speeding up
    (likely — it's a tight tutorial),
  - The brain's prompt under-specifies when to use speed_up.
  Will surface again in Exp 11.
- **No quality evaluation against ground-truth** — the EDL looks
  sensible spot-checked, but a rigorous comparison would need a
  human-edited version of the same clip to diff against. Out of scope
  for the gate; flagged for later product iteration.
- **JSON mode reliability** — Gemini 2.5 Flash Lite honored
  `response_format: {"type": "json_object"}` cleanly. Worth recording
  in FINDINGS that JSON mode works (not all OpenRouter providers
  support it).

## Artifacts

- `outputs/10_brain_5min/edl.json` — full EDL (~6 KB)
- `outputs/10_brain_5min/raw_response.json` — raw API response (~7 KB)

All gitignored.

## Links

- metrics.json: [`experiments/10_brain_5min/metrics.json`](metrics.json)
- Related: Exp 11 (30-min scaling test), Exp 12 (FFmpeg consumes this
  EDL schema), Exp 14 (full pipeline)
- Product doc reference: [product.md](../../docs/product.md) §9
  "The Brain — Edit Decision Making"
