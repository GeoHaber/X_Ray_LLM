#!/usr/bin/env python3
"""
benchmark.py — Performance comparison: Python vs Rust X-Ray.

Runs both implementations N times on the same inputs and measures:
  • Wall-clock time (p50, p95, min, max)
  • Peak RSS memory (via tracemalloc for Python, /proc or perf for Rust)
  • Per-stage timings (if supported by Rust --stats flag)
  • Scaling behaviour (fixture set → medium project → large project)

Usage:
    python tests/rust_harness/benchmark.py --rust-bin ./target/release/xray
    python tests/rust_harness/benchmark.py --rust-bin xray.exe --iterations 10 --project C:\\code\\big
"""
from __future__ import annotations

import argparse
import gc
import json
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# Allow importing from parent dirs
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

HARNESS_DIR = Path(__file__).parent
FIXTURES_DIR = HARNESS_DIR / "fixtures"


# ─────────────────────────────────────────────────────────────────────────────
#  Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TimingResult:
    times_ms: List[float] = field(default_factory=list)
    peak_memory_kb: float = 0.0

    @property
    def min(self) -> float:
        return min(self.times_ms) if self.times_ms else 0.0

    @property
    def max(self) -> float:
        return max(self.times_ms) if self.times_ms else 0.0

    @property
    def mean(self) -> float:
        return statistics.mean(self.times_ms) if self.times_ms else 0.0

    @property
    def median(self) -> float:
        return statistics.median(self.times_ms) if self.times_ms else 0.0

    @property
    def p95(self) -> float:
        if len(self.times_ms) < 2:
            return self.max
        sorted_t = sorted(self.times_ms)
        idx = int(len(sorted_t) * 0.95)
        return sorted_t[min(idx, len(sorted_t) - 1)]

    @property
    def stdev(self) -> float:
        if len(self.times_ms) < 2:
            return 0.0
        return statistics.stdev(self.times_ms)


@dataclass
class BenchmarkSuite:
    name: str
    path: Path
    file_count: int = 0
    function_count: int = 0
    python: TimingResult = field(default_factory=TimingResult)
    rust: TimingResult = field(default_factory=TimingResult)

    @property
    def speedup_mean(self) -> float:
        if self.rust.mean > 0:
            return self.python.mean / self.rust.mean
        return 0.0

    @property
    def speedup_median(self) -> float:
        if self.rust.median > 0:
            return self.python.median / self.rust.median
        return 0.0

    @property
    def memory_reduction(self) -> float:
        if self.rust.peak_memory_kb > 0 and self.python.peak_memory_kb > 0:
            return 1.0 - (self.rust.peak_memory_kb / self.python.peak_memory_kb)
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  Python benchmark runner
# ─────────────────────────────────────────────────────────────────────────────

def _run_python_once(scan_path: Path) -> tuple[float, dict]:
    """Run Python X-Ray once, return (elapsed_ms, report)."""
    from x_ray_claude import scan_codebase  # type: ignore

    gc.collect()
    gc.disable()

    t0 = time.perf_counter()
    report = scan_codebase(str(scan_path), verbose=False)
    elapsed = (time.perf_counter() - t0) * 1000

    gc.enable()
    return elapsed, report


