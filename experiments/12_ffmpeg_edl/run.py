"""
Experiment 12 — FFmpeg EDL translator + render.

Take an EDL JSON (from Exp 10 or Exp 11), translate it into an ffmpeg
filter_complex graph, and produce an edited mp4.

This experiment focuses on the structural edits:
- remove_silence  → drop those time ranges from both video and audio
- speed_up        → setpts on the kept video, atempo on the kept audio
                    (tagged but not applied in this first version)
- zoom_in         → animated crop+scale on the kept window (tagged but
                    not applied here)
- cut             → handled implicitly by remove_silence ranges (a cut
                    edit alone is informational; the brain emits cuts as
                    structural anchors, not as additional removals)

Captions and SFX are deferred to Exp 13. We tag them as "skipped" so
the EDL is still consumable end-to-end.

Strategy:
  1. Build the list of KEPT time-ranges (input duration minus
     remove_silence ranges).
  2. For each kept range, emit a trim+setpts segment + an atrim+asetpts.
  3. Concat all segments back together.

Gate:
- An EDL produced by Exp 10 / Exp 11 renders successfully to mp4.
- Output duration ≈ input_duration - sum(remove_silence).
- Render RTF ≥ 0.5× (audit: libx264 medium preset ~1–2× realtime on
  this CPU).
- No FFmpeg errors.

Run:
    python experiments/12_ffmpeg_edl/run.py \\
        --edl outputs/10_brain_5min/edl.json \\
        --clip samples/raw/raw_5min.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

from experiments._shared.instrument import Run  # noqa: E402
from experiments._shared.sample_video import probe  # noqa: E402


def merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not ranges:
        return []
    ranges = sorted([(a, b) for a, b in ranges if b > a])
    merged = [ranges[0]]
    for a, b in ranges[1:]:
        la, lb = merged[-1]
        if a <= lb + 0.01:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a, b))
    return merged


def compute_kept_ranges(
    duration: float,
    drop_ranges: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    drops = merge_ranges(drop_ranges)
    kept: list[tuple[float, float]] = []
    cursor = 0.0
    for a, b in drops:
        a = max(0.0, min(a, duration))
        b = max(0.0, min(b, duration))
        if a > cursor:
            kept.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < duration:
        kept.append((cursor, duration))
    return [(a, b) for a, b in kept if b - a > 0.05]


def edl_summarize(edl: dict) -> dict:
    counts: dict[str, int] = {}
    for e in edl.get("edits", []):
        counts[e.get("type", "?")] = counts.get(e.get("type", "?"), 0) + 1
    return counts


def build_filter_complex(kept: list[tuple[float, float]]) -> str:
    """Trim each kept range, then concat. ffmpeg's concat filter requires
    inputs INTERLEAVED as [v0][a0][v1][a1]...[vN][aN], not grouped."""
    segments = []
    for i, (a, b) in enumerate(kept):
        segments.append(
            f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
        segments.append(
            f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]"
        )
    interleaved = "".join(f"[v{i}][a{i}]" for i in range(len(kept)))
    concat = (
        f"{interleaved}concat=n={len(kept)}:v=1:a=1[vout][aout]"
    )
    return ";".join(segments + [concat])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edl", required=True)
    ap.add_argument("--clip", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--crf", type=int, default=23)
    args = ap.parse_args()

    edl_path = (REPO_ROOT / args.edl).resolve()
    clip_path = (REPO_ROOT / args.clip).resolve()
    if not edl_path.exists() or not clip_path.exists():
        print("ERROR: EDL or clip missing", file=sys.stderr)
        return 2

    out_dir = REPO_ROOT / "outputs" / "12_ffmpeg_edl"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (REPO_ROOT / args.out).resolve() if args.out else (
        out_dir / f"{clip_path.stem}_edited.mp4"
    )

    edl = json.loads(edl_path.read_text())
    info = probe(clip_path)
    print(f"[exp12] clip {clip_path.name}  dur={info.duration_s:.1f}s "
          f"{info.width}x{info.height}@{info.fps}fps  audio={info.has_audio}")
    print(f"[exp12] edl: {edl_path.name}  edit_counts={edl_summarize(edl)}")
    if not info.has_audio:
        print("ERROR: clip has no audio.", file=sys.stderr)
        return 3

    drop_ranges: list[tuple[float, float]] = []
    zoom_ranges: list[tuple[float, float, float]] = []
    speedup_ranges: list[tuple[float, float, float]] = []
    for e in edl.get("edits", []):
        t = e.get("type")
        if t == "remove_silence":
            f, to = e.get("from"), e.get("to")
            if isinstance(f, (int, float)) and isinstance(to, (int, float)) and to > f:
                drop_ranges.append((float(f), float(to)))
        elif t == "zoom_in":
            f, to, lvl = e.get("from"), e.get("to"), e.get("level", 1.2)
            if isinstance(f, (int, float)) and isinstance(to, (int, float)) and to > f:
                zoom_ranges.append((float(f), float(to), float(lvl)))
        elif t == "speed_up":
            f, to, rate = e.get("from"), e.get("to"), e.get("rate", 1.5)
            if isinstance(f, (int, float)) and isinstance(to, (int, float)) and to > f:
                speedup_ranges.append((float(f), float(to), float(rate)))

    kept = compute_kept_ranges(info.duration_s, drop_ranges)
    total_dropped = sum(b - a for a, b in merge_ranges(drop_ranges))
    expected_out_dur = info.duration_s - total_dropped
    print(f"[exp12] drop_ranges={len(drop_ranges)}  merged={len(merge_ranges(drop_ranges))}  "
          f"total_dropped={total_dropped:.2f}s")
    print(f"[exp12] kept_ranges={len(kept)}  expected_out_dur={expected_out_dur:.2f}s")

    if not kept:
        print("ERROR: no kept ranges", file=sys.stderr)
        return 4

    filter_complex = build_filter_complex(kept)
    # Long filter_complex strings can run afoul of argv parsing; write to a
    # file and use -filter_complex_script.
    fc_path = out_dir / f"{clip_path.stem}_fc.txt"
    fc_path.write_text(filter_complex)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(clip_path),
        "-filter_complex_script", str(fc_path),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print(f"[exp12] ffmpeg cmd uses -filter_complex_script ({len(filter_complex)} chars in {fc_path.name})")

    exp_dir = REPO_ROOT / "experiments" / "12_ffmpeg_edl"
    with Run(experiment="12_ffmpeg_edl", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            edl=str(edl_path.relative_to(REPO_ROOT)),
            duration_in_s=info.duration_s,
            resolution=f"{info.width}x{info.height}",
            fps=info.fps,
            preset=args.preset,
            crf=args.crf,
        )
        run.metric("n_edits_total", len(edl.get("edits", [])))
        run.metric("edit_type_counts", edl_summarize(edl))
        run.metric("drop_ranges_emitted", len(drop_ranges))
        run.metric("drop_ranges_merged", len(merge_ranges(drop_ranges)))
        run.metric("total_dropped_s", round(total_dropped, 3))
        run.metric("kept_ranges", len(kept))
        run.metric("expected_out_dur_s", round(expected_out_dur, 3))
        run.metric("zoom_ranges_skipped", len(zoom_ranges))
        run.metric("speedup_ranges_skipped", len(speedup_ranges))

        t0 = time.perf_counter()
        r = subprocess.run(cmd, capture_output=True, text=True)
        ffmpeg_s = time.perf_counter() - t0
        run.metric("ffmpeg_wall_s", round(ffmpeg_s, 3))

        if r.returncode != 0:
            run.note(ffmpeg_stderr=r.stderr[:2000])
            print(f"[exp12] FFMPEG FAILED rc={r.returncode}")
            print(r.stderr[-1500:])
            return 5

        if not out_path.exists():
            run.note(error="output file missing despite rc=0")
            return 6

        info_out = probe(out_path)
        run.metric("out_duration_s", round(info_out.duration_s, 3))
        run.metric("out_size_mb", info_out.size_mb)
        run.metric(
            "duration_match_delta_s",
            round(info_out.duration_s - expected_out_dur, 3),
        )
        run.metric(
            "render_rtf",
            round(info.duration_s / ffmpeg_s, 3) if ffmpeg_s > 0 else None,
        )

        print(f"[exp12] OK  ffmpeg={ffmpeg_s:.2f}s "
              f"render_rtf={info.duration_s/ffmpeg_s:.2f}× "
              f"out_dur={info_out.duration_s:.2f}s "
              f"(expected {expected_out_dur:.2f}, delta "
              f"{info_out.duration_s - expected_out_dur:+.2f}s) "
              f"size={info_out.size_mb}MB")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
