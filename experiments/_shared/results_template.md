# Experiment NN — <short name>

**Phase:** <Phase 1 / 2 / 3 / 4 / 5>
**Status:** planned | running | done
**Verdict:** PASS | FAIL | PARTIAL | — (fill on completion)
**Date run:** YYYY-MM-DD (UTC)
**Run by:** <human / claude>
**Host:** <hostname — vps / windows / etc.>

## Goal

One paragraph: what assumption are we testing, what's the gate to pass, why it matters for the product.

## Gate (from the plan)

Paste the exact GO/NO-GO criterion from the plan. Be precise — the verdict refers back to this.

> Example: large-v2 RTF ≥ 0.4 AND word-timestamp accuracy ≥ 90% within ±150 ms.

## What we ran

- Inputs: which sample video(s) and clip range(s)
- Models / params: model name, quant, threads, any flags
- Hardware: CPU model, RAM available at start (auto-captured in metrics.json — paste the relevant line)
- Command(s): the exact CLI you invoked

```bash
python experiments/NN_xxx/run.py --clip samples/raw/raw_15min.mp4 --model large-v2
```

## Observations

Bullet list. Be specific. Include numbers from metrics.json. Note anything surprising.

- Wall-clock: ____ s on a ____-s input → RTF = ____
- Peak RSS: ____ MB
- CPU avg / peak: ____ % / ____ %
- Task-specific quality metric: ____ (e.g. word-timestamp accuracy 92.3% within ±150 ms)
- Cost (if applicable): $____ (input tokens ____ + output tokens ____)

## Verdict against gate

State explicitly which gate clauses passed, which failed, with the specific numbers.

> Example: ✅ RTF gate (0.42 ≥ 0.40). ❌ Accuracy gate (87.1% < 90%). Overall: FAIL.

## Open questions / follow-ups

What's still unclear? What's the next experiment that gets triggered (e.g. "Exp 01b: retry with medium model")?

## Artifacts

Paths to anything produced (transcript JSONs, frame folders, output videos). These are gitignored — note their sizes so future-you knows what to regenerate.

- `outputs/01_whisperx/transcript_large-v2.json` (4.2 MB)
- `outputs/01_whisperx/words.csv` (180 KB)

## Links

- metrics.json: `experiments/NN_xxx/metrics.json`
- Related experiments: NN, NN
- Product doc reference: lines XXX–YYY of [product.md](../../docs/product.md)
