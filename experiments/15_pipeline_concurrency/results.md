# Experiment 15 — 2-worker concurrency stress test

**Phase:** Phase 5
**Status:** done
**Verdict:** ✅ **PASS** — per-worker slowdown 34.5%, just under the
40% gate. Aggregate throughput goes up 1.33× vs 1 worker.
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (Ryzen 5 3600, CPU-only)

## Goal

The product plan caps concurrent workers at 2 (per the
`vps_specs.md` audit predicting 30–50% per-job slowdown at that
concurrency). Empirically measure the real per-worker slowdown of
running two WhisperX transcriptions in parallel on this VPS — Whisper
is the long-pole stage so it's the worst-case for contention.

## Gate (per CLAUDE.md / vps_specs.md)

- **2-worker per-job slowdown ≤ 40%** (per-worker RTF ≥ 0.6× the
  1-worker baseline).
- Both workers complete successfully.
- **Aggregate throughput ≥ 1× baseline** (otherwise concurrency is a
  net regression).

## What we ran

- **Clip:** `samples/raw/raw_5min.mp4` (300.03 s, 360p30, with audio).
- **Model:** WhisperX `large-v2`, `int8`, `OMP_NUM_THREADS=4`,
  `CT2_USE_EXPERIMENTAL_PACKED_GEMM=1`.
- **Worker isolation:** each worker is a **fresh `subprocess.Popen`**
  of a small worker script (`_worker.py`). My first attempt used
  `ProcessPoolExecutor` and that crashed with
  `BrokenProcessPool — A process in the process pool was terminated
  abruptly`. **Root cause:** ProcessPoolExecutor defaults to `fork()`
  on Linux, but `whisperx`/`torch` start background threads at import
  time, so forking *after* those imports gave each child broken
  thread state. Fresh subprocesses avoid the entire class of fork-
  after-multithreaded-import bugs.
- **Procedure:** baseline run first (1 worker), then 2-worker
  concurrent run (both started simultaneously, wait for both to
  finish). All numbers below come from a single execution.
- **Command:**
  ```bash
  python experiments/15_pipeline_concurrency/run.py \
      --clip samples/raw/raw_5min.mp4
  ```

## Observations

| Metric | 1 worker (baseline) | 2 workers (concurrent) |
|---|---|---|
| Total wall clock | 171.93 s | 259.11 s |
| Model load | 9.06 s | 9.17 / 9.18 s |
| Transcribe wall | 162.15 s | 247.62 / 247.42 s |
| **RTF (transcribe)** | **1.85** | **1.21 / 1.21** |
| n_segments | 11 | 11 / 11 |
| Peak RSS (this exp wide) | — | 14.78 GB (both workers + parent) |
| CPU avg / peak | — | 52.2% / **96.8%** (~12 logical cores saturated) |

**Per-worker slowdown: 34.5%.** (Mean concurrent RTF 1.212 vs
baseline 1.85 → 1 − 1.212/1.85 = 0.345.)

**Aggregate throughput: 1.327× baseline** — two workers finished in
259 s vs one worker finishing in 172 s. Per unit time:
- 1-worker rate: 300 s of input transcribed in 172 s = 1.74 input-s/s.
- 2-worker rate: 600 s of input transcribed in 259 s = 2.32 input-s/s.
- Ratio: 1.33× — matches the headline.

**RAM was comfortable:** 14.78 GB peak across both workers (~7.4 GB
each), lower than Exp 01's solo 8.5 GB per worker. Probably page
sharing between siblings, or transient solo allocations that don't
recur under contention. Either way well under the 62 GB ceiling — a
**3rd worker would also fit in RAM** (~22 GB total), but the audit's
warning of ~40%+ slowdown applies; needs its own experiment to
confirm if anyone wants to try.

## Verdict against gate

- ✅ **Per-worker slowdown** (34.5% ≤ 40%)
- ✅ **Both workers completed successfully** (rc=0 for both
  subprocesses; n_segments matches baseline)
- ✅ **Aggregate throughput** (1.33× ≥ 1×)

**Overall: PASS.**

## What this means for the product

- **Run at most 2 concurrent workers.** Audit's prediction was correct
  and our measured number (34.5%) is at the optimistic end of the
  30–50% range.
- **Per-worker capacity at concurrency 2** = RTF 1.21 vs solo 1.85.
  Concretely:
  - A 15-min video at 2-worker concurrency takes ~12.4 min wall (vs
    8.1 min solo).
  - A 2-hr video at 2-worker concurrency takes ~99 min (vs 65 min solo).
  - **Per-worker** is slower, but **the queue empties faster** —
    relevant if the product gets bursty traffic.
- **Worker isolation must be subprocess-based**, not
  `multiprocessing.Process(target=...)` or ProcessPoolExecutor with
  default fork. Use `spawn` start-method or `subprocess.Popen`. This
  is a code-architecture decision the product needs from day one.
- **CPU peak hit 96.8%** during the concurrent phase — effectively
  full saturation across all 12 logical cores. No spare capacity for
  background workers (e.g., scene-detection, frame-extraction) to
  run alongside without further degrading Whisper. The pipeline
  orchestrator should serialize CPU-heavy stages, not overlap them.

## Open questions / follow-ups

- **3-worker test** — not part of this experiment's gate. The audit
  said it would thrash; would be a cheap follow-up to confirm.
- **Full-pipeline concurrency** — we tested only the Whisper stage.
  A full E2E concurrency test (Whisper + FFmpeg render running
  simultaneously across two jobs) would surface different contention
  (FFmpeg also wants all cores). Out of scope for this experiment's
  gate; would matter for the production scheduler.
- **What if the second worker is on a DIFFERENT clip?** Same-clip
  contention should be slightly more favorable due to cache reuse;
  different clips might see slightly more slowdown. Not exercised
  here.
- **Shared box noise** — we got CPU peak 96.8% which suggests no
  significant other-user activity during this run, but the audit
  flagged that 12 sessions exist on this box. A noisier neighbor
  could push us above 40% degradation. Worth recording.

## Artifacts

- `outputs/15_pipeline_concurrency/baseline.json` (baseline result)
- `outputs/15_pipeline_concurrency/worker0.json`,
  `outputs/15_pipeline_concurrency/worker1.json` (concurrent results)
- `outputs/15_pipeline_concurrency/worker0_raw_5min.wav`,
  `worker1_raw_5min.wav` (intermediate audio extracts, ~9 MB each)

All gitignored.

## Links

- metrics.json: [`experiments/15_pipeline_concurrency/metrics.json`](metrics.json)
- _worker.py: [`experiments/15_pipeline_concurrency/_worker.py`](_worker.py)
- Related: Exp 01 (WhisperX baseline), Exp 16 (length tiers)
- Product doc reference: [vps_specs.md](../../docs/vps_specs.md)
  "Parallelism" section (lines 86–92) + audit's concurrency
  recommendation.