def bench_python(scan_path: Path, iterations: int, warmup: int = 1) -> TimingResult:
    """Benchmark the Python implementation."""
    result = TimingResult()

    # Warmup
    for _ in range(warmup):
        _run_python_once(scan_path)

    # Measure memory on the first real run
    tracemalloc.start()
    _, _ = _run_python_once(scan_path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result.peak_memory_kb = peak / 1024.0

    # Timed runs
    for i in range(iterations):
        elapsed, _ = _run_python_once(scan_path)
        result.times_ms.append(elapsed)
        sys.stdout.write(f"\r    Python: {i+1}/{iterations}")
        sys.stdout.flush()
    print()

    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Rust benchmark runner
# ─────────────────────────────────────────────────────────────────────────────

def _run_rust_once(rust_bin: str, scan_path: Path,
                   timeout: int = 120) -> tuple[float, dict]:
    """Run Rust X-Ray once, return (elapsed_ms, report)."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w"
    ) as tmp:
        report_path = tmp.name

    cmd = [
        rust_bin,
        "--path", str(scan_path),
        "--full-scan",
        "--report", report_path,
        "--quiet",
    ]

    t0 = time.perf_counter()
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        print(f"\n  ERROR: Rust binary not found: {rust_bin}")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        return timeout * 1000, {}
    elapsed = (time.perf_counter() - t0) * 1000

    report = {}
    rp = Path(report_path)
    if rp.exists():
        try:
            report = json.loads(rp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
        rp.unlink(missing_ok=True)

    return elapsed, report


def _get_rust_peak_memory(rust_bin: str, scan_path: Path) -> float:
    """
    Estimate Rust peak RSS in KB.

    On Windows, use the job object approach or just measure from outside.
    On Linux, use /usr/bin/time -v.
    Falls back to 0 if not measurable.
    """
    import platform

    if platform.system() == "Linux":
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as tmp:
            report_path = tmp.name
        cmd = [
            "/usr/bin/time", "-v",
            rust_bin, "--path", str(scan_path),
            "--full-scan", "--report", report_path, "--quiet",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            for line in proc.stderr.splitlines():
                if "Maximum resident set size" in line:
                    return float(line.split(":")[-1].strip())
        except Exception:
            pass
        finally:
            Path(report_path).unlink(missing_ok=True)

    elif platform.system() == "Windows":
        # Use PowerShell to get peak working set
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as tmp:
            report_path = tmp.name
        ps_cmd = (
            f'$p = Start-Process -FilePath "{rust_bin}" '
            f'-ArgumentList "--path","{scan_path}","--full-scan",'
            f'"--report","{report_path}","--quiet" '
            f'-PassThru -NoNewWindow -Wait; '
            f'$p.PeakWorkingSet64 / 1024'
        )
        try:
            proc = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=120,
            )
            return float(proc.stdout.strip())
        except Exception:
            pass
        finally:
            Path(report_path).unlink(missing_ok=True)

    return 0.0


def bench_rust(rust_bin: str, scan_path: Path,
               iterations: int, warmup: int = 1) -> TimingResult:
    """Benchmark the Rust implementation."""
    result = TimingResult()

    # Warmup
    for _ in range(warmup):
        _run_rust_once(rust_bin, scan_path)

    # Memory measurement
    result.peak_memory_kb = _get_rust_peak_memory(rust_bin, scan_path)

    # Timed runs
    for i in range(iterations):
        elapsed, _ = _run_rust_once(rust_bin, scan_path)
        result.times_ms.append(elapsed)
        sys.stdout.write(f"\r    Rust:   {i+1}/{iterations}")
        sys.stdout.flush()
    print()

    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Report
# ─────────────────────────────────────────────────────────────────────────────

def print_benchmark_report(suites: List[BenchmarkSuite]):
    """Print pretty benchmark comparison table."""
    print(f"\n  {'='*72}")
    print("    PERFORMANCE BENCHMARK: Python vs Rust")
    print(f"  {'='*72}")

    for s in suites:
        print(f"\n    --- {s.name} ({s.file_count} files, {s.function_count} funcs) ---")
        print(f"    {'Metric':<20s} {'Python':>12s} {'Rust':>12s} {'Factor':>10s}")
        print(f"    {'-'*54}")
        print(f"    {'Mean time':.<20s} {s.python.mean:>10.1f}ms {s.rust.mean:>10.1f}ms "
              f"{s.speedup_mean:>8.1f}x")
        print(f"    {'Median time':.<20s} {s.python.median:>10.1f}ms {s.rust.median:>10.1f}ms "
              f"{s.speedup_median:>8.1f}x")
        print(f"    {'p95 time':.<20s} {s.python.p95:>10.1f}ms {s.rust.p95:>10.1f}ms")
        print(f"    {'Min / Max':.<20s} "
              f"{s.python.min:>5.0f}/{s.python.max:<5.0f}ms "
              f"{s.rust.min:>5.0f}/{s.rust.max:<5.0f}ms")
        if s.python.peak_memory_kb > 0 or s.rust.peak_memory_kb > 0:
            print(f"    {'Peak memory':.<20s} "
                  f"{s.python.peak_memory_kb:>9.0f}KB {s.rust.peak_memory_kb:>9.0f}KB "
                  f"{s.memory_reduction*100:>7.0f}% less")

    print(f"\n  {'='*72}")

    # Aggregate
    if len(suites) > 1:
        total_py = sum(s.python.mean for s in suites)
        total_rs = sum(s.rust.mean for s in suites)
        if total_rs > 0:
            print(f"    Overall speedup: {total_py / total_rs:.1f}x (all suites combined)")
        print(f"  {'='*72}")
    print()


def save_benchmark_json(suites: List[BenchmarkSuite], output_path: Path):
    """Save benchmark results as JSON for automated CI comparison."""
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "suites": [],
    }
    for s in suites:
        data["suites"].append({
            "name": s.name,
            "path": str(s.path),
            "file_count": s.file_count,
            "function_count": s.function_count,
            "python": {
                "mean_ms": s.python.mean,
                "median_ms": s.python.median,
                "p95_ms": s.python.p95,
                "min_ms": s.python.min,
                "max_ms": s.python.max,
                "stdev_ms": s.python.stdev,
                "peak_memory_kb": s.python.peak_memory_kb,
                "iterations": len(s.python.times_ms),
            },
            "rust": {
                "mean_ms": s.rust.mean,
                "median_ms": s.rust.median,
                "p95_ms": s.rust.p95,
                "min_ms": s.rust.min,
                "max_ms": s.rust.max,
                "stdev_ms": s.rust.stdev,
                "peak_memory_kb": s.rust.peak_memory_kb,
                "iterations": len(s.rust.times_ms),
            },
            "speedup_mean": s.speedup_mean,
            "speedup_median": s.speedup_median,
            "memory_reduction": s.memory_reduction,
        })

    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Saved benchmark JSON to: {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Benchmark Python vs Rust X-Ray")
    parser.add_argument("--rust-bin", required=True, help="Path to Rust binary")
    parser.add_argument("--iterations", "-n", type=int, default=5,
                        help="Number of timed iterations (default: 5)")
    parser.add_argument("--warmup", type=int, default=2,
                        help="Warmup iterations (default: 2)")
    parser.add_argument("--project", type=str, default=None,
                        help="Additional real-world project path to benchmark")
    parser.add_argument("--output", type=str, default=None,
                        help="Save JSON results to this path")
    parser.add_argument("--python-only", action="store_true",
                        help="Only run Python benchmarks (baseline)")
    args = parser.parse_args()

    suites: list[BenchmarkSuite] = []

    # ── Suite 1: Fixtures (small) ────────────────────────────────────────────
    suite_fixtures = BenchmarkSuite(
        name="fixtures (small)",
        path=FIXTURES_DIR,
    )

    print(f"\n  Benchmarking: {suite_fixtures.name}")
    print(f"  Path: {FIXTURES_DIR}")

    # Count files/functions
    py_files = list(FIXTURES_DIR.glob("*.py"))
    suite_fixtures.file_count = len(py_files)
    func_count = 0
    for pf in py_files:
        content = pf.read_text(encoding="utf-8", errors="replace")
        func_count += content.count("\ndef ") + content.count("\n    def ")
    suite_fixtures.function_count = func_count

    suite_fixtures.python = bench_python(
        FIXTURES_DIR, args.iterations, warmup=args.warmup
    )

    if not args.python_only:
        suite_fixtures.rust = bench_rust(
            args.rust_bin, FIXTURES_DIR, args.iterations, warmup=args.warmup
        )

    suites.append(suite_fixtures)

    # ── Suite 2: Real project (optional) ─────────────────────────────────────
    if args.project:
        project_path = Path(args.project)
        if not project_path.is_dir():
            print(f"  WARN: Project path not found: {args.project}")
        else:
            suite_project = BenchmarkSuite(
                name=f"project ({project_path.name})",
                path=project_path,
            )

            # Count files
            all_py = list(project_path.rglob("*.py"))
            suite_project.file_count = len(all_py)
            fc = 0
            for pf in all_py[:200]:  # Sample for speed
                try:
                    content = pf.read_text(encoding="utf-8", errors="replace")
                    fc += content.count("\ndef ") + content.count("\n    def ")
                except OSError:
                    pass
            suite_project.function_count = fc

            print(f"\n  Benchmarking: {suite_project.name}")
            print(f"  Path: {project_path}")
            print(f"  Files: {suite_project.file_count}, ~{fc} functions")

            suite_project.python = bench_python(
                project_path, args.iterations, warmup=args.warmup
            )

            if not args.python_only:
                suite_project.rust = bench_rust(
                    args.rust_bin, project_path,
                    args.iterations, warmup=args.warmup
                )

            suites.append(suite_project)

    # ── Report ───────────────────────────────────────────────────────────────
    print_benchmark_report(suites)

    if args.output:
        save_benchmark_json(suites, Path(args.output))


if __name__ == "__main__":
    main()
