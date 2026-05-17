"""
Experiment 14 — Full end-to-end pipeline on a 5-min clip.

Chain everything we built into a single run:

  1. Phase 1 outputs are loaded from previous experiments (transcript,
     scenes, faces, audio analysis, vm7) — we don't re-run them since
     each one was independently validated in Exp 01-05/08.
  2. Phase 3 multi-pass brain produces an EDL (re-runs to keep this
     experiment self-contained against the current model state).
  3. Phase 4a: silence-trim + concat (Exp 12 logic).
  4. Phase 4b: remap caption timestamps from source-time to output-time
     (subtract the cumulative silence dropped before each caption's
     `from`). Generate ASS file with remapped times.
  5. Phase 4c: burn captions into the trimmed video.

Gate:
- All four stages complete without errors.
- Final output mp4 is playable.
- Final duration ≈ input - sum(remove_silence).
- Captions appear at correct timestamps in the final output (visually
  verified by frame extraction).
- End-to-end wall clock is in the right ballpark vs the doc's 7-min
  estimate for a 15-min video (we run on 5-min, expect ~2-3 min).

Run:
    python experiments/14_full_pipeline_5min/run.py \\
        --clip-stem raw_5min \\
        --clip samples/raw/raw_5min.mp4
"""

from __future__ import annotations

import argparse
import json
import os
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

# The exp dirs are named with leading digits so we can't import them
# directly as `experiments.10_brain_5min.run`. Load each as a module
# via importlib so we can call their functions.
import importlib.util


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


_brain = _load_module("brain10", REPO_ROOT / "experiments" / "10_brain_5min" / "run.py")
_multipass = _load_module("brain11", REPO_ROOT / "experiments" / "11_brain_30min" / "run.py")
_ffmpeg = _load_module("ffmpeg12", REPO_ROOT / "experiments" / "12_ffmpeg_edl" / "run.py")
_ass = _load_module("ass13", REPO_ROOT / "experiments" / "13_ass_captions" / "run.py")
_zoom_sfx = _load_module(
    "render12b", REPO_ROOT / "experiments" / "12b_render_zoom_sfx" / "run.py",
)


def _shift_src_to_output(t: float, drops: list[tuple[float, float]]) -> float:
    """Convert a single source-time `t` to output-time after silence-trim,
    accounting for `drops` (sorted, non-overlapping) preceding it. If `t`
    falls inside a drop, returns the drop's start in output time."""
    out = t
    for a, b in drops:
        if t <= a:
            break
        if t < b:
            # t is inside this drop — snap to drop start (in output time)
            out = a - sum(min(d2, a) - d1 for d1, d2 in drops if d1 < a)
            return max(0.0, out)
        out -= (b - a)
    return max(0.0, out)


def remap_at_times(
    events: list[dict],
    drop_ranges: list[tuple[float, float]],
    duration: float | None = None,
) -> list[dict]:
    """Remap edits with an `at` field (e.g., sfx) from source-time to
    output-time. Events whose `at` falls inside a drop range get snapped
    to the drop's start in output time."""
    drops = _ffmpeg.merge_ranges(drop_ranges)
    out: list[dict] = []
    for e in events:
        t = e.get("at")
        if not isinstance(t, (int, float)):
            continue
        new_at = _shift_src_to_output(float(t), drops)
        if duration is not None and new_at > duration:
            continue
        out.append({**e, "at": round(new_at, 3), "_src_at": t})
    return out


def remap_range_times(
    events: list[dict],
    drop_ranges: list[tuple[float, float]],
    duration: float | None = None,
) -> list[dict]:
    """Remap edits with `from` and `to` fields (e.g., zoom_in) from
    source-time to output-time. Same clip-to-drop-boundary logic as the
    caption remap but simpler since we just shift endpoints."""
    drops = _ffmpeg.merge_ranges(drop_ranges)
    out: list[dict] = []
    for e in events:
        f = e.get("from")
        to = e.get("to")
        if not isinstance(f, (int, float)) or not isinstance(to, (int, float)):
            continue
        if to <= f:
            continue
        new_f = _shift_src_to_output(float(f), drops)
        new_to = _shift_src_to_output(float(to), drops)
        if duration is not None:
            new_to = min(new_to, duration)
            new_f = min(new_f, duration)
        if new_to <= new_f + 0.05:  # collapsed to nothing
            continue
        out.append({
            **e,
            "from": round(new_f, 3),
            "to": round(new_to, 3),
            "_src_from": f,
            "_src_to": to,
        })
    return out


