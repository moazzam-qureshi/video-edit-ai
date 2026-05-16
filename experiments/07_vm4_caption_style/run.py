"""
Experiment 07 — VM-4 Caption Style Extraction.

Goal: send a handful of reference frames containing captions to a vision
model and ask for a structured caption-style spec (font, color, position,
animation hints, etc.) per product.md §VM-4.

The pipeline doesn't know up-front which frames have captions. Two
strategies considered:
  A) sample many frames at low fps, ask model per-frame "does this have a
     caption? if so, describe style; else NONE."
  B) sample N candidates, send them as a batch (multiple images in one
     call), let model reason holistically over which look most like
     captions.

We use (A) — single-image calls. Simpler, gives per-frame structured
output, lets us aggregate across positive hits.

Gate (from product.md §VM-4):
- Cost ≤ $0.05 for the experiment (doc said $0.01 with Qwen Plus).
- ≥ 1 frame is classified as containing a caption (else either the clip
  has none or detection failed — both are useful signals).
- Returns parseable JSON for ≥ 80% of frames.
- Aggregate spec includes at minimum: font_weight, color_text, position,
  background — the fields the brain stage needs to drive ASS generation.

Model: Tier 2 (quality) per the doc's tiering — Qwen3-VL-32B-Instruct.

Run:
    python experiments/07_vm4_caption_style/run.py \
        --clip samples/reference/reference.mp4 \
        --n-frames 12
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

PROMPT = (
    "Look at this video frame. Is there a CAPTION or SUBTITLE overlaid on "
    "the video (not UI text, not text inside the recorded content)?\n"
    "\n"
    "If YES, respond with ONLY a JSON object describing the caption's "
    "visual style:\n"
    "{\n"
    '  "has_caption": true,\n'
    '  "text": "<exact caption text, up to 100 chars>",\n'
    '  "font_weight": "thin|regular|medium|bold|black",\n'
    '  "font_style": "sans|serif|mono|script",\n'
    '  "color_text": "#RRGGBB or color name",\n'
    '  "color_highlight": "#RRGGBB or null",\n'
    '  "color_stroke": "#RRGGBB or null",\n'
    '  "background": "none|box|gradient|blur",\n'
    '  "position": "top|middle|bottom|custom",\n'
    '  "capitalization": "ALL_CAPS|Title|Sentence|lowercase",\n'
    '  "words_visible": <integer>\n'
    "}\n"
    "\n"
    'If NO, respond with ONLY: {"has_caption": false}\n'
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
        "max_tokens": 400,
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
        parsed = {"has_caption": None, "_raw": content[:300]}
    return parsed, data.get("usage", {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--n-frames", type=int, default=12)
    ap.add_argument("--model", default=os.environ.get(
        "VISION_MODEL_PLUS", "qwen/qwen3-vl-32b-instruct"))
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    clip_path = (REPO_ROOT / args.clip).resolve()
    info = probe(clip_path)
    print(f"[exp07] clip {clip_path.name}  dur={info.duration_s:.1f}s  "
          f"model={args.model}  frames={args.n_frames}")

    # Evenly-spaced sample timestamps, avoiding first/last 5%
    n = args.n_frames
    times = [info.duration_s * (0.05 + 0.9 * i / (n - 1)) for i in range(n)]

    frames_dir = REPO_ROOT / "outputs" / "07_vm4_caption_style" / clip_path.stem / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    exp_dir = REPO_ROOT / "experiments" / "07_vm4_caption_style"
    with Run(experiment="07_vm4_caption_style", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            duration_s=info.duration_s,
            n_frames=n,
            model=args.model,
        )

        results = []
        total_cost = 0.0
        parse_ok = 0
        has_caption_count = 0
        total_prompt_tok = 0
        total_completion_tok = 0

        for i, t in enumerate(times):
            fp = frames_dir / f"frame_{i:02d}_t{t:.1f}.jpg"
            extract_frame_at(clip_path, t, fp, max_width=768, quality=3)
            try:
                parsed, usage = call_model(args.model, fp, api_key)
            except httpx.HTTPError as e:
                run.note(http_error=f"frame {i}: {type(e).__name__}: {e}")
                continue

            cost = float(usage.get("cost") or 0)
            total_cost += cost
            total_prompt_tok += int(usage.get("prompt_tokens", 0))
            total_completion_tok += int(usage.get("completion_tokens", 0))

            if isinstance(parsed, dict) and "has_caption" in parsed and parsed["has_caption"] is not None:
                parse_ok += 1
                if parsed["has_caption"] is True:
                    has_caption_count += 1

            results.append({
                "frame_idx": i,
                "t": round(t, 2),
                "frame_path": str(fp.relative_to(REPO_ROOT)),
                "result": parsed,
                "cost_usd": cost,
            })

        n_eval = len(results) or 1
        run.metric("n_frames", n_eval)
        run.metric("parse_success_rate", round(parse_ok / n_eval, 3))
        run.metric("frames_with_caption", has_caption_count)
        run.metric(
            "caption_hit_rate", round(has_caption_count / n_eval, 3),
        )
        run.metric("total_cost_usd", round(total_cost, 6))
        run.metric("avg_cost_per_frame_usd", round(total_cost / n_eval, 6))
        run.metric("total_prompt_tokens", total_prompt_tok)
        run.metric("total_completion_tokens", total_completion_tok)

        # Aggregate spec across caption-positive frames
        positives = [r["result"] for r in results
                     if isinstance(r.get("result"), dict)
                     and r["result"].get("has_caption") is True]
        if positives:
            def mode(field: str) -> str | None:
                counts: dict[str, int] = {}
                for p in positives:
                    v = p.get(field)
                    if v is None:
                        continue
                    counts[str(v)] = counts.get(str(v), 0) + 1
                if not counts:
                    return None
                return max(counts, key=counts.get)

            aggregated = {
                "n_positive_frames": len(positives),
                "font_weight_mode": mode("font_weight"),
                "font_style_mode": mode("font_style"),
                "color_text_mode": mode("color_text"),
                "background_mode": mode("background"),
                "position_mode": mode("position"),
                "capitalization_mode": mode("capitalization"),
            }
            run.metric("aggregated_style", aggregated)

        out_json = (REPO_ROOT / "outputs" / "07_vm4_caption_style" /
                    f"{clip_path.stem}_vm4_caption_style.json")
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps({
            "clip": str(clip_path.relative_to(REPO_ROOT)),
            "model": args.model,
            "total_cost_usd": total_cost,
            "n_positive": has_caption_count,
            "results": results,
        }, indent=2))
        run.metric("output", str(out_json.relative_to(REPO_ROOT)))

        print(f"[exp07] {n_eval} frames | parse_ok={parse_ok} | "
              f"has_caption={has_caption_count} | cost ${total_cost:.4f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
