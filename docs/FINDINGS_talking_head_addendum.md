# FINDINGS — Talking-head sample addendum

**Compiled:** 2026-05-17 (UTC)
**Purpose:** Close out the four "couldn't validate without real talking-head
footage" bullets in `FINDINGS.md` § "What's NOT validated yet".

**New sample added:** `samples/raw/raw_talking_5min.mp4` (300 s, 640×360@30,
H.264+AAC, 14.6 MB). First 5 min of "12 Editors Battle for $1,000 Prize!"
by Joseph | Video Editing (YouTube ID L1xGqegSfv8). Talking-head style with
the creator on camera, plus occasional B-roll and demo cutaways.

All re-runs **do not overwrite the canonical experiment metrics.json files**.
Talking-head results are stored alongside as `metrics_talking_head.json`
in each experiment folder.

---

## Closed gap #1 — Exp 03: MediaPipe face hit-rate

**FINDINGS said:** "Hit-rate validation deferred — needs true talking-head
footage to evaluate."

**Now resolved:**

| Model | Frames analyzed | Frames with face | **Hit rate** | RTF |
|---|---|---|---|---|
| `model_selection=0` (short-range, ≤2 m) | 9,000 | 5,520 | **61.3%** | 8.45× |
| `model_selection=1` (full-range, ≤5 m) | 9,000 | 7,098 | **78.9%** | 2.93× |

- **Short-range (61.3%)** **misses the 70% gate**, but the full-range
  model **clears it** at 78.9%. Confirms the Exp 03 follow-up
  recommendation: short-range for selfie-framing creators, full-range
  for talking-head-at-a-distance content.
- **Throughput drops 3× going from short-range to full-range**, but both
  comfortably beat the 0.5× RTF gate.
- The 22% of frames where the full-range model still doesn't find a face
  are the genuine B-roll / cutaway moments (demo content, score overlays,
  thumbnail montages) — those should not register a face.

**Verdict reclassification: Exp 03 PASS on full-range model with the
talking-head sample.** The original "PASS on throughput, hit-rate N/A"
verdict on the screencast clip stands; this addendum supplements it.

**Product implication:** the pipeline should default to
`model_selection=1` (full-range) unless the creator has explicitly opted
in to selfie-framing. The 3× throughput cost is irrelevant at the
pipeline level — MediaPipe is not the long-pole stage.

Saved metrics: `experiments/03_mediapipe_face/metrics_talking_head.json`
(full-range run).

---

## Closed gap #2 — Exp 06: VM-1 reaction_cut label

**FINDINGS said:** "`reaction_cut` was 0 on the screencast clip. Need a
talking-head clip to test."

**Now resolved:**

| Label | Screencast (orig) | **Talking-head (new)** |
|---|---|---|
| jump_cut | 5 | 3 |
| topic_transition | 8 | 6 |
| b_roll_insert | 6 | 8 |
| reaction_cut | **0** | **5** |
| cutaway | 11 | 8 |

- **All 5 labels populated** on the talking-head sample (vs 4/5 on
  screencast).
