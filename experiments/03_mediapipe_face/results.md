# Experiment 03 — MediaPipe face detection

**Phase:** Phase 1
**Status:** done
**Verdict:** ✅ **PASS** on throughput (gate met by 6–17×); ⚠️ **hit-rate
unmeasurable** on this sample (sample content is screencast-heavy, not
talking-head — MediaPipe behavior is correct, but the clip can't validate
a face-coverage gate).
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (Ryzen 5 3600, CPU-only)

## Goal

Confirm MediaPipe's face detection is fast enough to run on every frame
of a raw clip and that the bounding-box output is usable for
zoom/recompose decisions.

## Gate (assumed from `vps_specs.md` audit)

- **RTF ≥ 0.5** (audit predicted 0.5–1.5× on 1080p30; our raw clips are
  360p30 so we expect more).
- **Detects faces in most frames of a talking-head clip (≥ 70% hit rate).**
- Output schema: per-frame bbox (xmin, ymin, width, height, normalized
  0–1) + confidence.

## What we ran

- **Input:** `samples/raw/raw_15min.mp4` — 684.64 s, 640×360@30fps,
  h264, 20,539 frames total
- **Detector params:**
  - Run A: `model_selection=0` (short-range, ≤2 m), `min_confidence=0.5`
  - Run B: `model_selection=1` (full-range, ≤5 m), `min_confidence=0.5`
- **Command:**
  ```bash
  python experiments/03_mediapipe_face/run.py --clip samples/raw/raw_15min.mp4 \
      --model_selection 0
  python experiments/03_mediapipe_face/run.py --clip samples/raw/raw_15min.mp4 \
      --model_selection 1
  ```

## Observations

`metrics.json` holds **Run B** (full-range, slower + more recall).

| Metric | Run A: short-range (sel=0) | Run B: full-range (sel=1) |
|---|---|---|
| Wall clock | 80.4 s | 235.0 s |
| **RTF** | **8.51×** | **2.91×** |
| Throughput | 255 fps processed | 87 fps processed |
| Frames analyzed | 20,539 | 20,539 |
| Frames with face | 1897 | 3481 |
| Hit rate | 9.2% | 16.9% |
| Avg confidence (when found) | 0.756 | — |
| Peak RSS | 251 MB | 265 MB |
| CPU avg | 25.1% | 19.9% (of 12 logical cores) |

- **MediaPipe install bug surfaced and fixed.** Initial run on the pinned
  `mediapipe==0.10.14` crashed with `AttributeError: 'SymbolDatabase'
  object has no attribute 'GetPrototype'`. Cause: `protobuf 6.33.6`
  (pulled in by `transformers` via WhisperX) removed the legacy
  `GetPrototype` API. Bumped MediaPipe to `0.10.18` (the version that
  switched to the new `GetMessages` API). Side-effects: protobuf got
  downgraded back to `4.25.9` (MediaPipe's pin), `pillow` and
  `opencv-contrib-python` bumped. Verified transformers + whisperx
  still import and a tokenizer still loads cleanly — no Exp 01 retest
  needed.
- **9–17% hit rate is NOT a face-detection failure.** Spot-checked
  sample frames: `MISS` frames at t=0/30/60 are a YouTube search-bar
  screencast ("earthquake bangkok"); `DET` frames at t=90+ show a
  YouTube channel page with face thumbnails. **The video is an
  editing-tutorial screencast, not a talking-head take.** MediaPipe is
  correctly *not* finding faces in UI screenshots and correctly finding
  faces in thumbnails.
- **Throughput beats the audit's 1080p prediction by 6× (short-range) or
  ~2× (full-range)** on our 360p clip. 4× the pixel count (1080p) would
  bring us roughly back into the audit's 0.5–1.5× range. The 0.5×
  throughput gate is comfortable.

## Verdict against gate

- ✅ **RTF gate** (8.51× and 2.91× ≥ 0.5)
- ❌ **Hit-rate gate** (9.2% / 16.9% < 70%) — but the gate was wrong for
  *this* clip; reclassified as **N/A**. The clip is not a talking-head
  take so the gate cannot be meaningfully evaluated on it.
- ✅ **Output schema** (per-frame normalized bbox + confidence written
  to JSON; sample every 30 frames preserved as artifact).

**Overall: PASS on throughput. Hit-rate validation deferred** — needs
true talking-head footage to evaluate, which is not in our sample set.

## Open questions / follow-ups

- **Need a real talking-head clip** to validate the 70% hit-rate
  assumption. Flag in FINDINGS — for any real product evaluation we
  need a sample where the creator is on camera continuously. Until
  then we can only claim MediaPipe is fast enough, not that face
  tracking is *useful* on a given input.
- The 8.5× → 2.9× throughput hit going from short-range to full-range
  is significant. The product probably wants `model_selection=0` for
  selfie-style YouTube creators (standard framing) and `model_selection=1`
  for talking-head-at-a-distance content. Brain prompt or pipeline
  config decision, not a Phase 1 question.
- MediaPipe pin in `requirements.txt` is now wrong (says 0.10.14, we have
  0.10.18). Update at the next dependency hygiene commit; non-blocking
  for the rest of Phase 1.

## Artifacts

- `outputs/03_mediapipe_face/raw_15min_faces.json` (~140 KB, every-30-frame
  sample of bboxes + summary counts)

## Links

- metrics.json: [`experiments/03_mediapipe_face/metrics.json`](metrics.json) (full-range run)
- Related experiments: 14 (full pipeline — face tracking feeds zoom decisions)
- Product doc reference: [product.md](../../docs/product.md) §3 "Face Detection & Tracking"
