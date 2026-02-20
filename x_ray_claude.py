#!/usr/bin/env python3
"""
X_RAY_Claude.py — Smart AI-Powered Code Analyzer (X-Ray 5.0)
=============================================================

Unified code quality scanner combining:
  - AST-based structural analysis (smells, duplicates)
  - Ruff linter integration (style, imports, hygiene)
  - Bandit security scanner integration (vulnerabilities)

Usage::

    python X_RAY_Claude.py --path .                     # default: smells + lint + security
    python X_RAY_Claude.py --smell                      # code smell detection only
    python X_RAY_Claude.py --duplicates                 # find similar functions
    python X_RAY_Claude.py --lint                       # Ruff linter only
    python X_RAY_Claude.py --security                   # Bandit security only
    python X_RAY_Claude.py --full-scan                  # everything (all 4 analyzers)
    python X_RAY_Claude.py --report scan_results.json   # save JSON report
    python X_RAY_Claude.py --rustify                    # rank functions for Rust porting
    python X_RAY_Claude.py --rustify --report rust.json  # save candidate report
"""

from __future__ import annotations

import argparse
import json
import sys
import os
import time
import asyncio
import concurrent.futures
from pathlib import Path
from typing import List, Tuple

from Core.types import FunctionRecord, ClassRecord
from Core.config import BANNER
from Core.inference import LLMHelper

from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.lint import LintAnalyzer
from Analysis.security import SecurityAnalyzer
from Analysis.reporting import (
    print_smells, print_duplicates, print_lint_report,
    print_security_report, print_unified_grade,
)

from Core.utils import setup_logger
setup_logger()  # configure logging once — no duplicate basicConfig


# ═══════════════════════════════════════════════════════════════════════════
#  Interactive TUI — select scope and functionality
# ═══════════════════════════════════════════════════════════════════════════

def _supports_interactive() -> bool:
    """Check if stdin is a real terminal (not piped)."""
    import sys
    return hasattr(sys.stdin, 'isatty') and sys.stdin.isatty()


def _clear_line():
    """Move cursor up and clear the line."""
    print('\033[A\033[K', end='', flush=True)


def _interactive_menu() -> dict:
    """Show an interactive menu to select scan scope and options.

    Returns a dict with the selected options matching argparse flag names.
    Works on Windows (msvcrt) and Unix (tty/termios).
    """
    import sys
    options = [
        ('smell',       'Code Smell Detection',    True),
        ('duplicates',  'Duplicate Finder',         False),
        ('lint',        'Ruff Lint Analysis',       True),
        ('security',    'Bandit Security Scan',     True),
        ('rustify',     'Score for Rust Porting',   False),
        ('rustify_exe', 'Full Rustify → Executable', False),
    ]
    selected = [on for _, _, on in options]
    cursor = 0

    def _render():
        header = (
            "\n  \033[1;36m╔══════════════════════════════════════╗\033[0m\n"
            "  \033[1;36m║   X-RAY  Interactive Mode            ║\033[0m\n"
            "  \033[1;36m╚══════════════════════════════════════╝\033[0m\n"
            "\n  Use \033[1m↑↓\033[0m to move, \033[1mSpace\033[0m to toggle, \033[1mEnter\033[0m to run\n"
        )
        lines = [header]
        for i, (key, label, _) in enumerate(options):
            mark = '\033[1;32m✓\033[0m' if selected[i] else '\033[90m·\033[0m'
            arrow = '\033[1;33m►\033[0m ' if i == cursor else '  '
            lines.append(f"  {arrow}[{mark}] {label}")
        lines.append("\n  \033[90mPress \033[1mq\033[0;90m to quit\033[0m\n")
        return '\n'.join(lines)

    # Platform-specific key reading
    if sys.platform == 'win32':
        import msvcrt
        def _read_key():
            ch = msvcrt.getwch()
            if ch in ('\x00', '\xe0'):  # special key prefix
                ch2 = msvcrt.getwch()
                if ch2 == 'H': return 'up'
                if ch2 == 'P': return 'down'
                return 'unknown'
            if ch == ' ': return 'space'
            if ch in ('\r', '\n'): return 'enter'
            if ch.lower() == 'q': return 'quit'
            if ch.lower() == 'a': return 'all'
            if ch.lower() == 'n': return 'none'
            return 'unknown'
    else:
        import tty, termios
        def _read_key():
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
                if ch == '\x1b':
                    ch2 = sys.stdin.read(2)
                    if ch2 == '[A': return 'up'
                    if ch2 == '[B': return 'down'
                    return 'unknown'
                if ch == ' ': return 'space'
                if ch in ('\r', '\n'): return 'enter'
                if ch.lower() == 'q': return 'quit'
                if ch.lower() == 'a': return 'all'
                if ch.lower() == 'n': return 'none'
                return 'unknown'
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # Initial render
    display = _render()
    line_count = display.count('\n') + 1
    print(display, end='', flush=True)

    while True:
        key = _read_key()
        if key == 'up':
            cursor = (cursor - 1) % len(options)
        elif key == 'down':
            cursor = (cursor + 1) % len(options)
        elif key == 'space':
            selected[cursor] = not selected[cursor]
        elif key == 'enter':
            break
        elif key == 'quit':
            print('\n  Cancelled.')
            sys.exit(0)
        elif key == 'all':
            selected = [True] * len(options)
        elif key == 'none':
            selected = [False] * len(options)
        else:
            continue

        # Re-render: clear previous output, redraw
        for _ in range(line_count):
            _clear_line()
        display = _render()
        line_count = display.count('\n') + 1
        print(display, end='', flush=True)

    print()  # final newline after menu

    result = {}
    for i, (key, _, _) in enumerate(options):
        result[key] = selected[i]
    return result


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


