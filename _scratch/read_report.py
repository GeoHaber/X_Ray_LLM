import json
d = json.load(open("_training_ground/compile_report.json"))
print(f"Total errors:    {d['total_errors']}")
print(f"Total functions: {d['total_functions']}")
print(f"Rust lines:      {d['total_lines']:,}")
print(f"Error locations: {d['error_locations']}")
print(f"\nError code breakdown:")
for code, cnt in sorted(d['error_code_counts'].items(), key=lambda x: -x[1])[:15]:
    print(f"  {code:20s}: {cnt:5d}")
print(f"\nTop error patterns ({d.get('total_unique_errors', '?')} unique):")
for msg, funcs in list(d['error_messages'].items())[:10]:
    print(f"  [{len(funcs)} funcs] {msg[:80]}")
# Count syntax errors specifically
syntax = [e for e in d['raw_errors'] if e['code'] == 'error']
print(f"\nSyntax errors (no error code): {len(syntax)}")
from collections import Counter
msgs = Counter(e['message'][:80] for e in syntax)
for m, c in msgs.most_common(10):
    print(f"  [{c:3d}] {m}")
