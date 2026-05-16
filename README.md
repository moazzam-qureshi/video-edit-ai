# video-edit-ai — experimentation phase

We are not building product code yet. We are running 16 small experiments to
verify every assumption in [`docs/product.md`](docs/product.md) against the
hardware we actually have ([`docs/vps_specs.md`](docs/vps_specs.md)). Each
experiment passes or fails a written gate. The output is
[`docs/FINDINGS.md`](docs/FINDINGS.md), which becomes the source of truth for
the eventual product build.

The full plan is at `~/.claude/plans/d-personal-projects-video-edit-ai-docs-dynamic-rossum.md`
on the author's machine; the public-facing summary lives in the experiment
docs.

Status of every experiment: [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md).

## Where things run

| Step | Machine |
|---|---|
| Authoring scripts, docs, commits | Windows dev box |
| Running experiments (WhisperX, MediaPipe, FFmpeg) | Ryzen 5 3600 VPS, CPU-only |
| Calling vision/brain APIs | Either — they hit OpenRouter |

Experiment numbers in measurements only count if produced on the VPS — never
trust a wall-clock from the Windows dev box for a CPU-bound task.

## VPS bootstrap (run once)

```bash
# 1. System packages — ffmpeg is required by ~everything
sudo apt update
sudo apt install -y ffmpeg libsndfile1 libgl1 libglib2.0-0 python3.11 python3.11-venv python3.11-dev

# 2. Flush 8 GB of stale swap left over from a 93-day uptime (see vps_specs.md)
sudo swapoff -a && sudo swapon -a

# 3. Sanity: confirm ffmpeg + codecs
ffmpeg -version | head -1
ffmpeg -encoders 2>/dev/null | grep -E 'libx264|libx265|aac'

# 4. Clone & set up
git clone https://github.com/<owner>/video-edit-ai.git
cd video-edit-ai

python3.11 -m venv ~/.venvs/videdit
source ~/.venvs/videdit/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
# WhisperX is installed separately because it pins torch aggressively:
pip install git+https://github.com/m-bain/whisperx.git

# 5. Env
cp .env.example .env
# Edit .env: paste OPENROUTER_API_KEY etc.

# 6. Sanity: instrument self-test
python -m experiments._shared.instrument
# Expect: writes experiments/_shared/_selftest/metrics.json with wall_clock ~1s
```

## Sample data layout

Place your videos here. Both folders are gitignored (no media in the repo).

```
samples/
├── reference/         # videos in the target editing style
│   └── reference_youtube_creator.mp4
└── raw/               # raw talking-head footage to edit
    ├── raw_5min.mp4
    └── raw_15min.mp4
```

## Running an experiment

Each experiment is a self-contained folder under `experiments/`. Example:

```bash
cd ~/code/video-edit-ai
source ~/.venvs/videdit/bin/activate
python experiments/01_whisperx/run.py --help
```

Outputs:
- `experiments/NN_xxx/metrics.json` (auto-written by `_shared/instrument.Run`)
- `experiments/NN_xxx/results.md` (you fill this in by hand from the template)
- bulky artifacts (transcripts, frames, videos) → `outputs/NN_xxx/` (gitignored)

After each experiment, update its row in [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md).

## Workflow: Windows → GitHub → VPS

1. Author / edit scripts on Windows (this checkout)
2. `git commit && git push`
3. On VPS: `git pull && python experiments/NN_xxx/run.py`
4. Commit the resulting `metrics.json` and updated `results.md` from the VPS

`metrics.json` is small JSON — fine to commit. Sample videos and large
artifacts stay out (see `.gitignore`).
