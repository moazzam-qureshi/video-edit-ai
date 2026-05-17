"""
Experiment 15 — 2-worker concurrency stress test.

The product plan caps concurrent workers at 2 because the audit
predicted that 3 workers would thrash cache + threads and slow each job
~40%. This experiment measures the *actual* per-worker slowdown when
two WhisperX transcriptions run concurrently — the real-world CPU
contention scenario, since Whisper is the long pole.

Worker isolation: each worker runs as a fresh `subprocess.Popen` of a
small whisperx-worker script. ProcessPoolExecutor's default fork() is
incompatible with WhisperX (libtorch initializes background threads at
import; fork copies broken thread state → BrokenProcessPool). Fresh
subprocesses avoid the entire problem.

We compare:
  - **Baseline**: one WhisperX transcription of raw_5min — fresh.
  - **2-worker**: two WhisperX transcriptions of raw_5min running
    simultaneously. Measure per-worker wall clock and RTF.

Gate:
- 2-worker per-job slowdown ≤ 40% (per-worker RTF ≥ 0.6× baseline).
- Both workers complete successfully.
- Aggregate throughput at least 1× baseline (else concurrency is a
  regression).

Run:
    python experiments/15_pipeline_concurrency/run.py
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


WORKER_SCRIPT = REPO_ROOT / "experiments" / "15_pipeline_concurrency" / "_worker.py"


def run_whisperx_worker_subprocess(
    worker_id: int, clip: str, model: str, compute_type: str, language: str,
    output_json: Path,
) -> subprocess.Popen:
    """Launch a fresh Python subprocess that does the WhisperX work.
    Returns the Popen handle for the caller to wait on."""
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "4"
    env["CT2_USE_EXPERIMENTAL_PACKED_GEMM"] = "1"
    cmd = [
        sys.executable, str(WORKER_SCRIPT),
        "--worker-id", str(worker_id),
        "--clip", clip,
        "--model", model,
        "--compute-type", compute_type,
        "--language", language,
        "--output-json", str(output_json),
    ]
    return subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)


def wait_and_collect(p: subprocess.Popen, output_json: Path) -> dict:
    out, err = p.communicate()
    if p.returncode != 0:
        return {"worker_id": -1, "error": f"rc={p.returncode}",
                "stderr": err.decode("utf-8", errors="replace")[-1500:]}
    try:
        return json.loads(output_json.read_text())
    except Exception as e:
        return {"worker_id": -1, "error": f"output read failed: {e}",
                "stdout": out.decode("utf-8", errors="replace")[-500:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="samples/raw/raw_5min.mp4")
    ap.add_argument("--model", default="large-v2")
    ap.add_argument("--compute_type", default="int8")
    ap.add_argument("--language", default="en")
    ap.add_argument("--baseline", action="store_true",
                    help="run a 1-worker baseline first; default true")
    ap.add_argument("--no-baseline", dest="baseline", action="store_false")
    ap.set_defaults(baseline=True)
    args = ap.parse_args()

    clip_path = (REPO_ROOT / args.clip).resolve()
    info = probe(clip_path)
    print(f"[exp15] clip {clip_path.name} dur={info.duration_s:.1f}s")

    exp_dir = REPO_ROOT / "experiments" / "15_pipeline_concurrency"
    with Run(experiment="15_pipeline_concurrency", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            duration_s=info.duration_s,
            model=args.model,
            compute_type=args.compute_type,
        )

        out_dir = REPO_ROOT / "outputs" / "15_pipeline_concurrency"
        out_dir.mkdir(parents=True, exist_ok=True)

        baseline = None
        if args.baseline:
            print(f"[exp15] === 1-worker baseline ===")
            output_json = out_dir / "baseline.json"
            p = run_whisperx_worker_subprocess(
                0, args.clip, args.model, args.compute_type,
                args.language, output_json,
            )
            baseline = wait_and_collect(p, output_json)
            print(f"[exp15] baseline: {baseline}")
            if "error" in baseline:
                return 5
            run.metric("baseline_total_s", baseline["total_s"])
            run.metric("baseline_transcribe_s", baseline["transcribe_s"])
            run.metric("baseline_rtf_transcribe", baseline["rtf_transcribe"])
            run.metric("baseline_n_segments", baseline["n_segments"])

        print(f"[exp15] === 2-worker concurrent (subprocess isolation) ===")
        out_jsons = [out_dir / f"worker{i}.json" for i in range(2)]
        t_concurrent_start = time.perf_counter()
        procs = [
            run_whisperx_worker_subprocess(
                i, args.clip, args.model, args.compute_type,
                args.language, out_jsons[i],
            )
            for i in range(2)
        ]
        results = [wait_and_collect(p, j) for p, j in zip(procs, out_jsons)]
        concurrent_wall = time.perf_counter() - t_concurrent_start
        for r in results:
            print(f"[exp15] worker done: {r}")
        if any("error" in r for r in results):
            return 6

        run.metric("concurrent_wall_s", round(concurrent_wall, 3))
        for r in results:
            run.metric(f"worker{r['worker_id']}_total_s", r["total_s"])
            run.metric(f"worker{r['worker_id']}_transcribe_s", r["transcribe_s"])
            run.metric(f"worker{r['worker_id']}_rtf_transcribe", r["rtf_transcribe"])

        if baseline:
            mean_concurrent_rtf = sum(r["rtf_transcribe"] for r in results) / 2
            slowdown_pct = round(
                (1 - mean_concurrent_rtf / baseline["rtf_transcribe"]) * 100, 1,
            )
            aggregate_throughput = (2 * info.duration_s) / concurrent_wall
            baseline_throughput = info.duration_s / baseline["total_s"]
            speedup_aggregate = round(aggregate_throughput / baseline_throughput, 3)

            run.metric("mean_concurrent_rtf_transcribe", round(mean_concurrent_rtf, 3))
            run.metric("per_worker_slowdown_pct", slowdown_pct)
            run.metric("aggregate_throughput_speedup", speedup_aggregate)

            print()
            print(f"[exp15] === SUMMARY ===")
            print(f"  Baseline (1 worker)         RTF (transcribe) = {baseline['rtf_transcribe']}")
            print(f"  Concurrent (2 workers) mean RTF (transcribe) = {mean_concurrent_rtf:.3f}")
            print(f"  Per-worker slowdown:          {slowdown_pct}%")
            print(f"  Aggregate throughput speedup: {speedup_aggregate}× over 1-worker")
            print(f"  Gate: per-worker slowdown ≤ 40%? "
                  f"{'PASS' if slowdown_pct <= 40 else 'FAIL'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
