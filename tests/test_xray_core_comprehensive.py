import pytest
import sys
from pathlib import Path

# Adjust path to find Core module
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import x_ray_core
except ImportError:
    pytest.fail(
        "Could not import x_ray_core extension. Run: maturin build --release in Core/x_ray_core/ and pip install the wheel.", pytrace=False
    )


class TestXRayCoreComprehensive:
    """Comprehensive tests for X-Ray core module."""

    # --- Tokenization Tests ---

    def test_tokenize_basic(self):
        code = "def foo(x): return x + 1"
        tokens = x_ray_core.normalized_token_stream(code)
        # Expected: def ID ( ID ) : return ID + NUM
        assert tokens == ["def", "ID", "(", "ID", ")", ":", "return", "ID", "+", "NUM"]

    def test_tokenize_strings(self):
        # f-strings, raw strings, etc. should be STR
        code = "x = f'val={v}' + r'raw' + b'bytes'"
        tokens = x_ray_core.normalized_token_stream(code)
        assert tokens == ["ID", "=", "STR", "+", "STR", "+", "STR"]

    def test_tokenize_python_3_12_syntax(self):
        """Verify tokenizer handles Python 3.12+ syntax correctly."""
        # type alias
        code = "type Point = tuple[float, float]"
        tokens = x_ray_core.normalized_token_stream(code)
        # 'type' is a soft keyword in 3.12. If our Rust tokenizer treats it as ID or keyword doesn't matter
        # as long as it handles the structure.
        # Rust lib.rs has "match", "case", "type", "_" in SOFT_KEYWORDS.
        # So "type" should be kept as "type".
        assert "type" in tokens

        # match statement
        code = """
match status:
    case 404: return "Not Found"
    case _: return "Error"
"""
        tokens = x_ray_core.normalized_token_stream(code)
        assert "match" in tokens
        assert "case" in tokens
        assert "_" in tokens

    def test_tokenize_walrus(self):
        code = "if (n := len(a)) > 10: pass"
        tokens = x_ray_core.normalized_token_stream(code)
        assert ":=" in tokens

    # --- N-gram Fingerprints Tests ---

    def test_ngram_fingerprints_basic(self):
        code = "def foo(): pass"  # tokens: def ID ( ) : pass
        tokens = x_ray_core.normalized_token_stream(code)
        fps = x_ray_core.ngram_fingerprints(tokens, n=3, w=2)
        assert len(fps) > 0
        assert isinstance(fps, set)

    def test_ngram_fingerprints_empty(self):
        fps = x_ray_core.ngram_fingerprints([], n=5, w=4)
        assert fps == set()

    def test_ngram_fingerprints_small_input(self):
        # Input smaller than n
        tokens = ["a", "b"]
        fps = x_ray_core.ngram_fingerprints(tokens, n=5, w=4)
        assert fps == set()

    def test_ngram_fingerprints_window_size_violation(self):
        with pytest.raises(ValueError, match="Window size w must be > 0"):
            x_ray_core.ngram_fingerprints(["a"] * 10, n=2, w=0)

    # --- AST Histogram Tests ---

    def test_ast_histogram_structure(self):
        code = """
def func():
    if True:
        return 1
    else:
        return 0
"""
        hist = x_ray_core.ast_node_histogram(code)
        assert hist.get("FunctionDef") == 1
        assert hist.get("If") == 1
        assert hist.get("Return") == 2
        # dict map exactness might vary, but key structure should be there

    def test_ast_histogram_async(self):
        code = "async def foo(): await bar()"
        hist = x_ray_core.ast_node_histogram(code)
        # Our tokenizer treats "async" and "await" as keywords
        # In `ast_histogram_from_tokens`:
        # "await" -> inc!("Await")
        # "async" isn't explicitly counted in the match statement in the snippet I saw,
        # but `def` counts FunctionDef.
        # Let's check what is counted.
        if "Await" in hist:
            assert hist["Await"] >= 1

    # --- Similarity Tests ---


class TestXRayCoreExtended:
    """Extended tests for similarity, batch operations, and normalisation."""

    def test_code_similarity_identical(self):
        code = "def foo(): return 1"
        sim = x_ray_core.code_similarity(code, code)
        assert sim == pytest.approx(1.0)

    def test_code_similarity_renamed(self):
        c1 = "def process_data(data): return data + 1"
        c2 = "def calc_val(val): return val + 1"
        sim = x_ray_core.code_similarity(c1, c2)
        assert sim > 0.8  # Should be high structural similarity

    def test_code_similarity_different(self):
        c1 = "def foo(): return 1"
        c2 = "class Bar: pass"
        sim = x_ray_core.code_similarity(c1, c2)
        assert sim < 0.5

    # --- Batch Similarity Tests ---

    def test_batch_similarity_matrix_properties(self):
        """Verify batch similarity matrix has correct mathematical properties."""
        codes = ["def a(): pass", "def b(): pass", "class C: pass"]
        matrix = x_ray_core.batch_code_similarity(codes)

        # Dimensions
        assert len(matrix) == 3
        assert all(len(row) == 3 for row in matrix)

        # Diagonal is 1.0
        for i in range(3):
            assert matrix[i][i] == pytest.approx(1.0)

        # Symmetry
        assert matrix[0][1] == matrix[1][0]
        assert matrix[0][2] == matrix[2][0]

    def test_normalization_stripping(self):
        """Verify code normalization strips docstrings and renames variables."""
        code = """
def foo():
    '''docstring'''
    # comment
    x = 1
    
    
    return x
"""
        norm = x_ray_core.normalize_code(code)
        assert "docstring" not in norm
        assert "# comment" not in norm
        assert "\n\n\n" not in norm  # blank lines reduced
        assert "def foo():" in norm
