# Experiment 02 — PySceneDetect cut detection

**Phase:** Phase 1
**Status:** done
**Verdict:** ✅ **PASS** (RTF well above audit prediction on both clip types)
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (Ryzen 5 3600, CPU-only)

## Goal

Verify that PySceneDetect's `ContentDetector` finds scene boundaries
reliably and fast on this VPS. The audit predicted 3–8× realtime on
1080p. Confirm with both:

- a heavily-edited 1080p60 reference clip (worst case for throughput,
  best case for finding cuts — should detect many)
- a 360p30 "raw" clip (lighter pixel load, fewer expected cuts)

## Gate (assumed from `vps_specs.md` audit)

- **RTF ≥ 2.0** on 1080p (the audit said 3–8×; 2× leaves margin for the
  shared box).
- **Detects non-zero scenes** and produces a usable list (start/end
  timestamps in seconds + duration per scene).
- Output is **deterministic** given the same input (≤ 5% variation in
  RTF run-to-run).

## What we ran

- **Inputs:**
  - `samples/reference/reference.mp4` — 684.62 s, 1920×1080@60fps, h264, no audio
  - `samples/raw/raw_5min.mp4` — 300.03 s, 640×360@30fps, h264, with audio
- **Detector:** `ContentDetector(threshold=27.0)` (default — best for hard cuts)
- **Command:**
  ```bash
  python experiments/02_pyscenedetect/run.py --clip samples/reference/reference.mp4 \
      --detector content
  python experiments/02_pyscenedetect/run.py --clip samples/raw/raw_5min.mp4 \
      --detector content
  ```

## Observations

`metrics.json` holds the reference (1080p60) run — the harder workload.
The raw_5min numbers are kept here for the comparison.

| Metric | reference.mp4 (1080p60, 11.4 min, edited) | raw_5min.mp4 (360p30, 5 min) |
|---|---|---|
| Wall clock | 72.59 s | 3.01 s |
| **RTF** | **9.43×** (re-run: 9.54×) | **99.80×** |
| Peak RSS | 214 MB | 125 MB |
| CPU avg / peak | 39.6% / — | 36.2% / 42.9% |
| Scenes detected | 308 | 79 |
| Avg scene length | 2.22 s | 3.80 s |
| Median scene length | — | 3.03 s |
| Min / max scene length | — | 0.03 s / 10.37 s |

- **Run-to-run variance:** reference re-ran at 9.54× vs 9.43× — about
  1.2% variance. Well within the "deterministic" gate.
- **Scene-content sanity:** 79 cuts in 5 min of "raw" footage was
  surprising, but the source video is itself an editing tutorial — the
  "raw" clips inherit those cuts. Important context for Exp 14 (full
  pipeline) and any downstream EDL evaluation: our raw_5min and
  raw_15min slots contain edited material, not true talking-head raw
  footage. This needs flagging in `FINDINGS.md`.
- **Memory is negligible** (under 220 MB) — scene detection can run
  concurrently with a Whisper worker with no real RAM impact.

## Verdict against gate

- ✅ **RTF gate** (9.43× on 1080p60 ≥ 2.0; 99.8× on 360p30) — exceeded
  the audit's upper bound of 8× on the 1080p clip.
- ✅ **Non-zero scenes** (308 on reference, 79 on raw_5min) with usable
  start/end + duration data.
- ✅ **Deterministic** (~1% RTF variance across reruns).

**Overall: PASS.**

The audit's 3–8× prediction was for 1080p; we measured 9.4×. PySceneDetect
is not a throughput concern for any video length on this hardware.

## Open questions / follow-ups

- The "raw" clips actually contain cuts because the source video was an
  edited tutorial. This means Phase 5 end-to-end testing is technically
  running on edited input, not raw — which is *probably fine* for
  measuring throughput and pipeline correctness, but means we cannot
  evaluate edit *quality* against the source meaningfully. Surface this
  in FINDINGS and flag the need for a real raw-footage sample if any
  later quality experiment requires it.
- Try `AdaptiveDetector` for clips with camera motion — out of scope for
  this experiment's gate but a future-Brain input quality concern.

## Artifacts

- `outputs/02_pyscenedetect/reference_content_scenes.json` (~30 KB,
  308 scenes)
- `outputs/02_pyscenedetect/raw_5min_content_scenes.json` (~7 KB,
  79 scenes)

All gitignored.

## Links

- metrics.json: [`experiments/02_pyscenedetect/metrics.json`](metrics.json) (reference 1080p60 run)
- Related experiments: 06 (VM-1 edit intent — feeds on PySceneDetect's cut list)
- Product doc reference: [product.md](../../docs/product.md) §1 "Cut/Scene Detection"