# Reporting functions moved to Analysis.reporting


def _parse_args() -> argparse.Namespace:
    """Parse and normalise CLI arguments."""
    parser = argparse.ArgumentParser(
        description=BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--path", default=".", help="Root directory to scan")
    parser.add_argument("--smell", action="store_true", help="Run code smell detection")
    parser.add_argument("--duplicates", action="store_true", help="Run duplicate detection")
    parser.add_argument("--lint", action="store_true", help="Run Ruff linter analysis")
    parser.add_argument("--security", action="store_true", help="Run Bandit security scan")
    parser.add_argument("--full-scan", action="store_true", help="Run ALL analyses")
    parser.add_argument("--rustify", action="store_true",
                        help="Rank functions by Rust-porting suitability")
    parser.add_argument("--rustify-exe", action="store_true",
                        help="Full pipeline: scan → optimize → transpile → compile to executable")
    parser.add_argument("--use-llm", action="store_true", help="Enable LLM enrichment")
    parser.add_argument("--report", help="Save JSON report to file")
    parser.add_argument("--exclude", nargs="*", help="Exclude directories")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Launch interactive TUI to select scope and options")
    args = parser.parse_args()

    # Interactive mode: launch TUI to select options
    if args.interactive and _supports_interactive():
        choices = _interactive_menu()
        args.smell = choices.get('smell', False)
        args.duplicates = choices.get('duplicates', False)
        args.lint = choices.get('lint', False)
        args.security = choices.get('security', False)
        args.rustify = choices.get('rustify', False)
        args.rustify_exe = choices.get('rustify_exe', False)
        return args

    # Auto-select: if no specific flags, run smells + lint + security (not duplicates, it's slow)
    has_specific = (args.smell or args.duplicates or args.lint
                    or args.security or args.rustify or args.rustify_exe)
    if args.full_scan or not has_specific:
        args.smell = True
        args.lint = True
        args.security = True
        if args.full_scan:
            args.duplicates = True

    return args


def _init_llm(args: argparse.Namespace, root: Path):
    """Initialize LLM helper if requested."""
    if not args.use_llm:
        return None
    llm = LLMHelper(root=root)
    if not llm.available:
        print("  [!] LLM not available. Installation required (see Core/services).")
        return None
    return llm


def _scan_codebase_phase(root: Path, args: argparse.Namespace):
    """Run codebase scanning for smells/duplicates if needed."""
    if not (args.smell or args.duplicates):
        return [], [], []
    start = time.time()
    functions, classes, errors = scan_codebase(root, exclude=args.exclude)
    duration = time.time() - start
    print(f"  Scanned {len(functions)} functions, {len(classes)} classes in {duration:.2f}s")
    return functions, classes, errors


def _run_smell_phase(args, functions, classes):
    """Run AST smell detection if requested."""
    if not args.smell:
        return None, []
    detector = CodeSmellDetector()
    print("\n  >> Analyzing Code Smells (X-Ray)...")
    smells = detector.detect(functions, classes)
    return detector, smells


def _run_duplicate_phase(args, functions):
    """Run duplicate detection if requested."""
    if not args.duplicates:
        return None
    finder = DuplicateFinder()
    print("\n  >> Detecting Duplicates (X-Ray)...")
    finder.find(functions)
    return finder


def _run_lint_phase(args, root):
    """Run Ruff lint analysis if requested."""
    if not args.lint:
        return None, []
    linter = LintAnalyzer()
    if linter.available:
        print("\n  >> Running Linter (Ruff)...")
        return linter, linter.analyze(root, exclude=args.exclude)
    print("\n  [!] Ruff not installed. Skipping lint analysis. (pip install ruff)")
    return None, []


def _run_security_phase(args, root):
    """Run Bandit security analysis if requested."""
    if not args.security:
        return None, []
    sec = SecurityAnalyzer()
    if sec.available:
        print("\n  >> Running Security Scan (Bandit)...")
        return sec, sec.analyze(root, exclude=args.exclude)
    print("\n  [!] Bandit not installed. Skipping security scan. (pip install bandit)")
    return None, []


def _run_rustify(root: Path, args: argparse.Namespace) -> dict:
    """Rank functions by Rust-porting suitability and print results."""
    from Analysis.rust_advisor import RustAdvisor

    print("\n  >> Scanning codebase for Rust candidates...")
    functions, classes, errors = scan_codebase(root, exclude=args.exclude)
    if not functions:
        print("  No functions found.")
        return {"rustify": {"candidates": []}}

    advisor = RustAdvisor()
    candidates = advisor.score(functions)
    advisor.print_candidates(candidates)

    results = {
        "rustify": {
            "total_functions": len(functions),
            "scored": len(candidates),
            "pure_count": sum(1 for c in candidates if c.is_pure),
            "candidates": [c.to_dict() for c in candidates],
        }
    }
    return results


def _run_rustify_exe(root: Path, args: argparse.Namespace) -> dict:
    """Full pipeline: scan → optimize → transpile → compile → verify.

    Produces a native Windows/Mac/Linux executable from the Python project.
    """
    from Analysis.auto_rustify import RustifyPipeline

    print("\n  " + "═" * 60)
    print("  🔧 FULL RUSTIFY PIPELINE: Python → Rust → Executable")
    print("  " + "═" * 60)

    def progress_cb(frac: float, label: str):
        bar_len = 30
        filled = int(bar_len * frac)
        bar = '█' * filled + '░' * (bar_len - filled)
        print(f"\r  [{bar}] {frac*100:5.1f}% {label:<40}", end='', flush=True)

    pipeline = RustifyPipeline(
        project_dir=root,
        mode="binary",
        min_score=3.0,
        max_candidates=100,
        exclude_dirs=args.exclude or [],
    )

    report = pipeline.run(progress_cb=progress_cb)
    print()  # newline after progress bar

    # Print results
    print(f"\n  ── Pipeline Results {'─' * 39}")
    print(f"  System:     {report.system.os_name} {report.system.arch}")
    print(f"  Target:     {report.system.rust_target}")
    print(f"  Scanned:    {report.candidates_total} functions in {report.scan_duration_s}s")
    print(f"  Selected:   {report.candidates_selected} candidates (score ≥ 3.0)")

    for phase in report.phases:
        status = phase.get('status', 'unknown')
        name = phase.get('name', '')
        icon = '✅' if status == 'ok' else '❌' if status == 'failed' else '⚠️'
        print(f"  {icon} {name}: {status}")
        if 'artefact' in phase and phase['artefact']:
            print(f"     → Executable: {phase['artefact']}")

    if report.compile_result and report.compile_result.success:
        exe = report.compile_result.artefact_path
        print(f"\n  \033[1;32m✓ SUCCESS\033[0m — Executable built: {exe}")
        print(f"  Run it:  {exe} --help")
    elif report.errors:
        print(f"\n  \033[1;31m✗ ERRORS:\033[0m")
        for err in report.errors[:5]:
            print(f"    {err[:200]}")

    return {"rustify_exe": report.to_dict()}


async def _run_full_scan(root: Path, args: argparse.Namespace) -> dict:
    """Execute all requested scan phases and return the results dict."""
    # ── Rustify modes ──
    if args.rustify_exe:
        return _run_rustify_exe(root, args)
    if args.rustify:
        return _run_rustify(root, args)

    llm = _init_llm(args, root)
    functions, classes, errors = _scan_codebase_phase(root, args)

    results: dict = {}
    all_issues = []

    detector, smells = _run_smell_phase(args, functions, classes)
    all_issues.extend(smells)

    finder = _run_duplicate_phase(args, functions)

    linter, lint_issues = _run_lint_phase(args, root)
    all_issues.extend(lint_issues)

    sec_analyzer, sec_issues = _run_security_phase(args, root)
    all_issues.extend(sec_issues)

    # ── Async LLM Enrichment (Parallel) ──
    if llm and (detector or finder):
        tasks = []
        if detector:
            tasks.append(detector.enrich_with_llm_async(llm))
        if finder:
            tasks.append(finder.enrich_with_llm_async(llm, functions))
        if tasks:
            await asyncio.gather(*tasks)

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

    # ── Unified Grade ──
    grade_info = print_unified_grade(results)
    results["grade"] = grade_info

    return results


async def main_async():
    """Async entry point for X-Ray CLI scanner."""
    args = _parse_args()
    print(BANNER)

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory.")
        sys.exit(1)

    results = await _run_full_scan(root, args)

    # Save Report
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\n  Report saved to {args.report}")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
