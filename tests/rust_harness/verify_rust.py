#!/usr/bin/env python3
"""
verify_rust.py — Run the Rust binary on every fixture set and compare
its JSON output against the Python golden files.

This is the heart of the cross-language test harness. It verifies:
  1. CORRECTNESS — every field matches (counts, categories, keys, etc.)
  2. COMPLETENESS — no smells/duplicates missing or extra
  3. INVARIANTS — semantic properties that must hold regardless of impl

Usage:
    python tests/rust_harness/verify_rust.py --rust-bin ./target/release/xray
    python tests/rust_harness/verify_rust.py --rust-bin xray.exe --verbose
    python tests/rust_harness/verify_rust.py --rust-bin xray.exe --suite exact_dupes
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional


# ── Paths ────────────────────────────────────────────────────────────────────
HARNESS_DIR = Path(__file__).parent
FIXTURES_DIR = HARNESS_DIR / "fixtures"
GOLDEN_DIR = HARNESS_DIR / "golden"


# ─────────────────────────────────────────────────────────────────────────────
#  Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Mismatch:
    """A single verification mismatch."""
    field: str
    expected: Any
    actual: Any
    severity: str = "ERROR"  # ERROR | WARN | INFO
    message: str = ""


@dataclass
class SuiteResult:
    """Result of running one verification suite."""
    name: str
    status: str = "PENDING"     # PASS | FAIL | SKIP | ERROR
    mismatches: List[Mismatch] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rust_time_ms: float = 0.0
    python_time_ms: float = 0.0
    speedup: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def error_count(self) -> int:
        return sum(1 for m in self.mismatches if m.severity == "ERROR")

    @property
    def warn_count(self) -> int:
        return sum(1 for m in self.mismatches if m.severity == "WARN")


# ─────────────────────────────────────────────────────────────────────────────
#  Rust binary runner
# ─────────────────────────────────────────────────────────────────────────────

def run_rust_binary(rust_bin: str, fixture_path: Path,
                    include_files: Optional[List[str]] = None,
                    timeout: int = 120) -> tuple[dict, float]:
    """
    Execute the Rust X-Ray binary and capture its JSON report.

    The Rust binary must support the same CLI contract as the Python version:
        xray --path <dir> --full-scan --report <file> --quiet

    Returns:
        (report_dict, elapsed_ms)
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
        report_path = tmp.name

    cmd = [
        rust_bin,
        "--path", str(fixture_path),
        "--full-scan",
        "--report", report_path,
        "--quiet",
    ]

    # If specific files, pass as include filter
    if include_files:
        cmd.extend(["--include"] + include_files)

    t0 = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {}, timeout * 1000
    except FileNotFoundError:
        print(f"  ERROR: Rust binary not found at: {rust_bin}")
        print("         Build with: cargo build --release")
        sys.exit(1)

    elapsed = (time.perf_counter() - t0) * 1000  # ms

    if result.returncode != 0:
        print(f"  WARN: Rust binary exited with code {result.returncode}")
        if result.stderr:
            print(f"  stderr: {result.stderr[:500]}")

    # Read the JSON report
    report_file = Path(report_path)
    if not report_file.exists():
        return {}, elapsed

    try:
        report = json.loads(report_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ERROR: Failed to parse Rust JSON output: {e}")
        report = {}
    finally:
        report_file.unlink(missing_ok=True)

    return report, elapsed


# ─────────────────────────────────────────────────────────────────────────────
#  Comparison engine
# ─────────────────────────────────────────────────────────────────────────────

def _compare_scalar(field: str, expected, actual, result: SuiteResult,
                    severity: str = "ERROR"):
    """Compare a single scalar value."""
    if expected != actual:
        result.mismatches.append(Mismatch(
            field=field, expected=expected, actual=actual,
            severity=severity,
            message=f"{field}: expected {expected!r}, got {actual!r}",
        ))


def _compare_set(field: str, expected: set, actual: set,
                 result: SuiteResult, severity: str = "ERROR"):
    """Compare two sets, reporting missing and extra items."""
    missing = expected - actual
    extra = actual - expected
    if missing:
        result.mismatches.append(Mismatch(
            field=f"{field} (missing)",
            expected=sorted(missing), actual=None,
            severity=severity,
            message=f"{field}: missing {len(missing)} items: {sorted(missing)[:5]}",
        ))
    if extra:
        result.mismatches.append(Mismatch(
            field=f"{field} (extra)",
            expected=None, actual=sorted(extra),
            severity=severity,
            message=f"{field}: {len(extra)} unexpected items: {sorted(extra)[:5]}",
        ))


def _compare_list_sorted(field: str, expected: list, actual: list,
                         result: SuiteResult, severity: str = "ERROR"):
    """Compare two sorted lists element-by-element."""
    if expected != actual:
        # Find first difference
        for i, (e, a) in enumerate(zip(expected, actual)):
            if e != a:
                result.mismatches.append(Mismatch(
                    field=f"{field}[{i}]",
                    expected=e, actual=a,
                    severity=severity,
                    message=f"{field}[{i}]: expected {e!r}, got {a!r}",
                ))
                break
        if len(expected) != len(actual):
            result.mismatches.append(Mismatch(
                field=f"{field} (length)",
                expected=len(expected), actual=len(actual),
                severity=severity,
                message=f"{field}: expected {len(expected)} items, got {len(actual)}",
            ))


def _compare_similarity(field: str, expected: float, actual: float,
                        result: SuiteResult, tolerance: float = 0.05):
    """Compare float similarity values with tolerance."""
    if abs(expected - actual) > tolerance:
        result.mismatches.append(Mismatch(
            field=field,
            expected=expected, actual=actual,
            severity="WARN",
            message=f"{field}: expected ~{expected:.3f}, got {actual:.3f} (tol={tolerance})",
        ))


def _verify_hard_counts(exp, rust_stats, result):
    """L1: Verify total functions/classes/files/lines match exactly."""
    _compare_scalar("total_functions", exp.get("total_functions"),
                    rust_stats.get("total_functions"), result)
    _compare_scalar("total_classes", exp.get("total_classes"),
                    rust_stats.get("total_classes"), result)
    _compare_scalar("total_files", exp.get("total_files"),
                    rust_stats.get("total_files"), result)
    _compare_scalar("total_lines", exp.get("total_lines"),
                    rust_stats.get("total_lines"), result)


def _verify_smells(exp, rust_smells, rust_issues, result):
    """L2: Verify smell counts, categories, and fingerprints."""
    _compare_scalar("smell_total", exp.get("smell_total"),
                    rust_smells.get("total"), result)

    exp_sev = exp.get("smell_severities", {})
    rust_sev = {
        "critical": sum(1 for s in rust_issues if s.get("severity") == "critical"),
        "warning": sum(1 for s in rust_issues if s.get("severity") == "warning"),
        "info": sum(1 for s in rust_issues if s.get("severity") == "info"),
    }
    for sev in ("critical", "warning", "info"):
        _compare_scalar(f"smell_{sev}_count",
                        exp_sev.get(sev, 0), rust_sev.get(sev, 0), result)

    exp_cats = set(exp.get("smell_categories", []))
    rust_cats = set(s.get("category", "") for s in rust_issues)
    _compare_set("smell_categories", exp_cats, rust_cats, result)

    rust_fingerprints = sorted([
        f"{s.get('file', '')}:{s.get('line', 0)}:{s.get('category', '')}:"
        f"{s.get('severity', '')}:{s.get('name', '')}"
        for s in rust_issues
    ])
    exp_fingerprints = exp.get("smell_fingerprints", [])
    _compare_list_sorted("smell_fingerprints", exp_fingerprints,
                         rust_fingerprints, result)


def _verify_duplicates(exp, rust_dups, rust_groups, golden, result):
    """L2: Verify duplicate group counts and membership."""
    _compare_scalar("dup_total_groups", exp.get("dup_total_groups"),
                    rust_dups.get("total_groups"), result)

    exp_dtypes = exp.get("dup_types", {})
    rust_dtypes = {
        "exact": sum(1 for g in rust_groups if g.get("type") == "exact"),
        "structural": sum(1 for g in rust_groups if g.get("type") == "structural"),
        "near": sum(1 for g in rust_groups if g.get("type") == "near"),
        "semantic": sum(1 for g in rust_groups if g.get("type") == "semantic"),
    }
    for dtype in ("exact", "structural", "near", "semantic"):
        _compare_scalar(f"dup_{dtype}_count",
                        exp_dtypes.get(dtype, 0), rust_dtypes.get(dtype, 0), result)

    exp_group_keys = exp.get("dup_group_keys", [])
    rust_group_keys = [
        sorted([f.get("key", "") for f in g.get("functions", [])])
        for g in sorted(rust_groups, key=lambda g: g.get("id", 0))
    ]
    if len(exp_group_keys) == len(rust_group_keys):
        for i, (eg, rg) in enumerate(zip(exp_group_keys, rust_group_keys)):
            if eg != rg:
                result.mismatches.append(Mismatch(
                    field=f"dup_group[{i}].keys",
                    expected=eg, actual=rg,
                    severity="ERROR",
                    message=f"Group {i} membership differs",
                ))
    elif exp_group_keys or rust_group_keys:
        result.mismatches.append(Mismatch(
            field="dup_group_count",
            expected=len(exp_group_keys), actual=len(rust_group_keys),
            severity="ERROR",
            message=f"Group count mismatch: {len(exp_group_keys)} vs {len(rust_group_keys)}",
        ))

    # L3: Similarity values (soft check)
    golden_groups = golden.get("duplicates", {}).get("groups", [])
    for gg, rg in zip(
        sorted(golden_groups, key=lambda g: g.get("id", 0)),
        sorted(rust_groups, key=lambda g: g.get("id", 0)),
    ):
        _compare_similarity(
            f"group_{gg.get('id')}_avg_similarity",
            gg.get("avg_similarity", 0),
            rg.get("avg_similarity", 0),
            result,
            tolerance=0.05,
        )

    return rust_dtypes


def _verify_lib_suggestions(exp, rust_lib, result):
    """L2: Verify library suggestion counts and modules."""
    _compare_scalar("lib_total", exp.get("lib_total"),
                    rust_lib.get("total"), result)
    exp_modules = set(exp.get("lib_modules", []))
    rust_modules = set(s.get("module", "") for s in rust_lib.get("suggestions", []))
    _compare_set("lib_modules", exp_modules, rust_modules, result, severity="WARN")


def _verify_suite_assertions(exp, rust_smells, rust_dtypes,
                             rust_issues, rust_groups, result):
    """Verify suite-specific boolean assertions."""
    if exp.get("assert_zero_smells") and rust_smells.get("total", 0) > 0:
        result.mismatches.append(Mismatch(
            field="assert_zero_smells",
            expected=0, actual=rust_smells["total"],
            severity="ERROR",
            message="Clean code suite should produce zero smells!",
        ))

    for dtype_assert in ("exact", "structural", "near", "semantic"):
        flag = f"assert_has_{dtype_assert}_groups"
        if exp.get(flag) and rust_dtypes.get(dtype_assert, 0) == 0:
            result.mismatches.append(Mismatch(
                field=flag,
                expected=f">0 {dtype_assert} groups", actual=0,
                severity="ERROR",
                message=f"Expected at least one {dtype_assert} duplicate group!",
            ))

    if exp.get("assert_has_async_function"):
        result.warnings.append("Note: async function detection not yet verified in JSON")

    if exp.get("assert_nested_excluded"):
        all_names = set()
        for g in rust_groups:
            for f in g.get("functions", []):
                all_names.add(f.get("name", ""))
        for s in rust_issues:
            all_names.add(s.get("name", ""))
        if "_inner_helper" in all_names:
            result.mismatches.append(Mismatch(
                field="assert_nested_excluded",
                expected="no _inner_helper", actual="_inner_helper found",
                severity="ERROR",
                message="Nested function _inner_helper should not be extracted!",
            ))


def verify_suite(golden: dict, rust_report: dict) -> SuiteResult:
    """
    Compare Rust output against golden expectations.

    Three levels of verification:
      L1 — Hard counts: total functions/classes/files/lines MUST match
      L2 — Smell/duplicate detection: categories, keys, fingerprints MUST match
      L3 — Similarity values: SHOULD be close (within tolerance)
    """
    exp = golden.get("_expectations", {})
    suite_meta = golden.get("_suite", {})
    result = SuiteResult(name=suite_meta.get("name", "unknown"))

    if not rust_report:
        result.status = "ERROR"
        result.mismatches.append(Mismatch(
            field="report", expected="valid JSON", actual=None,
            severity="ERROR", message="Rust produced no JSON output.",
        ))
        return result

    rust_stats = rust_report.get("stats", {})
    rust_smells = rust_report.get("smells", {})
    rust_dups = rust_report.get("duplicates", {})
    rust_lib = rust_report.get("library_suggestions", {})
    rust_issues = rust_smells.get("issues", [])
    rust_groups = rust_dups.get("groups", [])

    _verify_hard_counts(exp, rust_stats, result)
    _verify_smells(exp, rust_smells, rust_issues, result)
    rust_dtypes = _verify_duplicates(exp, rust_dups, rust_groups, golden, result)
    _verify_lib_suggestions(exp, rust_lib, result)
    _verify_suite_assertions(exp, rust_smells, rust_dtypes,
                             rust_issues, rust_groups, result)

    result.status = "FAIL" if result.error_count > 0 else "PASS"
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Report generator
# ─────────────────────────────────────────────────────────────────────────────

def print_results(results: List[SuiteResult], verbose: bool = False):
    """Print a pretty verification report."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print(f"\n  {'='*60}")
    print("    RUST VERIFICATION REPORT")
    print(f"  {'='*60}")

    for r in results:
        icon = "✓" if r.passed else "✗"
        perf = ""
        if r.rust_time_ms > 0 and r.python_time_ms > 0:
            r.speedup = r.python_time_ms / r.rust_time_ms if r.rust_time_ms > 0 else 0
            perf = f" ({r.rust_time_ms:.0f}ms, {r.speedup:.1f}x faster)"
        print(f"    {icon} {r.name:<25s} {r.status:<6s}"
              f"  errors={r.error_count} warns={r.warn_count}{perf}")

        if verbose or not r.passed:
            for m in r.mismatches:
                sev_icon = "!!" if m.severity == "ERROR" else "?"
                print(f"      [{sev_icon}] {m.message}")
            for w in r.warnings:
                print(f"      [i] {w}")

    print(f"\n  {'-'*60}")
    print(f"    Total: {total}  ✓ Passed: {passed}  ✗ Failed: {failed}")

    # Performance summary
    rust_total = sum(r.rust_time_ms for r in results)
    py_total = sum(r.python_time_ms for r in results)
    if rust_total > 0 and py_total > 0:
        overall_speedup = py_total / rust_total
        print(f"\n    Performance: Python {py_total:.0f}ms → Rust {rust_total:.0f}ms "
              f"({overall_speedup:.1f}x speedup)")

    print(f"  {'='*60}\n")
    return failed == 0


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Verify Rust X-Ray binary against Python golden outputs",
    )
    parser.add_argument("--rust-bin", required=True,
                        help="Path to the Rust X-Ray binary")
    parser.add_argument("--suite", default=None,
                        help="Run only this suite (default: all)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show all comparison details")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Timeout per suite in seconds")
    args = parser.parse_args()

    # Discover golden files
    golden_files = sorted(GOLDEN_DIR.glob("*.json"))
    if not golden_files:
        print("  ERROR: No golden files found. Run generate_golden.py first.")
        sys.exit(1)

    results: list[SuiteResult] = []

    for golden_path in golden_files:
        suite_name = golden_path.stem
        if args.suite and suite_name != args.suite:
            continue

        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        suite_meta = golden.get("_suite", {})
        fixture_files = suite_meta.get("fixture_files", [])

        print(f"  [RUN] {suite_name}...")

        # Run Rust binary
        rust_report, rust_ms = run_rust_binary(
            args.rust_bin, FIXTURES_DIR, fixture_files, timeout=args.timeout
        )

        # Python time from golden (stored during generation)
        py_ms = golden.get("scan_time_seconds", 0) * 1000

        # Compare
        result = verify_suite(golden, rust_report)
        result.rust_time_ms = rust_ms
        result.python_time_ms = py_ms
        results.append(result)

    if not results:
        print(f"  No matching suites found (--suite={args.suite})")
        sys.exit(1)

    all_passed = print_results(results, verbose=args.verbose)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
