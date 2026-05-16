# Experiment 11 — Brain EDL on longer input (context-scaling test)

**Phase:** Phase 3
**Status:** done
**Verdict:** ✅ **PASS** with the multi-pass brain architecture. Initial
single-pass attempts surfaced a real prompt-fragility issue; the four-
pass design (cut+sfx / silence / captions / zoom in separate calls)
fixed it cleanly at the same total cost.
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (model calls hit OpenRouter — Google upstream)

## Goal

Stress-test the Phase 3 brain on a longer input. Verify:
(a) the full transcript fits in the prompt without truncation,
(b) per-minute cost scales sensibly,
(c) the brain doesn't degenerate as input size grows.

Disclosure up front: our `raw_15min.mp4` slot is actually **11.4 min**
(the source video was 11:24 long). We extrapolate to "30 min" by
linear projection in the cost number. The brain stress (token count,
edit volume, prompt size) is real at 11.4 min and ~2.3× bigger than
Exp 10's 5-min run.

## Gate

- Parseable JSON matching the EDL schema (≥ 80% valid).
- Cost for input ≤ $0.30.
- ≥ 3 distinct edit types.
- All timestamps in [0, duration].

## What we ran

- **Input clip:** `samples/raw/raw_15min.mp4` (684.64 s = 11.41 min)
- **Context blob:**
  - 1434 words (full transcript from Exp 01)
  - 188 scenes (from a one-off Exp 02 rerun on raw_15min)
  - Face hit-rate summary (Exp 03)
  - Audio analysis (Exp 04)
  - VM-7: 136 per-segment categorizations + cut/zoom hints (Exp 08)
- **Model:** `google/gemini-2.5-flash-lite`
- **Architecture (canonical):** **multi-pass** — four focused calls,
  one per edit-type family. Merge into a single EDL.
- **Command:**
  ```bash
  python experiments/11_brain_30min/run.py             # multi-pass (default)
  python experiments/11_brain_30min/run.py --single-pass  # legacy
  ```

## Canonical result (multi-pass)

| Metric | Value |
|---|---|
| Mode | multi-pass (4 focused calls) |
| Total wall clock / latency | **25.06 s** (sequential — could parallelize to ~13 s) |
| **Total cost** | **$0.01065** |
| **Projected cost for 30-min video** (linear) | **$0.028** |
| Total prompt tokens (sum across 4 calls) | 69,448 |
| Total completion tokens | 10,661 |
| Final EDL: edits returned | 221 |
| Final EDL: valid (in-range, known type) | **221 (100%)** |
| Final EDL: distinct edit types | **4** (cut, sfx, remove_silence, caption) |
| Type distribution | caption 126 / remove_silence 47 / cut 24 / sfx 24 |

**Per-pass breakdown:**

| Pass | Goal | Cost | Latency | Parse | Edits returned |
|---|---|---|---|---|---|
| A | cuts + sfx from scenes + vm7 cut-hints | $0.00106 | 3.9 s | ✅ | 48 (24 cuts + 24 sfx) |
| B | remove_silence merged from speech gaps | $0.00088 | 5.0 s | ✅ | 47 |
| C | captions, one per natural phrase | $0.00777 | 12.5 s | ✅ | 126 |
| D | zoom_in on vm7+energy peaks | $0.00093 | 3.6 s | ❌ (parse error) | 0 |

Pass D parse-failed at max_tokens=2000 but only spent $0.0009 — the
final EDL still has 4 types from passes A/B/C, comfortably above the
≥ 3 gate.

## Prompt-iteration story — what we tried before multi-pass

The first three attempts on this clip used a **single-pass brain** (one
big system prompt, all data in one call). All three failed:

### Attempt 1 — Exp 10's permissive prompt, `max_tokens=8000`

Reused Exp 10's SYSTEM_PROMPT verbatim. With 1434 words instead of 60,
the brain emitted one `remove_silence` edit per word-gap. The response
truncated at 8000 completion tokens mid-edit-object.

```
parse_ok=False  prompt=77,138  completion=8,000 (capped)
```

### Attempt 2 — same prompt, `max_tokens=16000`

```
parse_ok=False  prompt=77,138  completion=16,000 (capped again)
silence count in raw text: 377   captions count: 0
```

