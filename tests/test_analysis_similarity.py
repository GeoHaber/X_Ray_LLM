"""
Tests for Analysis/similarity.py — token normalization, n-gram fingerprints,
code similarity, name similarity, signature similarity, and semantic similarity.
"""

import pytest
from collections import Counter
from unittest.mock import MagicMock

from Analysis.similarity import (
    tokenize,
    _term_freq,
    _normalized_token_stream,
    _ngram_fingerprints,
    _token_ngram_similarity,
    _ast_node_histogram,
    cosine_similarity,
    code_similarity,
    name_similarity,
    signature_similarity,
    callgraph_overlap,
    semantic_similarity,
)
from tests.shared_tokenize_tests import (
    assert_tokenize_empty_string,
    assert_tokenize_snake_case,
    assert_tokenize_camel_case,
    assert_cosine_partial_overlap,
)


# ════════════════════════════════════════════════════════════════════
#  tokenize()
# ════════════════════════════════════════════════════════════════════


class TestTokenize:
    """Tests for tokenization utilities."""

    def test_empty_string(self):
        assert_tokenize_empty_string(tokenize)

    def test_snake_case(self):
        assert_tokenize_snake_case(tokenize)

    def test_camel_case(self):
        assert_tokenize_camel_case(tokenize)

    def test_filters_stop_words(self):
        """Keywords like 'self', 'return', 'class' are stop words."""
        tokens = tokenize("self_return_class")
        assert "self" not in tokens
        assert "return" not in tokens

    def test_single_char_filtered(self):
        """Single-character tokens are dropped."""
        tokens = tokenize("a b c data")
        assert "a" not in tokens
        assert "data" in tokens

    def test_mixed_alpha_numeric(self):
        tokens = tokenize("process2Data")
        assert "process" in tokens
        assert "data" in tokens


# ════════════════════════════════════════════════════════════════════
#  _term_freq()
# ════════════════════════════════════════════════════════════════════


class TestTermFreq:
    def test_basic_counts(self):
        tf = _term_freq(["a", "b", "a", "c", "a"])
        assert tf["a"] == 3
        assert tf["b"] == 1

    def test_empty(self):
        tf = _term_freq([])
        assert len(tf) == 0


# ════════════════════════════════════════════════════════════════════
#  _normalized_token_stream()
# ════════════════════════════════════════════════════════════════════


class TestNormalizedTokenStream:
    def test_normalizes_identifiers_to_id(self):
        tokens = _normalized_token_stream("x = 42")
        assert "ID" in tokens
        assert "NUM" in tokens

    def test_preserves_keywords(self):
        tokens = _normalized_token_stream("if True: pass")
        assert "if" in tokens
        assert "True" in tokens
        assert "pass" in tokens

    def test_normalizes_strings_to_str(self):
        tokens = _normalized_token_stream("x = 'hello'")
        assert "STR" in tokens

    def test_empty_code(self):
        tokens = _normalized_token_stream("")
        assert isinstance(tokens, list)

    def test_syntax_error_returns_partial(self):
        """Broken code should return whatever tokens were found before error."""
        tokens = _normalized_token_stream("def f(:\n")
        assert isinstance(tokens, list)


# ════════════════════════════════════════════════════════════════════
#  _ngram_fingerprints()
# ════════════════════════════════════════════════════════════════════


class TestNgramFingerprints:
    def test_short_input_returns_empty(self):
        """Fewer tokens than n → empty frozenset."""
        fp = _ngram_fingerprints(["a", "b"], n=5)
        assert fp == frozenset()

    def test_returns_frozenset(self):
        tokens = ["a", "b", "c", "d", "e", "f", "g", "h"]
        fp = _ngram_fingerprints(tokens, n=3)
        assert isinstance(fp, frozenset)
        assert len(fp) > 0

    def test_identical_tokens_same_fingerprint(self):
        tokens = ["def", "ID", "(", ")", ":"]
        fp1 = _ngram_fingerprints(tokens, n=3)
        fp2 = _ngram_fingerprints(tokens, n=3)
        assert fp1 == fp2


# ════════════════════════════════════════════════════════════════════
#  _token_ngram_similarity()
# ════════════════════════════════════════════════════════════════════


class TestTokenNgramSimilarity:
    def test_identical_code(self):
        code = "def process(x):\n    return x * 2\n"
        sim = _token_ngram_similarity(code, code)
        assert sim == pytest.approx(1.0)

    def test_disjoint_code(self):
        a = "class A:\n    def method(self):\n        return self.x\n"
        b = "import os\nfor i in range(10):\n    print(i)\n"
        sim = _token_ngram_similarity(a, b)
        assert sim < 0.5

    def test_empty_input(self):
        assert _token_ngram_similarity("", "x = 1") == 0.0
        assert _token_ngram_similarity("x = 1", "") == 0.0


# ════════════════════════════════════════════════════════════════════
#  _ast_node_histogram()
# ════════════════════════════════════════════════════════════════════


