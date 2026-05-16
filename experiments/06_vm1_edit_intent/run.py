"""
Experiment 06 — VM-1 Edit Intent Classification.

Goal: for each cut produced by Exp 02 (PySceneDetect), send a "before"
frame + "after" frame to a cheap vision model and ask it to classify
the cut INTENT, not just confirm it.

Five labels per product.md §VM-1:
  jump_cut, topic_transition, b_roll_insert, reaction_cut, cutaway

Gate (from product.md §VM-1 + this experiment's plan):
- Cost per 50-cut classification ≤ $0.05 (doc said $0.29 on GPT-4o,
  ~$0.005 on Qwen Flash — we use Qwen3-VL-8B-Instruct, the current
  cheap-tier successor).
- Model returns parseable JSON for ≥ 90% of cuts.
- Labels are non-trivially distributed (not all the same label) on a
  varied reference clip.

We process the reference clip — it has 308 cuts (Exp 02 measured it),
so we cap at the first N to keep cost predictable. Default: 30 cuts
(~$0.002 budget at $0.0001/call observed in smoke test).

Run:
    python experiments/06_vm1_edit_intent/run.py \
        --scenes outputs/02_pyscenedetect/reference_content_scenes.json \
        --clip samples/reference/reference.mp4 \
        --n-cuts 30
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

LABELS = [
    "jump_cut",  # same angle, time skip — pacing
    "topic_transition",  # new section/segment
    "b_roll_insert",  # screen recording, meme, image overlay, stock
    "reaction_cut",  # cut to face for emphasis
    "cutaway",  # product shot, demo, whiteboard
]

PROMPT = (
    "These are two consecutive video frames separated by a cut.\n"
    "Frame A is the LAST frame BEFORE the cut.\n"
    "Frame B is the FIRST frame AFTER the cut.\n"
    "Classify the editing INTENT of this cut. Pick exactly ONE label from:\n"
    f"  {', '.join(LABELS)}\n"
    "Definitions:\n"
    "  jump_cut: same angle/setting, time skipped for pacing.\n"
    "  topic_transition: clear shift to a new section/segment.\n"
    "  b_roll_insert: cuts INTO a screen recording, meme, image overlay,"
    " or stock footage.\n"
    "  reaction_cut: cut to a face/expression for emphasis.\n"
    "  cutaway: cut to a product, demo, whiteboard, or supporting visual.\n"
    "Respond with ONLY a JSON object: "
    '{"label": "<one_of_the_five>", "confidence": <0-1>, "rationale": "<one short sentence>"}'
)


def b64_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def call_model(model: str, frame_a: Path, frame_b: Path,
               api_key: str) -> tuple[dict, dict]:
    """Returns (parsed_classification, usage_dict)."""
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64_image(frame_a)}"}},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64_image(frame_b)}"}},
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
    # Models often emit ```json ... ``` fences — strip if present.
    if content.startswith("```"):
        content = content.split("```", 2)[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip().rstrip("`").strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"label": "PARSE_ERROR", "raw": content[:200]}
    return parsed, data.get("usage", {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", required=True,
                    help="path to PySceneDetect scenes JSON (from Exp 02)")
    ap.add_argument("--clip", required=True)
    ap.add_argument("--n-cuts", type=int, default=30)
    ap.add_argument("--model", default=os.environ.get(
        "VISION_MODEL_FLASH", "qwen/qwen3-vl-8b-instruct"))
    ap.add_argument("--frame-offset-s", type=float, default=0.1,
                    help="seconds before/after cut to grab frames at")
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    scenes_path = (REPO_ROOT / args.scenes).resolve()
    clip_path = (REPO_ROOT / args.clip).resolve()
    if not scenes_path.exists() or not clip_path.exists():
        print("ERROR: scenes or clip not found", file=sys.stderr)
        return 2

    scenes = json.loads(scenes_path.read_text())
    info = probe(clip_path)
    print(f"[exp06] clip {clip_path.name}  dur={info.duration_s:.1f}s  "
          f"scenes={len(scenes)}  model={args.model}")

    frames_dir = REPO_ROOT / "outputs" / "06_vm1_edit_intent" / clip_path.stem / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cuts = [s for s in scenes if s["scene_idx"] > 0][: args.n_cuts]
    print(f"[exp06] classifying first {len(cuts)} cuts")

    exp_dir = REPO_ROOT / "experiments" / "06_vm1_edit_intent"
    with Run(experiment="06_vm1_edit_intent", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            scenes_input=str(scenes_path.relative_to(REPO_ROOT)),
            n_cuts_total=len(scenes),
            n_cuts_evaluated=len(cuts),
            model=args.model,
            frame_offset_s=args.frame_offset_s,
        )

        results = []
        total_cost_usd = 0.0
        total_prompt_tok = 0
        total_completion_tok = 0
        parse_ok = 0
        label_counts: dict[str, int] = {}

        for c in cuts:
            cut_t = c["start_s"]
            t_a = max(0.0, cut_t - args.frame_offset_s)
            t_b = min(info.duration_s, cut_t + args.frame_offset_s)
            fa = frames_dir / f"cut_{c['scene_idx']:04d}_a.jpg"
            fb = frames_dir / f"cut_{c['scene_idx']:04d}_b.jpg"
            extract_frame_at(clip_path, t_a, fa, max_width=512, quality=4)
            extract_frame_at(clip_path, t_b, fb, max_width=512, quality=4)

            try:
                parsed, usage = call_model(args.model, fa, fb, api_key)
            except httpx.HTTPError as e:
                run.note(http_error=f"cut {c['scene_idx']}: {type(e).__name__}: {e}")
                continue

            cost = float(usage.get("cost") or 0)
            total_cost_usd += cost
            total_prompt_tok += int(usage.get("prompt_tokens", 0))
            total_completion_tok += int(usage.get("completion_tokens", 0))

            label = parsed.get("label", "MISSING")
            if label in LABELS:
                parse_ok += 1
                label_counts[label] = label_counts.get(label, 0) + 1

            results.append({
                "cut_idx": c["scene_idx"],
                "cut_t": cut_t,
                "frame_a": str(fa.relative_to(REPO_ROOT)),
                "frame_b": str(fb.relative_to(REPO_ROOT)),
                "label": label,
                "confidence": parsed.get("confidence"),
                "rationale": parsed.get("rationale"),
                "cost_usd": cost,
                "prompt_tokens": int(usage.get("prompt_tokens", 0)),
                "completion_tokens": int(usage.get("completion_tokens", 0)),
            })

        n = len(results) or 1
        run.metric("n_cuts_classified", len(results))
        run.metric("parse_success_rate", round(parse_ok / n, 3))
        run.metric("total_cost_usd", round(total_cost_usd, 6))
        run.metric("avg_cost_per_cut_usd", round(total_cost_usd / n, 6))
        run.metric("total_prompt_tokens", total_prompt_tok)
        run.metric("total_completion_tokens", total_completion_tok)
        run.metric("label_distribution", label_counts)

        # Project to a 15-min video at this clip's cut density:
        cuts_per_min = len(scenes) / (info.duration_s / 60.0)
        projected_cuts_15min = int(cuts_per_min * 15)
        run.metric("projected_cuts_15min", projected_cuts_15min)
        run.metric(
            "projected_cost_15min_video_usd",
            round((total_cost_usd / n) * projected_cuts_15min, 4),
        )

        # Persist results JSON (gitignored — too big for repo)
        out_json = (REPO_ROOT / "outputs" / "06_vm1_edit_intent" /
                    f"{clip_path.stem}_vm1_classifications.json")
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps({
            "clip": str(clip_path.relative_to(REPO_ROOT)),
            "model": args.model,
            "n_cuts": len(results),
            "total_cost_usd": total_cost_usd,
            "label_distribution": label_counts,
            "results": results,
        }, indent=2))
        run.metric("output", str(out_json.relative_to(REPO_ROOT)))

        print(f"[exp06] {len(results)} cuts | parse_ok={parse_ok}/{n} "
              f"({parse_ok/n*100:.0f}%) | cost ${total_cost_usd:.4f} "
              f"(avg ${total_cost_usd/n:.5f}/cut) | "
              f"labels={label_counts}")
        print(f"[exp06] projected 15-min video cost: "
              f"${(total_cost_usd/n) * projected_cuts_15min:.4f} "
              f"(over {projected_cuts_15min} projected cuts)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
