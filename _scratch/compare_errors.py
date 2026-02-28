"""Compare error counts: baseline (35,016) vs current (34,707)."""
# Baseline from Round 4 (pre-Tier-4)
baseline = {
    "error[E0425]": 21669,
    "error[E0308]": 5272,
    "error[E0277]": 1688,
    "error[E0599]": 1663,
    "error[E0609]": 1501,
    "error[E0282]": 863,
    "error[E0369]": 695,
    "error[E0600]": 340,
    "error[E0728]": 198,
    "error[E0689]": 190,
    "error[E0608]": 132,
    "error":         261,  # syntax errors
    "error[E0433]":   82,
    "error[E0605]":   76,
    "error[E0368]":   72,
    "error[E0061]":   65,
    "error[E0070]":   48,
    "error[E0423]":   46,
    "error[E0432]":   34,
    "error[E0618]":   32,
    "error[E0615]":   31,
}

import json
d = json.load(open("_training_ground/compile_report.json"))
current = d['error_code_counts']

print(f"{'Error Code':<20} {'Baseline':>10} {'Current':>10} {'Delta':>10}")
print("-" * 55)
all_codes = sorted(set(list(baseline.keys()) + list(current.keys())),
                   key=lambda c: -(current.get(c, 0) + baseline.get(c, 0)))
total_base = 0
total_curr = 0
for code in all_codes:
    b = baseline.get(code, 0)
    c = current.get(code, 0)
    delta = c - b
    sign = "+" if delta > 0 else ""
    total_base += b
    total_curr += c
    if b > 0 or c > 0:
        print(f"  {code:<18} {b:>10,} {c:>10,} {sign}{delta:>9,}")

print("-" * 55)
print(f"  {'TOTAL':<18} {total_base:>10,} {total_curr:>10,} {total_curr-total_base:>+10,}")
print(f"\n  Reduction: {total_base - total_curr:,} errors ({(total_base-total_curr)/total_base*100:.1f}%)")
