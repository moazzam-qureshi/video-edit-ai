# Experiment 16 — Length-tier validation + projections

**Phase:** Phase 5
**Status:** done
**Verdict:** ✅ **PASS** — pipeline runs cleanly on a 11.4-min input,
scales **sub-linearly** with input duration (0.69×), and the
per-tier projections are within 3× of the doc's table on the wall-
clock side and 1.5–3× higher on the API-cost side.
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (Ryzen 5 3600, CPU-only)

## Goal

Collect a "next-tier" empirical datapoint (full pipeline on the
11.4-min clip) and combine with Exp 14's 5-min datapoint to build the
length-vs-cost-vs-time table that Phase 6 will publish in FINDINGS.
This is the experiment that empirically backs (or refutes) the
pricing tiers in `product.md` lines 633–639.

## Gate

- Pipeline runs on the 11.4-min input without errors.
- 11.4-min wall ≤ ~3× the 5-min wall (sanity check for linearity).
- Per-tier projections are within 3× of `product.md`'s table.

## What we ran

- **Anchor (5-min):** loaded `experiments/14_full_pipeline_5min/metrics.json`
  from Exp 14's canonical live run.
- **New datapoint (11.4-min):** invoked Exp 14's pipeline as a
  subprocess on `raw_15min.mp4` (684.64 s). The brain step ran the
  full multi-pass against the live OpenRouter API.
- **Linear projections:** fit `pipeline_wall_s` and `brain_cost_usd`
  separately against `(duration_s, value)` pairs from the two
  datapoints; project to the four product tiers.
- **Cold-E2E projections:** add Phase 1 sequential / parallel time
  derived from Exp 01–05 numbers (Whisper dominant at ~40 s of wall
  per minute of input).
- **Command:**
  ```bash
  python experiments/16_length_tiers/run.py
  ```

## Observations

### Two empirical datapoints (stages 2–4 only)

| Stage | 5-min (anchor) | 11.4-min (new) | Ratio |
|---|---|---|---|
| Duration | 300.03 s | 684.64 s | **2.28×** |
| Stage 2 brain wall | 16.37 s | 31.82 s | 1.94× |
| Stage 3 trim render | 9.41 s | 11.18 s | 1.19× |
| Stage 4 caption | 4.61 s | 4.85 s | 1.05× |
| **Pipeline wall (2–4)** | **30.39 s** | **47.85 s** | **1.57×** |
| Brain cost (USD) | $0.00502 | $0.01140 | 2.27× |
| n_edits emitted | 153 | 209 | 1.37× |

### Linearity

**Wall ratio 1.57× for a 2.28× duration → sub-linear at 0.69×.**
The pipeline gets *more efficient* per unit input as the input grows:
- Stage 3 trim render is dominated by per-segment setup overhead; the
  marginal cost of each extra second of input is much lower than the
  first one.
- Stage 4 caption render is dominated by encoder startup; same story.
- Stage 2 brain costs scale near-perfectly linearly (2.27× for 2.28×
  input) — both prompt size and EDL output grow linearly.

### Per-tier projections — stages 2–4 only (the part we measured)

Linear fit through both empirical points:

| Tier | Duration | Wall (2–4) | Brain cost |
|---|---|---|---|
| Starter | 15 min | **0.96 min** | $0.0150 |
| Creator | 30 min | **1.64 min** | $0.0299 |
| Pro     | 60 min | **3.00 min** | $0.0598 |
| Studio  | 3 hr   | **8.45 min** | $0.179 |

### Cold-E2E projections — including Phase 1

Phase 1 timings (per minute of input, mean across Exp 01–05 results):
- WhisperX large-v2 int8: ~40 s/min (varies 36–46 s/min by length)
- All other Phase 1 (scenes + faces + audio + frames): ~2.8 s/min
- Total Phase 1 sequential: ~42.8 s/min
- Total Phase 1 parallel (Whisper dominates the long pole): ~40 s/min

Phase 2 cost: ~$0.008/min (from Exp 06 + 08 measured rates).

| Tier | API cost total | Cold E2E (seq) | Cold E2E (parallel) |
|---|---|---|---|
| Starter (15 min)  | **$0.135** | 11.7 min | 11.0 min |
| Creator (30 min)  | **$0.270** | 23.0 min | 21.6 min |
| Pro (60 min)      | **$0.540** | 45.8 min | 43.0 min |
| Studio (3 hr)     | **$1.619** | 137 min  | 128 min  |

### How does this stack vs the product.md pricing tiers?

`product.md` lines 633–639 published:

