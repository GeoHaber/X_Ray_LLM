"""Quick re-scan of ZEN_AI_RAG to check current score."""
import sys
sys.path.insert(0, r'C:\Users\Yo930\Desktop\_Python\X_Ray')
from pathlib import Path
from Core.scan_phases import (
    scan_codebase, run_smell_phase, run_lint_phase,
    run_security_phase, run_duplicate_phase, collect_reports, AnalysisComponents,
)
from Analysis.reporting import compute_grade

root = Path(r'C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG')
functions, classes, errors = scan_codebase(root)
detector, smell_issues = run_smell_phase(functions, classes)
finder = run_duplicate_phase(functions)
linter, lint_issues = run_lint_phase(root)
sec_analyzer, sec_issues = run_security_phase(root)
results = collect_reports(AnalysisComponents(
    detector, finder, linter, lint_issues, sec_analyzer, sec_issues))
grade = compute_grade(results)

print(f"Score: {grade['score']}/100  Grade: {grade['letter']}")
for k, v in grade['breakdown'].items():
    print(f"  {k}: penalty={v['penalty']}  details={v}")

crits = [i for i in smell_issues if i.severity == 'critical']
warns = [i for i in smell_issues if i.severity == 'warning']
infos = [i for i in smell_issues if i.severity == 'info']
print(f"Smells: {len(crits)} crit, {len(warns)} warn, {len(infos)} info")
print(f"Duplicates: {results['duplicates']['total_groups']} groups")
