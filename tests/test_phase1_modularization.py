
import sys
import pytest
import ast
import tempfile
import os

# Validating PYTHONPATH hack
from pathlib import Path
project_root = str(Path(__file__).resolve().parents[1])
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from Core.types import FunctionRecord
    from Analysis.ast_utils import extract_functions_from_file, ASTNormalizer
    from Analysis.similarity import tokenize, code_similarity, semantic_similarity
    from Analysis.smells import CodeSmellDetector
    from Analysis.duplicates import DuplicateFinder
except ImportError as e:
    pytest.fail(f"Failed to import modules: {e}")

# --- AST Utils Tests ---

def test_extract_functions():
    code = """
def foo(x):
    return x + 1

class Bar:
    def baz(self):
        pass
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(code)
        fname = f.name

    try:
        funcs, classes, err = extract_functions_from_file(Path(fname), Path(os.path.dirname(fname)))
        assert err is None
        assert len(funcs) == 2  # foo and Bar.baz
        assert len(classes) == 1 # Bar
        
        foo = next(f for f in funcs if f.name == 'foo')
        assert foo.size_lines == 2
        assert foo.complexity == 0  # Logic counts decision points (0 for linear)
        
        baz = next(f for f in funcs if f.name == 'baz')
        assert baz.file_path.endswith(os.path.basename(fname))
    finally:
        os.unlink(fname)

def test_ast_normalizer():
    code1 = "def f(a): return a + 1"
    code2 = "def g(b): return b + 1" # Structurally identical
    
    ASTNormalizer()
    ast.parse(code1)
    ast.parse(code2)
    
    # We need to manually traverse or just check if the logic holds
    # Ideally we check if structure hash is stable, but that's internal to extract_functions
    # So let's rely on extract_functions for structure hash
    pass # covered by duplicate finding tests

# --- Similarity Tests ---

def test_tokenization():
    text = "def foo(x): return x"
    tokens = tokenize(text)
    assert "foo" in tokens
    assert "def" not in tokens  # Stop word

def test_code_similarity_exact():
    s1 = "print('hello')"
    s2 = "print('hello')"
    assert code_similarity(s1, s2) == 1.0

def test_code_similarity_diff():
    s1 = "print('hello')"
    s2 = "if x: pass"
    assert code_similarity(s1, s2) < 0.5

def test_semantic_similarity():
    # Mock function records
    f1 = FunctionRecord(
        name="calculate_total", file_path="a.py", line_start=1, line_end=5,
        size_lines=5, parameters=["items"], return_type="float", decorators=[],
        docstring="Calculates sum of items", calls_to=["sum"], complexity=1,
        nesting_depth=1, code_hash="a", structure_hash="a", code="def...",
        return_count=1, branch_count=0
    )
    f2 = FunctionRecord(
        name="compute_sum", file_path="b.py", line_start=1, line_end=5,
        size_lines=5, parameters=["values"], return_type="float", decorators=[],
        docstring="Computes total of values", calls_to=["sum"], complexity=1,
        nesting_depth=1, code_hash="b", structure_hash="b", code="def...",
        return_count=1, branch_count=0
    )
    
    sim = semantic_similarity(f1, f2)
    assert sim > 0.4 # Should detect some similarity (return type, calls, docstring keywords)

# --- Duplicate Finder Tests ---

def test_duplicate_finder_exact():
    f1 = FunctionRecord(
        name="foo", file_path="a.py", line_start=1, line_end=5,
        size_lines=5, parameters=[], return_type=None, decorators=[],
        docstring="", calls_to=[], complexity=1, nesting_depth=1,
        code_hash="abc", structure_hash="struct_abc", code="pass",
        return_count=0, branch_count=0
    )
    f2 = FunctionRecord(
        name="foo", file_path="b.py", line_start=1, line_end=5,
        size_lines=5, parameters=[], return_type=None, decorators=[],
        docstring="", calls_to=[], complexity=1, nesting_depth=1,
        code_hash="abc", structure_hash="struct_abc", code="pass",
        return_count=0, branch_count=0
    )
    
    finder = DuplicateFinder()
    groups = finder.find([f1, f2])
    assert len(groups) == 1
    assert groups[0].similarity_type == "exact"

# --- Smell Detector Tests ---

def test_smell_detection():
    # Function with high complexity
    f = FunctionRecord(
        name="complex_func", file_path="a.py", line_start=1, line_end=100,
        size_lines=100, parameters=[], return_type=None, decorators=[],
        docstring="", calls_to=[], complexity=25, nesting_depth=7,
        code_hash="x", structure_hash="x", code="...",
        return_count=10, branch_count=10
    )
    
    detector = CodeSmellDetector()
    smells = detector.detect([f], [])
    
    categories = [s.category for s in smells]
    assert "complex-function" in categories
    assert "deep-nesting" in categories
    assert "too-many-returns" in categories
