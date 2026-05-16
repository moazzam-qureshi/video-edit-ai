"""
Experiment 10 — Brain EDL generation on a 5-min input.

Assemble all Phase 1 + Phase 2 outputs for a single raw clip into one
context blob, hand it to the brain model with a strict JSON schema for
the EDL (Edit Decision List), and measure cost / quality / parse rate.

EDL schema (locked here, becomes the contract for Phase 4):

  {
    "edits": [
      {"type": "cut",            "at": <s>,    "transition": "hard_cut|fade|crossfade"},
      {"type": "remove_silence", "from": <s>,  "to": <s>},
      {"type": "zoom_in",        "from": <s>,  "to": <s>, "level": <float>,
                                 "center": "face|frame|x,y"},
      {"type": "caption",        "text": "<str>", "from": <s>, "to": <s>,
                                 "style": "default|highlight"},
      {"type": "speed_up",       "from": <s>,  "to": <s>, "rate": <float>},
      {"type": "sfx",            "at": <s>,    "sound": "<str>"}
    ]
  }

Gate:
- Returns parseable JSON matching the schema (≥ 80% of edit objects pass
  basic shape validation).
- Cost for 5-min input ≤ $0.15 (doc estimated $0.06 with Gemini 3 Flash;
  Gemini 2.5 Flash Lite is cheaper at $0.10/$0.40 per MTok).
- EDL contains at least 3 distinct edit types — the brain isn't degenerate.
- EDL timestamps are bounded by the input duration.

Model: Tier 3 brain — `google/gemini-2.5-flash-lite` (1M context,
structured output, 3× cheaper than gemini-2.5-flash for same task).

Run:
    python experiments/10_brain_5min/run.py
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

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

from experiments._shared.instrument import Run  # noqa: E402

import httpx  # noqa: E402

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

VALID_EDIT_TYPES = {
    "cut", "remove_silence", "zoom_in", "caption", "speed_up", "sfx",
}


def load_inputs(clip_stem: str) -> dict:
    """Pull together all Phase 1 + Phase 2 outputs for one clip."""
    out = REPO_ROOT / "outputs"

    # Transcript — keep only words for brevity (drop redundant segments)
    transcript_path = out / "01_whisperx" / f"{clip_stem}_large-v2_int8.json"
    transcript = json.loads(transcript_path.read_text())
    words = []
    for seg in transcript.get("segments", []):
        for w in seg.get("words", []):
            words.append({
                "w": w.get("word", "").strip(),
                "s": round(w.get("start", 0.0), 3),
                "e": round(w.get("end", 0.0), 3),
            })

    # Scenes (might not exist for every clip — handle gracefully)
    scenes_path = out / "02_pyscenedetect" / f"{clip_stem}_content_scenes.json"
    scenes = json.loads(scenes_path.read_text()) if scenes_path.exists() else []
    scenes_compact = [
        {"i": s["scene_idx"], "s": round(s["start_s"], 3), "e": round(s["end_s"], 3)}
        for s in scenes
    ]

    # Face hit-rate summary (full per-frame data is too big; we send summary)
    faces_path = out / "03_mediapipe_face" / f"{clip_stem}_faces.json"
    faces_summary = None
    if faces_path.exists():
        faces = json.loads(faces_path.read_text())
        faces_summary = {
            "frames_total": faces.get("frames_total"),
            "frames_with_face": faces.get("frames_with_face"),
            "hit_rate": round(faces.get("frames_with_face", 0) /
                              max(faces.get("frames_total", 1), 1), 3),
        }

    # Audio analysis (Librosa onsets + Silero speech segments)
    audio_path = out / "04_librosa_vad" / f"{clip_stem}_audio_analysis.json"
    audio = json.loads(audio_path.read_text()) if audio_path.exists() else {}
    audio_compact = {
        "n_onsets": len(audio.get("onset_times_s", [])),
        "speech_segments": audio.get("speech_segments_s", []),
        "rms_mean": audio.get("rms_mean"),
        "rms_peak": audio.get("rms_peak"),
    }

    # VM-7 raw-footage analysis
    vm7_path = out / "08_vm7_raw_footage" / f"{clip_stem}_vm7.json"
    vm7 = json.loads(vm7_path.read_text()) if vm7_path.exists() else {}
    vm7_compact = {
        "sample_every_s": vm7.get("sample_every_s"),
        "category_distribution": vm7.get("category_distribution"),
        "segments": [
            {"t": r["t"],
             "cat": r["result"].get("category"),
             "cut": r["result"].get("should_cut_here"),
             "zoom": r["result"].get("zoom_hint")}
            for r in vm7.get("results", [])
            if isinstance(r.get("result"), dict) and "category" in r["result"]
        ],
    }

    return {
        "clip_stem": clip_stem,
        "duration_s": transcript.get("duration_s"),
        "words": words,
        "scenes": scenes_compact,
        "faces": faces_summary,
        "audio": audio_compact,
        "vm7": vm7_compact,
    }


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
    "Rules:\n"
    "- All timestamps must be within [0, duration_s] of the input.\n"
    "- Include at least 3 distinct edit types if the input supports them.\n"
    "- Prefer to remove silences ≥ 0.8 s (use the audio.speech_segments to find them).\n"
    "- Add captions for every significant phrase (use the words list).\n"
    "- Add zoom_in only where vm7 hints zoom=medium/tight or audio energy peaks.\n"
    "- Add SFX (e.g., whoosh) at significant cuts.\n"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip-stem", default="raw_5min")
    ap.add_argument("--model", default=os.environ.get(
        "BRAIN_MODEL", "google/gemini-2.5-flash-lite"))
    args = ap.parse_args()

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    print(f"[exp10] loading inputs for clip_stem={args.clip_stem}")
    inputs = load_inputs(args.clip_stem)
    print(f"[exp10] duration={inputs['duration_s']:.1f}s  words={len(inputs['words'])}  "
          f"scenes={len(inputs['scenes'])}  "
          f"vm7_segments={len(inputs['vm7'].get('segments') or [])}  "
          f"model={args.model}")

    user_msg = (
        f"Raw footage analysis for clip `{inputs['clip_stem']}` "
        f"(duration {inputs['duration_s']:.2f} s):\n\n"
        "```json\n" + json.dumps({
            "duration_s": inputs["duration_s"],
            "scenes": inputs["scenes"],
            "faces": inputs["faces"],
            "audio": inputs["audio"],
            "vm7": inputs["vm7"],
            "words_count": len(inputs["words"]),
            "words_preview_first_30": inputs["words"][:30],
            "words_preview_last_30": inputs["words"][-30:],
            # Full words list omitted to keep prompt under a reasonable size for
            # this experiment; expanding to full transcript is Exp 11's territory.
        }, indent=2) + "\n```\n\n"
        "Produce the EDL now. Output ONLY the JSON object."
    )

    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 4000,
        "temperature": 0.1,
        # Request JSON mode if the provider supports it
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/moazzam-qureshi/video-edit-ai",
        "X-Title": "video-edit-ai-experiments",
        "Content-Type": "application/json",
    }

    exp_dir = REPO_ROOT / "experiments" / "10_brain_5min"
    out_dir = REPO_ROOT / "outputs" / "10_brain_5min"
    out_dir.mkdir(parents=True, exist_ok=True)

    with Run(experiment="10_brain_5min", out_dir=exp_dir) as run:
        run.note(
            clip_stem=args.clip_stem,
            duration_s=inputs["duration_s"],
            model=args.model,
            n_words_total=len(inputs["words"]),
            n_scenes=len(inputs["scenes"]),
            vm7_segments=len(inputs["vm7"].get("segments") or []),
            prompt_size_chars=len(user_msg),
        )

        t0 = time.perf_counter()
        resp = httpx.post(ENDPOINT, headers=headers, json=payload, timeout=180)
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

        # Parse + validate
        try:
            edl = json.loads(content)
            parse_ok = True
        except json.JSONDecodeError as e:
            edl = {"_raw": content[:1000], "_error": str(e)}
            parse_ok = False
        run.metric("parse_ok", parse_ok)

        edits = edl.get("edits", []) if parse_ok else []
        run.metric("n_edits", len(edits))

        # Validate each edit's shape
        valid = 0
        type_counts: dict[str, int] = {}
        out_of_range = 0
        dur = inputs["duration_s"] or 0
        for e in edits:
            t = e.get("type")
            type_counts[t] = type_counts.get(t, 0) + 1
            if t not in VALID_EDIT_TYPES:
                continue
            # Cheap shape check: timestamps must be in-range
            ts = []
            for k in ("at", "from", "to"):
                if k in e and isinstance(e[k], (int, float)):
                    ts.append(e[k])
            if any(t < 0 or t > dur + 0.5 for t in ts):
                out_of_range += 1
                continue
            valid += 1
        run.metric("valid_edits", valid)
        run.metric("invalid_or_out_of_range", len(edits) - valid)
        run.metric("edit_type_distribution", type_counts)
        run.metric("n_distinct_edit_types", len(type_counts))

        # Save full EDL + raw response
        (out_dir / "edl.json").write_text(json.dumps(edl, indent=2))
        (out_dir / "raw_response.json").write_text(json.dumps(data, indent=2))

        print(f"[exp10] cost ${usage.get('cost', 0):.5f}  lat {latency:.2f}s  "
              f"tokens={usage.get('prompt_tokens')}+{usage.get('completion_tokens')}  "
              f"parse={parse_ok}  edits={len(edits)}  "
              f"valid={valid}  types={type_counts}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
