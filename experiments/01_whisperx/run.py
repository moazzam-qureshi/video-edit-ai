"""
Experiment 01 — WhisperX transcription (large-v2 int8) on the Ryzen 5 3600.

Gate (assumed from vps_specs.md audit, since the formal plan lives off-repo):
- RTF (real-time factor) ≥ 0.35 on CPU (audit predicts 0.4–0.6 for large-v2 int8).
- Produces word-level timestamps (alignment step succeeds).
- Peak RSS ≤ 5000 MB per worker (audit predicts 3–4 GB).

Run:
    python experiments/01_whisperx/run.py --clip samples/raw/raw_5min.mp4 \
        --model large-v2 --compute_type int8

Writes:
- experiments/01_whisperx/metrics.json   (auto, via instrument.Run)
- outputs/01_whisperx/<clip>_<model>_transcript.json   (word-level)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# Load .env so OMP_NUM_THREADS / CT2_USE_EXPERIMENTAL_PACKED_GEMM take effect
# *before* the heavy libs import.
from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

# Now safe to import:
from experiments._shared.instrument import Run  # noqa: E402
from experiments._shared.sample_video import probe, extract_audio  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True, help="path to video or audio file")
    ap.add_argument("--model", default="large-v2", help="whisper model size")
    ap.add_argument("--compute_type", default="int8", help="ctranslate2 quant")
    ap.add_argument("--language", default="en")
    ap.add_argument("--batch_size", type=int, default=8)
    ap.add_argument("--align", action="store_true", default=True,
                    help="run whisperx alignment for word-level timestamps")
    ap.add_argument("--no-align", dest="align", action="store_false")
    args = ap.parse_args()

    clip_path = (REPO_ROOT / args.clip).resolve()
    if not clip_path.exists():
        print(f"ERROR: clip not found: {clip_path}", file=sys.stderr)
        return 2

    out_dir = REPO_ROOT / "outputs" / "01_whisperx"
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_wav = out_dir / f"{clip_path.stem}.wav"

    info = probe(clip_path)
    print(f"[exp01] clip: {clip_path.name}  dur={info.duration_s:.2f}s  "
          f"audio={info.has_audio}  codec={info.codec}")
    if not info.has_audio:
        print("ERROR: clip has no audio track", file=sys.stderr)
        return 3

    # ------------------------------------------------------------------
    # Heavy imports inside the timed block — we measure cold + warm cost.
    # ------------------------------------------------------------------
    exp_dir = REPO_ROOT / "experiments" / "01_whisperx"
    with Run(experiment="01_whisperx", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            duration_s=info.duration_s,
            model=args.model,
            compute_type=args.compute_type,
            language=args.language,
            batch_size=args.batch_size,
            align=args.align,
        )

        # 1. extract 16 kHz mono WAV (Whisper input format)
        extract_audio(clip_path, audio_wav, sample_rate=16000, mono=True)
        run.metric("audio_extract_s", round(run.elapsed_so_far(), 3))

        # 2. transcribe
        import whisperx

        t_load_start = run.elapsed_so_far()
        model = whisperx.load_model(
            args.model,
            device="cpu",
            compute_type=args.compute_type,
            language=args.language,
        )
        run.metric("model_load_s", round(run.elapsed_so_far() - t_load_start, 3))

        t_transcribe_start = run.elapsed_so_far()
        audio = whisperx.load_audio(str(audio_wav))
        result = model.transcribe(audio, batch_size=args.batch_size, language=args.language)
        transcribe_s = run.elapsed_so_far() - t_transcribe_start
        run.metric("transcribe_s", round(transcribe_s, 3))

        segments = result.get("segments", [])
        run.metric("n_segments", len(segments))
        run.metric(
            "rtf_transcribe",
            round(info.duration_s / transcribe_s, 3) if transcribe_s > 0 else None,
        )

        # 3. alignment for word-level timestamps
        n_words = 0
        align_s = None
        if args.align and segments:
            t_align_start = run.elapsed_so_far()
            try:
                align_model, align_meta = whisperx.load_align_model(
                    language_code=args.language, device="cpu"
                )
                aligned = whisperx.align(
                    segments, align_model, align_meta, audio, device="cpu",
                    return_char_alignments=False,
                )
                segments = aligned.get("segments", segments)
                align_s = run.elapsed_so_far() - t_align_start
                n_words = sum(len(s.get("words", [])) for s in segments)
            except Exception as e:
                run.note(align_error=f"{type(e).__name__}: {e}")
            run.metric("align_s", round(align_s, 3) if align_s else None)

        run.metric("n_words", n_words)
        run.metric(
            "rtf_total_no_load",
            round(info.duration_s / (transcribe_s + (align_s or 0.0)), 3),
        )

        # 4. write transcript
        transcript_path = out_dir / f"{clip_path.stem}_{args.model}_{args.compute_type}.json"
        transcript_path.write_text(
            json.dumps(
                {
                    "clip": str(clip_path.relative_to(REPO_ROOT)),
                    "model": args.model,
                    "compute_type": args.compute_type,
                    "language": args.language,
                    "duration_s": info.duration_s,
                    "segments": segments,
                },
                ensure_ascii=False,
            )
        )
        run.metric("transcript_path", str(transcript_path.relative_to(REPO_ROOT)))
        run.metric("transcript_size_mb", round(transcript_path.stat().st_size / 1024**2, 2))

        print(f"[exp01] words={n_words} segments={len(segments)} "
              f"rtf_transcribe={run._metrics.get('rtf_transcribe')} "
              f"rtf_total={run._metrics.get('rtf_total_no_load')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
