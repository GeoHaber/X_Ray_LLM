"""Quick script to display self-scan results from scan_self.json."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "scan_self.json"
try:
    with open(path, encoding="utf-8-sig") as f:
        d = json.load(f)
except (OSError, json.JSONDecodeError) as exc:
    print(f"Error reading {path}: {exc}", file=sys.stderr)
    sys.exit(1)

print(f"Files scanned: {d['files_scanned']}")
print(f"Rules checked: {d['rules_checked']}")
s = d["summary"]
print(f"Total findings: {s['total']}")
print(f"  HIGH:   {s['high']}")
print(f"  MEDIUM: {s['medium']}")
print(f"  LOW:    {s['low']}")
print()

# Grade (same logic as xray/scanner.py)
total = s["total"]
if total == 0:
    grade = "A+"
elif total <= 3:
    grade = "A"
elif total <= 6:
    grade = "B"
elif total <= 10:
    grade = "C"
elif total <= 20:
    grade = "D"
else:
    grade = "F"
print(f"Grade: {grade}")
print("=" * 110)

for item in d["findings"]:
    msg = item.get("description", item.get("message", ""))[:72]
    fp = item.get("file", item.get("file_path", "?"))
    print(f"  {item['rule_id']:10s} {item['severity']:7s} {fp}:{item['line']:<4d}  {msg}")
