# Experiment 04 — Librosa energy + Silero VAD

**Phase:** Phase 1
**Status:** done
**Verdict:** ✅ **PASS** (both individually and combined RTF well above gate)
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (Ryzen 5 3600, CPU-only)

## Goal

Verify the two audio-analysis legs of the pipeline — energy/onset
detection (Librosa) and speech-vs-silence segmentation (Silero VAD) —
both run fast enough to be effectively free, and produce usable outputs
to feed into the brain (energy peaks for zoom triggers, speech regions
for silence trimming).

## Gate (from `vps_specs.md` audit)

- **RTF ≥ 5×** (audit predicted 5–20×; using lower bound as the gate).
- **Detects speech segments** (Silero VAD returns a non-empty list).
- **Produces RMS energy curve** aligned to the audio timeline.
- **Onset detection returns a plausible list** (>= 10 onsets on a 5-min
  talking-head; revised to "non-trivial number on any duration").

## What we ran

- **Input:** `samples/raw/raw_15min.mp4` — 684.64 s, audio extracted to
  16 kHz mono WAV
- **Librosa:** `librosa.feature.rms`, `librosa.onset.onset_strength`,
  `librosa.onset.onset_detect`
- **VAD:** `silero_vad.load_silero_vad()` + `get_speech_timestamps(...,
  return_seconds=True)`
- **Command:**
  ```bash
  python experiments/04_librosa_vad/run.py --clip samples/raw/raw_15min.mp4
  ```

## Observations

| Metric | Value |
|---|---|
| Wall clock (audio extract + librosa + VAD) | 23.24 s |
| Audio extract (ffmpeg → 16 kHz mono WAV) | 1.62 s |
| **Librosa wall** | 12.75 s |
| **Librosa RTF** | **53.69×** |
| **Silero VAD wall** | 8.86 s |
| **Silero VAD RTF** | **77.24×** |
| **Combined RTF** | **31.67×** |
| Peak RSS | 986 MB |
| CPU avg / peak | 15.6% / 26.3% (of 12 logical cores) |
| n_onsets (Librosa) | 2956 |
| n_speech_segments (VAD) | 175 |
| Speech duration | 382.9 s (55.93% of clip) |
| RMS mean / peak | 0.047 / 0.240 |

- **Audit predicted 5–20× RTF; we measured 31.67× combined** — about
  1.6× the upper bound. Silero VAD alone at 77× is faster than I/O for
  most practical purposes.
- **RSS 986 MB is dominated by torch model loads** (Silero is a torch
  model). Not a concern; well under the 8.5 GB-per-Whisper-worker budget.
- **55.93% speech** matches what we'd expect for a tutorial video that
  mixes talking with screencasts and silent B-roll. Cross-checks against
  Exp 01 (Whisper transcribed 1434 words over 11.4 min = ~125 wpm,
  consistent with a casual narration tempo over only ~6.4 min of actual
  speech).
- **2956 onset peaks over 11.4 min** is dense (~4.3/sec), but that's
  expected: onset detection picks up percussive elements in BGM, hard
  edits, mouse-clicks in screencast audio, etc. The brain stage will
  cross-reference these with the transcript to keep only the ones near
  word boundaries.
- Torchaudio deprecation warnings appeared at runtime (sox/load
  pathways). Non-fatal; future torchaudio 2.9 will remove these and
  Silero will likely move to TorchCodec. Note for FINDINGS as a
  maintenance task.

## Verdict against gate

- ✅ **RTF gate** (combined 31.67× ≥ 5×; individual 53.7× and 77.2×
  both > 5×)
- ✅ **Speech segments** (175 detected, totaling 56% of clip)
- ✅ **RMS curve** produced (mean 0.047, peak 0.240)
- ✅ **Onsets** (2956 — well above "non-trivial")

**Overall: PASS.**

## Open questions / follow-ups

- Whisper's VAD (pyannote, used inside WhisperX) vs Silero VAD —
  WhisperX already filters by VAD internally during transcription. Do
  we still need standalone Silero in the pipeline? Likely yes (Silero
  gives sub-word timing for silence-trim decisions whereas Whisper's
  internal VAD is just a preprocessing optimization), but it's worth
  surfacing the redundancy in FINDINGS so the pipeline doesn't
  double-pay for VAD.
- Onset density is high (4.3/s). The brain stage will need to filter to
  "salient" peaks — likely the top-quintile by `onset_env` strength.
  Out of scope here; flagged for Phase 3.
- Torchaudio deprecation: schedule a Silero/torchaudio migration to
  TorchCodec before torchaudio 2.9 ships. Tracking item, not blocking.

## Artifacts

- `outputs/04_librosa_vad/raw_15min.wav` (~21 MB, 16 kHz mono PCM)
- `outputs/04_librosa_vad/raw_15min_audio_analysis.json` (~30 KB —
  onsets + speech segments + RMS summary)

## Links

- metrics.json: [`experiments/04_librosa_vad/metrics.json`](metrics.json)
- Related experiments: 01 (Whisper internally uses pyannote VAD — possible redundancy)
- Product doc reference: [product.md](../../docs/product.md) §4 "Audio Analysis"
