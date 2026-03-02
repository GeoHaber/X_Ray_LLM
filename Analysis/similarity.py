import re
import hashlib
import keyword
import io
import tokenize as _tokenize_mod
import ast
from collections import Counter
from typing import List

# Optional Rust acceleration (preserved from original)
try:
    import x_ray_core as _rust_core

    _HAS_RUST = True
except ImportError:
    _rust_core = None
    _HAS_RUST = False

# Import canonical definitions — single source of truth
from Core.config import _BUILTIN_NAMES
from Lang.tokenizer import tokenize, term_freq as _term_freq, cosine_similarity

_SPLIT_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


# tokenize, _term_freq, cosine_similarity are imported from Lang.tokenizer


def _classify_name(name: str) -> str:
    """Classify a NAME token as keyword, builtin, or generic identifier."""
    if keyword.iskeyword(name) or keyword.issoftkeyword(name):
        return name
    if name in _BUILTIN_NAMES:
        return name
    return "ID"


_TOKEN_TYPE_MAP = {
    _tokenize_mod.NUMBER: "NUM",
    _tokenize_mod.STRING: "STR",
}

_PASSTHROUGH_TYPES = frozenset(
    {
        _tokenize_mod.OP,
        _tokenize_mod.NEWLINE,
        _tokenize_mod.INDENT,
        _tokenize_mod.DEDENT,
    }
)


def _classify_token(tok) -> str | None:
    """Map a single token to its normalized form, or None to skip."""
    if tok.type == _tokenize_mod.NAME:
        return _classify_name(tok.string)
    if tok.type in _TOKEN_TYPE_MAP:
        return _TOKEN_TYPE_MAP[tok.type]
    if tok.type in _PASSTHROUGH_TYPES:
        return tok.string
    return None


def _normalized_token_stream(code: str) -> List[str]:
    """Tokenize Python code, normalizing identifiers and literals."""
    tokens: List[str] = []
    try:
        for tok in _tokenize_mod.generate_tokens(io.StringIO(code).readline):
            normalized = _classify_token(tok)
            if normalized is not None:
                tokens.append(normalized)
    except _tokenize_mod.TokenError:
        pass
    return tokens


def _ngram_fingerprints(tokens: List[str], n: int = 5, w: int = 4) -> frozenset:
    """Winnowed n-gram fingerprinting (MOSS algorithm)."""
    if len(tokens) < n:
        return frozenset()
    hashes: List[int] = []
    for i in range(len(tokens) - n + 1):
        gram = " ".join(tokens[i : i + n])
        hashes.append(int(hashlib.sha256(gram.encode()).hexdigest()[:8], 16))
    if len(hashes) < w:
        return frozenset(hashes)
    fingerprints: set = set()
    for i in range(len(hashes) - w + 1):
        fingerprints.add(min(hashes[i : i + w]))
    return frozenset(fingerprints)


def _token_ngram_similarity(code_a: str, code_b: str) -> float:
    """Jaccard similarity of winnowed n-gram fingerprints."""
    fp_a = _ngram_fingerprints(_normalized_token_stream(code_a))
    fp_b = _ngram_fingerprints(_normalized_token_stream(code_b))
    if not fp_a or not fp_b:
        return 0.0
    return len(fp_a & fp_b) / len(fp_a | fp_b)


def _ast_node_histogram(code: str) -> Counter:
    """Count occurrences of each AST node type."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return Counter()
    return Counter(type(node).__name__ for node in ast.walk(tree))


# cosine_similarity is imported from Lang.tokenizer (clamped version)


def _ast_histogram_similarity(code_a: str, code_b: str) -> float:
    """Cosine similarity of AST node-type histograms."""
    ha = _ast_node_histogram(code_a)
    hb = _ast_node_histogram(code_b)
    return cosine_similarity(ha, hb)


def code_similarity(code_a: str, code_b: str) -> float:
    """
    Structural similarity between two code blocks (0–1).
    Uses Python implementation by default, falls back to Rust if configured.
    """
    if _HAS_RUST:
        return _rust_core.code_similarity(code_a, code_b)
    if not code_a or not code_b:
        return 0.0
    if code_a == code_b:
        return 1.0
    tok_sim = _token_ngram_similarity(code_a, code_b)
    ast_sim = _ast_histogram_similarity(code_a, code_b)
    return min(0.35 * tok_sim + 0.65 * ast_sim, 1.0)


def name_similarity(name_a: str, name_b: str) -> float:
    """Semantic similarity between two function names (0–1)."""
    ta = set(tokenize(name_a))
    tb = set(tokenize(name_b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def signature_similarity(func_a, func_b) -> float:
    """Compare two function signatures.
    Note: func_a/func_b are FunctionRecord objects (passed as duck types here to avoid circular dependencies).
    """
    scores: List[float] = []

    # Param-name overlap
    pa = set(tokenize(" ".join(func_a.parameters)))
    pb = set(tokenize(" ".join(func_b.parameters)))
    if pa or pb:
        scores.append(len(pa & pb) / len(pa | pb) if (pa | pb) else 0.0)
    else:
        scores.append(1.0)

    # Param-count ratio
    la, lb = len(func_a.parameters), len(func_b.parameters)
    if max(la, lb) > 0:
        scores.append(min(la, lb) / max(la, lb))
    else:
        scores.append(1.0)

    # Return type match
    ra = (func_a.return_type or "").lower()
    rb = (func_b.return_type or "").lower()
    if ra and rb:
        scores.append(1.0 if ra == rb else 0.0)
    elif not ra and not rb:
        scores.append(0.5)
    else:
        scores.append(0.0)

    # Async-flag match
    scores.append(1.0 if func_a.is_async == func_b.is_async else 0.0)

    return sum(scores) / len(scores) if scores else 0.0


def callgraph_overlap(func_a, func_b) -> float:
    """Jaccard overlap of functions each function calls."""
    ca = set(func_a.calls_to)
    cb = set(func_b.calls_to)
    if not ca or not cb:
        return 0.0
    return len(ca & cb) / len(ca | cb)


def semantic_similarity(func_a, func_b) -> float:
    """Weighted composite of behavioural signals (0–1)."""
    w_name = 0.30
    w_sig = 0.25
    w_call = 0.30
    w_doc = 0.15

    ns = name_similarity(func_a.name, func_b.name)
    ss = signature_similarity(func_a, func_b)
    cg = callgraph_overlap(func_a, func_b)

    # Docstring similarity (token cosine)
    da = _term_freq(tokenize(func_a.docstring or ""))
    db = _term_freq(tokenize(func_b.docstring or ""))
    ds = cosine_similarity(da, db) if (da and db) else 0.0

    return w_name * ns + w_sig * ss + w_call * cg + w_doc * ds
