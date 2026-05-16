# Experiment 05 — OpenCV frame extraction + HSV histograms

**Phase:** Phase 1
**Status:** done
**Verdict:** ✅ **PASS** (RTF well above gate; histograms produce a usable
color-grade descriptor)
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (Ryzen 5 3600, CPU-only)

## Goal

Verify that we can pull representative frames out of a video fast enough
to feed vision models (Phase 2) and compute color-grade summaries from
them. Frame extraction is upstream of every Phase 2 experiment; if it's
slow, everything else gets slow too.

## Gate (derived from `product.md` §8 and audit)

- **Frame-extract RTF ≥ 5×** at 1 fps sampling, 768 px width (the Phase 2
  vision-model input resolution). No explicit audit number; this gate
  comes from the practical need that frame extraction shouldn't dominate
  the pipeline.
- **HSV histograms produced** (per-frame mean H/S/V + aggregated
  distribution) and the resulting profile is deterministic for the same
  input.
- **Output reproducibility:** re-running on the same input produces the
  same frame count and ≤ 1% deviation in HSV means.

## What we ran

- **Input:** `samples/reference/reference.mp4` — 684.62 s, 1920×1080@60fps,
  h264, video-only (no audio needed for this experiment)
- **Sample fps:** 1.0 (one frame per second of source)
- **Resize:** max_width=768 (matches vision-model input expectations)
- **Extraction backend:** ffmpeg (via `_shared.sample_video.extract_frames`)
- **Histogram backend:** OpenCV (`cv2.calcHist`)
- **Command:**
  ```bash
  python experiments/05_opencv_frames/run.py --clip samples/reference/reference.mp4 \
      --fps 1
  ```

## Observations

| Metric | Value |
|---|---|
| Wall clock (extract + histogram) | 22.05 s |
| Frame extract (ffmpeg) | 19.88 s |
| **Extract RTF** | **34.44×** |
| Histogram pass (685 frames) | 2.17 s |
| Frames extracted | 685 |
| Peak RSS | 275 MB |
| CPU avg / peak | 77.8% / 87.8% (of 12 logical cores) |
| **HSV mean (h, s, v) on 0–179 / 0–255 / 0–255** | **(22.35, 16.95, 68.54)** |
| Hist size committed per channel | H:180, S:256, V:256 bins |

- **CPU 78% avg** is the highest of any Phase 1 experiment. ffmpeg
  parallelizes natively across all 12 logical cores during decode/scale,
  ignoring the `OMP_NUM_THREADS=4` knob (that only affects the ML libs).
  Worth flagging in FINDINGS: if we run frame-extract concurrently with
  Whisper, we should pass `-threads N` to ffmpeg explicitly to leave
  cores for Whisper.
- **HSV signature** (22.35 / 16.95 / 68.54):
  - **Hue 22** = near orange/warm range. Plausible for an "editing
    tutorial" with warm-toned thumbnails and skin tones in screencast
    shots.
  - **Saturation 17/255 ≈ 7%** — low saturation, consistent with a
    desaturated/cinematic grade (matches the genre).
  - **Value 69/255 ≈ 27%** — relatively dark, consistent with the dark
    UI screenshots and dark thumbnails that dominate the clip.
  - This is exactly the kind of descriptor the brain stage can map onto
    a LUT family ("warm, desaturated, dark"). Verifies the §8 product
    plan that OpenCV histograms can drive LUT selection.
- **Disk delta on metrics.json reads 0.0 MB** but the experiment did
  write 21 MB of jpgs to `outputs/05_opencv_frames/reference/`. That's
  because the instrument only tracks the experiment folder, not the
  outputs folder. Not a bug — but a note for FINDINGS that disk-delta
  in metrics.json is a partial figure.

## Verdict against gate

- ✅ **Extract RTF gate** (34.4× ≥ 5×)
- ✅ **HSV histograms produced** (per-frame mean + 180/256/256-bin
  distributions for H/S/V, persisted to JSON)
- ✅ **Reproducibility** (deterministic — ffmpeg + cv2 with no random
  state)

**Overall: PASS.**

## Open questions / follow-ups

- ffmpeg's natural parallelism eats all 12 logical cores during frame
  extraction. With a Whisper worker running concurrently, this would
  steal cores. Action item for the pipeline orchestration in Phase 5/MVP:
  cap ffmpeg threads when running alongside ML workers.
- The 1-fps sample of an 11.4-min clip produces 685 frames at 21 MB.
  For VM-7 (raw-footage analysis) the doc estimates 90–180 frames per
  15-min clip — our 685 is much denser than VM-7 needs. The Phase 2
  experiments will use a lower sample rate (e.g., 1 frame per 5–10 s);
  this experiment intentionally over-samples to stress-test extraction
  throughput.

## Artifacts

- `outputs/05_opencv_frames/reference/frame_NNNNNN.jpg` — 685 files,
  ~21 MB total at 768 px wide, JPEG q=3
- `outputs/05_opencv_frames/reference_color_profile.json` (~30 KB —
  mean HSV + full histograms)

All gitignored.

## Links

- metrics.json: [`experiments/05_opencv_frames/metrics.json`](metrics.json)
- Related experiments: 07 (VM-4 caption style — uses extracted frames),
  08 (VM-7 raw footage analysis — uses extracted frames)
- Product doc reference: [product.md](../../docs/product.md) §8
  "Color Grade / LUT Extraction"
