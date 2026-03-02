"""Find specific remaining syntax errors in Rust source."""
import json
from pathlib import Path

d = json.load(open("_training_ground/compile_report.json"))
CRATE = Path("_verify_crate")

# Find comparison chaining errors
chain = [e for e in d['raw_errors'] if 'chained' in e['message']]
print(f"=== Chained comparison errors ({len(chain)}) ===")
for e in chain[:5]:
    src = CRATE / e['file']
    if src.exists():
        lines = src.read_text(encoding='utf-8').splitlines()
        ln = e['line'] - 1
        print(f"\n  {e['file']}:{e['line']}")
        for i in range(max(0,ln-2), min(len(lines),ln+3)):
            marker = ">>>" if i == ln else "   "
            print(f"  {marker} {lines[i][:140]}")

# Find `invalid format string: expected }, found ,`
invalid_fmt = [e for e in d['raw_errors'] if 'expected `}`, found `,`' in e['message']]
print(f"\n\n=== Invalid format string (expected }}, found ,) ({len(invalid_fmt)}) ===")
for e in invalid_fmt[:5]:
    src = CRATE / e['file']
    if src.exists():
        lines = src.read_text(encoding='utf-8').splitlines()
        ln = e['line'] - 1
        print(f"\n  {e['file']}:{e['line']}")
        for i in range(max(0,ln-1), min(len(lines),ln+2)):
            marker = ">>>" if i == ln else "   "
            print(f"  {marker} {lines[i][:140]}")

# Find format argument must be string literal
fmt_literal = [e for e in d['raw_errors'] if 'format argument must be a string literal' in e['message']]
print(f"\n\n=== Format argument must be string literal ({len(fmt_literal)}) ===")
for e in fmt_literal[:5]:
    src = CRATE / e['file']
    if src.exists():
        lines = src.read_text(encoding='utf-8').splitlines()
        ln = e['line'] - 1
        print(f"\n  {e['file']}:{e['line']}")
        for i in range(max(0,ln-1), min(len(lines),ln+2)):
            marker = ">>>" if i == ln else "   "
            print(f"  {marker} {lines[i][:140]}")

# Find 2 positional arguments
pos2 = [e for e in d['raw_errors'] if '2 positional' in e['message']]
print(f"\n\n=== 2 positional arguments ({len(pos2)}) ===")
for e in pos2[:5]:
    src = CRATE / e['file']
    if src.exists():
        lines = src.read_text(encoding='utf-8').splitlines()
        ln = e['line'] - 1
        print(f"\n  {e['file']}:{e['line']}")
        for i in range(max(0,ln-1), min(len(lines),ln+2)):
            marker = ">>>" if i == ln else "   "
            print(f"  {marker} {lines[i][:140]}")
