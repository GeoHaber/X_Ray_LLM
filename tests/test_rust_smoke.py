"""Quick smoke test for the Rust x_ray_core module."""
import x_ray_core

# Test 1: normalized_token_stream
tokens = x_ray_core.normalized_token_stream("def foo(x, y): return x + y")
print("Tokens:", tokens)
assert "def" in tokens, "Keywords should be preserved"
assert "ID" in tokens, "Identifiers should be normalised to ID"

# Test 2: code_similarity - renamed variables (should be high)
sim1 = x_ray_core.code_similarity(
    "def foo(x): return x + 1",
    "def bar(y): return y + 2",
)
print(f"Renamed vars similarity: {sim1:.4f}")
assert sim1 > 0.5, f"Renamed vars should be similar, got {sim1}"

# Test 3: code_similarity - different structure (should be lower)
sim2 = x_ray_core.code_similarity(
    "def foo(x): return x + 1",
    "def bar(items):\n    result = []\n    for item in items:\n        if item > 0:\n            result.append(item)\n    return result",
)
print(f"Different structure: {sim2:.4f}")
assert sim2 < sim1, "Different structure should score lower than renamed vars"

# Test 4: token_ngram_similarity
ts = x_ray_core.token_ngram_similarity(
    "def f(x): return x + 1",
    "def g(y): return y + 2",
)
print(f"Token ngram sim: {ts:.4f}")

# Test 5: ast_histogram
hist = x_ray_core.ast_node_histogram(
    "if x > 0:\n    return x\nelse:\n    return -x"
)
print(f"AST histogram: {dict(hist)}")
assert "If" in hist, "Should detect If node"
assert "Return" in hist, "Should detect Return node"

# Test 6: normalize_code
code = 'def f():\n    """docstring"""\n    # comment\n    pass'
clean = x_ray_core.normalize_code(code)
print(f"Normalized: {repr(clean)}")
assert '"""' not in clean, "Docstrings should be removed"
assert "#" not in clean, "Comments should be removed"

# Test 7: batch_code_similarity
matrix = x_ray_core.batch_code_similarity([
    "def f(x): return x + 1",
    "def g(y): return y + 2",
    "class Foo:\n    def bar(self): pass",
])
print("Batch matrix:")
for row in matrix:
    print(f"  {[round(v, 3) for v in row]}")
assert matrix[0][0] == 1.0, "Diagonal should be 1.0"
assert matrix[0][1] == matrix[1][0], "Matrix should be symmetric"

# Test 8: cosine_similarity_map
sim_cos = x_ray_core.cosine_similarity_map(
    {"If": 3, "For": 2, "Call": 5},
    {"If": 3, "For": 2, "Call": 5},
)
print(f"Cosine identical: {sim_cos:.4f}")
assert sim_cos > 0.99, f"Identical maps should have cosine ~1.0, got {sim_cos}"

print("\n✅ All Rust smoke tests passed!")
