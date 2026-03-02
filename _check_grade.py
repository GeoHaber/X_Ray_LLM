import json

d = json.load(open("xray_zen_ai_rag.json"))
g = d["grade"]
print(f"Grade: {g['letter']} ({g['score']})")

b = g["breakdown"]
for k, v in b.items():
    parts = [f"  {k}: penalty={v.get('penalty', '?')}"]
    if "critical" in v:
        parts.append(f"crit={v['critical']} warn={v['warning']} info={v['info']}")
    if "groups" in v:
        parts.append(f"groups={v['groups']}")
    if "fixable" in v:
        parts.append(f"fixable={v['fixable']}")
    print(" ".join(parts))
