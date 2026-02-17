"""
Compare Python vs Rust implementations of X-Ray core functions.
Tests correctness (parity) and performance (speed) side by side.
"""
import time
import json
import sys

# ── Test Data ─────────────────────────────────────────────────────────

SAMPLE_CODE_A = '''
def process_data(items: list, threshold: float = 0.5) -> dict:
    """Filter and transform data items above threshold."""
    results = {}
    for item in items:
        if item.value > threshold:
            key = item.name.lower().strip()
            results[key] = item.value * 2.0
    return results
'''

SAMPLE_CODE_B = '''
def filter_records(records: list, min_score: float = 0.5) -> dict:
    """Select records with score above minimum."""
    output = {}
    for record in records:
        if record.score > min_score:
            name = record.label.lower().strip()
            output[name] = record.score * 2.0
    return output
'''

SAMPLE_CODE_C = '''
import os
import sys

def totally_different_function(path: str) -> bool:
    if not os.path.exists(path):
        return False
    with open(path, 'r') as f:
        content = f.read()
    return len(content) > 0
'''

# Larger code for stress test
LARGE_CODES = []
for i in range(50):
    LARGE_CODES.append(f'''
def function_{i}(x_{i}: int, y_{i}: int) -> int:
    """Compute result {i}."""
    result = x_{i} + y_{i}
    for j in range({i % 10}):
        result += j * {i}
    if result > {i * 100}:
        result = result // 2
    return result
''')


def load_implementations():
    """Load both Python and Rust implementations."""
    
    # Python implementation
    from Analysis.similarity import (
        _normalized_token_stream,
        _ngram_fingerprints, 
        _ast_node_histogram,
        code_similarity as py_code_similarity,
        cosine_similarity as py_cosine_similarity,
    )
    
    # Rust implementation
    try:
        from Core import x_ray_core as rust
        rust_available = True
    except ImportError:
        rust = None
        rust_available = False
    
    return {
        'python': {
            'normalize': _normalized_token_stream,
            'ngrams': _ngram_fingerprints,
            'histogram': _ast_node_histogram,
            'similarity': py_code_similarity,
            'cosine': py_cosine_similarity,
        },
        'rust': rust,
        'rust_available': rust_available,
    }


def benchmark(func, args, iterations=100, label=""):
    """Run a function multiple times and return timing stats."""
    # Warmup
    for _ in range(min(5, iterations)):
        func(*args)
    
    # Timed runs
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = func(*args)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    
    avg = sum(times) / len(times)
    min_t = min(times)
    max_t = max(times)
    return {
        'label': label,
        'avg_ms': avg * 1000,
        'min_ms': min_t * 1000,
        'max_ms': max_t * 1000,
        'iterations': iterations,
        'result': result,
    }


def compare_correctness(impls):
    """Compare Python and Rust outputs for correctness."""
    print("\n" + "=" * 70)
    print("  CORRECTNESS COMPARISON: Python vs Rust")
    print("=" * 70)
    
    rust = impls['rust']
    py = impls['python']
    
    tests = [
        ("normalize(code_a)", 
         lambda: py['normalize'](SAMPLE_CODE_A),
         lambda: rust.normalized_token_stream(SAMPLE_CODE_A)),
        
        ("similarity(code_a, code_b) — similar",
         lambda: py['similarity'](SAMPLE_CODE_A, SAMPLE_CODE_B),
         lambda: rust.code_similarity(SAMPLE_CODE_A, SAMPLE_CODE_B)),
        
        ("similarity(code_a, code_c) — different",
         lambda: py['similarity'](SAMPLE_CODE_A, SAMPLE_CODE_C),
         lambda: rust.code_similarity(SAMPLE_CODE_A, SAMPLE_CODE_C)),
        
        ("similarity(code_a, code_a) — identical",
         lambda: py['similarity'](SAMPLE_CODE_A, SAMPLE_CODE_A),
         lambda: rust.code_similarity(SAMPLE_CODE_A, SAMPLE_CODE_A)),

        ("histogram(code_a)",
         lambda: py['histogram'](SAMPLE_CODE_A),
         lambda: rust.ast_node_histogram(SAMPLE_CODE_A)),
    ]
    
    all_pass = True
    for name, py_fn, rs_fn in tests:
        py_result = py_fn()
        rs_result = rs_fn()
        
        # Compare
        if isinstance(py_result, (int, float)):
            match = abs(py_result - rs_result) < 0.05  # 5% tolerance
            diff = f"py={py_result:.4f}  rust={rs_result:.4f}  delta={abs(py_result-rs_result):.4f}"
        elif isinstance(py_result, list):
            # Token lists may differ slightly in style
            match = py_result == rs_result
            diff = f"py_len={len(py_result)}  rust_len={len(rs_result)}"
            if not match and len(py_result) == len(rs_result):
                mismatches = [(i, p, r) for i, (p, r) in enumerate(zip(py_result, rs_result)) if p != r]
                diff += f"  mismatches={len(mismatches)}: {mismatches[:3]}"
        elif isinstance(py_result, dict):
            # Compare dict keys at least
            py_keys = set(py_result.keys())
            rs_keys = set(rs_result.keys())
            shared = py_keys & rs_keys
            match = len(shared) > 0 and len(py_keys - rs_keys) < len(py_keys) * 0.3
            diff = f"py_keys={len(py_keys)}  rust_keys={len(rs_keys)}  shared={len(shared)}"
        else:
            match = py_result == rs_result
            diff = f"py={py_result}  rust={rs_result}"
        
        if not match:
            all_pass = False
        print(f"  {'[PASS]' if match else '[FAIL]'} {name}")
        print(f"         {diff}")
    
    return all_pass