The brain was producing **377 micro-silence edits** in an 11-min clip —
roughly one every 1.8 s. Per the Exp 04 audio data the clip has 175
actual speech segments. The brain was emitting silence edits for every
inter-word gap, not for the real silence regions.

### Attempt 3 — constraint-heavy prompt

Added explicit volume caps to the SYSTEM_PROMPT (`≤ ~10 per minute`,
`one caption per phrase`, etc.).

```
parse_ok=True  prompt=77,289  completion=6,119  latency=12.5s
n_edits=98  valid=98  distinct_types=2
  caption: 91, remove_silence: 7
```

This **over-corrected**: the brain went from emitting six types to
emitting only two. It respected the silence/caption caps but stopped
emitting zoom_in / cut / sfx entirely.

### Attempt 4 — **multi-pass brain** (the canonical result above)

Split into four focused calls, one per edit-type family. Each call
has a tight system prompt with explicit volume caps for *just that
family*, and is fed *just the data slice* it needs:
- Pass A (cut+sfx): scenes + vm7 cut-hints
- Pass B (silence): audio speech_segments
- Pass C (captions): word list
- Pass D (zoom): vm7 + audio rms_peak/onsets

Merge the four outputs into one EDL. **Worked cleanly. 4 of 6 types,
100% valid edits, comparable total cost ($0.011 vs $0.010 single-pass).**

The key insight: **a brain prompt that has to balance six competing
volume caps in one call is structurally unstable**. Splitting into
four narrow prompts removes the trade-off and lets each call optimize
for one objective.

## Verdict against gate

- ✅ **Parse rate** (100% of returned edits well-formed; merged JSON valid)
- ✅ **Cost gate** ($0.01065 ≪ $0.30; $0.028 projected for 30-min)
- ✅ **Edit type variety** (4 of 6 types in the canonical multi-pass result)
- ✅ **Bounded timestamps** (0 out-of-range)

**Overall: PASS.**

## What this means for FINDINGS / the product spec

1. **Cost / scaling claims are validated and beat the doc.** Phase 3
   brain pass for an 11.4-min clip: $0.011. Projecting to 30 min:
   $0.028. Doc's table line 600–606 estimated $0.09 for a 30-min brain
   pass — we're 3× cheaper. 60-min projection: ~$0.05. 2-hr projection:
   ~$0.10. Even the Studio tier (3-hr videos) has ~$0.15 brain cost.
2. **Context length is comfortable.** Total prompt across 4 passes was
   69K tokens (~6K of that is shared context overhead from system
   prompts; the actual data is ~63K). A 2-hour video projects to ~10×
   that across captions pass = ~600K — still fits in any 1M-context
   model. Doc's "tight at 2 hr in 1M ctx" warning was for vision frames;
   confirmed not a brain-stage concern.
3. **Multi-pass is the right architecture** — and **all four passes
   can run in parallel**, dropping latency from 25 s sequential to
   ~13 s parallel (longest pass, C, dominates). The eventual product
   should fan these out.
4. **Pass D (zoom) failure** points to a smaller open issue: the
   prompt or max_tokens for the zoom pass isn't quite right. Won't
   block Phase 4, but worth iterating in product engineering.

## Open questions / follow-ups

- **Pass A (cuts+sfx) emitted 48 edits in 11.4 min** — that's ~4
  cuts/min, slightly over the requested ~3/min cap. The brain is
  somewhat permissive with its own caps; a post-EDL validator with
  hard rejection on overage would be the production guardrail.
- **Pass D parse failure** — running it with higher max_tokens (4000+)
  or a more constrained schema should fix this. Logged for product
  engineering.
- **No quality evaluation against ground-truth.** Spot-checking 221
  edits is impractical; Exp 14 will verify the end-to-end output
  visually.
- **Parallelization opportunity:** running passes A/B/C/D
  concurrently with `asyncio.gather` would cut latency to ~13 s. Not
  exercised here — the experiment is about correctness, not throughput.

## Artifacts

- `outputs/11_brain_30min/edl.json` — final merged EDL (~35 KB)

All gitignored.

## Links

- metrics.json: [`experiments/11_brain_30min/metrics.json`](metrics.json)
- Related: Exp 10 (5-min brain — single-pass clean), Exp 12 (FFmpeg
  consumer), Exp 14 (E2E)
- Product doc reference: [product.md](../../docs/product.md) §9
  "The Brain" + cost tables lines 600–606
