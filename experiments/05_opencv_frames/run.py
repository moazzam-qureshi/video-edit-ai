"""
Experiment 05 — OpenCV frame extraction + HSV histograms.

Gate (assumed from product.md §8 and audit, since no explicit number given):
- Frame extraction must be fast enough not to bottleneck the pipeline (RTF ≥ 5 for
  1 fps sampling, which is what we actually need for vision-model frame inputs)
- HSV histograms produce plausible color-grade descriptors (mean H/S/V, distribution)
- Frame writes are deterministic and reproducible

We use ffmpeg (via _shared.sample_video.extract_frames) for I/O — the audit and
sample_video.py docstring both call out OpenCV's poor I/O accuracy. OpenCV is
used here only for histogram math, which is what it's good at.

Run:
    python experiments/05_opencv_frames/run.py --clip samples/raw/raw_5min.mp4 --fps 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

from experiments._shared.instrument import Run  # noqa: E402
from experiments._shared.sample_video import probe, extract_frames  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--max_width", type=int, default=768)
    args = ap.parse_args()

    clip_path = (REPO_ROOT / args.clip).resolve()
    if not clip_path.exists():
        print(f"ERROR: clip not found: {clip_path}", file=sys.stderr)
        return 2

    info = probe(clip_path)
    print(f"[exp05] clip: {clip_path.name}  dur={info.duration_s:.2f}s  "
          f"{info.width}x{info.height}@{info.fps}fps")

    import cv2
    import numpy as np

    frames_dir = REPO_ROOT / "outputs" / "05_opencv_frames" / clip_path.stem
    frames_dir.mkdir(parents=True, exist_ok=True)

    exp_dir = REPO_ROOT / "experiments" / "05_opencv_frames"
    with Run(experiment="05_opencv_frames", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            duration_s=info.duration_s,
            sample_fps=args.fps,
            max_width=args.max_width,
        )

        # ---- Extract frames via ffmpeg ----
        t_ext = run.elapsed_so_far()
        frame_paths = extract_frames(
            clip_path, frames_dir, fps=args.fps, max_width=args.max_width,
        )
        extract_s = run.elapsed_so_far() - t_ext
        run.metric("extract_s", round(extract_s, 3))
        run.metric("n_frames", len(frame_paths))
        run.metric(
            "extract_rtf",
            round(info.duration_s / extract_s, 3) if extract_s > 0 else None,
        )

        # ---- HSV histograms for color-grade extraction ----
        t_hist = run.elapsed_so_far()
        hsv_means = {"h": [], "s": [], "v": []}
        hist_h, hist_s, hist_v = (
            np.zeros(180, dtype=np.float64),
            np.zeros(256, dtype=np.float64),
            np.zeros(256, dtype=np.float64),
        )
        for fp in frame_paths:
            img = cv2.imread(str(fp))
            if img is None:
                continue
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            h, s, v = cv2.split(hsv)
            hsv_means["h"].append(float(h.mean()))
            hsv_means["s"].append(float(s.mean()))
            hsv_means["v"].append(float(v.mean()))
            hist_h += cv2.calcHist([hsv], [0], None, [180], [0, 180]).flatten()
            hist_s += cv2.calcHist([hsv], [1], None, [256], [0, 256]).flatten()
            hist_v += cv2.calcHist([hsv], [2], None, [256], [0, 256]).flatten()
        hist_s_elapsed = run.elapsed_so_far() - t_hist
        run.metric("histogram_s", round(hist_s_elapsed, 3))

        if hsv_means["h"]:
            run.metric("hue_mean", round(sum(hsv_means["h"]) / len(hsv_means["h"]), 2))
            run.metric("sat_mean", round(sum(hsv_means["s"]) / len(hsv_means["s"]), 2))
            run.metric("val_mean", round(sum(hsv_means["v"]) / len(hsv_means["v"]), 2))

        # ---- Persist concise color profile ----
        out_json = REPO_ROOT / "outputs" / "05_opencv_frames" / f"{clip_path.stem}_color_profile.json"
        out_json.write_text(json.dumps({
            "clip": str(clip_path.relative_to(REPO_ROOT)),
            "n_frames_sampled": len(frame_paths),
            "sample_fps": args.fps,
            "hsv_mean": {
                "h": round(sum(hsv_means["h"]) / max(len(hsv_means["h"]), 1), 2),
                "s": round(sum(hsv_means["s"]) / max(len(hsv_means["s"]), 1), 2),
                "v": round(sum(hsv_means["v"]) / max(len(hsv_means["v"]), 1), 2),
            },
            "hist_h": hist_h.tolist(),
            "hist_s": hist_s.tolist(),
            "hist_v": hist_v.tolist(),
        }, indent=2))
        run.metric("color_profile", str(out_json.relative_to(REPO_ROOT)))

        print(f"[exp05] extracted {len(frame_paths)} frames in {extract_s:.2f}s "
              f"(RTF={run._metrics['extract_rtf']}); "
              f"histograms in {hist_s_elapsed:.2f}s; "
              f"HSV mean = ({run._metrics.get('hue_mean')}, "
              f"{run._metrics.get('sat_mean')}, "
              f"{run._metrics.get('val_mean')})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
