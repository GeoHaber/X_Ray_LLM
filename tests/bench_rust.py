"""Benchmark: Python vs Rust code_similarity performance."""

import time
import sys

sys.path.insert(0, ".")

# --- Generate test corpus ---
FUNCTIONS = []
for i in range(200):
    if i % 3 == 0:
        FUNCTIONS.append(
            f"def func_{i}(x, y):\n    result = x + y\n    if result > {i}:\n        return result * 2\n    return result\n"
        )
    elif i % 3 == 1:
        FUNCTIONS.append(
            f"def process_{i}(items):\n    out = []\n    for item in items:\n        if item > {i}:\n            out.append(item)\n    return out\n"
        )
    else:
        FUNCTIONS.append(
            f"def calc_{i}(a, b, c):\n    total = a + b + c\n    avg = total / 3\n    return {{'sum': total, 'avg': avg}}\n"
        )

N = len(FUNCTIONS)
num_pairs = N * (N - 1) // 2
print(f"Corpus: {N} functions, {num_pairs} pairs\n")

# --- Benchmark Python-only ---
# Force Python path
import x_ray_claude  # noqa: E402

# Temporarily disable Rust
_saved = x_ray_claude._HAS_RUST
x_ray_claude._HAS_RUST = False

t0 = time.perf_counter()
py_results = []
for i in range(N):
    for j in range(i + 1, N):
        sim = x_ray_claude.code_similarity(FUNCTIONS[i], FUNCTIONS[j])
        py_results.append(sim)
py_time = time.perf_counter() - t0
print(f"Python:  {py_time:.3f}s  ({num_pairs / py_time:.0f} pairs/sec)")

# --- Benchmark Rust single-call ---
x_ray_claude._HAS_RUST = _saved
try:
    import x_ray_core

    t0 = time.perf_counter()
    rust_results = []
    for i in range(N):
        for j in range(i + 1, N):
            sim = x_ray_core.code_similarity(FUNCTIONS[i], FUNCTIONS[j])
            rust_results.append(sim)
    rust_single_time = time.perf_counter() - t0
    print(
        f"Rust:    {rust_single_time:.3f}s  ({num_pairs / rust_single_time:.0f} pairs/sec)"
    )
    print(f"  → {py_time / rust_single_time:.1f}× faster (single-threaded)")

    # --- Benchmark Rust batch (parallel) ---
    t0 = time.perf_counter()
    matrix = x_ray_core.batch_code_similarity(FUNCTIONS)
    rust_batch_time = time.perf_counter() - t0
    print(
        f"Rust batch: {rust_batch_time:.3f}s  ({num_pairs / rust_batch_time:.0f} pairs/sec)"
    )
    print(f"  → {py_time / rust_batch_time:.1f}× faster (parallel)")

    # Verify Rust batch vs single are consistent
    diffs = []
    idx = 0
    for i in range(N):
        for j in range(i + 1, N):
            diffs.append(abs(rust_results[idx] - matrix[i][j]))
            idx += 1
    max_diff = max(diffs)
    print(f"\n  Max batch vs single diff: {max_diff:.6f}")

except ImportError:
    print("Rust module not available — skipping Rust benchmarks")

print("\nDone.")
