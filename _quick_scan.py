"""Quick X-Ray self-scan — smells + lint + security → grade."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from Analysis.ast_utils import extract_functions_from_file, collect_py_files
from Analysis.smells import CodeSmellDetector
from Analysis.lint import LintAnalyzer
from Analysis.security import SecurityAnalyzer
from Analysis.reporting import compute_grade

root = Path(__file__).parent
exclude = [
    "_OLD",
    "_scratch",
    ".venv",
    "__pycache__",
    ".git",
    "tests",
    "_rustified_exe_build",
    "_mothership",
]

files = collect_py_files(root, exclude=exclude)
print(f"Files scanned: {len(files)}")

fns, cls = [], []
for f in files:
    fu, cl, _ = extract_functions_from_file(f, root)
    fns.extend(fu)
    cls.extend(cl)
print(f"Functions: {len(fns)}   Classes: {len(cls)}")

smells = CodeSmellDetector().detect(fns, cls)
print(f"Smells: {len(smells)}")
by_sev = {}
for s in smells:
    by_sev[s.severity] = by_sev.get(s.severity, 0) + 1
print("  by severity:", by_sev)

lint_issues = LintAnalyzer().analyze(root, exclude=exclude)
print(f"Lint issues: {len(lint_issues)}")

sec_issues = SecurityAnalyzer().analyze(root, exclude=exclude)
print(f"Security issues: {len(sec_issues)}")

# compute_grade takes a unified results dict
results = {
    "smells": smells,
    "lint": lint_issues,
    "security": sec_issues,
}
grade_info = compute_grade(results)

score = grade_info.get("score", grade_info.get("grade_score", "?"))
letter = grade_info.get("letter", grade_info.get("grade", "?"))
breakdown = grade_info.get("breakdown", {})

print(f"\n{'=' * 40}")
print(f"  GRADE: {letter}   SCORE: {score}/100")
print(f"{'=' * 40}")
for cat, detail in breakdown.items():
    print(f"  {cat}: {detail}")
