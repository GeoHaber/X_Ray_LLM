"""
Lang/tokenizer.py — Canonical tokenization & similarity primitives
====================================================================

Single source of truth for:
  - tokenize()               (text -> token list)
  - term_freq()              (tokens -> Counter)
  - cosine_similarity()      (Counter x Counter -> float)

All other modules must import from here instead of defining their own copies.
"""

import math
import re
from collections import Counter
from typing import List

from Core.config import _STOP_WORDS

_SPLIT_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def tokenize(text: str) -> List[str]:
    """Split text into meaningful lowercase tokens (camelCase/snake_case aware)."""
    if not text:
        return []
    cleaned = re.sub(r"[^a-zA-Z0-9]", " ", text)
    raw: List[str] = []
    for word in cleaned.split():
        parts = [m.group().lower() for m in _SPLIT_RE.finditer(word)]
        if parts:
            raw.extend(parts)
        else:
            raw.append(word.lower())
    return [t for t in raw if len(t) > 1 and t not in _STOP_WORDS]


def term_freq(tokens: List[str]) -> Counter:
    """Return a term-frequency Counter from a token list."""
    return Counter(tokens)


def cosine_similarity(a: Counter, b: Counter) -> float:
    """Cosine similarity between two term-frequency vectors (clamped to [0, 1])."""
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    result = dot / (mag_a * mag_b)
    return min(result, 1.0)
