"""
Experiment 02 — PySceneDetect cut/scene detection.

Gate (from vps_specs.md): ContentDetector should process 1080p video at 3–8× realtime.
On our 360p raw clips it should be faster still. PASS if:
- RTF ≥ 2.0 (well below the 3-8× audit prediction, leaves margin for 360p/shared box)
- Detects a non-zero number of scenes
- Produces a usable scene list (timestamps in seconds, exportable to JSON)

Run:
    python experiments/02_pyscenedetect/run.py --clip samples/raw/raw_15min.mp4

Note: our raw clips are talking-head with few hard cuts, so we also try the reference
video (heavily edited) to verify the detector finds many scenes when they exist.
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
from experiments._shared.sample_video import probe  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--detector", default="content",
                    choices=["content", "adaptive", "threshold"])
    ap.add_argument("--threshold", type=float, default=27.0,
                    help="ContentDetector threshold (default 27)")
    args = ap.parse_args()

    clip_path = (REPO_ROOT / args.clip).resolve()
    if not clip_path.exists():
        print(f"ERROR: clip not found: {clip_path}", file=sys.stderr)
        return 2

    out_dir = REPO_ROOT / "outputs" / "02_pyscenedetect"
    out_dir.mkdir(parents=True, exist_ok=True)

    info = probe(clip_path)
    print(f"[exp02] clip: {clip_path.name}  dur={info.duration_s:.2f}s  "
          f"{info.width}x{info.height}@{info.fps}fps")

    from scenedetect import (
        AdaptiveDetector,
        ContentDetector,
        ThresholdDetector,
        detect,
    )

    detectors = {
        "content": lambda: ContentDetector(threshold=args.threshold),
        "adaptive": lambda: AdaptiveDetector(),
        "threshold": lambda: ThresholdDetector(),
    }

    exp_dir = REPO_ROOT / "experiments" / "02_pyscenedetect"
    with Run(experiment="02_pyscenedetect", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            duration_s=info.duration_s,
            resolution=f"{info.width}x{info.height}",
            fps=info.fps,
            detector=args.detector,
            threshold=args.threshold if args.detector == "content" else None,
        )

        t0 = run.elapsed_so_far()
        scene_list = detect(str(clip_path), detectors[args.detector]())
        elapsed = run.elapsed_so_far() - t0

        run.metric("detect_s", round(elapsed, 3))
        run.metric("rtf", round(info.duration_s / elapsed, 3) if elapsed > 0 else None)
        run.metric("n_scenes", len(scene_list))

        scenes_json = [
            {
                "scene_idx": i,
                "start_s": start.get_seconds(),
                "end_s": end.get_seconds(),
                "duration_s": (end - start).get_seconds(),
            }
            for i, (start, end) in enumerate(scene_list)
        ]
        out_json = out_dir / f"{clip_path.stem}_{args.detector}_scenes.json"
        out_json.write_text(json.dumps(scenes_json, indent=2))
        run.metric("scenes_json", str(out_json.relative_to(REPO_ROOT)))

        if scenes_json:
            durations = [s["duration_s"] for s in scenes_json]
            run.metric("avg_scene_s", round(sum(durations) / len(durations), 3))
            run.metric("median_scene_s", round(sorted(durations)[len(durations) // 2], 3))
            run.metric("min_scene_s", round(min(durations), 3))
            run.metric("max_scene_s", round(max(durations), 3))

        print(f"[exp02] {args.detector}: {len(scene_list)} scenes in "
              f"{elapsed:.2f}s (RTF={run._metrics['rtf']})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