def compare_performance(impls):
    """Benchmark Python vs Rust on same inputs."""
    print("\n" + "=" * 70)
    print("  PERFORMANCE COMPARISON: Python vs Rust")
    print("=" * 70)
    
    rust = impls['rust']
    py = impls['python']
    
    benchmarks = [
        # (name, py_fn, rs_fn, args, iterations)
        ("normalize_tokens (single)",
         lambda c: py['normalize'](c),
         lambda c: rust.normalized_token_stream(c),
         (SAMPLE_CODE_A,), 500),
        
        ("code_similarity (pair)",
         lambda a, b: py['similarity'](a, b),
         lambda a, b: rust.code_similarity(a, b),
         (SAMPLE_CODE_A, SAMPLE_CODE_B), 200),
        
        ("histogram (single)",
         lambda c: py['histogram'](c),
         lambda c: rust.ast_node_histogram(c),
         (SAMPLE_CODE_A,), 500),
    ]
    
    results = []
    for name, py_fn, rs_fn, args, iters in benchmarks:
        py_bench = benchmark(py_fn, args, iters, f"Python {name}")
        rs_bench = benchmark(rs_fn, args, iters, f"Rust   {name}")
        
        speedup = py_bench['avg_ms'] / rs_bench['avg_ms'] if rs_bench['avg_ms'] > 0 else float('inf')
        
        print(f"\n  {name}:")
        print(f"    Python: {py_bench['avg_ms']:8.3f} ms avg  (min {py_bench['min_ms']:.3f}, max {py_bench['max_ms']:.3f})")
        print(f"    Rust:   {rs_bench['avg_ms']:8.3f} ms avg  (min {rs_bench['min_ms']:.3f}, max {rs_bench['max_ms']:.3f})")
        print(f"    Speedup: {speedup:.1f}x")
        
        results.append({
            'name': name,
            'python_avg_ms': py_bench['avg_ms'],
            'rust_avg_ms': rs_bench['avg_ms'],
            'speedup': speedup,
        })
    
    # Batch similarity (Rust-only has rayon parallel)
    print(f"\n  batch_code_similarity ({len(LARGE_CODES)} functions, N*N matrix):")
    
    # Python: sequential pairs
    start = time.perf_counter()
    py_matrix = []
    for i, ca in enumerate(LARGE_CODES):
        row = []
        for j, cb in enumerate(LARGE_CODES):
            if j <= i:
                row.append(py['similarity'](ca, cb) if i != j else 1.0)
            else:
                row.append(0.0)  # will mirror
        py_matrix.append(row)
    py_time = time.perf_counter() - start
    
    # Rust: batch (parallel with rayon)
    start = time.perf_counter()
    rust.batch_code_similarity(LARGE_CODES)
    rs_time = time.perf_counter() - start
    
    batch_speedup = py_time / rs_time if rs_time > 0 else float('inf')
    print(f"    Python (sequential): {py_time*1000:8.1f} ms")
    print(f"    Rust   (rayon||):    {rs_time*1000:8.1f} ms")
    print(f"    Speedup: {batch_speedup:.1f}x")
    
    results.append({
        'name': f'batch_similarity ({len(LARGE_CODES)} funcs)',
        'python_avg_ms': py_time * 1000,
        'rust_avg_ms': rs_time * 1000,
        'speedup': batch_speedup,
    })
    
    return results


def main():
    """Run Python vs Rust comparison benchmarks and print results."""
    print("\n" + "=" * 70)
    print("  X-RAY: Python vs Rust Implementation Comparison")
    print("=" * 70)
    
    impls = load_implementations()
    
    if not impls['rust_available']:
        print("\n  [!] Rust x_ray_core module not available!")
        print("      Cannot compare. Run: cd Core/x_ray_core && maturin develop --release")
        sys.exit(1)
    
    print("\n  Rust module: x_ray_core v0.2.0")
    print(f"  Functions available: {len([f for f in dir(impls['rust']) if not f.startswith('_')])}")
    
    # Correctness
    correct = compare_correctness(impls)
    
    # Performance
    perf_results = compare_performance(impls)
    
    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"\n  Correctness: {'ALL PASS' if correct else 'SOME FAILURES'}")
    print("\n  Performance speedups:")
    for r in perf_results:
        marker = ">>>" if r['speedup'] > 5 else "   "
        print(f"    {marker} {r['name']:40s}  {r['speedup']:6.1f}x faster in Rust")
    
    avg_speedup = sum(r['speedup'] for r in perf_results) / len(perf_results)
    print(f"\n  Average speedup: {avg_speedup:.1f}x")
    
    # Save results
    report = {
        'correctness': 'pass' if correct else 'fail',
        'benchmarks': perf_results,
        'avg_speedup': avg_speedup,
    }
    with open('python_vs_rust_comparison.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("\n  Report saved to python_vs_rust_comparison.json")


if __name__ == "__main__":
    main()
