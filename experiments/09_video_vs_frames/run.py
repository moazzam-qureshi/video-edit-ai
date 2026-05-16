"""
Experiment 09 — Native Video Input vs Frame Extraction.

The product.md doc claims native-video-input models can replace
frame-by-frame analysis, simplifying the pipeline. This experiment
empirically compares the two on the SAME content:

  A) Frame-based:  N evenly-spaced frames + per-frame prompt
  B) Video-based:  upload a short clip + one holistic prompt asking
                   for a list of timestamped observations.

Task: ask the model to identify cut points and label what's happening
in each segment. Compare cost, latency, and structural quality.

Model picks (verified live against OpenRouter on 2026-05-17):
- Qwen3-VL-8B doesn't accept video on OpenRouter ("No endpoints found
  that support input video"). The current Qwen "Flash" with video
  support is `qwen/qwen3.5-flash-02-23` at $0.065/$0.260.

Gate (this experiment's plan, since plan.md is off-repo):
- Both calls complete and return parseable JSON.
- Total experiment cost ≤ $0.20.
- Produce a head-to-head comparison: cost, latency, schema quality,
  qualitative output similarity.

Run:
    python experiments/09_video_vs_frames/run.py \
        --clip samples/reference/reference.mp4 \
        --start 60 --duration 30
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
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

# Same prompt structure for both paths so the comparison is apples-to-apples.
PROMPT_VIDEO = (
    "Analyze this short video clip. Identify each apparent cut (hard "
    "transition) and describe what's happening in the segment AFTER each cut.\n"
    "\n"
    "Respond with ONLY a JSON object:\n"
    "{\n"
    '  "n_cuts": <integer>,\n'
    '  "segments": [\n'
    '    {"start_s": <float>, "description": "<short>", "label": "talking_head|screen_recording|b_roll|demo|graphic|other"}\n'
    "  ]\n"
    "}\n"
)

PROMPT_FRAMES = (
    "These are evenly-spaced frames from a short video clip, in time order.\n"
    "Identify each apparent cut and describe what's in each segment.\n"
    "\n"
    "Respond with ONLY a JSON object with the same schema:\n"
    "{\n"
    '  "n_cuts": <integer>,\n'
    '  "segments": [\n'
    '    {"start_s": <float>, "description": "<short>", "label": "talking_head|screen_recording|b_roll|demo|graphic|other"}\n'
    "  ]\n"
    "}\n"
)


def b64_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def b64_video(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def parse_json_loose(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```", 2)[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip().rstrip("`").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"_raw": content[:500], "_parse_error": True}


def call_video(model: str, video: Path, api_key: str) -> tuple[dict, dict, float]:
    import time
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT_VIDEO},
                {"type": "video_url",
                 "video_url": {"url": f"data:video/mp4;base64,{b64_video(video)}"}},
            ],
        }],
        "max_tokens": 800,
        "temperature": 0.0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/moazzam-qureshi/video-edit-ai",
        "X-Title": "video-edit-ai-experiments",
        "Content-Type": "application/json",
    }
    t0 = time.perf_counter()
    resp = httpx.post(ENDPOINT, headers=headers, json=payload, timeout=180)
    latency = time.perf_counter() - t0
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    parsed = parse_json_loose(content)
    return parsed, data.get("usage", {}), latency


def call_frames(model: str, frames: list[Path], api_key: str) -> tuple[dict, dict, float]:
    import time
    content = [{"type": "text", "text": PROMPT_FRAMES}]
    for f in frames:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_image(f)}"},
        })
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 800,
        "temperature": 0.0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/moazzam-qureshi/video-edit-ai",
        "X-Title": "video-edit-ai-experiments",
        "Content-Type": "application/json",
    }
    t0 = time.perf_counter()
    resp = httpx.post(ENDPOINT, headers=headers, json=payload, timeout=180)
    latency = time.perf_counter() - t0
    resp.raise_for_status()
    data = resp.json()
    parsed = parse_json_loose(data["choices"][0]["message"]["content"])
    return parsed, data.get("usage", {}), latency


def cut_subclip(src: Path, dst: Path, start_s: float, duration_s: float,
                max_width: int = 512) -> Path:
    """Re-encode a small sub-clip suitable for upload (h264, no audio, ~30 KB/s)."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start_s),
        "-i", str(src),
        "-t", str(duration_s),
        "-vf", f"scale={max_width}:-2",
        "-c:v", "libx264", "-preset", "fast", "-crf", "30",
        "-an", "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--start", type=float, default=60.0)
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--n-frames", type=int, default=6,
                    help="frame count for the frames-based path; ~1 frame per "
                         "5s of clip is a sensible default")
    ap.add_argument("--video-model", default="qwen/qwen3.5-flash-02-23",
                    help="video-capable cheap model")
    ap.add_argument("--frames-model", default=os.environ.get(
        "VISION_MODEL_FLASH", "qwen/qwen3-vl-8b-instruct"))
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    clip_path = (REPO_ROOT / args.clip).resolve()
    info = probe(clip_path)
    print(f"[exp09] source: {clip_path.name} dur={info.duration_s:.1f}s; "
          f"sub-clip {args.start}–{args.start+args.duration}s")
    print(f"[exp09] video_model={args.video_model}  "
          f"frames_model={args.frames_model}  n_frames={args.n_frames}")

    out_dir = REPO_ROOT / "outputs" / "09_video_vs_frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    sub = out_dir / f"sub_{int(args.start)}_{int(args.start+args.duration)}.mp4"
    cut_subclip(clip_path, sub, args.start, args.duration, max_width=512)
    print(f"[exp09] sub-clip: {sub.name} ({sub.stat().st_size//1024} KB)")

    # Extract frames for the frames-based path, evenly spaced within the sub-clip
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    times = [args.start + args.duration * (0.5 + i) / args.n_frames
             for i in range(args.n_frames)]
    frame_paths: list[Path] = []
    for i, t in enumerate(times):
        fp = frames_dir / f"frame_{i:02d}_t{t:.1f}.jpg"
        extract_frame_at(clip_path, t, fp, max_width=512, quality=4)
        frame_paths.append(fp)
    print(f"[exp09] frames extracted: {len(frame_paths)}")

    exp_dir = REPO_ROOT / "experiments" / "09_video_vs_frames"
    with Run(experiment="09_video_vs_frames", out_dir=exp_dir) as run:
        run.note(
            clip=str(clip_path.relative_to(REPO_ROOT)),
            subclip=str(sub.relative_to(REPO_ROOT)),
            start_s=args.start,
            duration_s=args.duration,
            n_frames=args.n_frames,
            video_model=args.video_model,
            frames_model=args.frames_model,
            subclip_size_kb=sub.stat().st_size // 1024,
        )

        # --- Video path ---
        try:
            v_parsed, v_usage, v_latency = call_video(
                args.video_model, sub, api_key,
            )
            v_cost = float(v_usage.get("cost") or 0)
            v_prompt = int(v_usage.get("prompt_tokens", 0))
            v_completion = int(v_usage.get("completion_tokens", 0))
            v_n_segments = (len(v_parsed.get("segments", []))
                            if isinstance(v_parsed, dict) else 0)
            v_parse_ok = not v_parsed.get("_parse_error")
        except httpx.HTTPError as e:
            v_parsed = {"_http_error": f"{type(e).__name__}: {e}"}
            v_cost = v_prompt = v_completion = 0
            v_latency = 0.0
            v_n_segments = 0
            v_parse_ok = False

        run.metric("video_cost_usd", round(v_cost, 6))
        run.metric("video_prompt_tokens", v_prompt)
        run.metric("video_completion_tokens", v_completion)
        run.metric("video_latency_s", round(v_latency, 3))
        run.metric("video_n_segments", v_n_segments)
        run.metric("video_parse_ok", v_parse_ok)

        # --- Frames path ---
        try:
            f_parsed, f_usage, f_latency = call_frames(
                args.frames_model, frame_paths, api_key,
            )
            f_cost = float(f_usage.get("cost") or 0)
            f_prompt = int(f_usage.get("prompt_tokens", 0))
            f_completion = int(f_usage.get("completion_tokens", 0))
            f_n_segments = (len(f_parsed.get("segments", []))
                            if isinstance(f_parsed, dict) else 0)
            f_parse_ok = not f_parsed.get("_parse_error")
        except httpx.HTTPError as e:
            f_parsed = {"_http_error": f"{type(e).__name__}: {e}"}
            f_cost = f_prompt = f_completion = 0
            f_latency = 0.0
            f_n_segments = 0
            f_parse_ok = False

        run.metric("frames_cost_usd", round(f_cost, 6))
        run.metric("frames_prompt_tokens", f_prompt)
        run.metric("frames_completion_tokens", f_completion)
        run.metric("frames_latency_s", round(f_latency, 3))
        run.metric("frames_n_segments", f_n_segments)
        run.metric("frames_parse_ok", f_parse_ok)

        run.metric("total_cost_usd", round(v_cost + f_cost, 6))
        run.metric(
            "cost_ratio_video_over_frames",
            round(v_cost / f_cost, 3) if f_cost > 0 else None,
        )

        # Save both raw outputs
        out_json = out_dir / "comparison.json"
        out_json.write_text(json.dumps({
            "subclip": str(sub.relative_to(REPO_ROOT)),
            "start_s": args.start,
            "duration_s": args.duration,
            "video": {
                "model": args.video_model,
                "cost_usd": v_cost,
                "latency_s": v_latency,
                "n_segments": v_n_segments,
                "result": v_parsed,
            },
            "frames": {
                "model": args.frames_model,
                "n_frames": args.n_frames,
                "cost_usd": f_cost,
                "latency_s": f_latency,
                "n_segments": f_n_segments,
                "result": f_parsed,
            },
        }, indent=2))

        print()
        print(f"[exp09] VIDEO path : {args.video_model}")
        print(f"        cost ${v_cost:.5f}  lat {v_latency:.2f}s  "
              f"prompt={v_prompt} completion={v_completion}  "
              f"n_segments={v_n_segments}  parse_ok={v_parse_ok}")
        print(f"[exp09] FRAMES path: {args.frames_model} ({args.n_frames} frames)")
        print(f"        cost ${f_cost:.5f}  lat {f_latency:.2f}s  "
              f"prompt={f_prompt} completion={f_completion}  "
              f"n_segments={f_n_segments}  parse_ok={f_parse_ok}")
        if v_cost > 0 and f_cost > 0:
            print(f"[exp09] cost ratio video/frames: {v_cost/f_cost:.2f}×")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
