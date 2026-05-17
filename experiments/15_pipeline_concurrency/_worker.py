"""Subprocess worker for Exp 15. Transcribes one clip and writes result JSON.

Run via the main run.py — not directly. Each worker is a fresh Python
process so libtorch's threads start clean (avoids the fork-after-import
BrokenProcessPool problem).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from experiments._shared.sample_video import probe, extract_audio  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker-id", type=int, required=True)
    ap.add_argument("--clip", required=True)
    ap.add_argument("--model", default="large-v2")
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--language", default="en")
    ap.add_argument("--output-json", required=True)
    args = ap.parse_args()

    clip_path = (REPO_ROOT / args.clip).resolve()
    info = probe(clip_path)

    out_dir = REPO_ROOT / "outputs" / "15_pipeline_concurrency"
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_wav = out_dir / f"worker{args.worker_id}_{clip_path.stem}.wav"

    t_total_start = time.perf_counter()
    extract_audio(clip_path, audio_wav, sample_rate=16000, mono=True)

    import whisperx  # heavy import — done here so each subprocess pays it once

    t_load_start = time.perf_counter()
    model = whisperx.load_model(
        args.model, device="cpu", compute_type=args.compute_type,
        language=args.language,
    )
    model_load_s = time.perf_counter() - t_load_start

    audio = whisperx.load_audio(str(audio_wav))
    t_tr_start = time.perf_counter()
    result = model.transcribe(audio, batch_size=8, language=args.language)
    transcribe_s = time.perf_counter() - t_tr_start

    n_segments = len(result.get("segments", []))
    total_s = time.perf_counter() - t_total_start

    out = {
        "worker_id": args.worker_id,
        "model_load_s": round(model_load_s, 3),
        "transcribe_s": round(transcribe_s, 3),
        "total_s": round(total_s, 3),
        "duration_s": info.duration_s,
        "rtf_transcribe": round(info.duration_s / transcribe_s, 3),
        "n_segments": n_segments,
    }
    Path(args.output_json).write_text(json.dumps(out, indent=2))
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
