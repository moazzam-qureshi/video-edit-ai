
  Here's the full audit:

  ---
  Hardware findings

  CPU — AMD Ryzen 5 3600 (Zen 2)
  - 6 physical cores / 12 threads, boost ~4.2 GHz (currently scaling 115% of max → ~4.14 GHz observed)
  - Instruction sets: ✅ AVX, ✅ AVX2, ✅ FMA, ✅ F16C, ✅ SHA-NI, ✅ AES, ✅ BMI1/BMI2
  - ❌ No AVX-512 (Zen 2 doesn't have it). CTranslate2 / ONNX Runtime will fall back to AVX2 kernels — fully supported, just ~20–30% slower than an AVX-512
  box.
  - This is a desktop CPU on a dedicated/bare-metal host (systemd-detect-virt: none, cgroup: /init.scope), not a shared VPS slice. Good — the specs are
  real, not oversold.

  Memory — 64 GB real RAM + 32 GB swap
  - MemTotal: 65.7 GB confirmed in /proc/meminfo. 64 GB is genuine, not swap-padded.
  - 52 GB currently available. ⚠️ But 8 GB of swap is already in use despite 26 GB free RAM — something has been swapped out historically (uptime is 93
  days). Not a crisis, but worth a swapoff -a && swapon -a cleanup before heavy workloads to avoid stale pages slowing things down.
  - Swap is on /dev/md0 (NVMe RAID), so even swap is fast.

  Disk — 2× Toshiba KXG60ZNV512G NVMe SSDs in software RAID (md0/md1/md2)
  - 436 GB root, 317 GB free (24% used)
  - ROTA=0 → confirmed NVMe SSD (enterprise-grade Toshiba/Kioxia)
  - Sequential write: 763 MB/s — solid. Will not bottleneck video I/O even with multiple workers.
  - ⚠️ 317 GB free is tight if you're processing many 2-hour videos. A raw 1080p 2h video is 2–10 GB; intermediate frame dumps can easily 5–10× that. Plan
  disk hygiene (delete intermediates promptly) or expect to fill it.

  GPU
  - Physically present: GeForce GT 710 (a 2014 Kepler card, 2GB VRAM). Driver not loaded (nvidia-smi fails).
  - Even if you got the driver working: GT 710 is useless for ML (no usable tensor throughput, no modern CUDA features, won't help WhisperX or MediaPipe).
  Treat the box as CPU-only.

  Network
  - ~820 Mbps download (100 MB in <1 s). Model pulls and video transfers won't be a bottleneck.

  OS / environment
  - Ubuntu 24.04.4 LTS, kernel 6.8 — current and fine.
  - Python 3.12.3 installed (note: MediaPipe support for 3.12 is recent; if any dep balks, fall back to 3.11 in a venv).
  - ❌ ffmpeg is NOT installed. Must install: sudo apt install ffmpeg — Ubuntu's package includes libx264, libx265, AAC.
  - No speedtest-cli, no python symlink (only python3).

  Current load
  - Load avg 0.68 (12 logical cores → ~5% utilized). Plenty of headroom.
  - ⚠️ 12 logged-in users, 14 zombie processes, 8 GB swap used, 93-day uptime — this box is shared with other humans/workloads. The top snapshot caught my
  own claude process at 213% CPU, but no other heavy hitters. Still: someone else may spike CPU/RAM unpredictably. Worth checking who/what those 12 sessions
   are before committing to long jobs.
  - Tailscale running (~31 min CPU total over 93 days — negligible).

  Limits
  - ulimit -n 1048576 open files ✅
  - ulimit -u 256566 processes ✅
  - Both very generous; no need to raise.

  ---
  Verdict: 🟡 YELLOW — workload is feasible, but with real caveats

  The hardware itself is solid (6c/12t Zen 2 + 64 GB ECC-class workstation RAM + NVMe RAID + fast network). What pulls it to yellow:

  1. No AVX-512 → CTranslate2 runs at ~70–80% of an AVX-512 chip's speed. Not a blocker, just slower.
  2. Shared multi-user box — 12 user sessions, 8 GB swap in use, zombies. Resource contention is a real risk for long jobs.
  3. ffmpeg missing — install before doing anything.
  4. 317 GB free disk gets eaten fast with multi-hour videos + intermediate frames.

  Realistic throughput estimates (Ryzen 5 3600, CPU-only, int8)

  ┌─────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────────────┐
  │                    Task                     │                     Throughput (single worker, 8 threads)                     │
  ├─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ WhisperX large-v2 int8 (faster-whisper)     │ ~0.4–0.6× realtime → 15 min audio ≈ 25–37 min transcribe; 2 h audio ≈ 3.5–5 h │
  ├─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ WhisperX large-v3 int8                      │ ~0.3–0.5× realtime → 2 h audio ≈ 4–7 h                                        │
  ├─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ WhisperX medium int8                        │ ~1.0–1.5× realtime (consider if quality allows)                               │
  ├─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ PySceneDetect (content detector)            │ ~3–8× realtime on 1080p                                                       │
  ├─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ MediaPipe face detect, every frame, 1080p30 │ ~0.5–1.5× realtime per worker — the second-biggest CPU sink after Whisper     │
  ├─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ Librosa + Silero VAD                        │ ~5–20× realtime, trivial                                                      │
  ├─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ ffmpeg libx264 1080p encode (medium preset) │ ~1–2× realtime                                                                │
  ├─────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────────────┤
  │ ffmpeg libx265 1080p encode (medium preset) │ ~0.2–0.5× realtime — avoid x265 unless you really need it; use x264           │
  └─────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────────────┘

  Parallelism

  - 6 physical cores. WhisperX wants ~4–8 threads to be efficient; MediaPipe scales to ~4 threads.
  - Realistic parallel pipelines: 2 concurrent video workers, each pinned to ~4–6 threads. Going to 3 will cause cache/thread thrashing and slow each job
  ~40%.
  - RAM-wise 2 workers fit comfortably: WhisperX large int8 ≈ 3–4 GB, MediaPipe ≈ 1 GB, ffmpeg buffers ≈ 1 GB → ~12 GB for 2 workers, well within 52 GB
  available.

  Bottom line on 2-hour videos

  - A 2-hour video, end-to-end (transcribe + scene detect + face detect every frame + re-encode), will take roughly 5–8 hours on one worker with large-v3,
  or 3.5–5 hours with large-v2. If that's acceptable batch-style, you're fine. If you need near-realtime, rent GPU time for the Whisper step — that's by far
   the dominant cost.

  ---
  Concrete fixes before starting

  1. sudo apt update && sudo apt install -y ffmpeg libsndfile1 libgl1 libglib2.0-0 (ffmpeg + libs MediaPipe/OpenCV/librosa need)
  2. sudo swapoff -a && sudo swapon -a — flush 8 GB stale swap before heavy runs
  3. Decide on large-v2 over large-v3 unless you specifically need v3's quality — v2 is meaningfully faster on CPU for similar WER on English
  4. Use a Python 3.11 venv if MediaPipe install on 3.12 gives you trouble (it usually works now, but 3.11 is the safe path)
  5. Set OMP_NUM_THREADS=4 (or 6) per worker, and CT2_USE_EXPERIMENTAL_PACKED_GEMM=1 for CTranslate2 — measurable speedup on Zen 2
  6. Cap concurrency at 2 video pipelines; reject a 3rd or queue it
  7. Add a disk-space guard (refuse new job if <50 GB free) — running out mid-encode is the easiest way to corrupt outputs
  8. Find out who else uses this box (who, last) — if any of those 12 sessions also run heavy jobs, your throughput estimates above can drop 30–50%
  9. Skip libx265 unless you genuinely need the size savings; libx264 medium is 5–10× faster on CPU

  If the 5–8h-per-2h-video number is a dealbreaker, the right answer is not a bigger CPU box — it's a small GPU rental for the Whisper step only (a single
  H100 hour will do what this CPU does in a full day).