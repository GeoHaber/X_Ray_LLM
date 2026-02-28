"""Analyze remaining syntax errors in detail to guide transpiler fixes."""
import json

d = json.load(open("_training_ground/compile_report.json"))
syntax = [e for e in d['raw_errors'] if e['code'] == 'error']

# Group by full message
from collections import Counter
msgs = Counter(e['message'] for e in syntax)
print(f"=== {len(syntax)} SYNTAX ERRORS (no error code) ===\n")
for msg, cnt in msgs.most_common(30):
    print(f"  [{cnt:3d}] {msg}")

# Now look at specific Rust source lines for the format trait issues
from pathlib import Path
CRATE = Path("_verify_crate")

print("\n\n=== Samples: unknown format trait 'f' ===")
f_errors = [e for e in syntax if "format trait `f`" in e['message']]
for e in f_errors[:5]:
    src = CRATE / e['file']
    if src.exists():
        lines = src.read_text(encoding='utf-8').splitlines()
        ln = e['line'] - 1
        ctx = lines[max(0,ln-1):ln+2]
        print(f"\n  {e['file']}:{e['line']}")
        for i, l in enumerate(ctx):
            marker = " >>> " if i == min(1, ln) else "     "
            print(f"  {marker}{l[:120]}")

print("\n\n=== Samples: unknown format trait 'd' ===")
d_errors = [e for e in syntax if "format trait `d`" in e['message']]
for e in d_errors[:5]:
    src = CRATE / e['file']
    if src.exists():
        lines = src.read_text(encoding='utf-8').splitlines()
        ln = e['line'] - 1
        ctx = lines[max(0,ln-1):ln+2]
        print(f"\n  {e['file']}:{e['line']}")
        for i, l in enumerate(ctx):
            marker = " >>> " if i == min(1, ln) else "     "
            print(f"  {marker}{l[:120]}")

print("\n\n=== Samples: 'argument never used' ===")
unused = [e for e in syntax if "argument never used" in e['message']]
for e in unused[:5]:
    src = CRATE / e['file']
    if src.exists():
        lines = src.read_text(encoding='utf-8').splitlines()
        ln = e['line'] - 1
        ctx = lines[max(0,ln-1):ln+2]
        print(f"\n  {e['file']}:{e['line']}")
        for i, l in enumerate(ctx):
            marker = " >>> " if i == min(1, ln) else "     "
            print(f"  {marker}{l[:120]}")

print("\n\n=== Samples: 'expected `,`, found `.`' ===")
comma_dot = [e for e in syntax if "expected `,`, found `.`" in e['message']]
for e in comma_dot[:5]:
    src = CRATE / e['file']
    if src.exists():
        lines = src.read_text(encoding='utf-8').splitlines()
        ln = e['line'] - 1
        ctx = lines[max(0,ln-2):ln+3]
        print(f"\n  {e['file']}:{e['line']}")
        for i, l in enumerate(ctx):
            marker = " >>> " if i == min(2, ln) else "     "
            print(f"  {marker}{l[:120]}")

print("\n\n=== Samples: '2 positional arguments' ===")
pos2 = [e for e in syntax if "2 positional" in e['message']]
for e in pos2[:5]:
    src = CRATE / e['file']
    if src.exists():
        lines = src.read_text(encoding='utf-8').splitlines()
        ln = e['line'] - 1 
        ctx = lines[max(0,ln-1):ln+2]
        print(f"\n  {e['file']}:{e['line']}")
        for i, l in enumerate(ctx):
            marker = " >>> " if i == min(1, ln) else "     "
            print(f"  {marker}{l[:120]}")
