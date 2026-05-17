"""
Experiment 16 — Length-tier validation.

Goal: collect a "next-tier" empirical datapoint (full pipeline on the
11.4-min clip) and combine with Exp 14's 5-min datapoint to build the
length-vs-cost-vs-time table that Phase 6 will publish in FINDINGS.

The doc's pricing tiers (product.md lines 633–639):
- Starter:  ≤ 15 min, 10 videos/mo, $29/mo
- Creator:  ≤ 30 min, 30 videos/mo, $59/mo
- Pro:      ≤ 60 min, unlimited,    $99/mo
- Studio:   ≤ 3 hr,   unlimited,    $199/mo

What we're measuring:
- End-to-end pipeline wall clock for raw_15min (11.4 min input).
  Stages 2–4 (cached Phase 1+2 inputs); add Phase 1 cold-start later
  from Exp 01.
- Per-tier projections by linear scaling from our two empirical points
  (5 min, 11.4 min). Linear is the right model because every Phase 1
  stage we measured scales linearly with input duration.

Gate (per CLAUDE.md):
- Pipeline runs on the 11.4-min input without errors.
- 11.4-min wall clock ≤ ~3× the 5-min wall clock (sanity check: would
  be ~2.3× if exactly linear; allow some headroom).
- Projected per-tier costs are within 3× of the doc's product.md tier
  costs.

Run:
    python experiments/16_length_tiers/run.py
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

# Reuse Exp 14's pipeline by importing its main() — but that's structured
# around a single clip. Easier: run Exp 14's script as a subprocess and
# parse its metrics.json afterward.

EXP14_SCRIPT = REPO_ROOT / "experiments" / "14_full_pipeline_5min" / "run.py"


def run_pipeline_on(clip: str, clip_stem: str, use_cached_edl: str | None = None) -> dict:
    """Invoke Exp 14's pipeline on the given clip; capture metrics.json
    after the run completes."""
    metrics_dst = REPO_ROOT / "experiments" / "14_full_pipeline_5min" / "metrics.json"
    metrics_backup = REPO_ROOT / "outputs" / "16_length_tiers" / f"e14_{clip_stem}_metrics.json"
    metrics_backup.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(EXP14_SCRIPT),
        "--clip-stem", clip_stem,
        "--clip", clip,
    ]
    if use_cached_edl:
        cmd.extend(["--use-cached-edl", use_cached_edl])

    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, text=True)
    total_wall = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(
            f"Exp 14 pipeline failed (rc={r.returncode}):\n{r.stderr[-2000:]}"
        )

    metrics = json.loads(metrics_dst.read_text())
    # Snapshot for our own record
    metrics_backup.write_text(metrics_dst.read_text())
    return {
        "clip_stem": clip_stem,
        "subprocess_wall_s": round(total_wall, 3),
        "metrics": metrics,
    }


def project_tier(
    duration_s: float,
    base_5min_s: float,
    base_11min_s: float,
    base_5min_brain_cost: float,
    base_11min_brain_cost: float,
) -> dict:
    """Linear projection from two datapoints. Independent fits for
    wall-clock and brain-cost; both scale near-linearly per Phase 3
    observation."""
    # Coefficients for y = mx + b through (300, base_5min_s) and (684.6, base_11min_s)
    x1, y1 = 300.0, base_5min_s
    x2, y2 = 684.64, base_11min_s
    m = (y2 - y1) / (x2 - x1)
    b = y1 - m * x1
    proj_wall = max(0.0, m * duration_s + b)

    c1, c2 = base_5min_brain_cost, base_11min_brain_cost
    mc = (c2 - c1) / (x2 - x1)
    bc = c1 - mc * x1
    proj_cost = max(0.0, mc * duration_s + bc)
    return {
        "duration_min": duration_s / 60.0,
        "projected_wall_s": round(proj_wall, 1),
        "projected_wall_min": round(proj_wall / 60.0, 2),
        "projected_brain_cost_usd": round(proj_cost, 5),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-11min", action="store_true", default=True,
                    help="run the 11.4-min pipeline to collect the second datapoint")
    ap.add_argument("--no-run-11min", dest="run_11min", action="store_false")
    args = ap.parse_args()

    exp_dir = REPO_ROOT / "experiments" / "16_length_tiers"
    out_dir = REPO_ROOT / "outputs" / "16_length_tiers"
    out_dir.mkdir(parents=True, exist_ok=True)

    with Run(experiment="16_length_tiers", out_dir=exp_dir) as run:
        # ---- Anchor: Exp 14's 5-min result, loaded from disk ----
        e14_metrics = json.loads(
            (REPO_ROOT / "experiments" / "14_full_pipeline_5min" / "metrics.json").read_text()
        )
        m5 = e14_metrics["metrics"]
        base_5min = {
            "duration_s": e14_metrics["notes"]["duration_in_s"],
            "stage2_brain_s": m5["stage2_brain_s"],
            "stage3_trim_s": m5["stage3_trim_s"],
            "stage4_caption_s": m5["stage4_caption_s"],
            "pipeline_wall_s": m5["pipeline_wall_s"],
            "brain_cost_usd": m5["brain_cost_usd"],
            "n_edits": m5["n_edits_total"],
        }
        run.note(
            anchor_5min=base_5min,
        )
        print(f"[exp16] Exp 14 anchor (5-min): wall={base_5min['pipeline_wall_s']}s "
              f"brain=${base_5min['brain_cost_usd']:.5f}")

        # ---- New datapoint: 11.4-min full pipeline ----
        # Phase 1+2 outputs for raw_15min already exist (we ran them in Exp 11
        # context). The pipeline can use them.
        if args.run_11min:
            print(f"[exp16] running full pipeline on raw_15min (11.4 min)…")
            r11 = run_pipeline_on(
                clip="samples/raw/raw_15min.mp4",
                clip_stem="raw_15min",
            )
            m11 = r11["metrics"]["metrics"]
            base_11min = {
                "duration_s": r11["metrics"]["notes"]["duration_in_s"],
                "stage2_brain_s": m11.get("stage2_brain_s"),
                "stage3_trim_s": m11.get("stage3_trim_s"),
                "stage4_caption_s": m11.get("stage4_caption_s"),
                "pipeline_wall_s": m11.get("pipeline_wall_s"),
                "brain_cost_usd": m11.get("brain_cost_usd"),
                "n_edits": m11.get("n_edits_total"),
            }
            run.note(datapoint_11min=base_11min)
            run.metric("subprocess_wall_11min_s", r11["subprocess_wall_s"])
            print(f"[exp16] 11.4-min datapoint: wall={base_11min['pipeline_wall_s']}s "
                  f"brain=${base_11min['brain_cost_usd']:.5f}")
        else:
            base_11min = None

        if base_11min is None:
            print("ERROR: no 11.4-min datapoint to fit projections", file=sys.stderr)
            return 5

        # ---- Linearity sanity check ----
        # Pipeline wall scales how fast vs input? (stages 2-4 only here.)
        wall_ratio = base_11min["pipeline_wall_s"] / base_5min["pipeline_wall_s"]
        dur_ratio = base_11min["duration_s"] / base_5min["duration_s"]
        run.metric("dur_ratio_11min_over_5min", round(dur_ratio, 3))
        run.metric("wall_ratio_11min_over_5min", round(wall_ratio, 3))
        run.metric("wall_super_or_sublinear", round(wall_ratio / dur_ratio, 3))
        print(f"[exp16] dur ratio = {dur_ratio:.2f}×, wall ratio = {wall_ratio:.2f}×, "
              f"super/sub-linearity = {wall_ratio/dur_ratio:.2f}× (1.0 = perfectly linear)")

        # ---- Projections to product tiers ----
        tiers = [
            ("Starter (15 min)", 15 * 60.0),
            ("Creator (30 min)", 30 * 60.0),
            ("Pro (60 min)", 60 * 60.0),
            ("Studio (3 hr)", 3 * 3600.0),
        ]
        projections = {}
        for name, dur_s in tiers:
            p = project_tier(
                dur_s,
                base_5min["pipeline_wall_s"],
                base_11min["pipeline_wall_s"],
                base_5min["brain_cost_usd"],
                base_11min["brain_cost_usd"],
            )
            projections[name] = p
            print(f"[exp16] {name}: ~{p['projected_wall_min']:.1f} min wall "
                  f"(stages 2-4), brain ${p['projected_brain_cost_usd']}")

        run.metric("projections_stages_2_to_4", projections)

        # ---- Cold E2E projections (add Phase 1) ----
        # Phase 1 cost per minute of input (sequential, from Exp 01–05 numbers):
        # Whisper 230s/5min = 46s/min  (Exp 01 5-min run)
        # Whisper (11.4-min) was 409s / 11.4 = 36s/min — better at scale due to
        # warm model load amortization. Use 40 s/min as a working mean.
        # Other Phase 1 components combined: ~14s for a 5-min clip = ~2.8 s/min.
        phase1_per_min_sequential = 40.0 + 2.8  # s of Phase 1 per minute of input
        # Parallel Phase 1 (3 workers concurrent, Whisper dominates the long pole):
        phase1_per_min_parallel = 40.0  # Whisper dominates; others run inside

        # Phase 2 cost per minute (Exp 06/08 calls):
        # Exp 08 on 11.4 min = $0.011 for VM-7 alone; Exp 06 ≈ $0.005 per 50 cuts.
        # 80 cuts/min × $0.0001/cut on Qwen3-VL-8B = ~$0.008/min
        phase2_per_min_usd = 0.008

        cold_projections = {}
        for name, dur_s in tiers:
            dur_min = dur_s / 60.0
            phase1_seq = phase1_per_min_sequential * dur_min
            phase1_par = phase1_per_min_parallel * dur_min
            phase23_wall = projections[name]["projected_wall_s"]
            phase2_cost = phase2_per_min_usd * dur_min
            brain_cost = projections[name]["projected_brain_cost_usd"]
            total_cost = phase2_cost + brain_cost
            cold_projections[name] = {
                "duration_min": dur_min,
                "phase1_seq_s": round(phase1_seq, 1),
                "phase1_par_s": round(phase1_par, 1),
                "phase2_3_4_wall_s": round(phase23_wall, 1),
                "cold_e2e_seq_min": round((phase1_seq + phase23_wall) / 60.0, 2),
                "cold_e2e_par_min": round((phase1_par + phase23_wall) / 60.0, 2),
                "phase2_cost_usd": round(phase2_cost, 5),
                "brain_cost_usd": brain_cost,
                "api_cost_total_usd": round(total_cost, 5),
            }
        run.metric("cold_e2e_projections", cold_projections)

        print()
        print(f"[exp16] === COLD END-TO-END PROJECTIONS (Phase 1 sequential vs parallel) ===")
        print(f"{'Tier':22s}  {'P1seq':>7s}  {'P1par':>7s}  {'P234':>7s}  "
              f"{'Cold-seq':>10s}  {'Cold-par':>10s}  {'API cost':>10s}")
        for name, c in cold_projections.items():
            print(f"{name:22s}  {c['phase1_seq_s']:7.1f}  {c['phase1_par_s']:7.1f}  "
                  f"{c['phase2_3_4_wall_s']:7.1f}  "
                  f"{c['cold_e2e_seq_min']:>9.2f}m  {c['cold_e2e_par_min']:>9.2f}m  "
                  f"${c['api_cost_total_usd']:>8.4f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
