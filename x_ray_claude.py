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
    parser.add_argument("--use-llm", action="store_true", help="Enable LLM enrichment")
    parser.add_argument("--report", help="Save JSON report to file")
    parser.add_argument("--exclude", nargs="*", help="Exclude directories")
    args = parser.parse_args()

    # Auto-select: if no specific flags, run smells + lint + security (not duplicates, it's slow)
    has_specific = args.smell or args.duplicates or args.lint or args.security or args.rustify
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


async def _run_full_scan(root: Path, args: argparse.Namespace) -> dict:
    """Execute all requested scan phases and return the results dict."""
    # ── Rustify mode: rank functions for Rust porting ──
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
