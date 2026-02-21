"""Shared tokenization and cosine-similarity test assertions.

Eliminates duplicate test logic between test_analysis_similarity.py
and test_lang_tokenizer.py.
"""

from collections import Counter


# ── tokenize() assertions ────────────────────────────────────────────

def assert_tokenize_empty_string(tokenize_fn):
    """tokenize('') → []."""
    assert tokenize_fn("") == []


def assert_tokenize_snake_case(tokenize_fn):
    """tokenize('get_user_name') splits into get, user, name."""
    tokens = tokenize_fn("get_user_name")
    assert "get" in tokens
    assert "user" in tokens
    assert "name" in tokens


def assert_tokenize_camel_case(tokenize_fn):
    """tokenize('getUserName') splits into get, user, name."""
    tokens = tokenize_fn("getUserName")
    assert "get" in tokens
    assert "user" in tokens
    assert "name" in tokens


# ── cosine_similarity() assertions ───────────────────────────────────

def assert_cosine_partial_overlap(cosine_fn, a=None, b=None):
    """Partial-overlap counters yield 0 < similarity < 1."""
    if a is None:
        a = Counter({"x": 2, "y": 1})
    if b is None:
        b = Counter({"x": 1, "z": 1})
    sim = cosine_fn(a, b)
    assert 0.0 < sim < 1.0
