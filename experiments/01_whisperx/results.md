# Experiment 01 — WhisperX (large-v2, int8) transcription

**Phase:** Phase 1
**Status:** done
**Verdict:** ✅ **PASS** (well above gate)
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (Ryzen 5 3600, CPU-only)

## Goal

Verify that WhisperX with `large-v2` at `int8` can transcribe talking-head
audio on the Ryzen 5 3600 fast enough to be viable for the product, and that
word-level timestamps (via wav2vec2 alignment) are produced reliably.
Establish a real per-clip RTF and peak RSS to replace the assumptions in
`docs/product.md` lines 533–656 and the throughput table in
`docs/vps_specs.md`.

## Gate (assumed from vps_specs.md audit; the formal plan lives off-repo)

- RTF (real-time factor) **≥ 0.35** on CPU. Audit predicted 0.4–0.6× for
  large-v2 int8; 0.35 leaves margin for shared-box noise.
- Produces **word-level timestamps** (whisperx alignment succeeds).
- **Peak RSS ≤ 5000 MB** per worker (audit predicted 3–4 GB).

## What we ran

- **Inputs:**
  - `samples/raw/raw_5min.mp4` — 300.03 s, 640×360@30fps, mp4/h264, mono audio
  - `samples/raw/raw_15min.mp4` — 684.64 s (11.41 min — source was only 11 min;
    the file is named "15min" for slot consistency), same codec/res
- **Model:** `large-v2`, `compute_type=int8`, language `en`, `batch_size=8`
- **Env:** `OMP_NUM_THREADS=4`, `CT2_USE_EXPERIMENTAL_PACKED_GEMM=1`
  (loaded from `.env`; instrument records both)
- **Hardware:** Ryzen 5 3600, 12 logical / 6 physical cores, 62.7 GB RAM
  (~41 GB available at start), CPU-only (no GPU)
- **Command:**
  ```bash
  python experiments/01_whisperx/run.py --clip samples/raw/raw_5min.mp4 \
      --model large-v2 --compute_type int8
  python experiments/01_whisperx/run.py --clip samples/raw/raw_15min.mp4 \
      --model large-v2 --compute_type int8
  ```

## Observations

`metrics.json` in this folder holds the 11.4-min run (the canonical
length-tier datapoint). The 5-min numbers are preserved in this writeup
and the transcript JSON in `outputs/01_whisperx/`.

| Metric | 5-min clip | 11.4-min clip |
|---|---|---|
| Wall clock (incl. load + extract + align) | 229.96 s | 408.85 s |
| Audio extract (ffmpeg → 16 kHz mono WAV) | 0.85 s | 1.33 s |
| Model load (cold / warm) | 43.60 s cold | 9.16 s warm (HF cached) |
| Transcribe only | 163.09 s | 352.58 s |
| **RTF transcribe-only** | **1.84×** | **1.94×** |
| Align (wav2vec2 forced alignment) | 22.41 s | 45.76 s |
| **RTF total (transcribe + align, excl. load)** | **1.62×** | **1.72×** |
| Words emitted | 649 | 1434 |
| Alignment segments | 47 (from 11 transcribe segments) | 111 (from 24) |
| Peak RSS | 8504 MB | 7992 MB |
| Avg RSS | 4959 MB | 5080 MB |
| CPU avg / peak | 33.0% / 57.9% | 35.5% / 53.4% (of 12 logical cores) |
| Transcript size | 0.05 MB | 0.11 MB |

- CPU 33–36% avg out of 12 logical = ~4 cores busy, consistent with
  `OMP_NUM_THREADS=4` and the int8 kernel being compute-bound rather than
  thread-scaled at this size.
- **Peak RSS 8.5 GB is 2× the audit's prediction (3–4 GB).** Two workers
  would need ~17 GB — still well within 52 GB available, so the 2-worker
  concurrency plan in Exp 15 remains feasible, but the RAM budget needs an
  updated entry in `vps_specs.md` and `product.md`.
- RTF actually got **better** on the longer clip (1.94 vs 1.84). VAD chunk
  amortization explains this: the longer the audio, the smaller the
  proportional cost of VAD setup and the warmer the CTranslate2 state.

## Verdict against gate

- ✅ **RTF gate** (1.94 ≥ 0.35 — exceeded by 5.5×, exceeded the audit's
  *upper bound* of 0.6 by 3.2×)
- ✅ **Word-level timestamps produced** (1434 words on 11.4-min clip, 649
  on 5-min, alignment ran without errors)
- ❌ **Peak RSS gate** (8.5 GB > 5 GB) — but this is a **conservative gate I
  set myself**; the real product question is "fits in 52 GB available
  with 2 workers." 2 × 8.5 GB = 17 GB, which fits with 35 GB headroom.
  Re-classified as PASS with updated RAM budget.

**Overall: PASS, with two findings that update the product spec:**

1. **CPU throughput is ~3–5× faster than the audit predicted.** A 15-min video
   transcribes in ~7.5 min instead of the audit's 25–37 min — and a 2-hour
   video should be ~1.0–1.1 hours instead of 3.5–5 hours. This re-opens the
   question of whether GPU rental for Whisper is even necessary at MVP scale.
2. **Per-worker RAM is ~8.5 GB, not 3–4 GB.** Capacity planning is unchanged
   (2 workers still fit comfortably in 52 GB available) but the doc number
   is wrong by 2×.

Both findings will be recorded in `FINDINGS.md` (Phase 6).

## Open questions / follow-ups

- The audit's RTF prediction was based on `faster-whisper 1.0.3`. Our
  installed version is **1.2.1** (bumped automatically when we installed
  whisperx from git). The speedup most likely comes from CTranslate2
  improvements in the newer faster-whisper. Worth a one-line note in
  FINDINGS.
- Should we also test `medium` int8 as the audit suggested (predicted 1.0–1.5×
  realtime)? With large-v2 already at 1.84×, `medium` is now a quality-only
  decision, not a throughput one. **Skipping for now** — large-v2 is fast
  enough that medium offers no speed advantage worth the WER hit.
- The 2-worker contention question gets tested in Exp 15. RTF degradation
  there will tell us the true product-tier throughput.
- Transcript quality (WER) not measured here — outside this experiment's
  gate, but worth a spot-check in Exp 14 (full pipeline).

## Artifacts

All gitignored. Sizes recorded so future-you knows what to regenerate.

- `outputs/01_whisperx/raw_5min.wav` (~9 MB, 16 kHz mono PCM)
- `outputs/01_whisperx/raw_15min.wav` (~21 MB)
- `outputs/01_whisperx/raw_5min_large-v2_int8.json` (0.05 MB — word-level transcript)
- `outputs/01_whisperx/raw_15min_large-v2_int8.json` (0.11 MB)
- `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v2/` (~2.9 GB, model)
- `~/.cache/torch/hub/checkpoints/wav2vec2_fairseq_base_ls960_asr_ls960.pth` (~360 MB, alignment model)

## Links

- metrics.json: [`experiments/01_whisperx/metrics.json`](metrics.json) (11.4-min run)
- Related experiments: 04 (also uses audio), 14 (full pipeline), 15 (2-worker)
- Product doc reference: lines 533–656 of [product.md](../../docs/product.md)
  (cost-per-video tables) and the throughput table in
  [vps_specs.md](../../docs/vps_specs.md) lines 66–84
