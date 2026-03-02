"""Get detailed critical + warning smell issues from ZEN_AI_RAG."""
import sys, os
sys.path.insert(0, r'C:\Users\Yo930\Desktop\_Python\X_Ray')
from Core.scan_phases import scan_codebase, run_smell_phase
from pathlib import Path
from collections import Counter

root = Path(r'C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG')
functions, classes, errors = scan_codebase(root, exclude=None, verbose=False)
detector, issues = run_smell_phase(functions, classes)

crit = [i for i in issues if i.severity == 'critical']
warn = [i for i in issues if i.severity == 'warning']
info = [i for i in issues if i.severity == 'info']

print(f'Total: {len(issues)} (crit={len(crit)}, warn={len(warn)}, info={len(info)})')

print('\n=== ALL CRITICAL ISSUES (71) ===')
for i in sorted(crit, key=lambda x: (x.file_path, x.line)):
    print(f'  [{i.category}] {i.file_path}:{i.line} fn={i.name}: {i.message}')

print('\n=== WARNING ISSUES BY CATEGORY ===')
warn_cats = Counter(i.category for i in warn)
for c, n in warn_cats.most_common():
    print(f'  {c}: {n}')

print('\n=== WARNING ISSUES: deep-nesting ===')
for i in sorted([x for x in warn if x.category == 'deep-nesting'], key=lambda x: (x.file_path, x.line)):
    print(f'  {i.file_path}:{i.line} fn={i.name}: {i.message}')

print('\n=== WARNING ISSUES: long-function (top 30) ===')
lf = sorted([x for x in warn if x.category == 'long-function'], key=lambda x: -x.metric_value if x.metric_value else 0)
for i in lf[:30]:
    print(f'  {i.file_path}:{i.line} fn={i.name}: {i.message} (metric={i.metric_value})')

print('\n=== WARNING ISSUES: complex-function (top 30) ===')
cf = sorted([x for x in warn if x.category == 'complex-function'], key=lambda x: -x.metric_value if x.metric_value else 0)
for i in cf[:30]:
    print(f'  {i.file_path}:{i.line} fn={i.name}: {i.message} (metric={i.metric_value})')

print('\n=== FILES WITH MOST CRITICAL+WARNING ISSUES ===')
file_counts = Counter()
for i in crit + warn:
    file_counts[i.file_path] += 1
for f, c in file_counts.most_common(25):
    print(f'  {f}: {c} issues')