class TestAstNodeHistogram:
    def test_counts_node_types(self):
        hist = _ast_node_histogram("def f():\n    return 1\n")
        assert "FunctionDef" in hist
        assert "Return" in hist

    def test_syntax_error_returns_empty(self):
        hist = _ast_node_histogram("def (broken]]]")
        assert hist == Counter()


# ════════════════════════════════════════════════════════════════════
#  cosine_similarity()
# ════════════════════════════════════════════════════════════════════


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = Counter({"x": 3, "y": 2})
        assert cosine_similarity(a, a) == pytest.approx(1.0)

    def test_disjoint_vectors(self):
        a = Counter({"x": 1})
        b = Counter({"y": 1})
        assert cosine_similarity(a, b) == 0.0

    def test_empty_vector(self):
        assert cosine_similarity(Counter(), Counter({"x": 1})) == 0.0

    def test_partial_overlap(self):
        assert_cosine_partial_overlap(cosine_similarity)


# ════════════════════════════════════════════════════════════════════
#  code_similarity()
# ════════════════════════════════════════════════════════════════════


class TestCodeSimilarity:
    def test_identical_code_high(self):
        code = "def add(a, b):\n    return a + b\n"
        assert code_similarity(code, code) >= 0.9

    def test_empty_inputs(self):
        """At least one empty → 0.0 (Python path) or low (Rust path)."""
        sim = code_similarity("", "x = 1")
        assert sim <= 0.1

    def test_similar_code_moderate(self):
        a = "def add(x, y):\n    return x + y\n"
        b = "def sum_values(a, b):\n    return a + b\n"
        sim = code_similarity(a, b)
        assert sim > 0.3


# ════════════════════════════════════════════════════════════════════
#  name_similarity()
# ════════════════════════════════════════════════════════════════════


class TestNameSimilarity:
    def test_identical(self):
        assert name_similarity("get_user", "get_user") == 1.0

    def test_empty_returns_zero(self):
        assert name_similarity("", "foo") == 0.0
        assert name_similarity("foo", "") == 0.0

    def test_completely_different(self):
        sim = name_similarity("process_data", "render_widget")
        assert sim < 0.5


# ════════════════════════════════════════════════════════════════════
#  signature_similarity()
# ════════════════════════════════════════════════════════════════════


class TestSignatureSimilarity:
    def _mock_func(self, name="f", params=None, ret=None, **kw):
        f = MagicMock()
        f.name = name
        f.parameters = params or []
        f.return_type = ret
        f.is_async = kw.get("is_async", False)
        f.calls_to = kw.get("calls_to", [])
        f.docstring = kw.get("docstring", None)
        return f

    def test_identical_signatures(self):
        a = self._mock_func(params=["x", "y"], ret="int")
        b = self._mock_func(params=["x", "y"], ret="int")
        assert signature_similarity(a, b) == pytest.approx(1.0)

    def test_different_return_types(self):
        a = self._mock_func(params=["x"], ret="int")
        b = self._mock_func(params=["x"], ret="str")
        sim = signature_similarity(a, b)
        assert sim < 1.0

    def test_async_mismatch_penalized(self):
        a = self._mock_func(is_async=True)
        b = self._mock_func(is_async=False)
        sim = signature_similarity(a, b)
        assert sim < 1.0


# ════════════════════════════════════════════════════════════════════
#  callgraph_overlap()
# ════════════════════════════════════════════════════════════════════


class TestCallgraphOverlap:
    def test_identical_calls(self):
        a = self._mock_func(calls=["foo", "bar"])
        b = self._mock_func(calls=["foo", "bar"])
        assert callgraph_overlap(a, b) == 1.0

    def test_disjoint_calls(self):
        a = self._mock_func(calls=["foo"])
        b = self._mock_func(calls=["bar"])
        assert callgraph_overlap(a, b) == 0.0

    def test_empty_calls(self):
        a = self._mock_func(calls=[])
        b = self._mock_func(calls=["foo"])
        assert callgraph_overlap(a, b) == 0.0


# ════════════════════════════════════════════════════════════════════
#  semantic_similarity()
# ════════════════════════════════════════════════════════════════════


class TestSemanticSimilarity:
    """Tests for semantic similarity computation."""

    def test_identical_functions_high(self):
        a = self._mock_func(
            "process_data",
            ["items"],
            "list",
            calls_to=["filter", "map"],
            docstring="Process items.",
        )
        b = self._mock_func(
            "process_data",
            ["items"],
            "list",
            calls_to=["filter", "map"],
            docstring="Process items.",
        )
        sim = semantic_similarity(a, b)
        assert sim > 0.8

    def test_completely_different_low(self):
        a = self._mock_func(
            "render_widget",
            ["canvas"],
            "None",
            calls_to=["draw", "paint"],
            docstring="Render a widget.",
        )
        b = self._mock_func(
            "parse_config",
            ["path"],
            "dict",
            calls_to=["open", "json_load"],
            docstring="Load config file.",
        )
        sim = semantic_similarity(a, b)
        assert sim < 0.3

    def test_returns_float_0_to_1(self):
        a = self._mock_func("foo", ["x"])
        b = self._mock_func("bar", ["y"])
        sim = semantic_similarity(a, b)
        assert 0.0 <= sim <= 1.0