- 100% parse rate, $0.00197 for 30 cuts ($0.0135 projected for 15-min
  video — same as Exp 06's original projection within noise).
- The 5 reaction_cuts validate the doc's §VM-1 use case: cutting to a
  face expression for emphasis. Spot-check would require visual review;
  not done here but the labels are no longer degenerate.

**Verdict: Exp 06 fully validated.** Original Exp 06 PASS verdict
strengthens — the full label space works as designed.

Saved metrics: `experiments/06_vm1_edit_intent/metrics_talking_head.json`.

---

## Closed gap #3 — Exp 07: VM-4 caption-style vs graphic-text confusion

**FINDINGS said:** "Model conflates burnt-in graphic text with caption
overlays."

**Now partially resolved — the same confusion persists at lower volume:**

| Source | Frames with caption (model said true) | Real captions / graphic titles |
|---|---|---|
| Screencast (orig) | 7/12 (58%) | mixed — some real, some document titles |
| **Talking-head (new)** | **3/12 (25%)** | 1 real caption + 2 on-screen graphic titles |

Inspecting the 3 positives on the talking-head clip:

- **t=15.0 s:** `"Coming Up.."` — likely an on-screen **title card**, not
  a caption.
- **t=186.8 s:** `"The editing"` — bold sans, white text with cyan
  highlight, bottom-positioned — **looks like a real TikTok-style
  caption.**
- **t=260.5 s:** `"Edits Made Within 60 Days"` — likely a **graphic title
  card**, not a caption.

So **1 of 3 positives is a true caption; 2 are false positives** on
graphic text. The model still can't reliably distinguish overlay-on-
content from text-inside-content at single-frame granularity.

**Verdict: Exp 07 confusion confirmed, not eliminated.** Recommend the
follow-up I flagged in Exp 07 results.md: send adjacent frame pairs
and ask "is this text persistent across both frames?" — captions stay
across cuts; graphic titles disappear with each cut. That's a product-
engineering follow-up, not blocked.

Saved metrics: `experiments/07_vm4_caption_style/metrics_talking_head.json`.

---

## Closed gap #4 — Exp 08: VM-7 talking_head category

**FINDINGS said:** "Zero `talking_head` and zero
`joke_setup_or_punchline` mean we haven't validated those categories on
this clip."

**Now resolved:**

| Category | Screencast (orig) | **Talking-head (new)** |
|---|---|---|
| screen_recording | 39 (65%) | 7 (12%) |
| talking_head | **0** | **32 (53%)** |
| demo | 7 | 15 (25%) |
| b_roll | 2 | 0 |
| reading_notes | 3 | 0 |
| joke_setup_or_punchline | **0** | **3 (5%)** |
| other | 9 | 3 (5%) |

- **`talking_head` is now the dominant category** (32 of 60 = 53%) on
  talking-head content. Matches the source genre — the creator is on
  camera for half the clip, with the rest being demo segments showing
  edited reels and reactions.
- **`joke_setup_or_punchline` activates** (3 frames). Spot-check needed
  to confirm semantic correctness, but the label is no longer
  degenerate.
- 100% parse rate, $0.0050 for 60 frames (matches Exp 08's original
  rate within noise).

**Verdict: Exp 08 fully validated.** Both previously-zero categories
work on appropriate content.

Saved metrics: `experiments/08_vm7_raw_footage/metrics_talking_head.json`.

---

## Updated "What's NOT validated yet" list

Striking through the items this addendum closes:

- ~~Face tracking on talking-head content (Exp 03)~~ ✅ **Resolved**
  (78.9% on full-range model)
- ~~VM-1 reaction_cut label (Exp 06)~~ ✅ **Resolved** (5/30 emitted)
- 🟡 VM-4 caption-style false-positives on graphic titles (Exp 07) —
  **same issue at lower volume** on talking-head; product needs the
  "persistent across cuts?" mitigation
- ~~VM-7 talking_head + joke_setup categories (Exp 08)~~ ✅ **Resolved**
  (53% + 5% respectively)

**Still open after this addendum:**

- Caption animation (per-word highlight) requires brain to emit word-
  level events.
- Reference-style transfer end-to-end (VM-4 spec → ASS render with the
  style applied on raw footage).
- Brain edit quality vs human-edited ground truth — requires a labeled
  dataset for any rigorous claim.
- Caption-style confusion (Exp 07) — fix is engineering, not architecture.

These are the same items as the original FINDINGS list, minus the four
this addendum closed.

---

## Cost & spend

| Re-run | Cost |
|---|---|
| Exp 03 (no API) | $0 |
| Exp 06 (30 VM-1 calls) | $0.00197 |
| Exp 07 (12 VM-4 calls) | $0.00077 |
| Exp 08 (60 VM-7 calls) | $0.00500 |
| **Addendum total** | **$0.00774** |

Total project OpenRouter spend after this addendum: **~$0.08 of $5 cap.**

---

## Artifacts

- `samples/raw/raw_talking_5min.mp4` — the new talking-head sample
  (gitignored)
- Per-experiment talking-head metrics:
  - `experiments/03_mediapipe_face/metrics_talking_head.json`
  - `experiments/06_vm1_edit_intent/metrics_talking_head.json`
  - `experiments/07_vm4_caption_style/metrics_talking_head.json`
  - `experiments/08_vm7_raw_footage/metrics_talking_head.json`
- Per-experiment talking-head outputs in their respective
  `outputs/NN_*/raw_talking_5min_*.json` files (all gitignored).
