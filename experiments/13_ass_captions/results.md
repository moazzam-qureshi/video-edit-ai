# Experiment 13 — ASS caption rendering

**Phase:** Phase 4
**Status:** done
**Verdict:** ✅ **PASS** — captions render correctly, RTF 36×, visible
text confirmed via frame extraction.
**Date run:** 2026-05-17 (UTC)
**Run by:** claude (Opus 4.7)
**Host:** moazzam-vps (Ryzen 5 3600, ffmpeg 6.1.1 + libass)

## Goal

Take the `caption` edits from a Phase 3 EDL, generate a valid ASS
subtitle file, and burn the captions into a video via ffmpeg's `ass`
filter. Validates that the caption-rendering leg of the product
pipeline works end-to-end.

For this experiment we render onto the **original raw clip** (no
silence-trimming yet), so the EDL caption timestamps map directly onto
the output without remapping. Timestamp remapping after silence-trim
is Exp 14's job.

## Gate

- Generates a valid `.ass` file with all caption events from the EDL.
- ffmpeg `ass` filter renders without errors.
- Output file is playable (`probe()` returns sane duration / streams).
- **Captions are visually present** in the output (verified by
  extracting a frame during a caption window).
- Render **RTF ≥ 0.5×** (audit: libx264 medium ~1–2× realtime on this
  CPU; we use `fast` preset on 360p, expect more).

## What we ran

- **Input clip:** `samples/raw/raw_5min.mp4` (300.03 s, 360p30, with
  audio; H.264 video + AAC audio)
- **EDL:** `outputs/10_brain_5min/multipass_edl.json` (153 edits;
  61 captions)
- **ASS template style:** Arial 72 px, bold, white text, black stroke,
  bottom-center, margins 40/40/80, PlayRes 1920×1080 (libass scales
  to actual frame size at render time)
- **Render params:** libx264 `preset=fast`, `crf=23`, audio
  `-c:a copy` (no re-encode of audio — only video changes), `+faststart`
- **Command:**
  ```bash
  python experiments/13_ass_captions/run.py \
      --edl outputs/10_brain_5min/multipass_edl.json \
      --clip samples/raw/raw_5min.mp4 --preset fast
  ```

## Observations

| Metric | Value |
|---|---|
| Captions in EDL | 61 |
| **Captions written to ASS** | **61 (100%)** |
| ASS file size | 6,693 bytes |
| **Render wall clock** | **8.28 s** |
| **Render RTF** | **36.2×** |
| Output duration | 300.03 s (= input; no trimming) |
| Output size | 12.02 MB (vs 11.2 MB input — +0.8 MB for re-encode + captions) |
| Peak RSS | 188.8 MB |
| CPU avg / peak | 58.5% / 74.0% (libx264 + libass use all available cores) |
| Sample frame at midpoint (t=138.86 s) of caption #30 | rendered as `outputs/13_ass_captions/sample_caption_frame.jpg` |

### Visual verification

Sampled a frame at t=138.86 s (the midpoint of caption #30 in the
EDL). The frame shows:

- **Our rendered caption: "Here I'll add a film dust overlay for the
  background."** — bold white, bottom-centered, with black stroke.
  Matches the ASS style spec exactly.
- The source video's **own burnt-in subtitle** ("here i'll add a film
  dust overlay for the background") is visible just below the player
  panel in the screencast itself. Both texts agree (modulo casing) —
  great confirmation that WhisperX's transcription, the brain's
  caption generation, and the ASS burn-in line up.

The frame is gitignored (it shows the source's screencast content) but
is reproducible via the run command above.

### What I deliberately did NOT do

- **No animation** (per-word highlight, fade, pop-in). The ASS format
  supports karaoke/fade/move tags but the EDL only carries `{from, to,
  text, style}` fields. Animation is a brain-output upgrade
  (caption-by-word fields), not an ASS limitation. Flag for FINDINGS.
- **No style transfer from VM-4.** Exp 07's caption-style descriptor
  (regular sans, white, bottom, sentence case) was *implicitly* used
  to choose this experiment's ASS template — but I didn't programmatically
  wire VM-4 output into ASS style fields. That's an integration
  task for Exp 14.
- **No silence-trim integration.** Captions render at their source
  timestamps; if we'd rendered onto the Exp 12 silence-trimmed
  output the timestamps would all be wrong. Timestamp remapping is
  Exp 14's job.

## Verdict against gate

- ✅ **ASS file valid** (61/61 events written; libass parsed it
  without warnings)
- ✅ **ffmpeg renders without errors** (rc=0)
- ✅ **Output playable** (probe returns 300.03s, video + audio
  streams present)
- ✅ **Captions visually present** (sample frame extraction confirms
  bold white caption on screen)
- ✅ **Render RTF** (36.2× ≫ 0.5×)

**Overall: PASS.**

## Open questions / follow-ups

- **Animation upgrade.** Modern TikTok-style captions want per-word
  highlight + pop-in. ASS supports this via the `\k`/`\fad`/`\t` tags.
  Requires brain to emit per-word caption events (or a transform step
  that splits sentence-level captions into word-level with karaoke
  markup). Worth a small Exp 13b in future product engineering.
- **VM-4 style integration.** Phase 2 produces a `font_weight /
  color_text / position / background` style spec; this experiment
  hardcoded a reasonable default. Wiring the spec into the ASS style
  is straightforward (map font_weight→Bold, color_text→PrimaryColour,
  position→Alignment/MarginV).
- **Timestamp remapping.** For the full pipeline, captions emitted at
  source-time need their timestamps shifted to account for
  silence-trim. The remap function is mechanical: for each caption
  `(from, to)`, subtract the total silence dropped before `from`.
  Exp 14 will implement this.
- **Long captions truncate.** I capped caption text at 80 chars
  in-code; longer captions get a trailing `…`. The brain occasionally
  emits 100+-char captions; the eventual product should either split
  long captions into 2 lines (libass auto-wraps with WrapStyle) or
  split into multiple events.

## Artifacts

- `outputs/13_ass_captions/raw_5min.ass` (6.7 KB — generated subtitle)
- `outputs/13_ass_captions/raw_5min_captioned.mp4` (12.0 MB)
- `outputs/13_ass_captions/sample_caption_frame.jpg` (visual proof)

All gitignored.

## Links

- metrics.json: [`experiments/13_ass_captions/metrics.json`](metrics.json)
- Related: Exp 07 (VM-4 caption style — feeds the ASS template), Exp 12
  (silence-trim + render — the other half of Phase 4), Exp 14 (full
  pipeline with timestamp remapping)
- Product doc reference: [product.md](../../docs/product.md) §5
  "Caption Rendering (Animated Word-by-Word)"
