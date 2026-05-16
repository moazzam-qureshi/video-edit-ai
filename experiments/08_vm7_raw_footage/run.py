"""
Experiment 08 — VM-7 Raw Footage Visual Analysis.

Goal: for a "raw" video, sample frames at low fps (one every 5–10 s) and
ask the model what's happening in each. The brain stage uses this to
decide where to cut, where to zoom, where to speed up.

Per product.md §VM-7, output categories include:
  demo, story, reading_notes, joke_setup, joke_punchline,
  low_energy_tangent, talking_head, screen_recording, b_roll

Gate (from product.md §VM-7):
- Cost ≤ $0.05 for a 5-min video at this sampling rate.
- Parse success ≥ 90%.
- Output is non-trivially varied (not all same category) on a varied clip.
- Output schema includes a "should_cut" / "should_zoom" hint actionable
  by the brain (we'll ask the model directly).

Model: Tier 1 bulk classification (Qwen3-VL-8B-Instruct).

Run:
    python experiments/08_vm7_raw_footage/run.py \
        --clip samples/raw/raw_5min.mp4 \
        --sample-every-s 5
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

from experiments._shared.instrument import Run  # noqa: E402
from experiments._shared.sample_video import extract_frame_at, probe  # noqa: E402

import httpx  # noqa: E402

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

CATEGORIES = [
    "talking_head",
    "screen_recording",
    "b_roll",
    "demo",
    "reading_notes",
    "low_energy_tangent",
    "joke_setup_or_punchline",
    "other",
]

PROMPT = (
    "You are analyzing a single video frame from raw creator footage.\n"
    "Classify what's happening in this frame and give the brain editor\n"
    "two actionable hints. Categories:\n"
    f"  {', '.join(CATEGORIES)}\n"
    "\n"
    "Respond with ONLY a JSON object:\n"
    "{\n"
    '  "category": "<one_of_above>",\n'
    '  "should_cut_here": <true|false>,\n'
    '  "zoom_hint": "none|tight|medium|wide",\n'
    '  "rationale": "<one short sentence>"\n'
    "}\n"
)


def b64_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def call_model(model: str, frame: Path, api_key: str) -> tuple[dict, dict]:
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64_image(frame)}"}},
            ],
        }],
        "max_tokens": 200,
        "temperature": 0.0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/moazzam-qureshi/video-edit-ai",
        "X-Title": "video-edit-ai-experiments",
        "Content-Type": "application/json",
    }
    resp = httpx.post(ENDPOINT, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.split("```", 2)[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip().rstrip("`").strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"category": "PARSE_ERROR", "_raw": content[:200]}
    return parsed, data.get("usage", {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--sample-every-s", type=float, default=5.0)
    ap.add_argument("--model", default=os.environ.get(
        "VISION_MODEL_FLASH", "qwen/qwen3-vl-8b-instruct"))
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    clip_path = (REPO_ROOT / args.clip).resolve()
    info = probe(clip_path)
    n_samples = int(info.duration_s / args.sample_every_s)
    print(f"[exp08] clip {clip_path.name}  dur={info.duration_s:.1f}s  "
          f"sample_every={args.sample_every_s}s  n={n_samples}  "
          f"model={args.model}")

    times = [args.sample_every_s * (i + 0.5) for i in range(n_samples)]
    frames_dir = REPO_ROOT / "outputs" / "08_vm7_raw_footage" / clip_path.stem / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    exp_dir = REPO_ROOT / "experiments" / "08_vm7_raw_footage"
    with Run(experiment="08_vm7_raw_footage", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            duration_s=info.duration_s,
            sample_every_s=args.sample_every_s,
            n_samples=n_samples,
            model=args.model,
        )

        results = []
        total_cost = 0.0
        parse_ok = 0
        total_prompt_tok = 0
        total_completion_tok = 0
        cat_counts: dict[str, int] = {}
        cut_yes = 0
        zoom_counts: dict[str, int] = {}

        for i, t in enumerate(times):
            fp = frames_dir / f"frame_{i:03d}_t{t:.1f}.jpg"
            extract_frame_at(clip_path, t, fp, max_width=512, quality=4)
            try:
                parsed, usage = call_model(args.model, fp, api_key)
            except httpx.HTTPError as e:
                run.note(http_error=f"frame {i}: {type(e).__name__}: {e}")
                continue

            cost = float(usage.get("cost") or 0)
            total_cost += cost
            total_prompt_tok += int(usage.get("prompt_tokens", 0))
            total_completion_tok += int(usage.get("completion_tokens", 0))

            cat = parsed.get("category", "MISSING")
            if cat in CATEGORIES:
                parse_ok += 1
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
                if parsed.get("should_cut_here") is True:
                    cut_yes += 1
                zh = parsed.get("zoom_hint")
                if zh:
                    zoom_counts[zh] = zoom_counts.get(zh, 0) + 1

            results.append({
                "frame_idx": i,
                "t": round(t, 2),
                "frame_path": str(fp.relative_to(REPO_ROOT)),
                "result": parsed,
                "cost_usd": cost,
            })

        n = len(results) or 1
        run.metric("n_frames", n)
        run.metric("parse_success_rate", round(parse_ok / n, 3))
        run.metric("total_cost_usd", round(total_cost, 6))
        run.metric("avg_cost_per_frame_usd", round(total_cost / n, 6))
        run.metric("total_prompt_tokens", total_prompt_tok)
        run.metric("total_completion_tokens", total_completion_tok)
        run.metric("category_distribution", cat_counts)
        run.metric("zoom_hint_distribution", zoom_counts)
        run.metric("frames_with_cut_hint", cut_yes)
        run.metric(
            "cut_hint_rate", round(cut_yes / n, 3) if n else None,
        )

        # Project to 15-min video
        projected_n = int((15 * 60.0) / args.sample_every_s)
        run.metric(
            "projected_cost_15min_video_usd",
            round((total_cost / n) * projected_n, 4),
        )

        out_json = (REPO_ROOT / "outputs" / "08_vm7_raw_footage" /
                    f"{clip_path.stem}_vm7.json")
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps({
            "clip": str(clip_path.relative_to(REPO_ROOT)),
            "model": args.model,
            "sample_every_s": args.sample_every_s,
            "total_cost_usd": total_cost,
            "category_distribution": cat_counts,
            "results": results,
        }, indent=2))
        run.metric("output", str(out_json.relative_to(REPO_ROOT)))

        print(f"[exp08] {n} frames | parse={parse_ok} | cost ${total_cost:.4f} "
              f"| cats={cat_counts} | cut_hint={cut_yes}/{n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
