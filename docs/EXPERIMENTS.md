# Experiments — Index

Living index of every experiment in the verification plan. Update after each run.
Plan: [`plan.md`](../../../../C%3A/Users/Moazzam%20Qureshi/.claude/plans/d-personal-projects-video-edit-ai-docs-dynamic-rossum.md) (kept outside the repo)
Product spec: [product.md](./product.md) · Hardware audit: [vps_specs.md](./vps_specs.md)

**Statuses:** `planned` → `running` → `done`
**Verdicts:** `PASS` · `FAIL` · `PARTIAL` · `—` (not yet run)

---

## Phase 1 — Mechanical Extraction

| # | Name | Status | Verdict | Results |
|---|---|---|---|---|
| 01 | WhisperX transcription (large-v2 / medium, int8) | done | **PASS** (RTF 1.94, 3× audit prediction) | [`experiments/01_whisperx/results.md`](../experiments/01_whisperx/results.md) |
| 02 | PySceneDetect cut detection | done | **PASS** (RTF 9.43 on 1080p60) | [`experiments/02_pyscenedetect/results.md`](../experiments/02_pyscenedetect/results.md) |
| 03 | MediaPipe face detection | done | **PASS** on throughput (RTF 8.5/2.9); hit-rate N/A (sample is screencast, not talking-head) | [`experiments/03_mediapipe_face/results.md`](../experiments/03_mediapipe_face/results.md) |
| 04 | Librosa energy + Silero VAD | planned | — | [`experiments/04_librosa_vad/results.md`](../experiments/04_librosa_vad/results.md) |
| 05 | OpenCV frame extraction + histograms | planned | — | [`experiments/05_opencv_frames/results.md`](../experiments/05_opencv_frames/results.md) |

**Phase 1 exit gate:** all five pass, OR a written rationale for any that didn't.

---

## Phase 2 — Vision Model Layer

| # | Name | Status | Verdict | Results |
|---|---|---|---|---|
| 06 | VM-1 Edit-intent classification (Qwen Flash) | planned | — | [`experiments/06_vm1_edit_intent/results.md`](../experiments/06_vm1_edit_intent/results.md) |
| 07 | VM-4 Caption-style extraction | planned | — | [`experiments/07_vm4_caption_style/results.md`](../experiments/07_vm4_caption_style/results.md) |
| 08 | VM-7 Raw footage analysis | planned | — | [`experiments/08_vm7_raw_footage/results.md`](../experiments/08_vm7_raw_footage/results.md) |
| 09 | Native video input vs frame extraction | planned | — | [`experiments/09_video_vs_frames/results.md`](../experiments/09_video_vs_frames/results.md) |

**Phase 2 exit gate:** all four pass; measured cost for a 15-min video ≤ $0.06.

---

## Phase 3 — Edit Decision Brain

| # | Name | Status | Verdict | Results |
|---|---|---|---|---|
| 10 | Brain EDL generation (5-min input) | planned | — | [`experiments/10_brain_5min/results.md`](../experiments/10_brain_5min/results.md) |
| 11 | Brain context scaling (30-min input) | planned | — | [`experiments/11_brain_30min/results.md`](../experiments/11_brain_30min/results.md) |

**Phase 3 exit gate:** both pass; EDL schema locked; cost-per-video within 3× of doc estimate.

---

## Phase 4 — Execution

| # | Name | Status | Verdict | Results |
|---|---|---|---|---|
| 12 | FFmpeg EDL translator + render | planned | — | [`experiments/12_ffmpeg_edl/results.md`](../experiments/12_ffmpeg_edl/results.md) |
| 13 | ASS caption rendering | planned | — | [`experiments/13_ass_captions/results.md`](../experiments/13_ass_captions/results.md) |

**Phase 4 exit gate:** both pass; output is watchable.

---

## Phase 5 — Integration & Stress

| # | Name | Status | Verdict | Results |
|---|---|---|---|---|
| 14 | Full end-to-end pipeline (5-min) | planned | — | [`experiments/14_full_pipeline_5min/results.md`](../experiments/14_full_pipeline_5min/results.md) |
| 15 | 15-min pipeline + 2-worker concurrency | planned | — | [`experiments/15_pipeline_concurrency/results.md`](../experiments/15_pipeline_concurrency/results.md) |
| 16 | Length-tier validation (30-min + extrapolation) | planned | — | [`experiments/16_length_tiers/results.md`](../experiments/16_length_tiers/results.md) |

**Phase 5 exit gate:** end-to-end works; 2-worker slowdown ≤ 40%; per-tier costs within 3× of doc.

---

## Phase 6 — Synthesis

Final deliverable: [`FINDINGS.md`](./FINDINGS.md) — written once all 16 experiments are done.
