#!/usr/bin/env python3
"""
Parse X-Ray JSON report and check quality gates.
Generates quality-check.log with summary and PASS/FAIL status.
"""

import json
import sys
from pathlib import Path

# Quality gate thresholds (configurable)
QUALITY_GATES = {
    # Severity caps
    "max_critical_smells": 20,
    "max_warning_smells": 100,
    "max_total_smells": 200,
    # Function metrics
    "max_long_functions": 25,  # functions > 120 lines
    "max_complex_functions": 30,  # functions with complexity > 20
    "max_deep_nesting": 15,  # functions with nesting >= 6
    # Class metrics
    "max_god_classes": 5,  # classes with >= 15 methods
    # PEP 8 / high-impact
    "max_bare_except": 5,
    "max_mutable_default_arg": 10,
    "max_too_many_params": 20,
    # Duplicates
    "max_duplicate_groups": 50,
}


def main():
    if len(sys.argv) < 2:
        print("Usage: check_quality.py <report.json>")
        sys.exit(1)

    report_path = Path(sys.argv[1])

    if not report_path.exists():
        print(f"[ERROR] Report not found: {report_path}")
        sys.exit(1)

    with open(report_path) as f:
        report = json.load(f)

    smells = report.get("smells", {})
    duplicates = report.get("duplicates", {})
    by_cat = smells.get("by_category", {})

    # Parse metrics
    critical_count = smells.get("critical", 0)
    warning_count = smells.get("warning", 0)
    total_smells = smells.get("total", 0)
    long_funcs = by_cat.get("long-function", 0)
    complex_funcs = by_cat.get("complex-function", 0)
    deep_nesting = by_cat.get("deep-nesting", 0)
    god_classes = by_cat.get("god-class", 0)
    bare_except = by_cat.get("bare-except", 0)
    mutable_default = by_cat.get("mutable-default-arg", 0)
    too_many_params = by_cat.get("too-many-params", 0)
    dup_groups = duplicates.get("total_groups", 0)

    # Build report
    report_lines = [
        "=" * 70,
        "CODE QUALITY GATE CHECK",
        "=" * 70,
        "",
        "[METRICS] Code Smells (by severity)",
        f"  Critical: {critical_count}/{QUALITY_GATES['max_critical_smells']}",
        f"  Warning:  {warning_count}/{QUALITY_GATES['max_warning_smells']}",
        f"  Total:    {total_smells}/{QUALITY_GATES['max_total_smells']}",
        "",
        "[METRICS] Code Smells (by category)",
        f"  long-function:      {long_funcs}/{QUALITY_GATES['max_long_functions']}",
        f"  complex-function:   {complex_funcs}/{QUALITY_GATES['max_complex_functions']}",
        f"  deep-nesting:       {deep_nesting}/{QUALITY_GATES['max_deep_nesting']}",
        f"  god-class:          {god_classes}/{QUALITY_GATES['max_god_classes']}",
        f"  bare-except:        {bare_except}/{QUALITY_GATES['max_bare_except']}",
        f"  mutable-default:    {mutable_default}/{QUALITY_GATES['max_mutable_default_arg']}",
        f"  too-many-params:    {too_many_params}/{QUALITY_GATES['max_too_many_params']}",
        "",
        "[DUPLICATES] Detection Summary",
        f"  Groups: {dup_groups}/{QUALITY_GATES['max_duplicate_groups']}",
        f"  Exact: {duplicates.get('exact_duplicates', 0)} | "
        f"Structural: {duplicates.get('structural_duplicates', 0)} | "
        f"Near: {duplicates.get('near_duplicates', 0)} | "
        f"Semantic: {duplicates.get('semantic_duplicates', 0)}",
        "",
    ]

    # Gate checks (CRITICAL = fail, WARNING = advisory)
    failures = []

    if critical_count > QUALITY_GATES["max_critical_smells"]:
        failures.append(
            f"CRITICAL: {critical_count} critical smells (limit: {QUALITY_GATES['max_critical_smells']})"
        )
    if total_smells > QUALITY_GATES["max_total_smells"]:
        failures.append(
            f"CRITICAL: {total_smells} total smells (limit: {QUALITY_GATES['max_total_smells']})"
        )

    if warning_count > QUALITY_GATES["max_warning_smells"]:
        failures.append(
            f"WARNING: {warning_count} warning smells (limit: {QUALITY_GATES['max_warning_smells']})"
        )
    if long_funcs > QUALITY_GATES["max_long_functions"]:
        failures.append(
            f"WARNING: {long_funcs} long functions (limit: {QUALITY_GATES['max_long_functions']})"
        )
    if complex_funcs > QUALITY_GATES["max_complex_functions"]:
        failures.append(
            f"WARNING: {complex_funcs} complex functions (limit: {QUALITY_GATES['max_complex_functions']})"
        )
    if deep_nesting > QUALITY_GATES["max_deep_nesting"]:
        failures.append(
            f"WARNING: {deep_nesting} deep-nesting (limit: {QUALITY_GATES['max_deep_nesting']})"
        )
    if god_classes > QUALITY_GATES["max_god_classes"]:
        failures.append(
            f"WARNING: {god_classes} god-classes (limit: {QUALITY_GATES['max_god_classes']})"
        )
    if bare_except > QUALITY_GATES["max_bare_except"]:
        failures.append(
            f"WARNING: {bare_except} bare-except (limit: {QUALITY_GATES['max_bare_except']})"
        )
    if mutable_default > QUALITY_GATES["max_mutable_default_arg"]:
        failures.append(
            f"WARNING: {mutable_default} mutable-default-arg (limit: {QUALITY_GATES['max_mutable_default_arg']})"
        )
    if too_many_params > QUALITY_GATES["max_too_many_params"]:
        failures.append(
            f"WARNING: {too_many_params} too-many-params (limit: {QUALITY_GATES['max_too_many_params']})"
        )
    if dup_groups > QUALITY_GATES["max_duplicate_groups"]:
        failures.append(
            f"WARNING: {dup_groups} duplicate groups (limit: {QUALITY_GATES['max_duplicate_groups']})"
        )

    # Final status
    report_lines.append("")
    critical_failures = [f for f in failures if f.startswith("CRITICAL")]
    warning_failures = [f for f in failures if f.startswith("WARNING")]

    if critical_failures:
        report_lines.append("[FAIL] QUALITY GATE FAILED")
        report_lines.append("")
        for f in critical_failures:
            report_lines.append(f"  {f}")
        if warning_failures:
            report_lines.append("")
            report_lines.append("  Advisory warnings:")
            for f in warning_failures:
                report_lines.append(f"    {f}")
    elif warning_failures:
        report_lines.append("[WARN] QUALITY GATE PASSED (with advisory warnings)")
        report_lines.append("")
        for f in warning_failures:
            report_lines.append(f"  {f}")
    else:
        report_lines.append("[PASS] QUALITY GATE PASSED")

    report_lines.append("=" * 70)

    # Write to file
    log_path = Path("quality-check.log")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    # Print to stdout
    print("\n".join(report_lines))

    # Exit with error if critical failures
    sys.exit(1 if any(f.startswith("CRITICAL") for f in failures) else 0)


if __name__ == "__main__":
    main()
