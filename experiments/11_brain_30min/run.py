"""
Experiment 11 — Brain EDL on a longer input (context-scaling test).

Same brain stage as Exp 10, but on the longer raw_15min clip (which is
actually 11.4 min — the original source video was too short for a true
15-min sample, see results.md). We extrapolate to "30-min" in the
results writeup.

Differences vs Exp 10:
- Full word list passed to the brain (not just first/last 30), to
  stress prompt size.
- Larger scenes list (188 vs 79).
- Larger VM-7 segments list (136 vs 60).

Gate (same as Exp 10):
- Parseable JSON matching the EDL schema.
- Cost for input ≤ $0.30 (~2× the 5-min cap because the input is ~2.3×
  longer).
- ≥ 3 distinct edit types.
- All timestamps in [0, duration].

This is the upper-bound stress test of the Phase 3 cost-per-video tier
that feeds Phase 6's recommended pricing tiers.

Run:
    python experiments/11_brain_30min/run.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# Reuse helpers + EDL schema from Exp 10 (load_inputs, etc.), but use a
# stricter SYSTEM_PROMPT here. Exp 10's prompt produced a clean 5-type EDL
# on a 5-min clip, but on the 11.4-min clip with the full word list it
# emitted hundreds of micro-silence edits and hit max_tokens before
# completing. The constraint-heavy prompt below is the "scaling fix"
# attempt — it parses cleanly but over-constrains to 2 types. See
# results.md for the prompt-iteration story.
sys.path.insert(0, str(REPO_ROOT / "experiments" / "10_brain_5min"))
from run import (  # noqa: E402
    ENDPOINT,
    VALID_EDIT_TYPES,
    load_inputs,
)

SYSTEM_PROMPT = (
    "You are the editing brain for a YouTube creator tool. You receive "
    "structured analysis of raw footage (word-level transcript, scene "
    "cuts, face tracking summary, audio energy, and per-segment visual "
    "categorization) and you output an Edit Decision List (EDL) that "
    "describes how to edit the raw footage into a polished video.\n"
    "\n"
    "Output ONLY a JSON object matching this exact schema (no prose, no "
    "markdown):\n"
    "{\n"
    '  "edits": [\n'
    '    {"type": "cut",            "at": <float_seconds>, "transition": "hard_cut"},\n'
    '    {"type": "remove_silence", "from": <s>, "to": <s>},\n'
    '    {"type": "zoom_in",        "from": <s>, "to": <s>, "level": <float>, "center": "face"},\n'
    '    {"type": "caption",        "text": "<str>", "from": <s>, "to": <s>, "style": "default"},\n'
    '    {"type": "speed_up",       "from": <s>, "to": <s>, "rate": <float>},\n'
    '    {"type": "sfx",            "at": <s>, "sound": "<str>"}\n'
    "  ]\n"
    "}\n"
    "\n"
    "Rules — VOLUME CAPS are mandatory; do NOT exceed them:\n"
    "- All timestamps must be within [0, duration_s] of the input.\n"
    "- Include at least 3 distinct edit types if the input supports them.\n"
    "- remove_silence: emit at MOST ~10 per minute of input. Only merge "
    "consecutive silences ≥ 0.8s; do NOT emit one per word-gap. Combine "
    "adjacent silences into a single remove_silence range.\n"
    "- caption: emit one caption per SENTENCE or natural phrase (typically "
    "5–15 words). Do NOT emit one caption per word. Aim for ~10 captions "
    "per minute, max ~20 per minute.\n"
    "- zoom_in: emit only where vm7 hints zoom=medium/tight AND audio onset "
    "density is high. Cap at ~5 zooms per minute.\n"
    "- cut: only on hard topic transitions, NOT every scene boundary "
    "(PySceneDetect already found those). Cap at ~3 per minute.\n"
    "- sfx: only at cuts you also emit. Cap at ~2 per minute.\n"
    "- Total edit count target: ~30–50 per minute of input. A 15-minute "
    "video should produce 450–750 edits, NOT thousands.\n"
)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from experiments._shared.instrument import Run  # noqa: E402

import httpx  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip-stem", default="raw_15min")
    ap.add_argument("--model", default=os.environ.get(
        "BRAIN_MODEL", "google/gemini-2.5-flash-lite"))
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    inputs = load_inputs(args.clip_stem)
    n_words = len(inputs["words"])
    print(f"[exp11] clip_stem={args.clip_stem}  dur={inputs['duration_s']:.1f}s  "
          f"words={n_words}  scenes={len(inputs['scenes'])}  "
          f"vm7_segments={len(inputs['vm7'].get('segments') or [])}  "
          f"model={args.model}")

    # Send the FULL word list this time
    user_msg = (
        f"Raw footage analysis for clip `{inputs['clip_stem']}` "
        f"(duration {inputs['duration_s']:.2f} s):\n\n"
        "```json\n" + json.dumps({
            "duration_s": inputs["duration_s"],
            "scenes": inputs["scenes"],
            "faces": inputs["faces"],
            "audio": inputs["audio"],
            "vm7": inputs["vm7"],
            "words": inputs["words"],  # full list
        }, indent=2) + "\n```\n\n"
        "Produce the EDL now. Output ONLY the JSON object."
    )

    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 16000,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/moazzam-qureshi/video-edit-ai",
        "X-Title": "video-edit-ai-experiments",
        "Content-Type": "application/json",
    }

    exp_dir = REPO_ROOT / "experiments" / "11_brain_30min"
    out_dir = REPO_ROOT / "outputs" / "11_brain_30min"
    out_dir.mkdir(parents=True, exist_ok=True)

    with Run(experiment="11_brain_30min", out_dir=exp_dir) as run:
        run.note(
            clip_stem=args.clip_stem,
            duration_s=inputs["duration_s"],
            model=args.model,
            n_words=n_words,
            n_scenes=len(inputs["scenes"]),
            vm7_segments=len(inputs["vm7"].get("segments") or []),
            prompt_size_chars=len(user_msg),
        )

        t0 = time.perf_counter()
        resp = httpx.post(ENDPOINT, headers=headers, json=payload, timeout=300)
        latency = time.perf_counter() - t0
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip().rstrip("`").strip()

        usage = data.get("usage", {})
        run.metric("brain_cost_usd", round(float(usage.get("cost") or 0), 6))
        run.metric("prompt_tokens", int(usage.get("prompt_tokens", 0)))
        run.metric("completion_tokens", int(usage.get("completion_tokens", 0)))
        run.metric("latency_s", round(latency, 3))

        try:
            edl = json.loads(content)
            parse_ok = True
        except json.JSONDecodeError as e:
            edl = {"_raw": content[:1000], "_error": str(e)}
            parse_ok = False
        run.metric("parse_ok", parse_ok)

        edits = edl.get("edits", []) if parse_ok else []
        run.metric("n_edits", len(edits))

        valid = 0
        type_counts: dict[str, int] = {}
        out_of_range = 0
        dur = inputs["duration_s"] or 0
        for e in edits:
            t = e.get("type")
            type_counts[t] = type_counts.get(t, 0) + 1
            if t not in VALID_EDIT_TYPES:
                continue
            ts = []
            for k in ("at", "from", "to"):
                if k in e and isinstance(e[k], (int, float)):
                    ts.append(e[k])
            if any(tt < 0 or tt > dur + 0.5 for tt in ts):
                out_of_range += 1
                continue
            valid += 1
        run.metric("valid_edits", valid)
        run.metric("invalid_or_out_of_range", len(edits) - valid)
        run.metric("edit_type_distribution", type_counts)
        run.metric("n_distinct_edit_types", len(type_counts))

        # Extrapolate to 30-min for the FINDINGS pricing table
        scale_30 = 1800.0 / max(inputs["duration_s"], 1)
        projected_cost_30min = round(float(usage.get("cost") or 0) * scale_30, 5)
        run.metric("projected_cost_30min_video_usd", projected_cost_30min)

        (out_dir / "edl.json").write_text(json.dumps(edl, indent=2))
        (out_dir / "raw_response.json").write_text(json.dumps(data, indent=2))

        print(f"[exp11] cost ${usage.get('cost', 0):.5f}  lat {latency:.2f}s  "
              f"tokens={usage.get('prompt_tokens')}+{usage.get('completion_tokens')}  "
              f"parse={parse_ok}  edits={len(edits)}  valid={valid}  "
              f"types={type_counts}")
        print(f"[exp11] projected 30-min video cost: ${projected_cost_30min}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
