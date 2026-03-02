import json

d = json.load(open("xray_zen_ai_rag.json"))

lint = d["lint"]
print("=== LINT ===")
print(f"Total: {lint['total']} | Critical: {lint['critical']} | Warning: {lint['warning']} | Info: {lint['info']} | Fixable: {lint['fixable']}")
print("\nTop lint rules:")
for rule, cnt in sorted(lint.get("by_rule", {}).items(), key=lambda x: -x[1])[:15]:
    print(f"  {cnt:4d}  {rule}")
print("\nTop lint files:")
wf = lint.get("worst_files", [])
if isinstance(wf, dict):
    for f, cnt in sorted(wf.items(), key=lambda x: -x[1])[:10]:
        print(f"  {cnt:4d}  {f}")
else:
    for w in wf[:10]:
        print(f"  {w['count']:4d}  {w['file']}")

smells = d["smells"]
print("\n=== SMELLS ===")
print(f"Total: {smells['total']} | Critical: {smells['critical']} | Warning: {smells['warning']} | Info: {smells['info']}")
print("\nSmells by category:")
for cat, cnt in sorted(smells.get("by_category", {}).items(), key=lambda x: -x[1])[:15]:
    print(f"  {cnt:4d}  {cat}")
print("\nTop smell files:")
wf2 = smells.get("worst_files", [])
if isinstance(wf2, dict):
    for f, cnt in sorted(wf2.items(), key=lambda x: -x[1])[:10]:
        print(f"  {cnt:4d}  {f}")
else:
    for w in wf2[:10]:
        print(f"  {w['count']:4d}  {w['file']}")

sec = d["security"]
print("\n=== SECURITY ===")
print(f"Total: {sec['total']} | Critical: {sec['critical']} | Warning: {sec['warning']} | Info: {sec['info']}")
print("\nTop security rules:")
for rule, cnt in sorted(sec.get("by_rule", {}).items(), key=lambda x: -x[1])[:10]:
    print(f"  {cnt:4d}  {rule}")
print("\nTop security files:")
wf3 = sec.get("worst_files", [])
if isinstance(wf3, dict):
    for f, cnt in sorted(wf3.items(), key=lambda x: -x[1])[:10]:
        print(f"  {cnt:4d}  {f}")
else:
    for w in wf3[:10]:
        print(f"  {w['count']:4d}  {w['file']}")

dup = d["duplicates"]
print("\n=== DUPLICATES ===")
print(f"Total groups: {dup['total_groups']} | Exact: {dup['exact_duplicates']} | Structural: {dup['structural_duplicates']} | Near: {dup['near_duplicates']} | Semantic: {dup.get('semantic_duplicates', 0)}")
print(f"Functions involved: {dup['total_functions_involved']}")
