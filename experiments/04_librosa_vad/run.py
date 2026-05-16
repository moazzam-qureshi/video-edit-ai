"""
Experiment 04 — Librosa energy + Silero VAD.

Gate (from vps_specs.md): ~5–20× realtime, trivial CPU load.

PASS if:
- RTF ≥ 5 (audit lower bound)
- Detects speech segments (Silero VAD)
- Produces RMS energy curve aligned to audio timeline
- Onset detection returns a plausible list of energy peaks (>= 10 for 5-min talking head)

Run:
    python experiments/04_librosa_vad/run.py --clip samples/raw/raw_5min.mp4
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
from experiments._shared.sample_video import probe, extract_audio  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    args = ap.parse_args()

    clip_path = (REPO_ROOT / args.clip).resolve()
    if not clip_path.exists():
        print(f"ERROR: clip not found: {clip_path}", file=sys.stderr)
        return 2

    info = probe(clip_path)
    print(f"[exp04] clip: {clip_path.name}  dur={info.duration_s:.2f}s")

    out_dir = REPO_ROOT / "outputs" / "04_librosa_vad"
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / f"{clip_path.stem}.wav"

    import numpy as np

    exp_dir = REPO_ROOT / "experiments" / "04_librosa_vad"
    with Run(experiment="04_librosa_vad", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            duration_s=info.duration_s,
        )

        extract_audio(clip_path, wav_path, sample_rate=16000, mono=True)
        run.metric("audio_extract_s", round(run.elapsed_so_far(), 3))

        # ---- Librosa: load + RMS + onset detection ----
        import librosa

        t_lib_start = run.elapsed_so_far()
        y, sr = librosa.load(str(wav_path), sr=16000, mono=True)
        rms = librosa.feature.rms(y=y)[0]
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
        onset_times = librosa.frames_to_time(onset_frames, sr=sr).tolist()
        librosa_s = run.elapsed_so_far() - t_lib_start
        run.metric("librosa_s", round(librosa_s, 3))
        run.metric("librosa_rtf", round(info.duration_s / librosa_s, 3))
        run.metric("n_onsets", len(onset_times))
        run.metric("rms_mean", float(rms.mean()))
        run.metric("rms_peak", float(rms.max()))

        # ---- Silero VAD ----
        t_vad_start = run.elapsed_so_far()
        from silero_vad import get_speech_timestamps, load_silero_vad, read_audio

        vad_model = load_silero_vad()
        wav = read_audio(str(wav_path), sampling_rate=16000)
        speech_ts = get_speech_timestamps(
            wav, vad_model, sampling_rate=16000, return_seconds=True,
        )
        vad_s = run.elapsed_so_far() - t_vad_start
        run.metric("vad_s", round(vad_s, 3))
        run.metric("vad_rtf", round(info.duration_s / vad_s, 3))
        run.metric("n_speech_segments", len(speech_ts))

        speech_dur = sum(s["end"] - s["start"] for s in speech_ts)
        run.metric("speech_duration_s", round(speech_dur, 3))
        run.metric(
            "speech_pct",
            round(100 * speech_dur / info.duration_s, 2) if info.duration_s else None,
        )

        # ---- Combined RTF ----
        total_compute = librosa_s + vad_s
        run.metric("combined_rtf", round(info.duration_s / total_compute, 3))

        # ---- Persist sample output ----
        out_json = out_dir / f"{clip_path.stem}_audio_analysis.json"
        out_json.write_text(json.dumps({
            "clip": str(clip_path.relative_to(REPO_ROOT)),
            "sample_rate": 16000,
            "rms_n_frames": int(len(rms)),
            "rms_mean": float(rms.mean()),
            "rms_peak": float(rms.max()),
            "onset_times_s": onset_times,
            "speech_segments_s": speech_ts,
        }, indent=2))

        print(f"[exp04] librosa_rtf={run._metrics['librosa_rtf']}  "
              f"vad_rtf={run._metrics['vad_rtf']}  "
              f"speech={run._metrics['speech_pct']}%  "
              f"onsets={run._metrics['n_onsets']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
