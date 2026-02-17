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
    "max_critical_smells": 20,      # Fail if > 20 critical code smells
    "max_long_functions": 25,       # Fail if > 25 functions > 120 lines
    "max_complex_functions": 30,    # Fail if > 30 functions with complexity > 20
    "max_total_smells": 200,        # Fail if > 200 total smells
    "max_duplicate_groups": 50,     # Warn if > 50 duplicate groups
}


def main():
    if len(sys.argv) < 2:
        print("Usage: check_quality.py <report.json>")
        sys.exit(1)
    
    report_path = Path(sys.argv[1])
    
    if not report_path.exists():
        print(f"❌ Report not found: {report_path}")
        sys.exit(1)
    
    with open(report_path) as f:
        report = json.load(f)
    
    smells = report.get("smells", {})
    duplicates = report.get("duplicates", {})
    
    # Parse metrics
    critical_count = smells.get("critical", 0)
    total_smells = smells.get("total", 0)
    long_funcs = smells.get("by_category", {}).get("long-function", 0)
    complex_funcs = smells.get("by_category", {}).get("complex-function", 0)
    dup_groups = duplicates.get("total_groups", 0)
    
    # Generate report
    report_lines = [
        "=" * 70,
        "CODE QUALITY GATE CHECK",
        "=" * 70,
        "",
        "📊 Code Smells",
        f"  Critical Issues: {critical_count}/{QUALITY_GATES['max_critical_smells']}",
        f"  Total Issues: {total_smells}/{QUALITY_GATES['max_total_smells']}",
        f"  Long Functions: {long_funcs}/{QUALITY_GATES['max_long_functions']}",
        f"  Complex Functions: {complex_funcs}/{QUALITY_GATES['max_complex_functions']}",
        "",
        "🔄 Duplicates",
        f"  Groups Found: {dup_groups} (threshold: {QUALITY_GATES['max_duplicate_groups']})",
        f"  Exact: {duplicates.get('exact_duplicates', 0)}",
        f"  Structural: {duplicates.get('structural_duplicates', 0)}",
        f"  Near: {duplicates.get('near_duplicates', 0)}",
        f"  Semantic: {duplicates.get('semantic_duplicates', 0)}",
        "",
    ]
    
    # Check gates
    failures = []
    
    if critical_count > QUALITY_GATES["max_critical_smells"]:
        failures.append(f"CRITICAL: {critical_count} critical smells (limit: {QUALITY_GATES['max_critical_smells']})")
    
    if total_smells > QUALITY_GATES["max_total_smells"]:
        failures.append(f"CRITICAL: {total_smells} total smells (limit: {QUALITY_GATES['max_total_smells']})")
    
    if long_funcs > QUALITY_GATES["max_long_functions"]:
        failures.append(f"WARNING: {long_funcs} long functions (limit: {QUALITY_GATES['max_long_functions']})")
    
    if complex_funcs > QUALITY_GATES["max_complex_functions"]:
        failures.append(f"WARNING: {complex_funcs} complex functions (limit: {QUALITY_GATES['max_complex_functions']})")
    
    if dup_groups > QUALITY_GATES["max_duplicate_groups"]:
        report_lines.append(f"⚠️  Note: {dup_groups} duplicate groups (threshold: {QUALITY_GATES['max_duplicate_groups']})")
    
    # Final status
    report_lines.append("")
    if failures:
        report_lines.append("🔴 QUALITY GATE FAILED")
        report_lines.append("")
        for failure in failures:
            report_lines.append(f"  {failure}")
    else:
        report_lines.append("✅ QUALITY GATE PASSED")
    
    report_lines.append("=" * 70)
    
    # Write to file
    log_path = Path("quality-check.log")
    with open(log_path, "w") as f:
        f.write("\n".join(report_lines))
    
    # Print to stdout
    print("\n".join(report_lines))
    
    # Exit with error if critical failures
    sys.exit(1 if any(f.startswith("CRITICAL") for f in failures) else 0)


if __name__ == "__main__":
    main()
