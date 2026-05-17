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


def call_pass(label: str, model: str, system: str, user_msg: str,
              api_key: str, max_tokens: int = 4000) -> tuple[dict, dict, float]:
    """One brain call. Returns (parsed_obj, usage_dict, latency_s)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/moazzam-qureshi/video-edit-ai",
        "X-Title": "video-edit-ai-experiments",
        "Content-Type": "application/json",
    }
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
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        # Recovery: truncated `{"edits": [ ... <incomplete>` from hitting
        # max_tokens. Trim back to the last complete top-level edit object
        # in the array and close the JSON manually.
        recovered = _try_recover_truncated_edits(content)
        if recovered is not None:
            parsed = recovered
            parsed["_recovered_from_truncation"] = True
        else:
            parsed = {"_err": str(e), "_raw": content[:500]}
    return parsed, data.get("usage", {}), latency


def _try_recover_truncated_edits(content: str) -> dict | None:
    """If `content` looks like a truncated `{"edits":[ ... ]}` object,
    chop off the trailing incomplete object and close the JSON. Returns
    a parsed dict on success, None otherwise."""
    if '"edits"' not in content:
        return None
    # Find the last `},` that's followed by either whitespace+`{` or end
    # — that's the last completed edit. Conservative: find the last
    # complete `}` at depth 1 (inside the edits array).
    depth = 0
    in_str = False
    esc = False
    last_complete_close = -1
    for i, ch in enumerate(content):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 1:  # we just closed a top-level edit
                last_complete_close = i
    if last_complete_close < 0:
        return None
    fragment = content[: last_complete_close + 1] + "]}"
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        return None


def run_multi_pass(inputs: dict, model: str, api_key: str) -> tuple[list, dict, float]:
    """Four-pass brain: cut+sfx, silence, captions, zoom. Returns
    (merged_edits, total_usage_summary, total_latency_s)."""
    dur = inputs["duration_s"]
    n_cut = max(1, int(dur / 60 * 3))
    n_sil = max(1, int(dur / 60 * 10))
    n_cap = max(1, int(dur / 60 * 10))
    n_zoom = max(1, int(dur / 60 * 5))

    pa_sys = (
        "You are emitting cut+sfx edits ONLY. Output JSON: "
        '{"edits":[{"type":"cut","at":<s>,"transition":"hard_cut"},'
        '{"type":"sfx","at":<s>,"sound":"whoosh"}]}. '
        f"For a {dur:.0f}s clip, emit at most ~{n_cut} cuts (one every "
        "20–30s on hard topic shifts), and one sfx per cut. Pick from "
        "the provided scenes + vm7 segments where vm7 marks "
        "should_cut_here. Output ONLY the JSON."
    )
    pa_user = json.dumps({
        "duration_s": dur,
        "scenes_first_30": inputs["scenes"][:30],
        "vm7_segments": inputs["vm7"]["segments"][:60],
    }, indent=2)

    pb_sys = (
        "You are emitting remove_silence edits ONLY. Output JSON: "
        '{"edits":[{"type":"remove_silence","from":<s>,"to":<s>}]}. '
        f"For a {dur:.0f}s clip, emit at most ~{n_sil} remove_silence "
        "edits. MERGE adjacent silences — do NOT emit one per word-gap. "
        "Only target silence regions ≥0.8s long. Use audio.speech_segments "
        "to find inter-speech gaps. Output ONLY the JSON."
    )
    speech_segs = inputs["audio"]["speech_segments"][:50]
    pb_user = json.dumps(
        {"duration_s": dur, "speech_segments_first_50": speech_segs}, indent=2,
    )

    pc_sys = (
        "You are emitting caption edits ONLY. Output JSON: "
        '{"edits":[{"type":"caption","text":"<str>","from":<s>,"to":<s>,"style":"default"}]}. '
        "Group the words into natural sentences of 5–15 words each. Use "
        f"word timestamps as anchors. Emit ~{n_cap} captions for this "
        f"{dur:.0f}s clip, one per phrase. Output ONLY the JSON."
    )
    pc_user = json.dumps({"duration_s": dur, "words": inputs["words"]}, indent=2)

    pd_sys = (
        "You are emitting zoom_in edits ONLY. Output JSON: "
        '{"edits":[{"type":"zoom_in","from":<s>,"to":<s>,"level":<float>,"center":"face"}]}. '
        f"For a {dur:.0f}s clip, emit at most ~{n_zoom} zoom_in edits, "
        "only where vm7 hints zoom=medium or zoom=tight AND audio has "
        "high energy at that moment. Output ONLY the JSON."
    )
    pd_user = json.dumps({
        "duration_s": dur,
        "vm7_segments": inputs["vm7"]["segments"],
        "audio_rms_peak": inputs["audio"]["rms_peak"],
        "audio_n_onsets": inputs["audio"]["n_onsets"],
    }, indent=2)

    # Each pass declares the type(s) it emits and a function that decides
    # the type when the model omitted the field. This is Bug-1 defense:
    # Gemini 2.5 Flash Lite sometimes drops the `type` field even when the
    # schema demands it, and downstream code silently filters those out.
    def _type_for_pass_a(edit: dict) -> str:
        # Pass A emits cut OR sfx. `at + transition` → cut; `at + sound` → sfx.
        if "transition" in edit:
            return "cut"
        if "sound" in edit:
            return "sfx"
        # Default to cut (the more useful structural anchor)
        return "cut"
    def _type_for_pass_b(_e):
        return "remove_silence"
    def _type_for_pass_c(_e):
        return "caption"
    def _type_for_pass_d(_e):
        return "zoom_in"

    passes = [
        # max_tokens bumped from 2000 → 4000 on A and D (Bug 2): on longer
        # inputs both were truncating mid-array even though parse recovery
        # now exists. 4000 gives headroom while staying small.
        ("A:cut+sfx", pa_sys, pa_user, 4000, _type_for_pass_a),
        ("B:silence", pb_sys, pb_user, 2000, _type_for_pass_b),
        ("C:caption", pc_sys, pc_user, 8000, _type_for_pass_c),
        ("D:zoom",    pd_sys, pd_user, 4000, _type_for_pass_d),
    ]

    merged_edits: list = []
    total_cost = 0.0
    total_prompt_tok = 0
    total_completion_tok = 0
    total_latency = 0.0
    per_pass: dict = {}

    for label, sys_prompt, user_msg, mx, type_resolver in passes:
        parsed, usage, lat = call_pass(
            label, model, sys_prompt, user_msg, api_key, max_tokens=mx,
        )
        cost = float(usage.get("cost") or 0)
        prompt_tok = int(usage.get("prompt_tokens", 0))
        completion_tok = int(usage.get("completion_tokens", 0))
        total_cost += cost
        total_prompt_tok += prompt_tok
        total_completion_tok += completion_tok
        total_latency += lat
        edits_from_pass = parsed.get("edits", []) if isinstance(parsed, dict) else []
        backfilled = 0
        for e in edits_from_pass:
            if isinstance(e, dict) and "type" not in e:
                e["type"] = type_resolver(e)
                backfilled += 1
        per_pass[label] = {
            "parse_ok": "edits" in (parsed or {}),
            "parse_recovered": bool(parsed.get("_recovered_from_truncation")),
            "type_backfilled": backfilled,
            "cost_usd": cost,
            "prompt_tokens": prompt_tok,
            "completion_tokens": completion_tok,
            "latency_s": lat,
            "n_edits": len(edits_from_pass),
        }
        merged_edits.extend(edits_from_pass)
        print(f"  [{label}] cost ${cost:.5f}  lat {lat:.1f}s  "
              f"parse_ok={per_pass[label]['parse_ok']}  "
              f"recovered={per_pass[label]['parse_recovered']}  "
              f"prompt={prompt_tok}  completion={completion_tok}  "
              f"edits={per_pass[label]['n_edits']}  "
              f"type_backfilled={backfilled}")

    summary = {
        "total_cost_usd": total_cost,
        "total_prompt_tokens": total_prompt_tok,
        "total_completion_tokens": total_completion_tok,
        "per_pass": per_pass,
    }
    return merged_edits, summary, total_latency


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip-stem", default="raw_15min")
    ap.add_argument("--model", default=os.environ.get(
        "BRAIN_MODEL", "google/gemini-2.5-flash-lite"))
    ap.add_argument("--multi-pass", action="store_true", default=True,
                    help="use the 4-pass brain (default after the single-pass "
                         "approach surfaced prompt-fragility issues)")
    ap.add_argument("--single-pass", dest="multi_pass", action="store_false",
                    help="legacy single-pass mode — kept for the prompt-iteration"
                         " story in results.md")
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
          f"model={args.model}  "
          f"mode={'multi-pass' if args.multi_pass else 'single-pass'}")

    exp_dir = REPO_ROOT / "experiments" / "11_brain_30min"
    out_dir = REPO_ROOT / "outputs" / "11_brain_30min"
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = inputs["duration_s"] or 0

    with Run(experiment="11_brain_30min", out_dir=exp_dir) as run:
        run.note(
            clip_stem=args.clip_stem,
            duration_s=dur,
            model=args.model,
            n_words=n_words,
            n_scenes=len(inputs["scenes"]),
            vm7_segments=len(inputs["vm7"].get("segments") or []),
            mode=("multi-pass" if args.multi_pass else "single-pass"),
        )

        if args.multi_pass:
            merged_edits, summary, total_latency = run_multi_pass(
                inputs, args.model, api_key,
            )
            edits = merged_edits
            parse_ok = True
            edl = {"edits": edits}
            run.metric("brain_cost_usd", round(summary["total_cost_usd"], 6))
            run.metric("prompt_tokens", summary["total_prompt_tokens"])
            run.metric("completion_tokens", summary["total_completion_tokens"])
            run.metric("latency_s", round(total_latency, 3))
            run.metric("per_pass", summary["per_pass"])
        else:
            user_msg = (
                f"Raw footage analysis for clip `{inputs['clip_stem']}` "
                f"(duration {dur:.2f} s):\n\n"
                "```json\n" + json.dumps({
                    "duration_s": dur,
                    "scenes": inputs["scenes"],
                    "faces": inputs["faces"],
                    "audio": inputs["audio"],
                    "vm7": inputs["vm7"],
                    "words": inputs["words"],
                }, indent=2) + "\n```\n\n"
                "Produce the EDL now. Output ONLY the JSON object."
            )
            parsed, usage, lat = call_pass(
                "single", args.model, SYSTEM_PROMPT, user_msg, api_key,
                max_tokens=16000,
            )
            edits = parsed.get("edits", []) if isinstance(parsed, dict) else []
            parse_ok = "edits" in (parsed or {})
            edl = parsed
            run.metric("brain_cost_usd", round(float(usage.get("cost") or 0), 6))
            run.metric("prompt_tokens", int(usage.get("prompt_tokens", 0)))
            run.metric("completion_tokens", int(usage.get("completion_tokens", 0)))
            run.metric("latency_s", round(lat, 3))
            total_latency = lat
            summary = {"total_cost_usd": float(usage.get("cost") or 0)}

        run.metric("parse_ok", parse_ok)
        run.metric("n_edits", len(edits))

        valid = 0
        type_counts: dict[str, int] = {}
        out_of_range = 0
        for e in edits:
            tname = e.get("type")
            type_counts[tname] = type_counts.get(tname, 0) + 1
            if tname not in VALID_EDIT_TYPES:
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

        scale_30 = 1800.0 / max(dur, 1)
        projected_cost_30min = round(summary["total_cost_usd"] * scale_30, 5)
        run.metric("projected_cost_30min_video_usd", projected_cost_30min)

        (out_dir / "edl.json").write_text(json.dumps(edl, indent=2))

        print(f"[exp11] total cost ${summary['total_cost_usd']:.5f}  "
              f"latency {total_latency:.2f}s  parse_ok={parse_ok}  "
              f"edits={len(edits)}  valid={valid}  "
              f"distinct_types={len(type_counts)}  types={type_counts}")
        print(f"[exp11] projected 30-min video cost: ${projected_cost_30min}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
