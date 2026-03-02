"""Run full X-Ray analysis and report the score."""
import sys
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from Analysis.smells import CodeSmellDetector
from Core.scan_phases import (
    scan_codebase, run_smell_phase, run_duplicate_phase,
    run_lint_phase, run_security_phase, collect_reports,
    AnalysisComponents,
)
from Analysis.reporting import compute_grade
import json

root = _ROOT
exclude = ["_OLD", "_scratch", "_training_ground", "_verify_crate",
           "__pycache__", ".venv", "target"]

funcs, classes, errors = scan_codebase(root, exclude=exclude)

detector, smells = run_smell_phase(funcs, classes)
finder = run_duplicate_phase(funcs)
linter, lint_issues = run_lint_phase(root, exclude=exclude)
sec, sec_issues = run_security_phase(root, exclude=exclude)

components = AnalysisComponents(
    detector=detector, finder=finder,
    linter=linter, lint_issues=lint_issues,
    sec_analyzer=sec, sec_issues=sec_issues,
)
report = collect_reports(components)
report["grade"] = compute_grade(report)

grade = report["grade"]
print(f"Score: {grade['score']}/100  Grade: {grade['letter']}")
print(f"Penalties: {grade.get('penalties', {})}")

sm = report.get("smells", {})
print(f"Smells: critical={sm.get('critical',0)} warning={sm.get('warning',0)} "
      f"info={sm.get('info',0)} total={sm.get('total',0)}")

lint_data = report.get("lint", {})
print(f"Lint: critical={lint_data.get('critical',0)} "
      f"warning={lint_data.get('warning',0)} total={lint_data.get('total',0)}")

dup_data = report.get("duplicates", {})
print(f"Duplicates: groups={dup_data.get('groups',0)}")

sec_data = report.get("security", {})
print(f"Security: critical={sec_data.get('critical',0)} total={sec_data.get('total',0)}")

with open(_ROOT / "_scratch/grade_check.json", "w") as f:
    json.dump(report, f, indent=2, default=str)
print("Report saved to _scratch/grade_check.json")

# List remaining critical/warning smells
det = CodeSmellDetector()
issues = det.detect(funcs, classes)
print("\n--- Remaining critical/warning smells ---")
for i in issues:
    if i.severity in ("critical", "warning"):
        print(f"  {i.severity:8s} {i.category:26s} {i.file_path}:{i.line} "
              f"{i.name} metric={i.metric_value}")
print(f"\nTotal: {sum(1 for i in issues if i.severity in ('critical', 'warning'))} "
      f"critical+warning smells remaining")
