#!/usr/bin/env python3
"""
generate_golden.py — Run the Python analyzer on every fixture set and
save canonical JSON golden outputs.

These golden files are the single source of truth: the Rust implementation
must produce byte-identical JSON (after normalization) for every fixture.

Usage:
    python tests/rust_harness/generate_golden.py          # generate all golden files
    python tests/rust_harness/generate_golden.py --force   # overwrite existing

Golden files saved to:  tests/rust_harness/golden/<suite_name>.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
HARNESS_DIR = Path(__file__).parent
FIXTURES_DIR = HARNESS_DIR / "fixtures"
GOLDEN_DIR = HARNESS_DIR / "golden"
PROJECT_ROOT = HARNESS_DIR.parent.parent  # X_Ray/

sys.path.insert(0, str(PROJECT_ROOT))

from x_ray_claude import (  # noqa: E402
    scan_codebase,
    CodeSmellDetector,
    DuplicateFinder,
    LibraryAdvisor,
    build_json_report,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Suite definitions — each describes one fixture scan configuration
# ─────────────────────────────────────────────────────────────────────────────

SUITES = [
    # ── Suite 1: All fixtures, full-scan ─────────────────────────────────────
    {
        "name": "full_scan",
        "path": FIXTURES_DIR,
        "description": "Full-scan of all fixtures with every detector enabled.",
    },
    # ── Suite 2: Clean code only — zero smells expected ──────────────────────
    {
        "name": "clean_only",
        "path": FIXTURES_DIR,
        "include": ["clean_code.py"],
        "description": "Clean code should produce zero smells.",
    },
    # ── Suite 3: Smell factory only ──────────────────────────────────────────
    {
        "name": "smells_only",
        "path": FIXTURES_DIR,
        "include": ["smell_factory.py"],
        "description": "Every smell category should fire.",
    },
    # ── Suite 4: Exact duplicates only ───────────────────────────────────────
    {
        "name": "exact_dupes",
        "path": FIXTURES_DIR,
        "include": ["dup_exact_a.py", "dup_exact_b.py"],
        "description": "Byte-identical functions across two files.",
    },
    # ── Suite 5: Near duplicates ─────────────────────────────────────────────
    {
        "name": "near_dupes",
        "path": FIXTURES_DIR,
        "include": ["dup_near_a.py", "dup_near_b.py"],
        "description": "~85-95% similar functions.",
    },
    # ── Suite 6: Structural duplicates ───────────────────────────────────────
    {
        "name": "structural_dupes",
        "path": FIXTURES_DIR,
        "include": ["dup_structural_a.py", "dup_structural_b.py"],
        "description": "Same AST shape, different variable names.",
    },
    # ── Suite 7: Semantic duplicates ─────────────────────────────────────────
    {
        "name": "semantic_dupes",
        "path": FIXTURES_DIR,
        "include": ["dup_semantic_a.py", "dup_semantic_b.py"],
        "description": "Same purpose, different code.",
    },
    # ── Suite 8: Library candidates ──────────────────────────────────────────
    {
        "name": "library_candidates",
        "path": FIXTURES_DIR,
        "include": ["lib_candidate_a.py", "lib_candidate_b.py", "lib_candidate_c.py"],
        "description": "Cross-file same-name functions → library suggestions.",
    },
    # ── Suite 9: Edge cases ──────────────────────────────────────────────────
    {
        "name": "edge_cases",
        "path": FIXTURES_DIR,
        "include": ["edge_cases.py"],
        "description": "Async, decorators, nested funcs, inheritance, *args.",
    },
]


def _filter_files(files: list[Path], include: list[str]) -> list[Path]:
    """Keep only files whose name is in the include list."""
    return [f for f in files if f.name in include]


def _run_suite(suite: dict) -> dict:
    """Execute one test suite and return the full JSON report dict."""
    root = suite["path"]
    include = suite.get("include")

    # Scan
    t0 = time.perf_counter()
    functions, classes, errors = scan_codebase(root)
    time.perf_counter() - t0

    # If only specific files requested, filter
    if include:
        fn_set = set(include)
        # Strip .py → just match the filename part
        functions = [f for f in functions if Path(f.file_path).name in fn_set]
        classes = [c for c in classes if Path(c.file_path).name in fn_set]

    # Smells
    detector = CodeSmellDetector()
    smells = detector.detect(functions, classes)

    # Duplicates — need cross_file_only=False for single-file suites
    is_multi = len(set(f.file_path for f in functions)) > 1
    finder = DuplicateFinder()
    duplicates = finder.find(functions, cross_file_only=is_multi)

    # Library suggestions
    advisor = LibraryAdvisor()
    lib_suggestions = advisor.analyze(duplicates, functions)

    total_time = time.perf_counter() - t0

    report = build_json_report(
        root, functions, classes, smells, duplicates, lib_suggestions, total_time,
    )

    # Augment with per-suite metadata
    report["_suite"] = {
        "name": suite["name"],
        "description": suite["description"],
        "fixture_files": include or [p.name for p in root.glob("*.py")],
    }
    # Add detailed expectations that the Rust harness must match
    report["_expectations"] = _build_expectations(suite, report)

    return report


def _build_expectations(suite: dict, report: dict) -> dict:
    """
    Derive hard constraints the Rust output MUST satisfy.
    These are invariant regardless of performance.
    """
    stats = report["stats"]
    smells = report["smells"]
    dups = report["duplicates"]
    lib = report["library_suggestions"]

    exp: dict = {
        # Exact numeric counts
        "total_functions": stats["total_functions"],
        "total_classes": stats["total_classes"],
        "total_files": stats["total_files"],
        "total_lines": stats["total_lines"],
        # Smell counts
        "smell_total": smells["total"],
        "smell_categories": sorted(set(s["category"] for s in smells["issues"])),
        "smell_severities": {
            "critical": sum(1 for s in smells["issues"] if s["severity"] == "critical"),
            "warning": sum(1 for s in smells["issues"] if s["severity"] == "warning"),
            "info": sum(1 for s in smells["issues"] if s["severity"] == "info"),
        },
        # Per-smell detail: file, line, category, severity, name
        "smell_fingerprints": sorted([
            f"{s['file']}:{s['line']}:{s['category']}:{s['severity']}:{s['name']}"
            for s in smells["issues"]
        ]),
        # Duplicate counts
        "dup_total_groups": dups["total_groups"],
        "dup_types": {
            "exact": sum(1 for g in dups["groups"] if g["type"] == "exact"),
            "structural": sum(1 for g in dups["groups"] if g["type"] == "structural"),
            "near": sum(1 for g in dups["groups"] if g["type"] == "near"),
            "semantic": sum(1 for g in dups["groups"] if g["type"] == "semantic"),
        },
        # Duplicate function keys (sorted sets per group)
        "dup_group_keys": [
            sorted([f["key"] for f in g["functions"]])
            for g in sorted(dups["groups"], key=lambda g: g["id"])
        ],
        # Library suggestion counts
        "lib_total": lib["total"],
        "lib_modules": sorted(set(s["module"] for s in lib["suggestions"])),
    }

    # Suite-specific assertions
    name = suite["name"]
    if name == "clean_only":
        exp["assert_zero_smells"] = True
    if name == "exact_dupes":
        exp["assert_has_exact_groups"] = True
    if name == "structural_dupes":
        exp["assert_has_structural_groups"] = True
    if name == "near_dupes":
        exp["assert_has_near_groups"] = True
    if name == "semantic_dupes":
        exp["assert_has_semantic_groups"] = True
    if name == "edge_cases":
        exp["assert_has_async_function"] = True
        exp["assert_nested_excluded"] = True

    return exp


def _normalize_report(report: dict) -> dict:
    """
    Strip non-deterministic fields (timestamps, scan_time, paths with 
    drive letters) so golden files are stable across machines.
    """
    # Remove volatile fields
    report.pop("timestamp", None)
    report.pop("scan_time_seconds", None)
    report.pop("root", None)

    # Sort smells for deterministic order
    if "smells" in report and "issues" in report["smells"]:
        report["smells"]["issues"].sort(
            key=lambda s: (s["severity"], s["file"], s["line"], s["category"])
        )

    # Sort duplicate groups by id
    if "duplicates" in report and "groups" in report["duplicates"]:
        for g in report["duplicates"]["groups"]:
            if "functions" in g:
                g["functions"].sort(key=lambda f: f.get("key", ""))
        report["duplicates"]["groups"].sort(key=lambda g: g["id"])

    # Sort library suggestions
    if "library_suggestions" in report and "suggestions" in report["library_suggestions"]:
        for s in report["library_suggestions"]["suggestions"]:
            if "functions" in s:
                s["functions"].sort(key=lambda f: (f.get("file", ""), f.get("name", "")))
        report["library_suggestions"]["suggestions"].sort(
            key=lambda s: (s["module"], s["description"])
        )

    return report


def generate_all(force: bool = False):
    """Run every suite and save golden output."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    results = {}

    for suite in SUITES:
        name = suite["name"]
        golden_path = GOLDEN_DIR / f"{name}.json"

        if golden_path.exists() and not force:
            print(f"  [SKIP] {name} — golden file exists (use --force to overwrite)")
            continue

        print(f"  [RUN]  {name} — {suite['description']}")
        try:
            report = _run_suite(suite)
            report = _normalize_report(report)

            golden_path.write_text(
                json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False),
                encoding="utf-8",
            )
            # Quick summary
            exp = report.get("_expectations", {})
            funcs = exp.get("total_functions", "?")
            smells = exp.get("smell_total", "?")
            groups = exp.get("dup_total_groups", "?")
            print(f"         → {funcs} functions, {smells} smells, {groups} dup groups")
            print(f"         → saved {golden_path.name}")
            results[name] = "OK"
        except Exception as e:
            print(f"  [FAIL] {name} — {e}")
            import traceback
            traceback.print_exc()
            results[name] = f"FAIL: {e}"

    # Summary
    print(f"\n  {'='*50}")
    print("  Golden Generation Summary")
    print(f"  {'='*50}")
    for name, status in results.items():
        icon = "✓" if status == "OK" else "✗"
        print(f"    {icon} {name}: {status}")
    print(f"  {'='*50}")

    return all(v == "OK" for v in results.values())


if __name__ == "__main__":
    force = "--force" in sys.argv
    success = generate_all(force=force)
    sys.exit(0 if success else 1)
