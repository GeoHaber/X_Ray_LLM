"""Core/scan_phases.py — Shared scan phase runners for X-Ray CLI tools.

Consolidates the duplicated scan_codebase, phase runners, and report
collection logic that was previously copy-pasted across x_ray_claude.py,
x_ray_exe.py, and Lang/python_ast.py.
"""

from __future__ import annotations

import os
import concurrent.futures
from pathlib import Path
from typing import List, Tuple

from typing import NamedTuple, Any as _Any

from Core.types import FunctionRecord, ClassRecord
from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.reporting import (
    print_smells,
    print_duplicates,
    print_format_report,
    print_lint_report,
    print_security_report,
    print_unified_grade,
)


class AnalysisComponents(NamedTuple):
    """Bundle of analysis objects for collect_reports."""

    detector: _Any
    finder: _Any
    format_analyzer: _Any
    format_issues: _Any
    linter: _Any
    lint_issues: _Any
    sec_analyzer: _Any
    sec_issues: _Any


# ---------------------------------------------------------------------------
# Codebase scanning
# ---------------------------------------------------------------------------


def scan_codebase(
    root: Path,
    exclude: List[str] = None,
    include: List[str] = None,
    verbose: bool = False,
) -> Tuple[List[FunctionRecord], List[ClassRecord], List[str]]:
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
            executor.submit(extract_functions_from_file, f, root): f for f in py_files
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
                print(f"    [{pct:3d}%] {done}/{total} files scanned...", flush=True)

    return all_functions, all_classes, errors


# ---------------------------------------------------------------------------
# Individual analysis phases
# ---------------------------------------------------------------------------


def run_smell_phase(functions, classes):
    """Run AST smell detection. Returns (detector, smells)."""
    detector = CodeSmellDetector()
    print("\n  >> Analyzing Code Smells (X-Ray AST)...")
    smells = detector.detect(functions, classes)
    return detector, smells


def run_duplicate_phase(functions):
    """Run duplicate detection. Returns finder instance."""
    finder = DuplicateFinder()
    print("\n  >> Detecting Duplicates (X-Ray)...")
    finder.find(functions)
    return finder


def run_format_phase(root: Path, exclude=None):
    """Run Ruff format check. Returns (analyzer | None, issues)."""
    from Analysis.format import FormatAnalyzer

    fmt = FormatAnalyzer()
    if fmt.available:
        print("\n  >> Running Format Check (Ruff)...")
        return fmt, fmt.analyze(root, exclude=exclude)
    print("\n  [!] Ruff not found — skipping format check.")
    return None, []


def run_lint_phase(root: Path, exclude=None):
    """Run Ruff lint analysis. Returns (analyzer | None, issues)."""
    from Analysis.lint import LintAnalyzer

    linter = LintAnalyzer()
    if linter.available:
        print("\n  >> Running Linter (Ruff)...")
        return linter, linter.analyze(root, exclude=exclude)
    print("\n  [!] Ruff not found — skipping lint analysis.")
    return None, []


def run_security_phase(root: Path, exclude=None):
    """Run Bandit security analysis. Returns (analyzer | None, issues)."""
    from Analysis.security import SecurityAnalyzer

    sec = SecurityAnalyzer()
    if sec.available:
        print("\n  >> Running Security Scan (Bandit)...")
        return sec, sec.analyze(root, exclude=exclude)
    print("\n  [!] Bandit not found — skipping security scan.")
    return None, []


def run_ui_compat_phase(root: Path, exclude=None):
    """Run UI API compatibility check. Returns (analyzer | None, issues)."""
    from Analysis.ui_compat import UICompatAnalyzer
    analyzer = UICompatAnalyzer()
    print("\n  >> Checking UI API Compatibility (X-Ray)...")
    raw_issues = analyzer.analyze(root, exclude=exclude)
    smell_issues = [i.to_smell() for i in raw_issues]
    if raw_issues:
        analyzer.print_report(raw_issues)
    else:
        print("  ✅ All UI calls are compatible.")
    return analyzer, raw_issues, smell_issues


def run_rustify_scan(root: Path, exclude=None) -> dict:
    """Rank functions by Rust-porting suitability and print results."""
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
# Report collection
# ---------------------------------------------------------------------------


def collect_reports(components: AnalysisComponents) -> dict:
    """Print all analysis reports, compute unified grade, return combined results."""
    (
        detector,
        finder,
        fmt_analyzer,
        fmt_issues,
        linter,
        lint_issues,
        sec_analyzer,
        sec_issues,
    ) = components
    results: dict = {}

    if detector:
        summary = detector.summary()
        print_smells(detector.smells, summary)
        results["smells"] = summary

    if finder:
        summary = finder.summary()
        print_duplicates(finder.groups, summary)
        results["duplicates"] = summary

    if fmt_analyzer and fmt_issues:
        summary = fmt_analyzer.summary(fmt_issues)
        print_format_report(fmt_issues, summary)
        results["format"] = summary

    if linter and lint_issues:
        summary = linter.summary(lint_issues)
        print_lint_report(lint_issues, summary)
        results["lint"] = summary

    if sec_analyzer and sec_issues:
        summary = sec_analyzer.summary(sec_issues)
        print_security_report(sec_issues, summary)
        results["security"] = summary

    grade_info = print_unified_grade(results)
    results["grade"] = grade_info
    return results