| Tier     | Doc cost/customer/mo | Doc margin | Our measured cost/customer/mo (at doc's video count) | Adjusted margin |
|---|---|---|---|---|
| Starter ($29, 10 vids ≤ 15 min) | $0.90  | 97% | **$1.35** (10 × $0.135)  | **95.3%** |
| Creator ($59, 30 vids ≤ 30 min) | $4.50  | 92% | **$8.10** (30 × $0.270)  | **86.3%** |
| Pro ($99, unlimited ≤ 60 min)   | $8–15  | 85–92% | **$16–32** (30–60 × $0.54) | **68–84%** |
| Studio ($199, unlimited ≤ 3 hr) | $15–40 | 80–92% | **$48** (30 × $1.62)     | **76%** |

**The doc's API-cost estimates are 1.5–3× too low.** But margins are
still healthy: Starter holds 95%+, Creator holds 86%, Pro and Studio
hold 68–84% even at the assumed unlimited usage rates.

**Why the doc underestimated:** doc table at lines 600–606 used
Qwen Flash at $0.04/MTok input pricing and assumed ~400 tokens/frame.
Our measured rate on `qwen/qwen3-vl-8b-instruct` is **~$0.08/MTok
input + ~200 tokens/frame** (Exp 06 found per-image tokens were ~200,
not the doc's GPT-4o-era 765). But the doc didn't account for:
- VM-7 sampling at 1 frame/5s adds up faster than the per-cut VM-1.
- The brain stage on 60-min input is ~$0.06 not $0.15 (we're cheaper
  here), but the Phase 2 sampling rate is the driver.

Net: **Phase 2 cost dominates total API cost**, not Phase 3. The doc
under-weighted Phase 2 frame counts.

## Verdict against gate

- ✅ **Ran on 11.4-min input without errors** (rc=0, all stages
  completed, 209 valid edits).
- ✅ **Linearity sanity** (1.57× wall for 2.28× duration = sub-linear).
- 🟡 **Per-tier costs within 3×** — wall-clock projections are
  conservative (within 1.5× of doc); API cost projections are 1.5–3×
  *over* doc estimates but still acceptable.

**Overall: PASS.**

## What this means for FINDINGS

The pricing-tier table from `product.md` 633–639 needs an update.
**My recommended adjusted version**:

| Plan     | Tier limit  | Videos/mo | Price   | Cost/customer | Margin |
|---|---|---|---|---|---|
| Starter  | ≤ 15 min    | 10        | **$29** | **$1.35** | **95%** |
| Creator  | ≤ 30 min    | 30        | **$59** | **$8.10** | **86%** |
| Pro      | ≤ 60 min    | unlimited | **$99** | **$16–32** | **68–84%** |
| Studio   | ≤ 3 hr      | unlimited | **$199** | **$48** (30 vids/mo) | **76%** |

Even worst-case Pro / Studio usage clears 65–75% margin. The doc's
"98% margin" claim from line 182 was optimistic but the *business
case stands*. The product is viable at every length tier.

## Open questions / follow-ups

- **3-hour test is fully projected, not measured.** A real Studio-
  tier run would take ~2 hours of wall on this VPS. Worth doing once
  per quarter as a regression check, but not for the experimentation
  phase budget.
- **Phase 1 parallelization.** Sequentially Phase 1 is ~40 s/min of
  input × 180 min = 2 hours, dominating cold E2E. Parallelizing (3-4
  workers running Whisper + face + audio simultaneously) shaves only
  about 7% off because Whisper is the long pole. The real fix is
  GPU rental for Whisper alone (rent an H100 for ~$2/hr to do what
  this CPU does in 2 hours in ~10 min). FINDINGS will recommend this.
- **The sub-linear scaling is encouraging** — suggests we can serve
  longer videos at proportionally lower marginal cost. Studio tier
  may be more profitable than the doc projected.

## Artifacts

- `outputs/16_length_tiers/e14_raw_15min_metrics.json` — the 11.4-min
  pipeline's metrics.json (backup; the canonical Exp 14 metrics.json
  in the experiments folder reflects this run's overwriting since it
  was the last invocation).

All gitignored.

## Links

- metrics.json: [`experiments/16_length_tiers/metrics.json`](metrics.json)
- Related: Exp 01 (Whisper baseline), Exp 14 (anchor 5-min), Exp 15
  (concurrency adjustment to per-worker rate)
- Product doc reference: [product.md](../../docs/product.md) lines
  600–606 (cost table) and 633–639 (pricing tiers)
