#!/usr/bin/env python3
"""Self-scan: Run X-Ray on its own codebase."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from Core.config import SMELL_THRESHOLDS
from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder
from Analysis.reporting import compute_grade
from Analysis.rust_advisor import RustAdvisor

root = Path(__file__).parent
exclude = [
    ".venv", "venv", "__pycache__", ".git", "_OLD", "node_modules", "target",
    "build_exe", "build_web", "build_desktop", "X_Ray_Desktop", "X_Ray_Standalone",
    "X_Ray_Rust_Full", "_archive", "_scratch",
]

print("=== Collecting .py files ===")
py_files = collect_py_files(root, exclude)
print(f"Found {len(py_files)} Python files")

print("\n=== Parsing AST ===")
t0 = time.time()
funcs, classes, errors = [], [], []
for f in py_files:
    fn, cl, err = extract_functions_from_file(f, root)
    funcs.extend(fn)
    classes.extend(cl)
    if err:
        errors.append(f"{f}: {err}")
print(f"Parsed: {len(funcs)} functions, {len(classes)} classes, {len(errors)} errors in {time.time()-t0:.1f}s")
if errors:
    print("Parse errors:")
    for e in errors:
        print(f"  {e}")

print("\n=== Code Smells ===")
det = CodeSmellDetector(thresholds=SMELL_THRESHOLDS)
smells = det.detect(funcs, classes)
summary = det.summary()
print(f"Total: {summary['total']}  Critical: {summary['critical']}  Warning: {summary['warning']}  Info: {summary['info']}")
by_cat = summary.get("by_category", {})
for cat, cnt in sorted(by_cat.items(), key=lambda x: -x[1]):
    print(f"  {cat}: {cnt}")

print("\n=== Critical + Warning Issues ===")
for s in sorted(smells, key=lambda x: (0 if x.severity == "critical" else 1 if x.severity == "warning" else 2)):
    if s.severity in ("critical", "warning"):
        print(f"  {s.severity.upper():10s} [{s.category}] {s.name}")
        print(f"             File: {s.file_path}:{s.line}")
        print(f"             {s.message}")
        if s.suggestion:
            print(f"             FIX: {s.suggestion}")

print("\n=== Duplicates ===")
finder = DuplicateFinder()
finder.find(funcs)
dup_sum = finder.summary()
print(f"Groups: {dup_sum['total_groups']}  Exact: {dup_sum['exact_duplicates']}  Near: {dup_sum['near_duplicates']}  Semantic: {dup_sum['semantic_duplicates']}  Involved: {dup_sum['total_functions_involved']}")
if dup_sum["total_groups"] > 0:
    for g in finder.groups[:10]:
        names = [f"{fn.get('name','?')} ({fn.get('file','?')}:{fn.get('line','?')})" for fn in g.functions[:3]]
        print(f"  [{g.similarity_type}] {' <-> '.join(names)}")

print("\n=== Lint (Ruff) ===")
lint_issues = []
try:
    from Core.scan_phases import run_lint_phase
    linter, lint_issues = run_lint_phase(root, exclude=exclude)
    if linter:
        ls = linter.summary(lint_issues)
        print(f"Total: {ls['total']}  Critical: {ls['critical']}  Warning: {ls['warning']}  Fixable: {ls['fixable']}")
        top_rules = sorted(ls.get("by_rule", {}).items(), key=lambda x: -x[1])[:10]
        for r, c in top_rules:
            print(f"  {r}: {c}")
    else:
        ls = {"total": 0, "critical": 0, "warning": 0, "fixable": 0}
        print("Ruff not available")
except Exception as e:
    ls = {"total": 0, "critical": 0, "warning": 0, "fixable": 0}
    print(f"Lint error: {e}")

print("\n=== Security (Bandit) ===")
try:
    from Core.scan_phases import run_security_phase
    sec, sec_issues = run_security_phase(root, exclude=exclude)
    if sec:
        ss = sec.summary(sec_issues)
        print(f"Total: {ss['total']}  Critical: {ss['critical']}  Warning: {ss['warning']}")
        for issue in sec_issues:
            sev = getattr(issue, "severity", "") if hasattr(issue, "severity") else issue.get("severity", "") if isinstance(issue, dict) else ""
            if sev in ("HIGH", "MEDIUM"):
                tid = getattr(issue, "test_id", "") if hasattr(issue, "test_id") else issue.get("test_id", "") if isinstance(issue, dict) else ""
                txt = getattr(issue, "message", "") if hasattr(issue, "message") else issue.get("issue_text", "") if isinstance(issue, dict) else ""
                fname = getattr(issue, "file_path", "") if hasattr(issue, "file_path") else issue.get("filename", "") if isinstance(issue, dict) else ""
                ln = getattr(issue, "line", "") if hasattr(issue, "line") else issue.get("line_number", "") if isinstance(issue, dict) else ""
                print(f"  {sev} [{tid}] {txt} @ {fname}:{ln}")
    else:
        ss = {"total": 0, "critical": 0, "warning": 0}
        print("Bandit not available")
except Exception as e:
    ss = {"total": 0, "critical": 0, "warning": 0}
    print(f"Security error: {e}")

print("\n=== Rustify Candidates ===")
advisor = RustAdvisor()
candidates = advisor.score(funcs)
pure_count = sum(1 for c in candidates if c.is_pure)
top_score = candidates[0].score if candidates else 0
print(f"Scored: {len(candidates)}  Pure: {pure_count}  Top score: {top_score}")
for c in candidates[:5]:
    print(f"  {c.score:.1f}  {c.func.name} ({c.func.file_path}:{c.func.line_start})  pure={c.is_pure}")

results = {
    "smells": summary,
    "duplicates": dup_sum,
    "lint": ls,
    "security": ss,
    "rustify": {"total_scored": len(candidates)},
}
grade = compute_grade(results)
print(f"\n{'='*60}")
print(f"  GRADE: {grade['letter']}   SCORE: {grade['score']}/100")
print(f"{'='*60}")
breakdown = grade.get("breakdown", {})
for k, v in breakdown.items():
    penalty = v.get("penalty", 0) if isinstance(v, dict) else 0
    print(f"  {k:12s}  penalty: -{penalty:.0f}")
print(f"  Files: {len(py_files)}  Functions: {len(funcs)}  Classes: {len(classes)}")
print(f"  Duration: {time.time()-t0:.1f}s")

# Save results to JSON for reference
output = {
    "grade": grade,
    "files": len(py_files),
    "functions": len(funcs),
    "classes": len(classes),
    "smells_summary": summary,
    "duplicates_summary": dup_sum,
    "lint_summary": ls,
    "security_summary": ss,
    "critical_smells": [
        {"severity": s.severity, "category": s.category, "name": s.name,
         "file": s.file_path, "line": s.line, "message": s.message, "suggestion": s.suggestion}
        for s in smells if s.severity in ("critical", "warning")
    ],
}
with open(root / "xray_self_scan_latest.json", "w") as fp:
    json.dump(output, fp, indent=2)
print("\nResults saved to xray_self_scan_latest.json")
