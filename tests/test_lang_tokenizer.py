"""
Tests for Lang/tokenizer.py — tokenize, term_freq, cosine_similarity.
"""
import math
import pytest
from collections import Counter
from Lang.tokenizer import tokenize, term_freq, cosine_similarity


# ════════════════════════════════════════════════════════════════════
#  tokenize
# ════════════════════════════════════════════════════════════════════

class TestTokenize:

    def test_empty_string(self):
        assert tokenize("") == []

    def test_snake_case(self):
        tokens = tokenize("get_user_name")
        assert "get" in tokens
        assert "user" in tokens
        assert "name" in tokens

    def test_camel_case(self):
        tokens = tokenize("getUserName")
        assert "get" in tokens
        assert "user" in tokens
        assert "name" in tokens

    def test_stop_words_removed(self):
        tokens = tokenize("self return def class")
        # All are stop words — should produce nothing (or very little)
        for t in tokens:
            assert t not in {"self", "return", "def", "class"}

    def test_single_char_removed(self):
        tokens = tokenize("a b c x y z")
        assert all(len(t) > 1 for t in tokens)

    def test_special_chars_stripped(self):
        tokens = tokenize("hello@world#test!")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens

    def test_numbers_in_identifiers(self):
        tokens = tokenize("value2process")
        # depending on regex, at least some tokens
        assert len(tokens) >= 1

    def test_all_uppercase(self):
        tokens = tokenize("MAX_RETRIES")
        # Should split or keep as lowercase
        assert any("max" in t or "retries" in t for t in tokens)

    def test_mixed_input(self):
        tokens = tokenize("calculateTotalPrice_v2")
        assert "calculate" in tokens
        assert "total" in tokens
        assert "price" in tokens


# ════════════════════════════════════════════════════════════════════
#  term_freq
# ════════════════════════════════════════════════════════════════════

class TestTermFreq:

    def test_returns_counter(self):
        result = term_freq(["a", "b", "a"])
        assert isinstance(result, Counter)
        assert result["a"] == 2
        assert result["b"] == 1

    def test_empty(self):
        assert term_freq([]) == Counter()

    def test_all_same(self):
        result = term_freq(["x", "x", "x"])
        assert result["x"] == 3


# ════════════════════════════════════════════════════════════════════
#  cosine_similarity
# ════════════════════════════════════════════════════════════════════

class TestCosineSimilarity:

    def test_identical(self):
        a = Counter({"hello": 3, "world": 2})
        assert cosine_similarity(a, a) == pytest.approx(1.0)

    def test_disjoint(self):
        a = Counter({"hello": 1})
        b = Counter({"world": 1})
        assert cosine_similarity(a, b) == 0.0

    def test_partial_overlap(self):
        a = Counter({"hello": 1, "world": 1})
        b = Counter({"hello": 1, "foo": 1})
        sim = cosine_similarity(a, b)
        assert 0.0 < sim < 1.0

    def test_empty_a(self):
        assert cosine_similarity(Counter(), Counter({"x": 1})) == 0.0

    def test_empty_b(self):
        assert cosine_similarity(Counter({"x": 1}), Counter()) == 0.0

    def test_both_empty(self):
        assert cosine_similarity(Counter(), Counter()) == 0.0

    def test_known_value(self):
        """cos([1,1], [1,0]) = 1/sqrt(2) ≈ 0.7071"""
        a = Counter({"x": 1, "y": 1})
        b = Counter({"x": 1})
        expected = 1.0 / math.sqrt(2)
        assert cosine_similarity(a, b) == pytest.approx(expected, abs=1e-4)
