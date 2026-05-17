"""
Experiment 12b — Animated zoom + SFX overlay rendering.

Builds on Exp 12 (silence-trim) and adds the two render layers FINDINGS
flagged as deferred:

  - **Animated zoom_in**: for each zoom edit in (output-time) `(from, to,
    level, center)`, apply a smooth 1.0 → `level` ramp using ffmpeg's
    zoompan filter, centered on the speaker (best-effort) and snap back
    to 1.0 at the end of the window.
  - **SFX overlay**: for each sfx edit in (output-time) `(at, sound)`,
    overlay the corresponding sample from `assets/sfx/` (currently only
    `whoosh.wav` exists; all sfx edits use it) onto the audio track
    using `adelay` + `amix`.

This experiment is parametrized on:
  - input mp4 (typically the silence-trimmed output of Exp 12),
  - a list of zoom edits in OUTPUT time,
  - a list of sfx edits in OUTPUT time.

The caller (Exp 14) handles the timestamp-remapping from source-time
EDL → output-time edits.

Gate:
  - Output mp4 is playable and has the same duration as the input
    (zoom + sfx don't change duration).
  - For each zoom edit, the output has a visibly zoomed-in window at
    the right timestamp (verified by frame extraction).
  - For each sfx edit, the output audio is louder at the right
    timestamp (verified by sample-level energy check via Librosa).

Run (standalone):
    python experiments/12b_render_zoom_sfx/run.py \\
        --in outputs/14_full_pipeline_5min/raw_talking_5min_trimmed.mp4 \\
        --zooms-json /tmp/zooms_output_time.json \\
        --sfx-json /tmp/sfx_output_time.json \\
        --out outputs/12b_render_zoom_sfx/test.mp4
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


SFX_LIBRARY = REPO_ROOT / "assets" / "sfx"


def merge_adjacent_zooms(zooms: list[dict], gap_threshold: float = 1.0) -> list[dict]:
    """Merge zoom windows that are within `gap_threshold` seconds of each
    other. Without this, brains that emit dense zooms (one per 5s VM-7
    frame) overflow ffmpeg's expression-string length limit on the
    zoompan `z` expression.

    Conservative merge: combine only if `level` is identical (so we don't
    silently change a zoom's intensity). If levels differ across adjacent
    zooms, keep them separate."""
    if not zooms:
        return []
    zs = sorted(zooms, key=lambda e: float(e["from"]))
    merged = [dict(zs[0])]
    for z in zs[1:]:
        last = merged[-1]
        same_level = float(z.get("level", 1.2)) == float(last.get("level", 1.2))
        if same_level and float(z["from"]) - float(last["to"]) <= gap_threshold:
            last["to"] = max(float(last["to"]), float(z["to"]))
        else:
            merged.append(dict(z))
    return merged


def face_center_for_window(
    face_data: dict, fps: float,
    window_from: float, window_to: float,
    fallback: tuple[float, float] = (0.5, 0.5),
) -> tuple[float, float]:
    """Compute the median face center (in normalized 0..1 image coords) for
    face bboxes that fall inside [window_from, window_to] seconds. The
    face_data is the JSON saved by Exp 03 (sample_every_30_frames).
    Returns (cx, cy) in 0..1. Falls back to `fallback` (frame center)
    if no face data in window."""
    sample = face_data.get("sample_every_30_frames", [])
    cxs, cys = [], []
    for s in sample:
        t = s.get("frame", 0) / max(fps, 1.0)
        if t < window_from or t > window_to:
            continue
        bbox = s.get("bbox") or {}
        cx = bbox.get("xmin", 0) + bbox.get("width", 0) / 2
        cy = bbox.get("ymin", 0) + bbox.get("height", 0) / 2
        cxs.append(cx)
        cys.append(cy)
    if not cxs:
        return fallback
    cxs.sort(); cys.sort()
    return cxs[len(cxs) // 2], cys[len(cys) // 2]


def build_video_filter_with_zooms(
    duration: float, fps: float, width: int, height: int,
    zooms: list[dict],
    max_zooms_in_expr: int = 20,
    face_data: dict | None = None,
) -> str:
    """Build a video filter that takes [0:v] and emits [vout], applying
    animated zoom-in over each zoom edit window.

    Strategy: zoompan operates per-frame with `z` as a piecewise
    expression of `it` (input time). Each zoom contributes a nested
    if(between(it, from, to), ramp, fallthrough). ffmpeg's expression
    parser has a length limit; on dense brain output we'd overflow.

    Defensive: (1) merge adjacent zooms via merge_adjacent_zooms,
    (2) cap the number of zooms baked into the expression at
    `max_zooms_in_expr` (drop the rest with a logged warning).
    """
    if not zooms:
        return ""

    # Merge adjacent — collapses the brain's "one zoom per 5s frame"
    # output into a small number of long windows.
    merged = merge_adjacent_zooms(zooms, gap_threshold=1.0)
    if len(merged) > max_zooms_in_expr:
        print(f"[exp12b] WARNING: {len(merged)} merged zoom windows exceeds "
              f"cap of {max_zooms_in_expr}; keeping first {max_zooms_in_expr}.")
        merged = merged[:max_zooms_in_expr]

    # Compute per-window face center (normalized 0..1). Each window gets
    # the MEDIAN face position observed inside that window. Falls back to
    # frame center (0.5, 0.5) if no face data is provided or no faces fall
    # in the window.
    windows = []
    for z in merged:
        f = float(z["from"])
        to = float(z["to"])
        level = float(z.get("level", 1.2))
        if face_data:
            cx, cy = face_center_for_window(face_data, fps, f, to)
        else:
            cx, cy = 0.5, 0.5
        windows.append((f, to, level, cx, cy))

    # Build piecewise expressions for z, x, y. zoompan exposes `it` (input
    # time in seconds) and `iw`/`ih` (input width/height). Each window
    # contributes a ramp 1.0 → level (in z) and a face-centered crop
    # (in x, y). When a window is active, x = iw*cx - iw/(2*zoom),
    # clamped to [0, iw - iw/zoom]. Equivalent in expression form using
    # min/max. Same for y.
    z_expr = "1.0"
    x_expr = "(iw-iw/zoom)/2"  # frame-center when no window is active
    y_expr = "(ih-ih/zoom)/2"
    for (f, to, level, cx, cy) in reversed(windows):
        ramp_end = f + (to - f) * 0.8
        z_ramp = (
            f"if(between(it,{f:.2f},{ramp_end:.2f}),"
            f"1.0+({level:.2f}-1.0)*(it-{f:.2f})/({ramp_end:.2f}-{f:.2f}),"
            f"if(between(it,{ramp_end:.2f},{to:.2f}),{level:.2f},{z_expr}))"
        )
        z_expr = z_ramp
        # Face-centered crop: top-left of the window we keep.
        # Clamp so we don't drift off the source frame: max(0, min(iw - iw/z, x_raw))
        x_target = (
            f"max(0,min(iw-iw/zoom,iw*{cx:.3f}-iw/(2*zoom)))"
        )
        y_target = (
            f"max(0,min(ih-ih/zoom,ih*{cy:.3f}-ih/(2*zoom)))"
        )
        x_expr = f"if(between(it,{f:.2f},{to:.2f}),{x_target},{x_expr})"
        y_expr = f"if(between(it,{f:.2f},{to:.2f}),{y_target},{y_expr})"

    vf = (
        f"zoompan=z='{z_expr}':"
        f"x='{x_expr}':"
        f"y='{y_expr}':"
        f"d=1:"
        f"s={width}x{height}:"
        f"fps={fps}"
    )
    return vf


def build_audio_filter_with_sfx(
    sfx_edits: list[dict],
    sfx_inputs_start_idx: int,
) -> tuple[str, list[Path]]:
    """Build an audio filter that mixes the input audio with whoosh
    overlays at the given timestamps.

    Returns (filter_str, list_of_sfx_paths). The caller adds each path
    as an `-i` ffmpeg input. `sfx_inputs_start_idx` is the index of the
    first sfx input in ffmpeg's input order (e.g., 1 if the video is 0).
    """
    if not sfx_edits:
        return "[0:a]anull[aout]", []

    sfx_paths: list[Path] = []
    delayed_labels: list[str] = []
    for i, e in enumerate(sfx_edits):
        sound = e.get("sound", "whoosh")
        sfx_path = SFX_LIBRARY / f"{sound}.wav"
        if not sfx_path.exists():
            # Fall back to whoosh
            sfx_path = SFX_LIBRARY / "whoosh.wav"
        sfx_paths.append(sfx_path)
        delay_ms = int(round(float(e["at"]) * 1000))
        input_idx = sfx_inputs_start_idx + i
        # adelay delays each sfx by its start time. volume=2 lifts the
        # whoosh above the speech RMS so it's actually audible in the
        # mix; amix=normalize=1 would otherwise cap the combined signal
        # at the loudest source and the whoosh would disappear under
        # speech. We use normalize=0 + manual whoosh boost instead.
        delayed_labels.append(
            f"[{input_idx}:a]volume=2.5,adelay={delay_ms}|{delay_ms}[sfx{i}]"
        )

    # Mix original audio + all sfx tracks. `duration=first` makes the
    # mix length equal to the original audio (sfx past the end clipped).
    # `normalize=0` keeps each track at its existing gain.
    n_inputs = 1 + len(sfx_edits)
    mix_inputs = "[0:a]" + "".join(f"[sfx{i}]" for i in range(len(sfx_edits)))
    delays = ";".join(delayed_labels)
    audio_filter = (
        f"{delays};"
        f"{mix_inputs}amix=inputs={n_inputs}:duration=first:normalize=0[aout]"
    )
    return audio_filter, sfx_paths


def render_zoom_sfx(
    in_mp4: Path, out_mp4: Path,
    zooms: list[dict], sfx_edits: list[dict],
    preset: str = "fast", crf: int = 23,
    face_data: dict | None = None,
) -> tuple[float, dict]:
    """Render `in_mp4` to `out_mp4` applying the given zoom + sfx edits.
    All timestamps must be in OUTPUT time (i.e., already remapped from
    source-time through any silence-trim that produced in_mp4).

    `face_data` (optional) is the JSON saved by Exp 03 with
    `sample_every_30_frames`. When provided, zoom crops are centered on
    the median face position for each window instead of frame-center.

    Returns (ffmpeg_wall_s, metadata_dict).
    """
    info = probe(in_mp4)
    vf = build_video_filter_with_zooms(
        info.duration_s, info.fps, info.width, info.height, zooms,
        face_data=face_data,
    )
    af, sfx_paths = build_audio_filter_with_sfx(sfx_edits, sfx_inputs_start_idx=1)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(in_mp4)]
    for p in sfx_paths:
        cmd.extend(["-i", str(p)])

    # Filter complex: video and audio in one graph
    fc_parts = []
    if vf:
        fc_parts.append(f"[0:v]{vf}[vout]")
    else:
        fc_parts.append("[0:v]copy[vout]")
    fc_parts.append(af)
    fc = ";".join(fc_parts)

    # Write filter to a script file in the output dir
    out_dir = out_mp4.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    fc_path = out_dir / f"{out_mp4.stem}_fc.txt"
    fc_path.write_text(fc)

    cmd.extend([
        "-filter_complex_script", str(fc_path),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_mp4),
    ])

    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (rc={r.returncode}):\n{r.stderr[-2000:]}"
        )

    meta = {
        "n_zooms_applied": len(zooms),
        "n_sfx_applied": len(sfx_edits),
        "sfx_paths": [str(p.relative_to(REPO_ROOT)) for p in sfx_paths],
        "filter_complex_len": len(fc),
        "filter_complex_path": str(fc_path.relative_to(REPO_ROOT)),
    }
    return wall, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_mp4", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--zooms-json", default=None,
                    help="JSON file with a list of zoom edits in OUTPUT time")
    ap.add_argument("--sfx-json", default=None,
                    help="JSON file with a list of sfx edits in OUTPUT time")
    ap.add_argument("--preset", default="fast")
    ap.add_argument("--crf", type=int, default=23)
    args = ap.parse_args()

    in_mp4 = (REPO_ROOT / args.in_mp4).resolve()
    out_mp4 = (REPO_ROOT / args.out).resolve()
    zooms = json.loads(Path(args.zooms_json).read_text()) if args.zooms_json else []
    sfx_edits = json.loads(Path(args.sfx_json).read_text()) if args.sfx_json else []

    info_in = probe(in_mp4)
    print(f"[exp12b] input: {in_mp4.name} {info_in.duration_s:.2f}s "
          f"{info_in.width}x{info_in.height}@{info_in.fps}fps")
    print(f"[exp12b] zooms={len(zooms)}  sfx={len(sfx_edits)}")

    exp_dir = REPO_ROOT / "experiments" / "12b_render_zoom_sfx"
    with Run(experiment="12b_render_zoom_sfx", out_dir=exp_dir) as run:
        run.note(
            in_mp4=str(in_mp4.relative_to(REPO_ROOT)) if in_mp4.is_relative_to(REPO_ROOT) else str(in_mp4),
            out_mp4=str(out_mp4.relative_to(REPO_ROOT)) if out_mp4.is_relative_to(REPO_ROOT) else str(out_mp4),
            duration_in_s=info_in.duration_s,
            preset=args.preset,
            crf=args.crf,
        )
        run.metric("n_zooms", len(zooms))
        run.metric("n_sfx", len(sfx_edits))

        wall, meta = render_zoom_sfx(
            in_mp4, out_mp4, zooms, sfx_edits, args.preset, args.crf,
        )
        run.metric("ffmpeg_wall_s", round(wall, 3))
        run.note(**meta)

        info_out = probe(out_mp4)
        run.metric("out_duration_s", round(info_out.duration_s, 3))
        run.metric("out_size_mb", info_out.size_mb)
        run.metric(
            "duration_match_delta_s",
            round(info_out.duration_s - info_in.duration_s, 3),
        )
        run.metric(
            "render_rtf",
            round(info_in.duration_s / wall, 3) if wall > 0 else None,
        )
        print(f"[exp12b] OK  ffmpeg={wall:.2f}s  rtf={info_in.duration_s/wall:.2f}×  "
              f"out={info_out.duration_s:.2f}s size={info_out.size_mb}MB")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
