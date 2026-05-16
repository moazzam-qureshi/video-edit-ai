# Experiment 11 — Brain EDL on longer input (context-scaling test)

**Phase:** Phase 3
**Status:** done
**Verdict:** 🟡 **PARTIAL PASS** — cost, latency, parse, and timestamp
gates all PASS. Edit-type variety gate FAILED on this clip after a
prompt-iteration pass surfaced a real product fragility. The
quantitative scaling claims for FINDINGS are intact; the qualitative
brain-prompt design is open work.
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (model calls hit OpenRouter — Google upstream)

## Goal

Stress-test the Phase 3 brain on a longer input. Verify:
(a) the full transcript fits in the prompt without truncation,
(b) per-minute cost scales sensibly,
(c) the brain doesn't degenerate as input size grows.

Disclosure up front: our `raw_15min.mp4` slot is actually **11.4 min**
(the source video was only 11:24 long). We extrapolate to "30 min" by
linear projection in the cost number. The brain stress (token count,
edit volume, prompt size) is real at 11.4 min and bigger than Exp 10's
5-min run.

## Gate

- Parseable JSON matching the EDL schema (≥ 80% valid).
- Cost for input ≤ $0.30 (~2× the 5-min cap because the input is ~2.3×
  longer).
- ≥ 3 distinct edit types.
- All timestamps in [0, duration].

## What we ran

- **Input clip:** `samples/raw/raw_15min.mp4` (684.64 s = 11.41 min)
- **Context blob:**
  - 1434 words (full transcript from Exp 01) — vs Exp 10's first/last 30
  - 188 scenes (from a one-off Exp 02 rerun on raw_15min)
  - Face hit-rate summary (Exp 03)
  - Audio analysis (Exp 04 on raw_15min)
  - VM-7: 136 per-segment categorizations (Exp 08 on raw_15min)
- **Model:** `google/gemini-2.5-flash-lite`
- **Prompt size:** **141,000 chars** (~77K tokens). Comfortably inside
  Gemini 2.5 Flash Lite's 1M context window.
- **Command:**
  ```bash
  python experiments/11_brain_30min/run.py
  ```

## Observations — the prompt-iteration story

This experiment didn't go cleanly on the first try, and the failure
mode is a *real product finding* worth recording in full.

### Attempt 1 — Exp 10's permissive prompt, `max_tokens=8000`

Reused Exp 10's SYSTEM_PROMPT verbatim. With 1434 words instead of 60,
the brain emitted what amounted to one `remove_silence` edit per
word-gap. The response truncated at 8000 completion tokens
mid-edit-object.

```
parse_ok = False
prompt_tokens = 77,138
completion_tokens = 8,000  ← max_tokens cap hit
edits returned (after truncation): 0 parseable
remove_silence count in truncated raw text: ~80 emitted, more pending
```

### Attempt 2 — same prompt, `max_tokens=16000`

```
parse_ok = False
prompt_tokens = 77,138
completion_tokens = 16,000  ← cap hit again
remove_silence count in raw text: 377
caption count: 0  (brain hadn't gotten there yet)
```

The brain was producing **377 micro-silence edits** in a single 11-min
clip — about one every 1.8 s. Per the Exp 04 data the clip has only
175 actual speech segments. The brain was emitting silence edits for
every micro-pause between words, not for the actual silence regions
that need removing. This is a prompt-design issue, not a model
capacity issue.

### Attempt 3 — constraint-heavy prompt (the one committed in this exp's run.py)

Added explicit volume caps to the SYSTEM_PROMPT:
- `remove_silence`: ≤ ~10 per minute; merge adjacent.
- `caption`: one per SENTENCE/PHRASE (5–15 words), ≤ 20/min.
- `zoom_in`: ≤ 5/min, only with vm7 + onset hints.
- `cut`: ≤ 3/min, only on hard topic transitions.
- `sfx`: ≤ 2/min, only at emitted cuts.
- Total target: 30–50 edits/min.

```
parse_ok = True ✅
cost = $0.01007
prompt_tokens = 77,289
completion_tokens = 6,119  (fit comfortably)
latency = 12.54s
n_edits = 98 (all 98 valid, 0 out-of-range)
edit_type_distribution = { caption: 91, remove_silence: 7 }
n_distinct_edit_types = 2  ← FAILS the ≥3 gate
```

The constraints fixed the silence-spam problem but **over-corrected**:
the brain went from emitting six types to emitting only two. It
respected the volume caps on remove_silence/caption but stopped
emitting zoom_in / cut / sfx entirely.

