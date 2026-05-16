# Context for Claude Code (project-level)

You are continuing a project that was started on a Windows laptop and now
runs on this Ubuntu VPS. The plan below was already agreed with the user.
Read [`docs/product.md`](docs/product.md) and [`docs/vps_specs.md`](docs/vps_specs.md)
before any non-trivial work — they hold the product spec and the binding
hardware reality.

## What we are doing

**Not yet:** building the SaaS product, web UI, auth, billing, or queue
infrastructure.
**Right now:** running 16 small, gated experiments that empirically verify
every assumption in [`docs/product.md`](docs/product.md) against this VPS,
producing a final synthesis in `docs/FINDINGS.md` that the eventual product
build will reference.

Index of all 16: [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md). Each phase
has a written GO/NO-GO exit gate; do not advance to the next phase if a
gate fails — surface it to the user and replan.

## Hardware reality (don't forget this)

- AMD Ryzen 5 3600 — 6 physical / 12 logical cores. **No AVX-512.**
- 64 GB RAM, 32 GB swap (flush stale swap before heavy runs).
- 2× NVMe SSDs in software RAID (≈760 MB/s sequential write).
- **CPU-only.** GT 710 is present but unusable for ML. The user is not
  renting GPU. Plan around this — WhisperX large-v2 int8 runs at
  ~0.4–0.6× realtime here.
- Shared multi-user box. Long jobs can be distorted by other users.
  `metrics.json` records system fingerprint at start so we can spot it.

Full audit: [`docs/vps_specs.md`](docs/vps_specs.md).

## Working agreements

1. **Stack:** Python 3.11 venv at `~/.venvs/videdit`. Plain scripts, no notebooks.
2. **Env flags every worker should set:** `OMP_NUM_THREADS=4`,
   `CT2_USE_EXPERIMENTAL_PACKED_GEMM=1`. Already in `.env.example`.
3. **Concurrency:** 1 worker at a time during measurement runs (so numbers
   are clean). 2-worker contention is its own experiment (Exp 15).
4. **Every experiment uses `experiments._shared.instrument.Run`** as a
   context manager. It writes `metrics.json` automatically — never roll
   your own timing.
5. **Every experiment produces `results.md`** from
   `experiments/_shared/results_template.md`, with an explicit
   PASS/FAIL/PARTIAL verdict against the gate from the plan.
6. **No new file types committed without first updating `.gitignore`.**
   The repo is public — sample videos, model files, API keys, transcripts
   of real people's footage all stay out.
7. **Bulky artifacts → `outputs/NN_xxx/`** (gitignored). Only `metrics.json`
   and `results.md` are committed.

## When you finish an experiment

1. Write `experiments/NN_xxx/results.md` against the gate.
2. Update the row in [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) (status →
   done, fill in verdict link).
3. Commit only `metrics.json`, `results.md`, the updated `EXPERIMENTS.md`,
   and any code changes to `run.py`. Push.

## How to talk to the user

- The user is a builder, fast-moving, prefers verified facts over guesses.
- They wrote this VPS audit themselves and care about cost / margins
  ([`docs/product.md`](docs/product.md) lines 533–656). When a measured
  number breaks an assumption in the doc, say so plainly and with the
  delta — don't soften it.
- Ask before doing anything destructive on the VPS (deleting outputs,
  resetting venv, etc.). Ask before pushing commits the user didn't
  request.
- When proposing the next experiment, restate the gate first.

## What's NOT in scope for the experimentation phase

- Product UI, auth, billing, queue, workers, deployment.
- VM-2, VM-3, VM-5, VM-6 (zoom-purpose, b-roll-class, color-grade,
  style-summary) — deferred to "round 2" after Phase 6 synthesis says
  they're needed for MVP.
- Solving 2-hour-video latency on CPU. Phase 6 will surface the right
  recommendation (likely: rent GPU for Whisper step only).

## Useful entry points

- Plan exit gates per experiment: see each phase section in
  [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md).
- Instrumentation contract: docstring at the top of
  [`experiments/_shared/instrument.py`](experiments/_shared/instrument.py).
- Sample-data layout, run workflow, VPS bootstrap: [`README.md`](README.md).
