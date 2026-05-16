"""
Instrumentation context manager used by every experiment.

Typical usage at the bottom of an experiment's run.py:

    from experiments._shared.instrument import Run

    with Run(experiment="01_whisperx", out_dir="experiments/01_whisperx") as run:
        run.note(model="large-v2", quant="int8", clip="raw_15min.mp4")
        result = do_the_work(...)
        run.metric("words_transcribed", len(result.words))
        run.metric("rtf", result.duration_s / run.elapsed_so_far())

On __exit__, writes:
    <out_dir>/metrics.json   — all collected metrics + system context

Captures (all sampled while the `with` block runs):
    - wall_clock_s          : time.perf_counter delta
    - peak_rss_mb           : peak resident set size of THIS process (and children if available)
    - cpu_avg_pct           : average system-wide CPU% during the block
    - cpu_peak_pct          : peak system-wide CPU% during the block
    - disk_used_delta_mb    : disk-usage delta of the experiment folder
    - system                : machine fingerprint (CPU, RAM, OS) for traceability
    - user_metrics          : whatever the experiment recorded via .metric() / .note()

The system fingerprint matters because results are only meaningful relative to the
hardware they were measured on (per vps_specs.md). A metrics.json taken on a
laptop is a different beast from one taken on the Ryzen VPS — recording the
fingerprint makes that explicit and prevents bad comparisons.
"""

from __future__ import annotations

import json
import os
import platform
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _system_fingerprint() -> dict[str, Any]:
    """Snapshot of the box at run time. Lets us tell results apart later."""
    vm = psutil.virtual_memory()
    cpu_freq = psutil.cpu_freq()
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_model": platform.processor() or "unknown",
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_freq_max_mhz": getattr(cpu_freq, "max", None),
        "ram_total_gb": round(vm.total / 1024**3, 2),
        "ram_available_gb_at_start": round(vm.available / 1024**3, 2),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
        "ct2_packed_gemm": os.environ.get("CT2_USE_EXPERIMENTAL_PACKED_GEMM"),
    }


@dataclass
class _Sampler:
    """Background thread that samples CPU% and RSS every `interval_s`."""

    interval_s: float = 0.5
    cpu_samples: list[float] = field(default_factory=list)
    rss_samples_mb: list[float] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def _loop(self) -> None:
        proc = psutil.Process(os.getpid())
        proc.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None)
        while not self._stop.wait(self.interval_s):
            try:
                self.cpu_samples.append(psutil.cpu_percent(interval=None))
                rss = proc.memory_info().rss
                for child in proc.children(recursive=True):
                    try:
                        rss += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                self.rss_samples_mb.append(rss / 1024**2)
            except Exception:
                continue

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


class Run:
    """
    Context manager for one experimental run.

    Args:
        experiment: short id, e.g. "01_whisperx". Goes into metrics.json.
        out_dir:    folder where metrics.json is written. Usually the experiment folder itself.
        sample_interval_s: how often the background sampler ticks. Default 0.5 s — fine for
                           multi-minute jobs. Drop to 0.1 s only for sub-10s runs.
    """

    def __init__(
        self,
        experiment: str,
        out_dir: str | Path,
        sample_interval_s: float = 0.5,
    ) -> None:
        self.experiment = experiment
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._sampler = _Sampler(interval_s=sample_interval_s)
        self._t0: float = 0.0
        self._t1: float = 0.0
        self._disk_start_bytes: int = 0
        self._metrics: dict[str, Any] = {}
        self._notes: dict[str, Any] = {}
        self._started_at_iso: str = ""

    def __enter__(self) -> "Run":
        self._started_at_iso = datetime.now(timezone.utc).isoformat()
        self._disk_start_bytes = _dir_size_bytes(self.out_dir)
        self._sampler.start()
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._t1 = time.perf_counter()
        self._sampler.stop()

        wall_clock_s = self._t1 - self._t0
        cpu_samples = self._sampler.cpu_samples
        rss_samples = self._sampler.rss_samples_mb
        disk_delta_mb = (_dir_size_bytes(self.out_dir) - self._disk_start_bytes) / 1024**2

        record = {
            "experiment": self.experiment,
            "started_at_utc": self._started_at_iso,
            "wall_clock_s": round(wall_clock_s, 3),
            "cpu_avg_pct": round(sum(cpu_samples) / len(cpu_samples), 1) if cpu_samples else None,
            "cpu_peak_pct": round(max(cpu_samples), 1) if cpu_samples else None,
            "cpu_samples_n": len(cpu_samples),
            "peak_rss_mb": round(max(rss_samples), 1) if rss_samples else None,
            "avg_rss_mb": round(sum(rss_samples) / len(rss_samples), 1) if rss_samples else None,
            "disk_delta_mb": round(disk_delta_mb, 2),
            "exception": None if exc_type is None else f"{exc_type.__name__}: {exc}",
            "system": _system_fingerprint(),
            "notes": self._notes,
            "metrics": self._metrics,
        }

        metrics_path = self.out_dir / "metrics.json"
        metrics_path.write_text(json.dumps(record, indent=2, sort_keys=False))
        print(f"[instrument] wrote {metrics_path}")
        print(
            f"[instrument] wall_clock={record['wall_clock_s']}s "
            f"cpu_avg={record['cpu_avg_pct']}% "
            f"peak_rss={record['peak_rss_mb']}MB "
            f"disk_delta={record['disk_delta_mb']}MB"
        )

    def elapsed_so_far(self) -> float:
        """Seconds since __enter__. Useful for computing RTF mid-run."""
        return time.perf_counter() - self._t0

    def metric(self, name: str, value: Any) -> None:
        """Record a numeric/structured result (accuracy, throughput, $, etc.)."""
        self._metrics[name] = value

    def note(self, **kwargs: Any) -> None:
        """Record free-form context (model name, clip name, params)."""
        self._notes.update(kwargs)


def self_test() -> int:
    """Smoke-test the instrumentation. Run from CLI to verify the box is set up."""
    out = Path(__file__).parent / "_selftest"
    with Run(experiment="_selftest", out_dir=out, sample_interval_s=0.1) as run:
        run.note(purpose="verify instrument.py works end-to-end")
        total = 0
        for i in range(200_000):
            total += i * i
        run.metric("loop_sum", total)
        time.sleep(1.0)
    print("[self_test] OK — see metrics.json in", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