def remap_caption_times(
    captions: list[dict],
    drop_ranges: list[tuple[float, float]],
    trim_duration: float | None = None,
) -> list[dict]:
    """Shift caption (from, to) timestamps from source-time to output-time
    by subtracting the total silence dropped before each caption's `from`.

    A caption that falls entirely inside a dropped region is removed.
    A caption that straddles a drop boundary is clipped to the non-dropped
    portion.

    Bug-3 fix: `trim_duration` (the duration of the silence-trimmed
    output) is now a parameter. Any remapped `to` past that is clipped
    rather than left for the ASS writer to silently drop. Without this,
    a caption whose source `to` extends into a drop range that comes
    after the caption's `from` could end up with a remapped `to` larger
    than `trim_duration`, and the ASS writer would reject it.
    """
    drops = _ffmpeg.merge_ranges(drop_ranges)
    remapped: list[dict] = []
    for c in captions:
        f = c.get("from")
        to = c.get("to")
        if not isinstance(f, (int, float)) or not isinstance(to, (int, float)):
            continue
        if to <= f:
            continue
        # Compute cumulative drop before each timestamp + check overlap
        new_f = f
        new_to = to
        for (a, b) in drops:
            if to <= a:
                break
            if new_to <= a:
                break
            if f >= b:
                # caption is entirely after this drop — shift both by (b-a)
                shift = b - a
                new_f -= shift
                new_to -= shift
                continue
            if to <= b and f >= a:
                # caption is entirely inside a drop — skip
                new_f = new_to = -1
                break
            if f >= a and f < b:
                # caption starts inside the drop — clip its start to b
                f_clip = b
                new_f = f_clip - sum(min(d2, f_clip) - d1 for d1, d2 in drops if d1 < f_clip)
                # new_to recomputed via the per-segment shift logic by
                # re-running on the clipped value:
                new_to = to - sum(min(d2, to) - d1 for d1, d2 in drops if d1 < to)
                break
            if to > a and to <= b and f < a:
                # caption ends inside the drop — clip its end to a
                new_to = a - sum(min(d2, a) - d1 for d1, d2 in drops if d1 < a)
                new_f = f - sum(min(d2, f) - d1 for d1, d2 in drops if d1 < f)
                break
            if f < a and to > b:
                # caption straddles the drop — emit two segments? for
                # simplicity, clip to the pre-drop portion.
                new_to = a - sum(min(d2, a) - d1 for d1, d2 in drops if d1 < a)
                new_f = f - sum(min(d2, f) - d1 for d1, d2 in drops if d1 < f)
                break
        if new_f < 0 or new_to <= new_f:
            continue
        # Defensively clip both endpoints to [0, trim_duration].
        new_f = max(0.0, new_f)
        if trim_duration is not None:
            new_to = min(new_to, trim_duration)
            new_f = min(new_f, trim_duration)
        if new_to <= new_f:
            continue
        remapped.append({
            **c,
            "from": round(new_f, 3),
            "to": round(new_to, 3),
            "_src_from": f,
            "_src_to": to,
        })
    return remapped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip-stem", default="raw_5min")
    ap.add_argument("--clip", default="samples/raw/raw_5min.mp4")
    ap.add_argument("--model", default=os.environ.get(
        "BRAIN_MODEL", "google/gemini-2.5-flash-lite"))
    ap.add_argument("--preset", default="fast")
    ap.add_argument("--crf", type=int, default=23)
    ap.add_argument("--use-cached-edl", default=None,
                    help="path to an existing EDL JSON; skip the brain step")
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key and not args.use_cached_edl:
        print("ERROR: OPENROUTER_API_KEY not set (and no --use-cached-edl)", file=sys.stderr)
        return 2

    clip_path = (REPO_ROOT / args.clip).resolve()
    if not clip_path.exists():
        print(f"ERROR: clip missing: {clip_path}", file=sys.stderr)
        return 2

    info = probe(clip_path)
    print(f"[exp14] clip={clip_path.name}  dur={info.duration_s:.1f}s")

    out_dir = REPO_ROOT / "outputs" / "14_full_pipeline_5min"
    out_dir.mkdir(parents=True, exist_ok=True)
    edl_path = out_dir / "edl.json"
    trimmed_mp4 = out_dir / f"{clip_path.stem}_trimmed.mp4"
    final_mp4 = out_dir / f"{clip_path.stem}_final.mp4"
    ass_path = out_dir / f"{clip_path.stem}_remapped.ass"
    fc_path = out_dir / f"{clip_path.stem}_fc.txt"

    exp_dir = REPO_ROOT / "experiments" / "14_full_pipeline_5min"

    with Run(experiment="14_full_pipeline_5min", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            duration_in_s=info.duration_s,
            resolution=f"{info.width}x{info.height}",
            fps=info.fps,
            brain_model=args.model,
            preset=args.preset,
            crf=args.crf,
        )

        # =====================================================================
        # Stage 1: load Phase 1+2 outputs (already produced in earlier exps)
        # =====================================================================
        t_stage1_start = time.perf_counter()
        inputs = _brain.load_inputs(args.clip_stem)
        run.metric("stage1_load_inputs_s", round(time.perf_counter() - t_stage1_start, 3))
        run.metric("n_words", len(inputs["words"]))
        run.metric("n_scenes", len(inputs["scenes"]))
        run.metric("vm7_segments", len(inputs["vm7"].get("segments") or []))
        print(f"[exp14] loaded inputs: words={len(inputs['words'])} "
              f"scenes={len(inputs['scenes'])} vm7={len(inputs['vm7'].get('segments') or [])}")

        # =====================================================================
        # Stage 2: brain — multi-pass EDL
        # =====================================================================
        t_brain_start = time.perf_counter()
        if args.use_cached_edl:
            edl = json.loads((REPO_ROOT / args.use_cached_edl).read_text())
            brain_cost = 0.0
            brain_latency = 0.0
            print(f"[exp14] using cached EDL from {args.use_cached_edl}")
        else:
            merged_edits, summary, brain_latency = _multipass.run_multi_pass(
                inputs, args.model, api_key,
            )
            edl = {"edits": merged_edits}
            brain_cost = summary["total_cost_usd"]
        edl_path.write_text(json.dumps(edl, indent=2))
        run.metric("stage2_brain_s", round(time.perf_counter() - t_brain_start, 3))
        run.metric("brain_cost_usd", round(brain_cost, 6))
        edit_counts = _ffmpeg.edl_summarize(edl)
        run.metric("edit_type_counts", edit_counts)
        run.metric("n_edits_total", sum(edit_counts.values()))
        print(f"[exp14] brain done: cost=${brain_cost:.5f} edits={edit_counts}")

        # =====================================================================
        # Stage 3: silence-trim render (Exp 12 logic)
        # =====================================================================
        t_trim_start = time.perf_counter()
        drop_ranges: list[tuple[float, float]] = []
        captions: list[dict] = []
        zoom_edits: list[dict] = []
        sfx_edits: list[dict] = []
        for e in edl.get("edits", []):
            t = e.get("type")
            if t == "remove_silence":
                f, to = e.get("from"), e.get("to")
                if isinstance(f, (int, float)) and isinstance(to, (int, float)) and to > f:
                    drop_ranges.append((float(f), float(to)))
            elif t == "caption":
                captions.append(e)
            elif t == "zoom_in":
                zoom_edits.append(e)
            elif t == "sfx":
                sfx_edits.append(e)

        kept = _ffmpeg.compute_kept_ranges(info.duration_s, drop_ranges)
        total_dropped = sum(b - a for a, b in _ffmpeg.merge_ranges(drop_ranges))
        expected_trim_dur = info.duration_s - total_dropped
        run.metric("total_dropped_s", round(total_dropped, 3))
        run.metric("kept_ranges", len(kept))
        run.metric("expected_trim_dur_s", round(expected_trim_dur, 3))

        if not kept:
            print("ERROR: EDL drops entire clip", file=sys.stderr)
            return 4

        fc = _ffmpeg.build_filter_complex(kept)
        fc_path.write_text(fc)
        cmd_trim = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(clip_path),
            "-filter_complex_script", str(fc_path),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(trimmed_mp4),
        ]
        r = subprocess.run(cmd_trim, capture_output=True, text=True)
        trim_s = time.perf_counter() - t_trim_start
        run.metric("stage3_trim_s", round(trim_s, 3))
        if r.returncode != 0:
            run.note(trim_stderr=r.stderr[:2000])
            print(f"[exp14] trim render FAILED rc={r.returncode}")
            print(r.stderr[-1500:])
            return 5
        trim_info = probe(trimmed_mp4)
        run.metric("trim_out_dur_s", round(trim_info.duration_s, 3))
        run.metric("trim_delta_s", round(trim_info.duration_s - expected_trim_dur, 3))
        run.metric(
            "stage3_render_rtf",
            round(info.duration_s / trim_s, 3) if trim_s > 0 else None,
        )
        print(f"[exp14] trim render: {trim_s:.2f}s  out_dur={trim_info.duration_s:.2f}s "
              f"(expected {expected_trim_dur:.2f})")

        # =====================================================================
        # Stage 4a: remap caption timestamps to trimmed output-time
        # =====================================================================
        remapped = remap_caption_times(
            captions, drop_ranges, trim_duration=trim_info.duration_s,
        )
        run.metric("captions_in_edl", len(captions))
        run.metric("captions_after_remap", len(remapped))

        # =====================================================================
        # Stage 4b: write ASS + burn captions
        # =====================================================================
        # Load the VM-4 style spec for this clip's reference (if available)
        # and build a customized ASS header. Falls back to the hardcoded
        # default when no Exp 07 output exists.
        vm4_metrics_path = (
            REPO_ROOT / "experiments" / "07_vm4_caption_style"
            / "metrics_talking_head.json"
        )
        # Use the talking-head variant if running on that clip, otherwise
        # the canonical metrics.json from Exp 07.
        if args.clip_stem == "raw_talking_5min" and vm4_metrics_path.exists():
            vm4_metrics = json.loads(vm4_metrics_path.read_text())
        else:
            vm4_metrics = json.loads(
                (REPO_ROOT / "experiments" / "07_vm4_caption_style" / "metrics.json").read_text()
            )
        vm4_style = (vm4_metrics.get("metrics", {}) or {}).get("aggregated_style")
        run.note(vm4_style=vm4_style)
        header = _ass.build_ass_header_from_style(vm4_style)

        # Use karaoke (per-word) captions when WhisperX words are available.
        words = inputs.get("words") or []
        t_cap_start = time.perf_counter()
        if words:
            n_ass = _ass.edl_to_ass_karaoke(
                remapped, words, ass_path, trim_info.duration_s,
                header=header,
            )
            run.metric("ass_style", "karaoke_per_word")
        else:
            n_ass = _ass.edl_to_ass(
                remapped, ass_path, trim_info.duration_s, header=header,
            )
            run.metric("ass_style", "static")
        run.metric("ass_events_written", n_ass)
        run.metric("ass_file_size_bytes", ass_path.stat().st_size)

        cmd_cap = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(trimmed_mp4),
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(final_mp4),
        ]
        r = subprocess.run(cmd_cap, capture_output=True, text=True)
        cap_s = time.perf_counter() - t_cap_start
        run.metric("stage4_caption_s", round(cap_s, 3))
        if r.returncode != 0:
            run.note(caption_stderr=r.stderr[:2000])
            print(f"[exp14] caption burn FAILED rc={r.returncode}")
            print(r.stderr[-1500:])
            return 6
        final_info = probe(final_mp4)
        run.metric("final_out_dur_s", round(final_info.duration_s, 3))
        run.metric("final_out_size_mb", final_info.size_mb)

        # The captioned mp4 is the input to Stage 5 (zoom + sfx). After
        # Stage 5 finishes we overwrite `final_mp4` with the fully rendered
        # version. Keep the intermediate alongside for debugging.
        captioned_mp4 = out_dir / f"{clip_path.stem}_captioned.mp4"
        # Rename the captioned output we just made; we'll write the
        # fully-rendered final on top.
        if captioned_mp4.exists():
            captioned_mp4.unlink()
        final_mp4.rename(captioned_mp4)

        # =====================================================================
        # Stage 5: animated zoom + sfx overlay (Exp 12b)
        # =====================================================================
        t_stage5_start = time.perf_counter()
        # Remap zoom + sfx timestamps from source-time to output-time
        remapped_zooms = remap_range_times(
            zoom_edits, drop_ranges, duration=trim_info.duration_s,
        )
        remapped_sfx = remap_at_times(
            sfx_edits, drop_ranges, duration=trim_info.duration_s,
        )
        run.metric("zoom_edits_in_edl", len(zoom_edits))
        run.metric("zoom_edits_after_remap", len(remapped_zooms))
        run.metric("sfx_edits_in_edl", len(sfx_edits))
        run.metric("sfx_edits_after_remap", len(remapped_sfx))

        # Load face data so zoom crops can center on the speaker's face.
        face_data_path = (REPO_ROOT / "outputs" / "03_mediapipe_face" /
                          f"{args.clip_stem}_faces.json")
        face_data = None
        if face_data_path.exists():
            face_data = json.loads(face_data_path.read_text())
            run.metric("face_data_samples", len(face_data.get("sample_every_30_frames", [])))

        if remapped_zooms or remapped_sfx:
            try:
                z_wall, z_meta = _zoom_sfx.render_zoom_sfx(
                    captioned_mp4, final_mp4,
                    remapped_zooms, remapped_sfx,
                    args.preset, args.crf,
                    face_data=face_data,
                )
                run.note(stage5_meta=z_meta)
            except RuntimeError as e:
                run.note(stage5_error=str(e)[:1500])
                print(f"[exp14] Stage 5 FAILED: {e}")
                # Fall back: captioned mp4 is the final output
                captioned_mp4.rename(final_mp4)
                z_wall = 0.0
        else:
            # Nothing to do — captioned mp4 IS the final output
            captioned_mp4.rename(final_mp4)
            z_wall = 0.0

        stage5_s = time.perf_counter() - t_stage5_start
        run.metric("stage5_zoom_sfx_s", round(stage5_s, 3))
        run.metric("stage5_ffmpeg_wall_s", round(z_wall, 3))

        # Re-probe (final_mp4 may now be the zoom+sfx render)
        final_info = probe(final_mp4)
        run.metric("final_out_dur_s", round(final_info.duration_s, 3))
        run.metric("final_out_size_mb", final_info.size_mb)

        # Sample frame at middle of a remapped caption
        if remapped:
            mid = remapped[len(remapped) // 2]
            t_check = (mid["from"] + mid["to"]) / 2.0
            check_frame = out_dir / "final_sample_frame.jpg"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-ss", f"{t_check:.3f}", "-i", str(final_mp4),
                 "-frames:v", "1", "-q:v", "3", str(check_frame)],
                check=True,
            )
            run.metric("sample_frame_t_s", round(t_check, 3))
            run.metric("sample_caption_text", mid.get("text", "")[:120])

        # =====================================================================
        # Summary
        # =====================================================================
        total_pipeline_s = (
            run._metrics.get("stage1_load_inputs_s", 0)
            + run._metrics.get("stage2_brain_s", 0)
            + run._metrics.get("stage3_trim_s", 0)
            + run._metrics.get("stage4_caption_s", 0)
            + run._metrics.get("stage5_zoom_sfx_s", 0)
        )
        run.metric("pipeline_wall_s", round(total_pipeline_s, 3))
        run.metric(
            "pipeline_rtf",
            round(info.duration_s / total_pipeline_s, 3) if total_pipeline_s > 0 else None,
        )

        print()
        print(f"[exp14] === SUMMARY ===")
        print(f"  Stage 1 (load inputs):      {run._metrics['stage1_load_inputs_s']}s")
        print(f"  Stage 2 (brain multi-pass): {run._metrics['stage2_brain_s']}s  (${brain_cost:.5f})")
        print(f"  Stage 3 (silence-trim):     {run._metrics['stage3_trim_s']}s")
        print(f"  Stage 4 (captions):         {run._metrics['stage4_caption_s']}s")
        print(f"  Stage 5 (zoom+sfx):         {run._metrics['stage5_zoom_sfx_s']}s")
        print(f"  TOTAL pipeline wall:        {total_pipeline_s:.2f}s")
        print(f"  Pipeline RTF:               {info.duration_s/total_pipeline_s:.2f}×")
        print(f"  Final output:               {final_info.duration_s:.2f}s, "
              f"{final_info.size_mb}MB")
        print(f"  Captions after remap:       {len(remapped)}/{len(captions)}")
        print(f"  Zooms applied:              {len(remapped_zooms)}/{len(zoom_edits)}")
        print(f"  SFX applied:                {len(remapped_sfx)}/{len(sfx_edits)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