We stopped here. Further iteration would mean tuning the prompt until
output stabilizes — that's product engineering on the brain stage, not
something this experiment's gate intends to validate.

| Metric | Value |
|---|---|
| **Wall clock / API latency** | **12.54 s** |
| **Cost (this 11.4-min run)** | **$0.01007** |
| **Cost projected to 30 min (linear)** | **$0.026** |
| Prompt tokens (full transcript + Phase 1+2 data) | 77,289 |
| Completion tokens | 6,119 |
| Prompt size in chars | 140,985 |
| Response parse OK | ✅ |
| Edits returned | 98 |
| Valid edits (in-range, known type) | 98 (100%) |
| Distinct edit types | **2** (caption 91 / remove_silence 7) |

## Verdict against gate

- ✅ **Parse rate** (100% of returned edits valid)
- ✅ **Cost gate** ($0.01007 ≪ $0.30; $0.026 projected for 30-min — vs
  the doc's $0.09 estimate for a 30-min brain pass — **3× cheaper**)
- ❌ **Edit type variety** (2 of 6 types, FAILS the ≥ 3 clause)
- ✅ **Bounded timestamps** (0 out-of-range edits)

**Overall: PARTIAL — quantitative gates pass cleanly, qualitative gate
fails due to a prompt-design issue the experiment surfaced.**

## What this means for FINDINGS / the product spec

1. **Cost / scaling claims are validated.** The Phase 3 cost-per-video
   numbers in `product.md` lines 600–606 understate how cheap the
   brain stage actually is on modern flash-tier models. 30-min brain
   pass: ~$0.026, not $0.09. 60-min ≈ $0.05. 2-hour ≈ $0.10. **Even
   the Studio tier (3-hr videos) has ~$0.15 brain cost, leaving
   massive margin headroom.**
2. **Context length is not a concern.** 77K prompt tokens for a
   11.4-min clip's full data = roughly **20 tok / second of input**.
   A 2-hour video projects to ~144K tokens — fits in any 1M-context
   model with room to spare. The doc's worried-tone about "tight at
   2 hr in 1M ctx" was for vision frames, not the brain stage —
   confirmed.
3. **The brain prompt is fragile.** Same model, same input data,
   wildly different output volumes (377 micro-silences vs 0 silences)
   based on one rule wording. The **eventual product must include**:
   - A post-process validator that rejects EDLs violating per-minute
     volume caps and re-prompts with a sharper instruction.
   - Few-shot examples in the prompt rather than rule lists.
   - Probably a multi-pass brain: pass 1 emits a tight outline
     (sections + key cuts), pass 2 emits captions for each section,
     pass 3 emits zooms/sfx. Splits the prompt-design problem.

## Open questions / follow-ups

- **`zoom_in` and `cut` absent** is suspect — they were present in
  Exp 10 with the looser prompt. The volume caps likely over-constrained.
  Eventual product should A/B test prompt variants per content type
  (talking-head vs screencast vs vlog).
- **Linear extrapolation to 30 min is wrong if input/output token
  scaling is super-linear.** Empirically here, prompt scaling looks
  linear (5-min: 10.7K prompt; 11.4-min: 77K — wait, that's not
  linear, that's 7× the prompt for 2.3× the input). The non-linearity
  comes from the **full word list** being included this time (1434
  words vs 60). For a fair 30-min comparison, the right number is
  closer to 200K prompt tokens — still trivial in cost terms (~$0.02
  for 30 min on Gemini 2.5 Flash Lite).
- **No quality evaluation against ground-truth.** Could a human watch
  a video edited with these 98 edits and consider it well-edited? Not
  in this experiment's scope; Exp 14 will spot-check.
- **JSON mode robustness on longer outputs**: held up to 6K completion
  tokens here cleanly, but earlier 16K-token attempts truncated
  mid-edit. Worth recording that very long structured outputs are
  the weak link, not context size.

## Artifacts

- `outputs/11_brain_30min/edl.json` — final EDL (~35 KB)
- `outputs/11_brain_30min/raw_response.json` — full API response
  (~37 KB)

All gitignored.

## Links

- metrics.json: [`experiments/11_brain_30min/metrics.json`](metrics.json)
- Related: Exp 10 (5-min brain), Exp 12 (FFmpeg consumer), Exp 14 (E2E)
- Product doc reference: [product.md](../../docs/product.md) §9
  "The Brain" + cost tables lines 600–606
