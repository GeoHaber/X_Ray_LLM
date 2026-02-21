"""
Tests for X_RAY_Claude.py — Smart AI Code Analyzer
====================================================

Comprehensive test suite covering:
  - AST extraction engine
  - Code smell detection
  - Duplicate detection
  - Library advisor
  - Smart graph generation
  - CLI / reporting
  - Edge cases & error handling
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from collections import Counter

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Core.types import (
    FunctionRecord, ClassRecord, SmellIssue, DuplicateGroup, LibrarySuggestion,
    Severity
)
from Core.config import __version__
from Analysis.similarity import (
    tokenize, cosine_similarity, code_similarity, _normalized_token_stream, _ngram_fingerprints,
    _token_ngram_similarity, _ast_node_histogram, _ast_histogram_similarity,
    name_similarity, signature_similarity, callgraph_overlap,
    semantic_similarity
)
from Analysis.ast_utils import (
    extract_functions_from_file as _extract_functions_from_file,
    collect_py_files
)
from Analysis.smells import CodeSmellDetector
from Analysis.duplicates import DuplicateFinder, UnionFind
from Analysis.library_advisor import LibraryAdvisor
from Analysis.smart_graph import SmartGraph
from Analysis.reporting import (
    print_smells as print_smell_report,
    print_duplicates as print_duplicate_report,
    print_library_report,
    build_json_report,
    ScanData,
)

from x_ray_claude import scan_codebase

# Fix missing import in test file for UNICODE_OK if it uses it directly (it does in test_icons)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_func(name="test_func", file_path="test.py", code=None,
               complexity=2, **kw) -> FunctionRecord:
    """Helper to create FunctionRecord with defaults."""
    kw.setdefault('line_start', 1)
    kw.setdefault('size_lines', 10)
    kw.setdefault('nesting_depth', 1)
    kw.setdefault('is_async', False)
    if code is None:
        code = f"def {name}():\n    pass"
    import hashlib
    import ast as _ast
    # Auto-compute return_count and branch_count from code
    try:
        _tree = _ast.parse(code)
        return_count = sum(1 for n in _ast.walk(_tree) if isinstance(n, _ast.Return))
        branch_count = sum(1 for n in _ast.walk(_tree) if isinstance(n, _ast.If))
    except SyntaxError:
        return_count = 0
        branch_count = 0
    from tests.conftest import make_func
    kw.setdefault('code_hash', hashlib.sha256(code.encode()).hexdigest())
    kw.setdefault('structure_hash', hashlib.sha256(code.encode()).hexdigest())
    return make_func(
        name=name,
        file_path=file_path,
        code=code,
        complexity=complexity,
        return_count=return_count,
        branch_count=branch_count,
        **kw,
    )


def _make_class(name="TestClass", file_path="test.py",
                size_lines=50, **kw) -> ClassRecord:
    """Helper to create ClassRecord with defaults."""
    kw.setdefault('line_start', 1)
    kw.setdefault('method_count', 5)
    kw.setdefault('base_classes', [])
    kw.setdefault('methods', ["__init__", "run"])
    kw.setdefault('has_init', True)
    from tests.conftest import make_cls
    return make_cls(
        name=name,
        file_path=file_path,
        size_lines=size_lines,
        **kw,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  1. Severity
# ─────────────────────────────────────────────────────────────────────────────

class TestSeverity:
    def test_levels(self):
        assert Severity.CRITICAL == "critical"
        assert Severity.WARNING == "warning"
        assert Severity.INFO == "info"

    def test_icons(self):
        # Directly test Severity class, assuming UNICODE_OK or mocked
        # The test originally imported UNICODE_OK from x_ray_claude
        from Core.utils import UNICODE_OK
        if UNICODE_OK:
            assert Severity.icon("critical") == "\U0001F534"
            assert Severity.icon("warning") == "\U0001F7E1"
            assert Severity.icon("info") == "\U0001F7E2"
        else:
            assert Severity.icon("critical") == "[!!]"
            assert Severity.icon("warning") == "[!]"
            assert Severity.icon("info") == "[i]"
        assert Severity.icon("unknown") == "?"


# ─────────────────────────────────────────────────────────────────────────────
#  2. FunctionRecord
# ─────────────────────────────────────────────────────────────────────────────

class TestFunctionRecord:
    """Tests for FunctionRecord construction."""

    def test_key(self):
        f = _make_func(name="do_stuff", file_path="utils/helpers.py")
        assert f.key == "utils/helpers::do_stuff"

    def test_location(self):
        f = _make_func(file_path="a.py", line_start=42)
        assert f.location == "a.py:42"

    def test_signature_no_return(self):
        f = _make_func(name="greet", parameters=["name", "age"])
        assert f.signature == "greet(name, age)"

    def test_signature_with_return(self):
        f = _make_func(name="add", parameters=["a", "b"], return_type="int")
        assert f.signature == "add(a, b) -> int"

    def test_key_stem_extraction(self):
        f = _make_func(name="parse", file_path="core/parser.py")
        assert f.key == "core/parser::parse"

    def test_key_different_dirs_same_stem(self):
        """Same filename in different directories should have different keys."""
        f1 = _make_func(name="parse", file_path="utils/config.py")
        f2 = _make_func(name="parse", file_path="core/config.py")
        assert f1.key != f2.key
        assert f1.key == "utils/config::parse"
        assert f2.key == "core/config::parse"

    def test_is_async_default_false(self):
        f = _make_func()
        assert f.is_async is False

    def test_is_async_true(self):
        f = _make_func(is_async=True)
        assert f.is_async is True


# ─────────────────────────────────────────────────────────────────────────────
#  3. ClassRecord
# ─────────────────────────────────────────────────────────────────────────────

class TestClassRecord:
    def test_basic(self):
        c = _make_class(name="MyClass", method_count=3)
        assert c.name == "MyClass"
        assert c.method_count == 3
        assert c.has_init is True

    def test_no_init(self):
        c = _make_class(has_init=False)
        assert c.has_init is False

    def test_base_classes(self):
        c = _make_class(base_classes=["Base", "Mixin"])
        assert c.base_classes == ["Base", "Mixin"]


# ─────────────────────────────────────────────────────────────────────────────
#  4. Tokenization
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenization:
    """Tests for tokenization pipeline."""

    def test_empty(self):
        assert tokenize("") == []

    def test_snake_case(self):
        tokens = tokenize("parse_model_info")
        assert "parse" in tokens
        assert "model" in tokens
        assert "info" in tokens

    def test_camel_case(self):
        tokens = tokenize("parseModelInfo")
        assert "parse" in tokens
        assert "model" in tokens
        assert "info" in tokens

    def test_stop_words_removed(self):
        tokens = tokenize("def self return")
        assert tokens == []

    def test_single_char_removed(self):
        tokens = tokenize("a b c parse")
        assert "parse" in tokens
        assert "a" not in tokens

    def test_mixed(self):
        tokens = tokenize("load_JSON_data from file")
        assert "load" in tokens
        assert "data" in tokens

    def test_digits_in_identifiers(self):
        """Digits embedded in identifiers should be preserved as tokens."""
        tokens = tokenize("base64_encoder")
        assert "base" in tokens
        assert "64" in tokens
        assert "encoder" in tokens

    def test_no_double_counting(self):
        """Each word should appear only once per occurrence (no duplicate tokens)."""
        tokens = tokenize("data")
        assert tokens.count("data") == 1


class TestCosineSimilarity:
    def test_identical(self):
        a = Counter({"hello": 2, "world": 1})
        assert cosine_similarity(a, a) == pytest.approx(1.0)

    def test_disjoint(self):
        a = Counter({"hello": 1})
        b = Counter({"goodbye": 1})
        assert cosine_similarity(a, b) == 0.0

    def test_partial_overlap(self):
        a = Counter({"hello": 1, "world": 1})
        b = Counter({"hello": 1, "earth": 1})
        assert 0 < cosine_similarity(a, b) < 1.0

    def test_empty(self):
        assert cosine_similarity(Counter(), Counter()) == 0.0

    def test_one_empty(self):
        assert cosine_similarity(Counter({"a": 1}), Counter()) == 0.0


class TestCodeSimilarity:
    """Test language-aware structural similarity (token n-gram + AST histogram)."""

    def test_identical(self):
        code = "def foo():\n    return 42"
        assert code_similarity(code, code) == 1.0

    def test_completely_different(self):
        a = "def foo():\n    return 42"
        b = "class Bar:\n    x = 'hello world asdf'"
        assert code_similarity(a, b) < 0.5

    def test_empty(self):
        assert code_similarity("", "") == 0.0
        assert code_similarity("", "some code") == 0.0

    def test_similar(self):
        a = "def process_data(data):\n    return data.strip()"
        b = "def process_text(text):\n    return text.strip()"
        assert code_similarity(a, b) > 0.6

    def test_renamed_variables_high_similarity(self):
        """Renamed variables should NOT reduce similarity (unlike SequenceMatcher)."""
        a = "def clean(x):\n    for i in x:\n        if i > 0:\n            print(i)"
        b = "def sanitize(val):\n    for v in val:\n        if v > 0:\n            print(v)"
        # Both should be very similar — only names differ
        sim = code_similarity(a, b)
        assert sim > 0.90, f"Renamed variables should be similar, got {sim:.3f}"

    def test_different_logic_low_similarity(self):
        """Same-looking code with different operations should score low."""
        a = "def calc(x, y):\n    return x + y"
        b = "def calc(x, y):\n    return x * y"
        sim = code_similarity(a, b)
        # AST differs (Add vs Mult), so similarity should drop
        assert sim < 0.95, f"Different operations should score lower, got {sim:.3f}"

    def test_loop_vs_comprehension(self):
        """Same semantics, different style — should still show some similarity."""
        a = textwrap.dedent("""\
        def evens(lst):
            result = []
            for x in lst:
                if x % 2 == 0:
                    result.append(x)
            return result
        """)
        b = "def evens(lst):\n    return [x for x in lst if x % 2 == 0]"
        sim = code_similarity(a, b)
        # Different AST structure, so won't be 1.0, but should have some overlap
        assert sim > 0.2, f"Semantically similar code should have some overlap, got {sim:.3f}"


class TestTokenNgramSimilarity:
    """Test the MOSS-style token n-gram fingerprinting."""

    def test_identical_code(self):
        code = "def foo():\n    return 42"
        assert _token_ngram_similarity(code, code) == 1.0

    def test_empty_code(self):
        assert _token_ngram_similarity("", "") == 0.0

    def test_renamed_vars_identical(self):
        """Normalised token streams should match for renamed variables."""
        a = "def foo(x):\n    return x * 2"
        b = "def bar(y):\n    return y * 2"
        assert _token_ngram_similarity(a, b) == 1.0

    def test_different_structure(self):
        a = "def foo():\n    for x in y:\n        pass"
        b = "def foo():\n    while x > 0:\n        x -= 1"
        sim = _token_ngram_similarity(a, b)
        assert sim < 0.5

    def test_normalized_token_stream_normalizes_names(self):
        tokens = _normalized_token_stream("x = my_variable + 42")
        assert "ID" in tokens
        assert "NUM" in tokens
        # Keywords should be preserved
        assert "my_variable" not in tokens

    def test_normalized_token_stream_preserves_keywords(self):
        tokens = _normalized_token_stream("if True:\n    return None")
        assert "if" in tokens
        assert "return" in tokens

    def test_ngram_fingerprints_short_code(self):
        """Very short token streams should return empty fingerprints."""
        tokens = ["ID", "=", "NUM"]  # shorter than n=5
        fps = _ngram_fingerprints(tokens, n=5)
        assert len(fps) == 0


class TestASTHistogramSimilarity:
    """Test DECKARD-style AST node histogram comparison."""

    def test_identical(self):
        code = "def foo():\n    return 42"
        sim = _ast_histogram_similarity(code, code)
        assert sim >= 0.99

    def test_same_structure(self):
        """Same AST structure, different names."""
        a = "def foo(x):\n    if x > 0:\n        return x"
        b = "def bar(y):\n    if y > 0:\n        return y"
        assert _ast_histogram_similarity(a, b) == 1.0

    def test_different_structure(self):
        """For loop vs while loop — different AST nodes."""
        a = "def foo():\n    for i in range(10):\n        pass"
        b = "def foo():\n    while True:\n        break"
        sim = _ast_histogram_similarity(a, b)
        assert sim < 0.9

    def test_add_vs_mult(self):
        """Addition vs multiplication — different BinOp sub-nodes."""
        a = "def f(x, y):\n    return x + y"
        b = "def f(x, y):\n    return x * y"
        # AST structure is similar but the operator node differs
        sim = _ast_histogram_similarity(a, b)
        assert sim < 1.0

    def test_node_histogram_counts(self):
        hist = _ast_node_histogram("if x > 0:\n    y = x + 1")
        assert hist["If"] >= 1
        assert hist["Compare"] >= 1
        assert hist["BinOp"] >= 1

    def test_syntax_error_returns_empty(self):
        hist = _ast_node_histogram("def (broken syntax::::")
        assert len(hist) == 0


# ─────────────────────────────────────────────────────────────────────────────
#  5. Code Smell Detector
# ─────────────────────────────────────────────────────────────────────────────

class TestCodeSmellDetectorFunctions:
    """Test function-level smell detection."""

    def test_clean_function(self):
        """Small clean function should have no smells."""
        f = _make_func(size_lines=10, complexity=2, nesting_depth=1,
                       docstring="Does something.", parameters=["x"])
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert len(smells) == 0

    def test_long_function_warning(self):
        f = _make_func(size_lines=65, complexity=3, nesting_depth=2)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        cats = [s.category for s in smells]
        assert "long-function" in cats

    def test_very_long_function_critical(self):
        f = _make_func(size_lines=130, complexity=3, nesting_depth=2)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        critical = [s for s in smells if s.severity == Severity.CRITICAL]
        cats = [s.category for s in critical]
        assert "long-function" in cats

    def test_deep_nesting_warning(self):
        f = _make_func(nesting_depth=4)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        cats = [s.category for s in smells]
        assert "deep-nesting" in cats

    def test_very_deep_nesting_critical(self):
        f = _make_func(nesting_depth=7)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        critical = [s for s in smells if s.severity == Severity.CRITICAL]
        assert any(s.category == "deep-nesting" for s in critical)

    def test_high_complexity_warning(self):
        f = _make_func(complexity=12)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert any(s.category == "complex-function" for s in smells)

    def test_very_high_complexity_critical(self):
        f = _make_func(complexity=25)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        critical = [s for s in smells if s.severity == Severity.CRITICAL]
        assert any(s.category == "complex-function" for s in critical)

    def test_too_many_params(self):
        f = _make_func(parameters=["a", "b", "c", "d", "e", "f", "g"])
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert any(s.category == "too-many-params" for s in smells)

    def test_exactly_threshold_params_not_smell(self):
        """Params at threshold-1 should not be flagged."""
        f = _make_func(parameters=["a", "b", "c", "d", "e"])
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert not any(s.category == "too-many-params" for s in smells)

    def test_missing_docstring(self):
        f = _make_func(size_lines=20, docstring=None, name="do_stuff")
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert any(s.category == "missing-docstring" for s in smells)


class TestCodeSmellDetectorAdvanced:
    """Advanced function-level smell detection tests."""

    def test_missing_docstring_private_skipped(self):
        """Private functions (starting with _) should not be flagged for missing docstring."""
        f = _make_func(size_lines=20, docstring=None, name="_internal")
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert not any(s.category == "missing-docstring" for s in smells)

    def test_missing_docstring_small_func_skipped(self):
        """Small functions below threshold should not be flagged."""
        f = _make_func(size_lines=5, docstring=None)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert not any(s.category == "missing-docstring" for s in smells)

    def test_boolean_blindness(self):
        f = _make_func(name="process_data", return_type="bool")
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert any(s.category == "boolean-blindness" for s in smells)

    def test_boolean_blindness_not_flagged_good_name(self):
        for prefix in ("is_valid", "has_data", "can_run", "should_stop",
                       "check_input", "validate_data", "contains_item", "exists_file"):
            f = _make_func(name=prefix, return_type="bool")
            detector = CodeSmellDetector()
            smells = detector.detect([f], [])
            assert not any(s.category == "boolean-blindness" for s in smells), \
                f"Should not flag {prefix}"

    def test_too_many_returns(self):
        code = "def big():\n" + "\n    return x\n" * 6
        f = _make_func(code=code)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert any(s.category == "too-many-returns" for s in smells)

    def test_too_many_branches(self):
        """Functions with too many if branches should be flagged."""
        code = "def branchy(x):\n" + "    if x:\n        pass\n" * 9
        f = _make_func(code=code)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert any(s.category == "too-many-branches" for s in smells)

    def test_branches_below_threshold_not_flagged(self):
        """Functions with few branches should not be flagged."""
        code = "def simple(x):\n    if x:\n        pass\n    if not x:\n        pass\n"
        f = _make_func(code=code)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        assert not any(s.category == "too-many-branches" for s in smells)

    def test_multiple_smells_same_function(self):
        """A function can have multiple smells."""
        f = _make_func(size_lines=130, complexity=25, nesting_depth=7,
                       parameters=["a"]*8, docstring=None)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        cats = {s.category for s in smells}
        assert "long-function" in cats
        assert "complex-function" in cats
        assert "deep-nesting" in cats
        assert "too-many-params" in cats

    def test_custom_thresholds(self):
        """Custom thresholds should override defaults."""
        f = _make_func(size_lines=30)
        detector = CodeSmellDetector(thresholds={"long_function": 20})
        smells = detector.detect([f], [])
        assert any(s.category == "long-function" for s in smells)

    def test_sorting_critical_first(self):
        """Critical issues should sort before warnings."""
        f1 = _make_func(name="a", size_lines=130)  # critical
        f2 = _make_func(name="b", size_lines=65)   # warning
        detector = CodeSmellDetector()
        smells = detector.detect([f1, f2], [])
        severities = [s.severity for s in smells]
        # Critical should appear before warning
        if Severity.CRITICAL in severities and Severity.WARNING in severities:
            critical_idx = severities.index(Severity.CRITICAL)
            warning_idx = severities.index(Severity.WARNING)
            assert critical_idx < warning_idx


class TestCodeSmellDetectorClasses:
    """Test class-level smell detection."""

    def test_god_class(self):
        c = _make_class(method_count=20)
        detector = CodeSmellDetector()
        smells = detector.detect([], [c])
        assert any(s.category == "god-class" for s in smells)

    def test_large_class(self):
        c = _make_class(size_lines=600)
        detector = CodeSmellDetector()
        smells = detector.detect([], [c])
        assert any(s.category == "large-class" for s in smells)

    def test_missing_class_docstring(self):
        c = _make_class(size_lines=50, docstring=None)
        detector = CodeSmellDetector()
        smells = detector.detect([], [c])
        assert any(s.category == "missing-class-docstring" for s in smells)

    def test_small_class_docstring_not_flagged(self):
        c = _make_class(size_lines=20, docstring=None)
        detector = CodeSmellDetector()
        smells = detector.detect([], [c])
        assert not any(s.category == "missing-class-docstring" for s in smells)

    def test_dataclass_candidate(self):
        c = _make_class(method_count=2, has_init=True, base_classes=[])
        detector = CodeSmellDetector()
        smells = detector.detect([], [c])
        assert any(s.category == "dataclass-candidate" for s in smells)

    def test_dataclass_candidate_not_with_bases(self):
        c = _make_class(method_count=2, has_init=True, base_classes=["Base"])
        detector = CodeSmellDetector()
        smells = detector.detect([], [c])
        assert not any(s.category == "dataclass-candidate" for s in smells)

    def test_clean_class(self):
        c = _make_class(size_lines=100, method_count=5, docstring="A good class.")
        detector = CodeSmellDetector()
        smells = detector.detect([], [c])
        # Only INFO-level stuff at most
        assert not any(s.severity == Severity.CRITICAL for s in smells)


class TestCodeSmellSummary:
    def test_summary_empty(self):
        detector = CodeSmellDetector()
        detector.detect([], [])
        s = detector.summary()
        assert s["total"] == 0
        assert s["critical"] == 0

    def test_summary_counts(self):
        f1 = _make_func(name="a", size_lines=130, file_path="a.py")
        f2 = _make_func(name="b", size_lines=65, file_path="b.py")
        detector = CodeSmellDetector()
        detector.detect([f1, f2], [])
        s = detector.summary()
        assert s["total"] > 0
        assert isinstance(s["by_category"], dict)
        assert isinstance(s["worst_files"], dict)


# ─────────────────────────────────────────────────────────────────────────────
#  6. Duplicate Finder
# ─────────────────────────────────────────────────────────────────────────────

class TestDuplicateFinder:
    """Tests for duplicate function detection."""

    def test_no_duplicates(self):
        f1 = _make_func(name="foo", file_path="a.py",
                         code="def foo():\n    return 1")
        f2 = _make_func(name="bar", file_path="b.py",
                         code="def bar(x, y):\n    return x * y + 42")
        finder = DuplicateFinder()
        groups = finder.find([f1, f2])
        exact = [g for g in groups if g.similarity_type == "exact"]
        assert len(exact) == 0

    def test_exact_duplicates(self):
        """Verify exact duplicate detection identifies identical functions."""
        code = "def helper(data):\n    cleaned = data.strip()\n    return cleaned.lower()"
        import hashlib
        hashlib.sha256(code.encode()).hexdigest()
        f1 = _make_func(name="helper", file_path="a.py", code=code,
                         size_lines=3)
        f2 = _make_func(name="helper", file_path="b.py", code=code,
                         size_lines=3)
        # Ensure same hash
        assert f1.code_hash == f2.code_hash
        finder = DuplicateFinder()
        groups = finder.find([f1, f2])
        exact = [g for g in groups if g.similarity_type == "exact"]
        assert len(exact) == 1
        assert len(exact[0].functions) == 2

    def test_same_file_skipped_cross_file_only(self):
        """Same-file duplicates should be skipped when cross_file_only=True."""
        code = "def helper():\n    return 'same'"
        f1 = _make_func(name="helper1", file_path="a.py", code=code, size_lines=2)
        f2 = _make_func(name="helper2", file_path="a.py", code=code, size_lines=2)
        finder = DuplicateFinder()
        groups = finder.find([f1, f2], cross_file_only=True)
        assert len(groups) == 0

    def test_same_file_found_when_not_cross_file(self):
        code = "def helper():\n    return 'same'"
        f1 = _make_func(name="helper1", file_path="a.py", code=code, size_lines=2)
        f2 = _make_func(name="helper2", file_path="a.py", code=code, size_lines=2)
        finder = DuplicateFinder()
        groups = finder.find([f1, f2], cross_file_only=False)
        assert len(groups) >= 1

    def test_near_duplicates(self):
        """Similar but not identical code should be detected as near-duplicates."""
        code_a = textwrap.dedent("""\
        def process_data(data, config=None):
            result = []
            for item in data:
                cleaned = item.strip()
                if cleaned and len(cleaned) > 0:
                    result.append(cleaned.lower())
            return result
        """)
        code_b = textwrap.dedent("""\
        def transform_data(data, config=None):
            result = []
            for item in data:
                cleaned = item.strip()
                if cleaned and len(cleaned) > 0:
                    result.append(cleaned.upper())
            return result
        """)
        f1 = _make_func(name="process_data", file_path="a.py", code=code_a,
                         size_lines=8, parameters=["data", "config"],
                         docstring="Process data items", calls_to=["strip", "lower", "append"])
        f2 = _make_func(name="transform_data", file_path="b.py", code=code_b,
                         size_lines=8, parameters=["data", "config"],
                         docstring="Transform data items", calls_to=["strip", "upper", "append"])
        finder = DuplicateFinder()
        groups = finder.find([f1, f2])
        near = [g for g in groups if g.similarity_type == "near"]
        assert len(near) >= 1

    def test_boilerplate_skipped(self):
        """__init__ and other boilerplate should be skipped."""
        code = "def __init__(self):\n    self.x = 1"
        f1 = _make_func(name="__init__", file_path="a.py", code=code, size_lines=2)
        f2 = _make_func(name="__init__", file_path="b.py", code=code, size_lines=2)
        finder = DuplicateFinder()
        groups = finder.find([f1, f2])
        assert len(groups) == 0

    def test_tiny_functions_skipped(self):
        """Functions < 5 lines should be skipped in near-dup stage 2."""
        code = "def x():\n    pass"
        f1 = _make_func(name="x", file_path="a.py", code=code, size_lines=2)
        f2 = _make_func(name="y", file_path="b.py", code=code, size_lines=2)
        finder = DuplicateFinder()
        groups = finder.find([f1, f2])
        # Exact match still detected (hash), but near-dup stage skips tiny
        # (tiny functions have same hash so they'd be exact)
        # but if different names with same hash, they ARE exact
        assert all(g.similarity_type == "exact" for g in groups) or len(groups) == 0

    def test_wildly_different_sizes_skipped(self):
        """Functions with very different sizes should not be compared."""
        code_a = "def small():\n    return 1\n" * 3
        code_b = "def big():\n    x = 1\n" * 30
        f1 = _make_func(name="small", file_path="a.py", code=code_a, size_lines=6)
        f2 = _make_func(name="big", file_path="b.py", code=code_b, size_lines=60)
        finder = DuplicateFinder()
        groups = finder.find([f1, f2])
        near = [g for g in groups if g.similarity_type == "near"]
        assert len(near) == 0

    def test_summary(self):
        finder = DuplicateFinder()
        finder.find([])
        s = finder.summary()
        assert s["total_groups"] == 0
        assert s["exact_duplicates"] == 0
        assert s["near_duplicates"] == 0
        assert s["semantic_duplicates"] == 0


# ─────────────────────────────────────────────────────────────────────────────
#  6a. UnionFind
# ─────────────────────────────────────────────────────────────────────────────

class TestUnionFind:
    def test_basic_union(self):
        uf = UnionFind()
        uf.union("a", "b")
        assert uf.find("a") == uf.find("b")

    def test_transitive_union(self):
        uf = UnionFind()
        uf.union("a", "b")
        uf.union("b", "c")
        assert uf.find("a") == uf.find("c")

    def test_disjoint(self):
        uf = UnionFind()
        uf.union("a", "b")
        uf.union("c", "d")
        assert uf.find("a") != uf.find("c")

    def test_find_without_union(self):
        uf = UnionFind()
        root = uf.find("x")
        assert root == "x"


# ─────────────────────────────────────────────────────────────────────────────
#  6b. Semantic Similarity
# ─────────────────────────────────────────────────────────────────────────────

class TestNameSimilarity:
    def test_identical_names(self):
        assert name_similarity("load_config", "load_config") == 1.0

    def test_similar_names(self):
        """Names with shared tokens should have high similarity."""
        sim = name_similarity("load_config", "read_config")
        assert sim > 0.3  # 'config' token in common

    def test_different_naming_style(self):
        """camelCase vs snake_case with same meaning."""
        sim = name_similarity("loadConfig", "load_config")
        assert sim > 0.5

    def test_completely_different(self):
        sim = name_similarity("parse_xml", "render_image")
        assert sim == 0.0

    def test_empty_name(self):
        assert name_similarity("", "something") == 0.0
        assert name_similarity("", "") == 0.0


class TestSignatureSimilarity:
    def test_identical_signatures(self):
        f1 = _make_func(parameters=["data", "config"], return_type="dict")
        f2 = _make_func(parameters=["data", "config"], return_type="dict")
        sim = signature_similarity(f1, f2)
        assert sim > 0.8

    def test_different_signatures(self):
        f1 = _make_func(parameters=["x", "y"], return_type="int")
        f2 = _make_func(parameters=["name", "age", "address"],
                        return_type="str", is_async=True)
        sim = signature_similarity(f1, f2)
        assert sim < 0.4

    def test_no_params_both(self):
        f1 = _make_func(parameters=[])
        f2 = _make_func(parameters=[])
        sim = signature_similarity(f1, f2)
        assert sim > 0.5  # both zero-param → match


class TestCallgraphOverlap:
    def test_same_calls(self):
        f1 = _make_func(calls_to=["json.loads", "open", "strip"])
        f2 = _make_func(calls_to=["json.loads", "open", "strip"])
        assert callgraph_overlap(f1, f2) == 1.0

    def test_partial_overlap(self):
        f1 = _make_func(calls_to=["open", "read", "close"])
        f2 = _make_func(calls_to=["open", "write", "close"])
        overlap = callgraph_overlap(f1, f2)
        assert 0.4 < overlap < 0.8  # 2/4 overlap

    def test_no_overlap(self):
        f1 = _make_func(calls_to=["parse"])
        f2 = _make_func(calls_to=["render"])
        assert callgraph_overlap(f1, f2) == 0.0

    def test_empty_calls(self):
        f1 = _make_func(calls_to=[])
        f2 = _make_func(calls_to=[])
        assert callgraph_overlap(f1, f2) == 0.0


class TestSemanticSimilarity:
    def test_functionally_similar(self):
        """Functions with same name tokens, params, and calls should score high."""
        f1 = _make_func(name="load_settings", parameters=["path", "defaults"],
                        return_type="dict", calls_to=["open", "json.load", "update"],
                        docstring="Load settings from a JSON file.")
        f2 = _make_func(name="read_settings", parameters=["filepath", "defaults"],
                        return_type="dict", calls_to=["open", "json.load", "merge"],
                        docstring="Read settings from a config file.")
        sim = semantic_similarity(f1, f2)
        assert sim > 0.4

    def test_completely_different_semantics(self):
        """Unrelated functions should score low."""
        f1 = _make_func(name="render_image", parameters=["pixels", "width"],
                        return_type="bytes", calls_to=["encode", "compress"])
        f2 = _make_func(name="send_email", parameters=["to", "subject", "body"],
                        return_type="bool", calls_to=["smtp.connect", "send"],
                        is_async=True)
        sim = semantic_similarity(f1, f2)
        assert sim < 0.2

    def test_same_function(self):
        f = _make_func(name="process", parameters=["data"],
                       return_type="list", calls_to=["filter", "map"],
                       docstring="Process data items.")
        sim = semantic_similarity(f, f)
        assert sim > 0.8


class TestSemanticStageInDuplicateFinder:
    """Tests for semantic stage in duplicate finder."""

    def test_semantic_detection(self):
        """Functions with different code but same purpose should be detected."""
        f1 = _make_func(
            name="load_config", file_path="a.py", size_lines=15,
            parameters=["path", "defaults"],
            return_type="dict",
            calls_to=["open", "json.load", "update", "close"],
            docstring="Load configuration from file.",
            code="def load_config(path, defaults):\n    with open(path) as f:\n        data = json.load(f)\n    defaults.update(data)\n    return defaults\n" + "    # padding\n" * 10,
        )
        f2 = _make_func(
            name="read_config", file_path="b.py", size_lines=15,
            parameters=["filepath", "defaults"],
            return_type="dict",
            calls_to=["open", "json.load", "merge", "close"],
            docstring="Read configuration from disk.",
            code="def read_config(filepath, defaults):\n    fh = open(filepath, 'r')\n    cfg = json.load(fh)\n    fh.close()\n    return {**defaults, **cfg}\n" + "    # pad\n" * 10,
        )
        finder = DuplicateFinder()
        groups = finder.find([f1, f2])
        semantic = [g for g in groups if g.similarity_type == "semantic"]
        assert len(semantic) >= 1

    def test_semantic_skips_tiny_functions(self):
        """Functions below SEMANTIC_MIN_LINES should not be semantic-matched."""
        f1 = _make_func(name="load_data", file_path="a.py", size_lines=3,
                        calls_to=["open", "read"])
        f2 = _make_func(name="read_data", file_path="b.py", size_lines=3,
                        calls_to=["open", "read"])
        finder = DuplicateFinder()
        groups = finder.find([f1, f2])
        semantic = [g for g in groups if g.similarity_type == "semantic"]
        assert len(semantic) == 0

    def test_summary_includes_semantic(self):
        finder = DuplicateFinder()
        finder.find([])
        s = finder.summary()
        assert "semantic_duplicates" in s
        assert s["semantic_duplicates"] == 0


# ─────────────────────────────────────────────────────────────────────────────
#  7. Library Advisor
# ─────────────────────────────────────────────────────────────────────────────

class TestLibraryAdvisor:
    """Tests for library advisor suggestions."""

    def test_no_suggestions_empty(self):
        advisor = LibraryAdvisor()
        suggestions = advisor.analyze([], [])
        assert len(suggestions) == 0

    def test_suggestion_from_duplicate_group(self):
        """Verify library suggestions are generated from duplicate groups."""
        group = DuplicateGroup(
            group_id=0, similarity_type="near", avg_similarity=0.85,
            functions=[
                {"key": "a::parse", "name": "parse", "file": "a.py",
                 "line": 1, "size": 10, "similarity": 0.85},
                {"key": "b::parse", "name": "parse", "file": "b.py",
                 "line": 5, "size": 12, "similarity": 0.85},
            ],
        )
        f1 = _make_func(name="parse", file_path="a.py", size_lines=10,
                         docstring="Parse data")
        f2 = _make_func(name="parse", file_path="b.py", size_lines=12)
        advisor = LibraryAdvisor()
        suggestions = advisor.analyze([group], [f1, f2])
        assert len(suggestions) >= 1
        assert suggestions[0].module_name  # should have a name
        assert len(suggestions[0].functions) >= 2

    def test_cross_file_name_analysis(self):
        """Functions with same name across files should be suggested."""
        f1 = _make_func(name="normalize", file_path="a.py")
        f2 = _make_func(name="normalize", file_path="b.py")
        f3 = _make_func(name="normalize", file_path="c.py")
        advisor = LibraryAdvisor()
        suggestions = advisor.analyze([], [f1, f2, f3])
        assert len(suggestions) >= 1
        assert any("normalize" in s.description for s in suggestions)

    def test_single_file_not_suggested(self):
        """Function in only one file should not be suggested."""
        f1 = _make_func(name="unique_func", file_path="a.py")
        advisor = LibraryAdvisor()
        suggestions = advisor.analyze([], [f1])
        assert len(suggestions) == 0

    def test_module_name_suggestion_patterns(self):
        advisor = LibraryAdvisor()
        assert advisor._suggest_module_name(["parse_data"]) == "utils"
        assert advisor._suggest_module_name(["read_file"]) == "io_helpers"
        assert advisor._suggest_module_name(["validate_input"]) == "validators"
        assert advisor._suggest_module_name(["search_index"]) == "search"
        assert advisor._suggest_module_name(["some_random"]) == "shared_utils"

    def test_summary(self):
        advisor = LibraryAdvisor()
        advisor.analyze([], [])
        s = advisor.summary()
        assert s["total_suggestions"] == 0
        assert s["total_functions"] == 0


# ─────────────────────────────────────────────────────────────────────────────
#  8. Smart Graph
# ─────────────────────────────────────────────────────────────────────────────

class TestSmartGraph:
    """Tests for smart graph visualization."""

    def test_empty(self):
        graph = SmartGraph()
        graph.build([], [], [], Path("."))
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_nodes_from_functions(self):
        f1 = _make_func(name="a", file_path="module_a.py")
        f2 = _make_func(name="b", file_path="module_b.py")
        graph = SmartGraph()
        graph.build([f1, f2], [], [], Path("."))
        assert len(graph.nodes) == 2

    def test_health_coloring_green(self):
        f = _make_func(file_path="clean.py")
        graph = SmartGraph()
        graph.build([f], [], [], Path("."))
        node = graph.nodes[0]
        assert node["color"] == "#2ecc71"  # green
        assert node["health"] == "healthy"

    def test_health_coloring_yellow(self):
        f = _make_func(file_path="warn.py")
        smell = SmellIssue(
            file_path="warn.py", line=1, end_line=10,
            category="long-function", severity=Severity.WARNING,
            message="too long", suggestion="fix it", name="test_func",
            metric_value=70,
        )
        graph = SmartGraph()
        graph.build([f], [smell], [], Path("."))
        node = graph.nodes[0]
        assert node["color"] == "#f39c12"  # orange

    def test_health_coloring_red(self):
        f = _make_func(file_path="bad.py")
        smell = SmellIssue(
            file_path="bad.py", line=1, end_line=10,
            category="god-class", severity=Severity.CRITICAL,
            message="bad", suggestion="fix", name="test_func", metric_value=20,
        )
        graph = SmartGraph()
        graph.build([f], [smell], [], Path("."))
        node = graph.nodes[0]
        assert node["color"] == "#e74c3c"  # red

    def test_duplicate_edges(self):
        f1 = _make_func(name="a", file_path="a.py")
        f2 = _make_func(name="b", file_path="b.py")
        group = DuplicateGroup(
            group_id=0, similarity_type="near", avg_similarity=0.8,
            functions=[
                {"key": "a::a", "name": "a", "file": "a.py", "line": 1},
                {"key": "b::b", "name": "b", "file": "b.py", "line": 1},
            ],
        )
        graph = SmartGraph()
        graph.build([f1, f2], [], [group], Path("."))
        assert len(graph.edges) == 1

    def test_write_html(self, tmp_path):
        f = _make_func(file_path="test.py")
        graph = SmartGraph()
        graph.build([f], [], [], Path("."))
        out = tmp_path / "graph.html"
        graph.write_html(out)
        assert out.exists()
        content = out.read_text()
        assert "vis-network" in content
        assert "X-RAY Claude" in content

    def test_tooltip_includes_smells(self):
        f = _make_func(file_path="smelly.py")
        smell = SmellIssue(
            file_path="smelly.py", line=1, end_line=5,
            category="deep-nesting", severity=Severity.WARNING,
            message="deep", suggestion="fix", name="test_func",
            metric_value=5,
        )
        graph = SmartGraph()
        graph.build([f], [smell], [], Path("."))
        title = graph.nodes[0]["title"]
        assert "deep-nesting" in title


# ─────────────────────────────────────────────────────────────────────────────
#  9. AST Extraction (Integration with real code)
# ─────────────────────────────────────────────────────────────────────────────

class TestASTExtraction:
    """Tests for AST extraction pipeline."""

    _SAMPLE_CODE = textwrap.dedent("""\
    def greet(name: str) -> str:
        \"\"\"Say hello.\"\"\"
        return f"Hello, {name}!"
    
    async def fetch_data(url):
        pass
    
    class MyClass:
        def __init__(self):
            self.x = 1
        
        def process(self, data):
            for item in data:
                if item > 0:
                    yield item
    """)

    def _extract_sample(self, tmp_path):
        """Write sample code and extract functions/classes."""
        py_file = tmp_path / "sample.py"
        py_file.write_text(self._SAMPLE_CODE)
        return _extract_functions_from_file(py_file, tmp_path)

    def test_extract_from_temp_file(self, tmp_path):
        """Verify function extraction from temporary Python files."""
        functions, classes, error = self._extract_sample(tmp_path)
        assert error is None
        assert len(functions) >= 3  # greet, fetch_data, __init__, process
        assert len(classes) == 1

    def test_extract_greet_details(self, tmp_path):
        """Verify 'greet' function metadata."""
        functions, _, _ = self._extract_sample(tmp_path)
        greet = next(f for f in functions if f.name == "greet")
        assert greet.return_type == "str"
        assert greet.docstring == "Say hello."
        assert "name" in greet.parameters

    def test_extract_async_flag(self, tmp_path):
        """Verify async function detection."""
        functions, _, _ = self._extract_sample(tmp_path)
        fetch = next(f for f in functions if f.name == "fetch_data")
        assert fetch.is_async is True

    def test_extract_class_details(self, tmp_path):
        """Verify class extraction details."""
        _, classes, _ = self._extract_sample(tmp_path)
        cls = classes[0]
        assert cls.name == "MyClass"
        assert cls.has_init is True
        assert "process" in cls.methods

    def test_syntax_error_handled(self, tmp_path):
        """Files with syntax errors should return error, not crash."""
        py_file = tmp_path / "bad.py"
        py_file.write_text("def broken(\n    # missing close paren")
        functions, classes, error = _extract_functions_from_file(py_file, tmp_path)
        assert error is not None
        assert "SyntaxError" in error
        assert len(functions) == 0

    def test_empty_file(self, tmp_path):
        py_file = tmp_path / "empty.py"
        py_file.write_text("")
        functions, classes, error = _extract_functions_from_file(py_file, tmp_path)
        assert error is None
        assert len(functions) == 0
        assert len(classes) == 0

    def test_nesting_depth_calculation(self, tmp_path):
        """Verify nesting depth calculation for nested control structures."""
        code = textwrap.dedent("""\
        def deep():
            for i in range(10):
                if i > 0:
                    for j in range(5):
                        if j > 0:
                            while True:
                                break
        """)
        py_file = tmp_path / "deep.py"
        py_file.write_text(code)
        functions, _, _ = _extract_functions_from_file(py_file, tmp_path)
        assert len(functions) == 1
        assert functions[0].nesting_depth >= 4

    def test_complexity_calculation(self, tmp_path):
        """Verify cyclomatic complexity calculation for branching functions."""
        code = textwrap.dedent("""\
        def complex_func(x, y):
            if x > 0:
                for i in range(y):
                    if i % 2 == 0:
                        try:
                            pass
                        except ValueError:
                            pass
                    elif i > 5:
                        pass
            while x > 0:
                x -= 1
        """)
        py_file = tmp_path / "complex.py"
        py_file.write_text(code)
        functions, _, _ = _extract_functions_from_file(py_file, tmp_path)
        assert functions[0].complexity >= 5

    def test_nested_functions_excluded(self, tmp_path):
        """Nested functions inside other functions should NOT be extracted."""
        code = textwrap.dedent("""\
        def outer():
            def inner():
                return 42
            return inner()
        """)
        py_file = tmp_path / "nested.py"
        py_file.write_text(code)
        functions, _, _ = _extract_functions_from_file(py_file, tmp_path)
        names = [f.name for f in functions]
        assert "outer" in names
        assert "inner" not in names

    def test_nested_in_method_excluded(self, tmp_path):
        """Nested functions inside class methods should NOT be extracted."""
        code = textwrap.dedent("""\
        class MyClass:
            def method(self):
                def helper():
                    return 1
                return helper()
        """)
        py_file = tmp_path / "nested_method.py"
        py_file.write_text(code)
        functions, classes, _ = _extract_functions_from_file(py_file, tmp_path)
        names = [f.name for f in functions]
        assert "method" in names
        assert "helper" not in names
        assert len(classes) == 1


class TestScanCodebase:
    def test_scan_temp_project(self, tmp_path):
        """Test scanning a mini project."""
        (tmp_path / "main.py").write_text("def main():\n    print('hi')\n")
        (tmp_path / "utils.py").write_text(
            "def helper(x):\n    return x + 1\n\n"
            "def format_text(t):\n    return t.strip()\n"
        )
        sub = tmp_path / "core"
        sub.mkdir()
        (sub / "engine.py").write_text("class Engine:\n    def run(self):\n        pass\n")

        functions, classes, errors = scan_codebase(tmp_path)
        assert len(functions) >= 3
        assert len(classes) >= 1
        assert len(errors) == 0

    def test_scan_excludes_venv(self, tmp_path):
        """Files in .venv should be excluded."""
        venv = tmp_path / ".venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "somelib.py").write_text("def internal():\n    pass\n")
        (tmp_path / "app.py").write_text("def app():\n    pass\n")

        functions, _, _ = scan_codebase(tmp_path)
        files = {f.file_path for f in functions}
        assert not any(".venv" in fp for fp in files)
        assert any("app" in fp for fp in files)


class TestCollectPyFiles:
    def test_basic(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1")
        (tmp_path / "b.txt").write_text("not python")
        files = collect_py_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "a.py"

    def test_exclude(self, tmp_path):
        sub = tmp_path / "tests"
        sub.mkdir()
        (sub / "test_a.py").write_text("pass")
        (tmp_path / "app.py").write_text("pass")
        files = collect_py_files(tmp_path, exclude=["tests"])
        names = [f.name for f in files]
        assert "test_a.py" not in names
        assert "app.py" in names

    def test_always_skip(self, tmp_path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.py").write_text("pass")
        files = collect_py_files(tmp_path)
        assert len(files) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 10. Report Printing (smoke tests — just don't crash)
# ─────────────────────────────────────────────────────────────────────────────

class TestReportPrinting:
    """Tests for report printing functions."""

    def test_smell_report_empty(self, capsys):
        print_smell_report([], {"total": 0, "critical": 0, "warning": 0,
                                "info": 0, "by_category": {}, "worst_files": {}})
        out = capsys.readouterr().out
        assert "CODE SMELL REPORT" in out

    def test_smell_report_with_issues(self, capsys):
        smell = SmellIssue(
            file_path="a.py", line=1, end_line=10,
            category="long-function", severity=Severity.WARNING,
            message="too long", suggestion="split it",
            name="big_func", metric_value=70,
        )
        summary = {"total": 1, "critical": 0, "warning": 1, "info": 0,
                    "by_category": {"long-function": 1},
                    "worst_files": {"a.py": 1}}
        print_smell_report([smell], summary)
        out = capsys.readouterr().out
        assert "LONG-FUNCTION" in out
        assert "big_func" in out

    def test_duplicate_report_empty(self, capsys):
        print_duplicate_report([], {"total_groups": 0, "exact_duplicates": 0,
                                     "near_duplicates": 0,
                                     "structural_duplicates": 0,
                                     "semantic_duplicates": 0,
                                     "total_functions_involved": 0,
                                     "avg_similarity": 0})
        out = capsys.readouterr().out
        assert "SIMILAR FUNCTIONS" in out

    def test_library_report_empty(self, capsys):
        print_library_report([], {"total_suggestions": 0, "total_functions": 0,
                                   "modules_proposed": []})
        out = capsys.readouterr().out
        assert "LIBRARY EXTRACTION" in out


# ─────────────────────────────────────────────────────────────────────────────
# 11. JSON Report
# ─────────────────────────────────────────────────────────────────────────────

class TestJSONReport:
    """Tests for JSON report generation."""

    def test_basic_structure(self):
        f = _make_func()
        c = _make_class()
        report = build_json_report(
            Path("."), ScanData([f], [c], [], [], []), 1.23
        )
        assert report["version"] == __version__
        assert report["scan_time_seconds"] == 1.23
        assert report["stats"]["total_functions"] == 1
        assert report["stats"]["total_classes"] == 1

    def test_serializable(self):
        f = _make_func()
        report = build_json_report(Path("."), ScanData([f], [], [], [], []), 0.5)
        # Should be JSON-serializable
        j = json.dumps(report)
        assert isinstance(j, str)
        parsed = json.loads(j)
        assert parsed["version"] == __version__

    def test_includes_smells(self):
        f = _make_func(size_lines=130)
        detector = CodeSmellDetector()
        smells = detector.detect([f], [])
        report = build_json_report(Path("."), ScanData([f], [], smells, [], []), 0.1)
        assert report["smells"]["total"] > 0
        assert len(report["smells"]["issues"]) > 0

    def test_includes_duplicates(self):
        group = DuplicateGroup(
            group_id=0, similarity_type="exact", avg_similarity=1.0,
            functions=[{"key": "a.f", "name": "f", "file": "a.py", "line": 1}],
        )
        report = build_json_report(Path("."), ScanData([], [], [], [group], []), 0.1)
        assert report["duplicates"]["total_groups"] == 1

    def test_includes_library_suggestions(self):
        sug = LibrarySuggestion(
            module_name="utils", description="test",
            functions=[{"name": "f", "file": "a.py", "line": 1}],
            unified_api="def f():", rationale="reason",
        )
        report = build_json_report(Path("."), ScanData([], [], [], [], [sug]), 0.1)
        assert report["library_suggestions"]["total"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 12. Integration: Full Pipeline
# ─────────────────────────────────────────────────────────────────────────────

class TestFullPipeline:
    """Tests for full analysis pipeline."""

    @staticmethod
    def _create_test_project(tmp_path):
        """Create a small project with deliberate smells and duplicates."""
        (tmp_path / "module_a.py").write_text(textwrap.dedent("""\
        def process_data(data):
            result = []
            for item in data:
                cleaned = item.strip()
                if cleaned:
                    result.append(cleaned.lower())
            return result
        
        def big_function(x, y, z, a, b, c, d, e):
            \"\"\"Too many params.\"\"\"
            if x > 0:
                for i in range(y):
                    if i > z:
                        for j in range(a):
                            if j > b:
                                pass
            return None
        """))
        (tmp_path / "module_b.py").write_text(textwrap.dedent("""\
        def process_text(text):
            result = []
            for item in text:
                cleaned = item.strip()
                if cleaned:
                    result.append(cleaned.upper())
            return result
        
        class HugeClass:
            def m1(self): pass
            def m2(self): pass
            def m3(self): pass
            def m4(self): pass
            def m5(self): pass
            def m6(self): pass
            def m7(self): pass
            def m8(self): pass
            def m9(self): pass
            def m10(self): pass
            def m11(self): pass
            def m12(self): pass
            def m13(self): pass
            def m14(self): pass
            def m15(self): pass
            def m16(self): pass
        """))

    @staticmethod
    def _assert_pipeline(tmp_path, functions, classes):
        """Run smell, duplicate, library, report, and graph assertions."""
        # Smells
        detector = CodeSmellDetector()
        smells = detector.detect(functions, classes)
        categories = {s.category for s in smells}
        assert "too-many-params" in categories or "deep-nesting" in categories
        assert "god-class" in categories

        # Duplicates
        finder = DuplicateFinder()
        groups = finder.find(functions)
        assert len(groups) >= 0

        # Library suggestions
        advisor = LibraryAdvisor()
        lib_sug = advisor.analyze(groups, functions)

        # JSON report
        report = build_json_report(
            tmp_path, ScanData(functions, classes, smells, groups, lib_sug), 0.5
        )
        assert report["stats"]["total_functions"] >= 2
        j = json.dumps(report)
        assert isinstance(j, str)

        # Graph
        graph = SmartGraph()
        graph.build(functions, smells, groups, tmp_path)
        graph_path = tmp_path / "test_graph.html"
        graph.write_html(graph_path)
        assert graph_path.exists()

    def test_end_to_end(self, tmp_path):
        """Test the full pipeline on a mini project."""
        self._create_test_project(tmp_path)

        # Scan
        functions, classes, errors = scan_codebase(tmp_path)
        assert len(functions) >= 2
        assert len(classes) >= 1

        self._assert_pipeline(tmp_path, functions, classes)


# ─────────────────────────────────────────────────────────────────────────────
# 13. Edge Cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Tests for edge case handling."""

    def test_function_record_key_no_dirs(self):
        """File in root dir should use stem directly."""
        f = _make_func(name="run", file_path="main.py")
        assert f.key == "main::run"

    def test_function_record_empty_params(self):
        f = _make_func(parameters=[])
        assert f.signature == "test_func()"

    def test_smell_issue_all_fields(self):
        s = SmellIssue(
            file_path="x.py", line=1, end_line=5,
            category="test", severity=Severity.INFO,
            message="msg", suggestion="fix", name="fn",
            metric_value=42, llm_analysis="LLM says fix it",
        )
        assert s.llm_analysis == "LLM says fix it"
        assert s.metric_value == 42

    def test_duplicate_group_merge_suggestion_default(self):
        g = DuplicateGroup(
            group_id=0, similarity_type="near",
            avg_similarity=0.8, functions=[],
        )
        assert g.merge_suggestion == ""

    def test_library_suggestion_all_fields(self):
        s = LibrarySuggestion(
            module_name="utils", description="d",
            functions=[], unified_api="def f():",
            rationale="r",
        )
        assert s.module_name == "utils"

    def test_cosine_with_large_vectors(self):
        a = Counter({f"word_{i}": i for i in range(100)})
        b = Counter({f"word_{i}": i + 1 for i in range(100)})
        sim = cosine_similarity(a, b)
        assert 0.9 < sim <= 1.0  # should be very similar

    def test_tokenize_unicode(self):
        tokens = tokenize("café_handler résumé_parser")
        assert "handler" in tokens or "caf" in tokens

    def test_detector_no_functions(self):
        detector = CodeSmellDetector()
        smells = detector.detect([], [])
        assert smells == []

    def test_finder_no_functions(self):
        finder = DuplicateFinder()
        groups = finder.find([])
        assert groups == []

    def test_advisor_boilerplate_excluded(self):
        """Library advisor should not suggest __init__, __repr__, etc."""
        f1 = _make_func(name="__repr__", file_path="a.py")
        f2 = _make_func(name="__repr__", file_path="b.py")
        advisor = LibraryAdvisor()
        # DuplicateFinder would skip these, but test advisor's name-based analysis
        suggestions = advisor.analyze([], [f1, f2])
        # __repr__ should not be suggested for library extraction
        assert len(suggestions) == 0

    def test_file_with_only_classes(self, tmp_path):
        code = textwrap.dedent("""\
        class Config:
            DEBUG = True
            VERSION = "1.0"
        """)
        py_file = tmp_path / "config.py"
        py_file.write_text(code)
        functions, classes, error = _extract_functions_from_file(py_file, tmp_path)
        assert error is None
        assert len(classes) == 1
        assert classes[0].name == "Config"

    def test_decorators_extracted(self, tmp_path):
        """Verify decorator information is preserved during extraction."""
        code = textwrap.dedent("""\
        import functools
        
        @functools.lru_cache(maxsize=128)
        @staticmethod
        def cached_helper():
            return 42
        """)
        py_file = tmp_path / "dec.py"
        py_file.write_text(code)
        functions, _, _ = _extract_functions_from_file(py_file, tmp_path)
        assert len(functions) >= 1
        func = functions[0]
        assert len(func.decorators) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 14. LLMHelper (unit tests without actual LLM)
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMHelper:
    def test_not_available_without_core(self, tmp_path):
        """LLMHelper should report not available if Core not found."""
        from x_ray_claude import LLMHelper
        helper = LLMHelper(tmp_path)  # tmp_path has no Core/
        # Force re-check
        helper._available = None
        # It may or may not be available depending on sys.path
        # but we can at least verify it doesn't crash
        _ = helper.available

    def test_query_sync_raises_without_llm(self, tmp_path):
        from x_ray_claude import LLMHelper
        helper = LLMHelper(tmp_path)
        helper._force_unavailable = True
        with pytest.raises(RuntimeError, match="not available"):
            helper.query_sync("test prompt")


# ─────────────────────────────────────────────────────────────────────────────
# 15. Version & Banner
# ─────────────────────────────────────────────────────────────────────────────

class TestVersion:
    def test_version_format(self):
        parts = __version__.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_version_is_5(self):
        assert __version__.startswith("5.")
