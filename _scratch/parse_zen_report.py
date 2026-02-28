"""Parse and summarize the X-Ray scan results for ZEN_AI_RAG."""
import json

with open(r'C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG\xray_scan_latest.json', 'r') as f:
    data = json.load(f)

# Grade breakdown
g = data.get('grade', {})
print(f"GRADE: {g.get('letter', '?')} ({g.get('score', 0)}/100)")
print()
bd = g.get('breakdown', {})
for k, v in bd.items():
    print(f"  {k}: deduction={v}")

print()
# Smells summary
sm = data.get('smells', {})
print(f"SMELLS: total = {sm.get('total', 0)}")
print(f"  critical: {sm.get('critical', 0)}")
print(f"  warning: {sm.get('warning', 0)}")
print(f"  info: {sm.get('info', 0)}")
cats = sm.get('by_category', {})
print("  By category:")
for c, n in sorted(cats.items(), key=lambda x: -x[1]):
    print(f"    {c}: {n}")

print()
# Duplicates
dup = data.get('duplicates', {})
print(f"DUPLICATES: groups = {dup.get('total_groups', 0)}")

print()
# Lint
lint = data.get('lint', {})
print(f"LINT: total = {lint.get('total', 0)}")
rules = lint.get('by_rule', {})
for r, c in rules.items():
    print(f"  {r}: {c}")

print()
# Security
sec = data.get('security', {})
print(f"SECURITY: total = {sec.get('total', 0)}")
sev = sec.get('by_severity', {})
for s, c in sev.items():
    print(f"  {s}: {c}")

print()
# Critical smells (most impactful)
print("=== CRITICAL SMELL ISSUES (worst files) ===")
issues = data.get('_smell_issues', [])
crit_files = {}
for issue in issues:
    sev = issue.get('severity', '')
    loc = issue.get('location', '')
    fname = loc.split(':')[0] if ':' in loc else loc
    if sev == 'critical':
        crit_files[fname] = crit_files.get(fname, 0) + 1
for f, c in sorted(crit_files.items(), key=lambda x: -x[1])[:20]:
    print(f"  {f}: {c} critical issues")

print()
print("=== CRITICAL SMELL CATEGORIES ===")
crit_cats = {}
for issue in issues:
    if issue.get('severity') == 'critical':
        cat = issue.get('category', 'unknown')
        crit_cats[cat] = crit_cats.get(cat, 0) + 1
for c, n in sorted(crit_cats.items(), key=lambda x: -x[1]):
    print(f"  {c}: {n}")

# Security issues by file
print()
print("=== SECURITY ISSUES (HIGH severity) ===")
sec_issues = data.get('_sec_issues', [])
for si in sec_issues:
    if si.get('severity') == 'HIGH':
        print(f"  {si.get('location', '?')}: {si.get('issue', '?')}")

print()
print("=== WARNING SMELL CATEGORIES ===")
warn_cats = {}
for issue in issues:
    if issue.get('severity') == 'warning':
        cat = issue.get('category', 'unknown')
        warn_cats[cat] = warn_cats.get(cat, 0) + 1
for c, n in sorted(warn_cats.items(), key=lambda x: -x[1]):
    print(f"  {c}: {n}")
