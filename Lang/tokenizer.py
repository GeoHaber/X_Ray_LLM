
import math
import re
from collections import Counter
from typing import List

_STOP_WORDS = frozenset(
    "self cls none true false return def class if else elif for while try "
    "except finally with as import from raise pass break continue yield "
    "lambda and or not in is assert del global nonlocal async await "
    "the a an of to is it that this be on at by do has was are were "
    "str int float bool list dict set tuple bytes type any all len "
    "range print open super init new call".split()
)

_SPLIT_RE = re.compile(r"[A-Z][a-z]+|[a-z]+|[A-Z]+(?=[A-Z]|$)")

def tokenize(text: str) -> List[str]:
    """Split text into meaningful lowercase tokens (camelCase/snake_case aware)."""
    if not text:
        return []
    cleaned = re.sub(r"[^a-zA-Z0-9]", " ", text)
    raw: List[str] = []
    for word in cleaned.split():
        raw.extend(m.group().lower() for m in _SPLIT_RE.finditer(word))
        if word.islower() or word.isupper():
            raw.append(word.lower())
    return [t for t in raw if len(t) > 1 and t not in _STOP_WORDS]


def term_freq(tokens: List[str]) -> Counter:
    return Counter(tokens)


def cosine_similarity(a: Counter, b: Counter) -> float:
    """Cosine similarity between two term-frequency vectors."""
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)
