"""
Experiment 03 — MediaPipe face detection on every frame.

Gate (from vps_specs.md): ~0.5–1.5× realtime per worker on 1080p30. Our raw clips
are 360p30 so we expect faster — but we record what we measure, not what the
audit predicted for 1080p.

PASS if:
- RTF ≥ 0.5 (audit lower bound for 1080p; 360p should beat this easily)
- Detects faces in most frames of a talking-head clip (≥ 70% hit rate)
- Output schema: per-frame bbox (xmin, ymin, width, height) + confidence

Run:
    python experiments/03_mediapipe_face/run.py --clip samples/raw/raw_5min.mp4
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
    ap.add_argument("--min_confidence", type=float, default=0.5)
    ap.add_argument("--model_selection", type=int, default=0,
                    help="0 = close-range, 1 = full-range")
    args = ap.parse_args()

    clip_path = (REPO_ROOT / args.clip).resolve()
    if not clip_path.exists():
        print(f"ERROR: clip not found: {clip_path}", file=sys.stderr)
        return 2

    info = probe(clip_path)
    print(f"[exp03] clip: {clip_path.name}  dur={info.duration_s:.2f}s  "
          f"{info.width}x{info.height}@{info.fps}fps")

    import cv2
    import mediapipe as mp

    out_dir = REPO_ROOT / "outputs" / "03_mediapipe_face"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"{clip_path.stem}_faces.json"

    exp_dir = REPO_ROOT / "experiments" / "03_mediapipe_face"
    with Run(experiment="03_mediapipe_face", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            duration_s=info.duration_s,
            resolution=f"{info.width}x{info.height}",
            fps=info.fps,
            min_confidence=args.min_confidence,
            model_selection=args.model_selection,
        )

        cap = cv2.VideoCapture(str(clip_path))
        if not cap.isOpened():
            print("ERROR: cv2 cannot open clip", file=sys.stderr)
            return 3

        mp_fd = mp.solutions.face_detection
        per_frame: list[dict] = []
        frames_total = 0
        frames_with_face = 0
        confidences: list[float] = []

        with mp_fd.FaceDetection(
            min_detection_confidence=args.min_confidence,
            model_selection=args.model_selection,
        ) as fd:
            while True:
                ok, frame_bgr = cap.read()
                if not ok:
                    break
                frames_total += 1
                rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                result = fd.process(rgb)
                if result.detections:
                    frames_with_face += 1
                    det = result.detections[0]
                    bbox = det.location_data.relative_bounding_box
                    score = det.score[0] if det.score else 0.0
                    confidences.append(score)
                    per_frame.append({
                        "frame": frames_total - 1,
                        "bbox": {
                            "xmin": bbox.xmin, "ymin": bbox.ymin,
                            "width": bbox.width, "height": bbox.height,
                        },
                        "confidence": score,
                    })

        cap.release()

        elapsed = run.elapsed_so_far()
        run.metric("frames_total", frames_total)
        run.metric("frames_with_face", frames_with_face)
        run.metric(
            "hit_rate",
            round(frames_with_face / frames_total, 3) if frames_total else None,
        )
        run.metric(
            "avg_confidence",
            round(sum(confidences) / len(confidences), 3) if confidences else None,
        )
        run.metric("processing_s", round(elapsed, 3))
        run.metric(
            "fps_processed",
            round(frames_total / elapsed, 2) if elapsed > 0 else None,
        )
        run.metric(
            "rtf",
            round(info.duration_s / elapsed, 3) if elapsed > 0 else None,
        )

        # Drop full per-frame data — too noisy to commit; sample every 30 frames
        sample = per_frame[::30]
        out_json.write_text(json.dumps({
            "clip": str(clip_path.relative_to(REPO_ROOT)),
            "frames_total": frames_total,
            "frames_with_face": frames_with_face,
            "sample_every_30_frames": sample,
        }, indent=2))
        run.metric("output", str(out_json.relative_to(REPO_ROOT)))

        print(f"[exp03] {frames_with_face}/{frames_total} frames had a face "
              f"({run._metrics['hit_rate']*100:.1f}%) in {elapsed:.1f}s "
              f"(RTF={run._metrics['rtf']}, {run._metrics['fps_processed']} fps)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
