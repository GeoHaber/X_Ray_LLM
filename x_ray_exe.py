#!/usr/bin/env python3
"""
X-Ray Standalone — Self-Contained Windows Code Quality Scanner
===============================================================

This is the standalone entry point for the X-Ray .exe build.
It bundles:
  - Hardware detection (CPU, OS, RAM)
  - Tool availability checks (ruff, bandit, Rust extensions)
  - Full code quality scanning (smells, duplicates, lint, security)
  - Rust porting advisor
  - JSON report export

Works on any Windows machine without requiring Python or any
external tools to be pre-installed (all bundled inside the .exe).

Usage::

    x_ray.exe --path C:\\my_project                  # full scan
    x_ray.exe --path . --smell                       # smells only
    x_ray.exe --path . --lint                        # lint only
    x_ray.exe --path . --security                    # security only
    x_ray.exe --path . --duplicates                  # duplicates only
    x_ray.exe --path . --full-scan                   # everything
    x_ray.exe --path . --rustify                     # Rust porting advisor
    x_ray.exe --path . --report out.json             # save JSON report
    x_ray.exe --hw                                   # hardware info only
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import concurrent.futures
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

# ---------------------------------------------------------------------------
# Fix for PyInstaller frozen bundles: ensure our package root is on sys.path
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    _BUNDLE_DIR = Path(sys._MEIPASS)
    _EXE_DIR = Path(sys.executable).parent
    # Add the bundle dir so our Core/Analysis/Lang packages are importable
    if str(_BUNDLE_DIR) not in sys.path:
        sys.path.insert(0, str(_BUNDLE_DIR))
else:
    _BUNDLE_DIR = Path(__file__).resolve().parent
    _EXE_DIR = _BUNDLE_DIR

# ---------------------------------------------------------------------------
# Imports from the X-Ray project
# ---------------------------------------------------------------------------
from Core.types import FunctionRecord, ClassRecord
from Core.config import __version__

from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.reporting import (
    print_smells, print_duplicates, print_lint_report,
    print_security_report, print_unified_grade,
)

# ---------------------------------------------------------------------------
# ASCII Art banner
# ---------------------------------------------------------------------------

_EXE_BANNER = f"""
{'='*66}
  X-RAY v{__version__} — Standalone Code Quality Scanner (.exe)
  AST Smells + Ruff Lint + Bandit Security + Rust Advisor
{'='*66}
"""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

from Core.utils import setup_logger
log = setup_logger("x_ray_exe")


# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------

def detect_hardware() -> Dict[str, Any]:
    """Detect CPU, OS, RAM and other hardware info."""
    info: Dict[str, Any] = {}

    # OS
    info["os"] = platform.system()
    info["os_version"] = platform.version()
    info["os_release"] = platform.release()
    info["machine"] = platform.machine()

    # CPU
    info["processor"] = platform.processor() or "Unknown"
    info["cpu_count_logical"] = os.cpu_count() or 1

    # Physical cores (Windows)
    try:
        result = subprocess.run(
            ["wmic", "cpu", "get", "NumberOfCores", "/value"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split('\n'):
            if line.startswith("NumberOfCores="):
                info["cpu_count_physical"] = int(line.split('=')[1].strip())
    except Exception:
        info["cpu_count_physical"] = info["cpu_count_logical"]

    # RAM (Windows)
    try:
        result = subprocess.run(
            ["wmic", "os", "get", "TotalVisibleMemorySize", "/value"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split('\n'):
            if line.startswith("TotalVisibleMemorySize="):
                kb = int(line.split('=')[1].strip())
                info["ram_gb"] = round(kb / 1024 / 1024, 1)
    except Exception:
        info["ram_gb"] = "unknown"

    # CPU name
    try:
        result = subprocess.run(
            ["wmic", "cpu", "get", "Name", "/value"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split('\n'):
            if line.startswith("Name="):
                info["cpu_name"] = line.split('=', 1)[1].strip()
    except Exception:
        info["cpu_name"] = info["processor"]

    # Check for Rust environment
    info["rust_available"] = shutil.which("rustc") is not None
    if info["rust_available"]:
        try:
            result = subprocess.run(
                ["rustc", "--version"],
                capture_output=True, text=True, timeout=5
            )
            info["rust_version"] = result.stdout.strip()
        except Exception:
            info["rust_version"] = "unknown"

    # Check for x_ray_core (Rust acceleration)
    try:
        import x_ray_core  # noqa: F401
        info["rust_acceleration"] = True
    except ImportError:
        info["rust_acceleration"] = False

    return info


def print_hardware(hw: Dict[str, Any]) -> None:
    """Pretty-print hardware information."""
    print(f"\n{'='*50}")
    print("  SYSTEM HARDWARE PROFILE")
    print(f"{'='*50}")
    print(f"  OS:           {hw['os']} {hw.get('os_release', '')} ({hw['machine']})")
    print(f"  CPU:          {hw.get('cpu_name', hw['processor'])}")
    print(f"  Cores:        {hw.get('cpu_count_physical', '?')} physical, "
          f"{hw['cpu_count_logical']} logical")
    if hw.get('ram_gb') and hw['ram_gb'] != 'unknown':
        print(f"  RAM:          {hw['ram_gb']} GB")
    if hw.get('rust_available'):
        print(f"  Rust:         {hw.get('rust_version', 'available')}")
    else:
        print(f"  Rust:         not installed")
    print(f"  Accelerator:  {'x_ray_core (Rust)' if hw.get('rust_acceleration') else 'Pure Python'}")
    print(f"{'='*50}\n")


# ---------------------------------------------------------------------------
# Tool availability (ruff / bandit)
# ---------------------------------------------------------------------------

def _find_tool(name: str) -> Optional[str]:
    """Find an external tool. Checks: PATH, bundled dir, .exe dir."""
    # 1. System PATH
    found = shutil.which(name)
    if found:
        return found

    # 2. Bundled inside PyInstaller
    if getattr(sys, 'frozen', False):
        bundled = _BUNDLE_DIR / f"{name}.exe"
        if bundled.is_file():
            return str(bundled)
        # Also check _EXE_DIR/tools/
        tools_dir = _EXE_DIR / "tools"
        if tools_dir.is_dir():
            tool_path = tools_dir / f"{name}.exe"
            if tool_path.is_file():
                return str(tool_path)

    return None


def check_tools() -> Dict[str, str]:
    """Check availability of external tools."""
    tools = {}
    for name in ("ruff", "bandit"):
        path = _find_tool(name)
        tools[name] = path or ""
    return tools


# ---------------------------------------------------------------------------
# Core scanning (same as x_ray_claude.py but self-contained)
# ---------------------------------------------------------------------------

def scan_codebase(root: Path, exclude: List[str] = None,
                  include: List[str] = None,
                  verbose: bool = False) -> Tuple[
        List[FunctionRecord], List[ClassRecord], List[str]]:
    """Parallel-scan the codebase, returning functions, classes, and errors."""
    py_files = collect_py_files(root, exclude, include)
    all_functions: List[FunctionRecord] = []
    all_classes: List[ClassRecord] = []
    errors: List[str] = []
    total = len(py_files)
    done = 0

    print(f"  Scanning {total} files using {os.cpu_count() or 4} threads...")

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(extract_functions_from_file, f, root): f
            for f in py_files
        }
        for future in concurrent.futures.as_completed(futures):
            funcs, clses, err = future.result()
            all_functions.extend(funcs)
            all_classes.extend(clses)
            if err:
                errors.append(f"{futures[future]}: {err}")
            done += 1
            if verbose and total > 20 and done % max(1, total // 10) == 0:
                pct = done * 100 // total
                print(f"    [{pct:3d}%] {done}/{total} files scanned...",
                      flush=True)

    return all_functions, all_classes, errors


def run_smell_phase(functions, classes):
    """Run AST smell detection."""
    detector = CodeSmellDetector()
    print("\n  >> Analyzing Code Smells (X-Ray AST)...")
    smells = detector.detect(functions, classes)
    return detector, smells


def run_duplicate_phase(functions):
    """Run duplicate detection."""
    finder = DuplicateFinder()
    print("\n  >> Detecting Duplicates (X-Ray)...")
    finder.find(functions)
    return finder


def run_lint_phase(root: Path, exclude=None):
    """Run Ruff lint analysis."""
    from Analysis.lint import LintAnalyzer
    linter = LintAnalyzer()
    if linter.available:
        print("\n  >> Running Linter (Ruff)...")
        return linter, linter.analyze(root, exclude=exclude)
    print("\n  [!] Ruff not found — skipping lint analysis.")
    return None, []


def run_security_phase(root: Path, exclude=None):
    """Run Bandit security analysis."""
    from Analysis.security import SecurityAnalyzer
    sec = SecurityAnalyzer()
    if sec.available:
        print("\n  >> Running Security Scan (Bandit)...")
        return sec, sec.analyze(root, exclude=exclude)
    print("\n  [!] Bandit not found — skipping security scan.")
    return None, []


def run_rustify(root: Path, exclude=None) -> dict:
    """Rank functions by Rust-porting suitability."""
    from Analysis.rust_advisor import RustAdvisor

    print("\n  >> Scanning codebase for Rust candidates...")
    functions, classes, errors = scan_codebase(root, exclude=exclude)
    if not functions:
        print("  No functions found.")
        return {"rustify": {"candidates": []}}

    advisor = RustAdvisor()
    candidates = advisor.score(functions)
    advisor.print_candidates(candidates)

    return {
        "rustify": {
            "total_functions": len(functions),
            "scored": len(candidates),
            "pure_count": sum(1 for c in candidates if c.is_pure),
            "candidates": [c.to_dict() for c in candidates],
        }
    }


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse and normalise CLI arguments."""
    parser = argparse.ArgumentParser(
        description=_EXE_BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--path", default=".", help="Root directory to scan")
    parser.add_argument("--smell", action="store_true", help="Code smell detection")
    parser.add_argument("--duplicates", action="store_true", help="Duplicate detection")
    parser.add_argument("--lint", action="store_true", help="Ruff linter analysis")
    parser.add_argument("--security", action="store_true", help="Bandit security scan")
    parser.add_argument("--full-scan", action="store_true", help="Run ALL analyses")
    parser.add_argument("--rustify", action="store_true",
                        help="Rank functions by Rust-porting suitability")
    parser.add_argument("--report", help="Save JSON report to file")
    parser.add_argument("--exclude", nargs="*", help="Exclude directories")
    parser.add_argument("--hw", action="store_true", help="Show hardware info and exit")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Auto-select defaults
    has_specific = args.smell or args.duplicates or args.lint or args.security or args.rustify
    if args.full_scan or (not has_specific and not args.hw):
        args.smell = True
        args.lint = True
        args.security = True
        if args.full_scan:
            args.duplicates = True

    return args


def main():
    """Main entry point for x_ray.exe."""
    args = _parse_args()

    print(_EXE_BANNER)

    # ── Hardware detection ──
    hw = detect_hardware()
    print_hardware(hw)

    if args.hw:
        # Just hardware info — exit
        return

    # ── Tool check ──
    tools = check_tools()
    print("  Tool Status:")
    for name, path in tools.items():
        status = f"OK ({path})" if path else "not found (skipped)"
        print(f"    {name:10s}  {status}")
    try:
        import x_ray_core  # noqa: F401
        print(f"    {'x_ray_core':10s}  OK (Rust acceleration)")
    except ImportError:
        print(f"    {'x_ray_core':10s}  not available (using pure Python)")
    print()

    # ── Resolve target path ──
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"  ERROR: {root} is not a directory.")
        sys.exit(1)
    print(f"  Target: {root}\n")

    # ── Rustify mode ──
    if args.rustify:
        results = run_rustify(root, exclude=args.exclude)
        if args.report:
            with open(args.report, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)
            print(f"\n  Report saved to {args.report}")
        return

    # ── Standard scan phases ──
    start_time = time.time()
    results: Dict[str, Any] = {}
    all_issues = []

    if args.smell or args.duplicates:
        functions, classes, errors = scan_codebase(
            root, exclude=args.exclude, verbose=args.verbose)
        print(f"  Found {len(functions)} functions, {len(classes)} classes")
        if errors:
            print(f"  ({len(errors)} parse errors)")
    else:
        functions, classes, errors = [], [], []

    # Smells
    if args.smell:
        detector, smells = run_smell_phase(functions, classes)
        all_issues.extend(smells)
    else:
        detector = None

    # Duplicates
    if args.duplicates:
        finder = run_duplicate_phase(functions)
    else:
        finder = None

    # Lint
    if args.lint:
        linter, lint_issues = run_lint_phase(root, exclude=args.exclude)
        all_issues.extend(lint_issues)
    else:
        linter, lint_issues = None, []

    # Security
    if args.security:
        sec_analyzer, sec_issues = run_security_phase(root, exclude=args.exclude)
        all_issues.extend(sec_issues)
    else:
        sec_analyzer, sec_issues = None, []

    # ── Reporting ──
    if detector:
        summary = detector.summary()
        print_smells(detector.smells, summary)
        results["smells"] = summary

    if finder:
        summary = finder.summary()
        print_duplicates(finder.groups, summary)
        results["duplicates"] = summary

    if linter and lint_issues:
        summary = linter.summary(lint_issues)
        print_lint_report(lint_issues, summary)
        results["lint"] = summary

    if sec_analyzer and sec_issues:
        summary = sec_analyzer.summary(sec_issues)
        print_security_report(sec_issues, summary)
        results["security"] = summary

    # ── Unified grade ──
    grade_info = print_unified_grade(results)
    results["grade"] = grade_info
    results["hardware"] = hw

    duration = time.time() - start_time
    print(f"\n  Total scan time: {duration:.2f}s")

    # ── Save report ──
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"  Report saved to {args.report}")

    print(f"\n{'='*66}")
    print("  X-Ray scan complete.")
    print(f"{'='*66}\n")


if __name__ == "__main__":
    main()
