#!/usr/bin/env python3
"""
X_RAY_Claude.py — Smart AI-Powered Code Analyzer (X-Ray 4.0)
=============================================================

Builds on top of x_ray_project.py's static analysis with deep AI features:

  --smell            Code smell detection (AST heuristics + targeted LLM)
  --duplicates       Cross-file function similarity (TF-IDF + SequenceMatcher + LLM)
  --suggest-library  Groups similar functions → suggests shared library extraction
  --full-scan        Runs all AI features in one pass
  --report FILE      Save full JSON report to FILE

Architecture
------------
- CodeSmellDetector  — AST-based heuristics flag suspects, LLM rates & advises
- DuplicateFinder    — Token cosine pre-filter → SequenceMatcher → optional LLM confirm
- LibraryAdvisor     — Consumes duplicate clusters → LLM designs unified APIs
- SmartGraph         — Enhanced graph with health-colored nodes + smell/duplicate tooltips

All features work WITHOUT an LLM (fast heuristic mode).
LLM enrichment is optional and uses Core.services.inference_engine if available.

Usage::

    python X_RAY_Claude.py --path .                     # default scan + smells
    python X_RAY_Claude.py --smell                      # code smell detection only
    python X_RAY_Claude.py --duplicates                 # find similar functions
    python X_RAY_Claude.py --suggest-library             # library extraction advisor
    python X_RAY_Claude.py --full-scan                   # everything
    python X_RAY_Claude.py --full-scan --use-llm         # everything with LLM enrichment
    python X_RAY_Claude.py --report scan_results.json    # save JSON report
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import logging
import math
import os
import re
import sys
import textwrap
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, TypedDict
import asyncio
import copy
import concurrent.futures

# === SAFE UNICODE OUTPUT ===
# Many Windows terminals (cp1252, cp437) crash on emoji / box-drawing chars.
# We detect capability once, provide ASCII fallbacks, and wrap stdout.

def _supports_unicode() -> bool:
    """Detect whether the current stdout can handle full Unicode."""
    enc = getattr(sys.stdout, 'encoding', None) or ''
    if enc.lower().replace('-', '').replace('_', '') in ('utf8', 'utf8'):
        return True
    # Try reconfigure  (CPython 3.7+)
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        return True
    except Exception:
        pass
    # Last resort: wrap the raw buffer
    import io
    try:
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding='utf-8', errors='replace',
                line_buffering=True,
            )
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding='utf-8', errors='replace',
                line_buffering=True,
            )
        return True
    except Exception:
        return False

UNICODE_OK = _supports_unicode()

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("X_RAY_Claude")

__version__ = "4.2.0"


# ─────────────────────────────────────────────────────────────────────────────
#  FunctionInfo TypedDict (for typed dict interfaces)
# ─────────────────────────────────────────────────────────────────────────────

class FunctionInfo(TypedDict, total=False):
    """Lightweight dict shape returned inside DuplicateGroup.functions."""
    key: str
    name: str
    file: str
    line: int
    size: int
    similarity: float
    signature: str

# Safe separator: always ASCII dash — renders correctly on every terminal/console
SEP = "-"

BANNER = f"""
{'='*64}
  X-RAY Claude v{__version__} — Smart AI Code Analyzer
  Powered by AST heuristics + optional Local LLM
{'='*64}
"""

# ─────────────────────────────────────────────────────────────────────────────
#  Severity Enum
# ─────────────────────────────────────────────────────────────────────────────

class Severity:
    """Severity levels for issues."""
    CRITICAL = "critical"   # 🔴
    WARNING  = "warning"    # 🟡
    INFO     = "info"       # 🟢

    _ICONS_UNICODE = {
        "critical": "\U0001F534",  # 🔴
        "warning":  "\U0001F7E1",  # 🟡
        "info":     "\U0001F7E2",  # 🟢
    }
    _ICONS_ASCII = {
        "critical": "[!!]",
        "warning":  "[!]",
        "info":     "[i]",
    }

    @staticmethod
    def icon(level: str) -> str:
        icons = Severity._ICONS_UNICODE if UNICODE_OK else Severity._ICONS_ASCII
        return icons.get(level, "?")


# ─────────────────────────────────────────────────────────────────────────────
#  Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FunctionRecord:
    """Extracted function metadata from AST."""
    name: str
    file_path: str          # relative path
    line_start: int
    line_end: int
    size_lines: int
    parameters: List[str]
    return_type: Optional[str]
    decorators: List[str]
    docstring: Optional[str]
    calls_to: List[str]
    complexity: int         # cyclomatic (if/for/while/try/except/assert/bool)
    nesting_depth: int      # max nesting level
    code_hash: str          # SHA-256 of function body
    structure_hash: str     # MD5 of normalized AST (for structural duplicates)
    code: str               # actual source code
    is_async: bool = False

    @property
    def key(self) -> str:
        stem = Path(self.file_path).stem
        return f"{stem}.{self.name}"

    @property
    def location(self) -> str:
        return f"{self.file_path}:{self.line_start}"

    @property
    def signature(self) -> str:
        params = ", ".join(self.parameters)
        ret = f" -> {self.return_type}" if self.return_type else ""
        return f"{self.name}({params}){ret}"


@dataclass
class ClassRecord:
    """Extracted class metadata from AST."""
    name: str
    file_path: str
    line_start: int
    line_end: int
    size_lines: int
    method_count: int
    base_classes: List[str]
    docstring: Optional[str]
    methods: List[str]      # method names
    has_init: bool


@dataclass
class SmellIssue:
    """A detected code smell."""
    file_path: str
    line: int
    end_line: int
    category: str           # e.g. "long-function", "god-class", "deep-nesting"
    severity: str           # Severity.CRITICAL / WARNING / INFO
    message: str
    suggestion: str
    name: str               # function/class name
    metric_value: int       # the number that triggered the smell (size, depth, etc.)
    llm_analysis: str = ""  # optional LLM-generated detailed analysis


@dataclass
class DuplicateGroup:
    """A group of similar/duplicate functions."""
    group_id: int
    similarity_type: str    # "exact", "near", "semantic"
    avg_similarity: float
    functions: List[Dict[str, Any]]
    merge_suggestion: str = ""


@dataclass
class LibrarySuggestion:
    """A suggestion to extract functions into a shared library."""
    module_name: str
    description: str
    functions: List[Dict[str, Any]]
    unified_api: str        # suggested function signature
    rationale: str


# ─────────────────────────────────────────────────────────────────────────────
#  File Collection (reused from x_ray_project.py pattern)
# ─────────────────────────────────────────────────────────────────────────────

_ALWAYS_SKIP = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".tox", ".nox", ".eggs", "node_modules",
    "venv", ".venv", "env", ".env",
    "site-packages", "dist-packages",
    "_archive", "_Old", "_old", "_bin",
    "portable",
})


def collect_py_files(root: Path, exclude: List[str] = None,
                     include: List[str] = None) -> List[Path]:
    """Walk root and return .py files respecting include/exclude rules."""
    exclude = exclude or []
    include = include or []
    results = []
    try:
        walker = os.walk(root)
    except PermissionError:
        logger.warning(f"Permission denied: {root}")
        return results
    for dirpath, dirnames, filenames in walker:
        rel_dir = os.path.relpath(dirpath, root)
        # Prune dirs in-place
        dirnames[:] = [
            d for d in dirnames
            if d not in _ALWAYS_SKIP
            and not d.endswith(".egg-info")
            and not (exclude and any(
                (os.path.join(rel_dir, d) if rel_dir != "." else d).startswith(p)
                for p in exclude))
        ]
        if include:
            top = rel_dir.split(os.sep)[0] if rel_dir != "." else "."
            if top != "." and not any(top.startswith(p) for p in include):
                continue
        for fn in filenames:
            if fn.endswith(".py"):
                results.append(Path(dirpath) / fn)
    return results


# ─────────────────────────────────────────────────────────────────────────────
#  AST Extraction Engine
# ─────────────────────────────────────────────────────────────────────────────

def _compute_nesting_depth(node: ast.AST) -> int:
    """Compute maximum nesting depth of control flow in a function."""
    max_depth = 0

    def _walk(n, depth):
        nonlocal max_depth
        nesting_types = (ast.If, ast.For, ast.While, ast.Try, ast.With,
                         ast.ExceptHandler)
        for child in ast.iter_child_nodes(n):
            if isinstance(child, nesting_types):
                new_depth = depth + 1
                max_depth = max(max_depth, new_depth)
                _walk(child, new_depth)
            else:
                _walk(child, depth)

    _walk(node, 0)
    return max_depth


def _compute_complexity(node: ast.AST) -> int:
    """Cyclomatic complexity approximation."""
    return sum(
        1 for c in ast.walk(node)
        if isinstance(c, (ast.If, ast.For, ast.While, ast.Try,
                          ast.ExceptHandler, ast.BoolOp, ast.Assert,
                          ast.comprehension))
    )


# ─────────────────────────────────────────────────────────────────────────────
#  AST Normalizer (for structural duplicate detection)
# ─────────────────────────────────────────────────────────────────────────────

class ASTNormalizer(ast.NodeTransformer):
    """
    Normalizes AST to detect structural duplicates.
    1. Removes docstrings.
    2. Renames all arguments to 'argN'.
    3. Renames all local variables to 'varN' (simple scope-agnostic).
    """
    def __init__(self):
        self.arg_map = {}
        self.var_map = {}
        self.arg_count = 0
        self.var_count = 0

    def visit_FunctionDef(self, node):
        node.name = "func"
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            node.body.pop(0)
        for arg in node.args.args:
            if arg.arg != 'self':
                name = f"arg{self.arg_count}"
                self.arg_map[arg.arg] = name
                arg.arg = name
                self.arg_count += 1
        self.generic_visit(node)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Load)):
            if node.id in self.arg_map:
                node.id = self.arg_map[node.id]
            elif node.id not in self.var_map:
                name = f"var{self.var_count}"
                self.var_map[node.id] = name
                self.var_count += 1
                node.id = name
            else:
                node.id = self.var_map[node.id]
        return node

    def visit_arg(self, node):
        if node.arg in self.arg_map:
            node.arg = self.arg_map[node.arg]
        return node


def _compute_structure_hash(node: ast.AST) -> str:
    """Compute MD5 of normalized AST dump."""
    try:
        normalized = ASTNormalizer().visit(copy.deepcopy(node))
        return hashlib.md5(ast.dump(normalized).encode()).hexdigest()
    except Exception:
        return ""


def _walk_definitions(node: ast.AST):
    """Yield top-level and class-method function/class defs, skipping nested functions.

    Does NOT recurse into function bodies, so nested/inner functions are excluded.
    DOES recurse into class bodies (to find methods) and other compound statements
    (if/try/with at module level).
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield child
        elif isinstance(child, ast.ClassDef):
            yield child
            yield from _walk_definitions(child)
        else:
            yield from _walk_definitions(child)


def _extract_functions_from_file(fpath: Path, root: Path) -> Tuple[
        List[FunctionRecord], List[ClassRecord], Optional[str]]:
    """Parse one file and extract all functions and classes."""
    try:
        source = fpath.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return [], [], str(e)

    try:
        tree = ast.parse(source, filename=str(fpath))
    except SyntaxError as e:
        return [], [], f"SyntaxError: {e}"

    rel_path = str(fpath.relative_to(root)).replace("\\", "/")
    lines = source.splitlines()
    functions = []
    classes = []

    for node in _walk_definitions(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = max(node.lineno - 1, 0)
            end = node.end_lineno or start + 1
            code = "\n".join(lines[start:end])
            code_hash = hashlib.sha256(code.encode()).hexdigest()
            structure_hash = _compute_structure_hash(node)

            params = [a.arg for a in node.args.args if a.arg != "self"]
            ret = ast.unparse(node.returns) if node.returns and hasattr(ast, "unparse") else None
            try:
                decorators = [ast.unparse(d) for d in node.decorator_list]
            except Exception:
                decorators = []

            calls: List[str] = []
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name):
                        calls.append(child.func.id)
                    elif isinstance(child.func, ast.Attribute):
                        calls.append(child.func.attr)

            functions.append(FunctionRecord(
                name=node.name,
                file_path=rel_path,
                line_start=node.lineno,
                line_end=end,
                size_lines=end - start,
                parameters=params,
                return_type=ret,
                decorators=decorators,
                docstring=ast.get_docstring(node) or None,
                calls_to=list(set(calls)),
                complexity=_compute_complexity(node),
                nesting_depth=_compute_nesting_depth(node),
                code_hash=code_hash,
                structure_hash=structure_hash,
                code=code,
                is_async=isinstance(node, ast.AsyncFunctionDef),
            ))

        elif isinstance(node, ast.ClassDef):
            start = max(node.lineno - 1, 0)
            end = node.end_lineno or start + 1
            methods = [
                n.name for n in ast.walk(node)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except Exception:
                    bases.append("?")

            classes.append(ClassRecord(
                name=node.name,
                file_path=rel_path,
                line_start=node.lineno,
                line_end=end,
                size_lines=end - start,
                method_count=len(methods),
                base_classes=bases,
                docstring=ast.get_docstring(node) or None,
                methods=methods,
                has_init="__init__" in methods,
            ))

    return functions, classes, None


def scan_codebase(root: Path, exclude: List[str] = None,
                  include: List[str] = None) -> Tuple[
        List[FunctionRecord], List[ClassRecord], List[str]]:
    """Parallel-scan the codebase, returning functions, classes, and errors."""
    py_files = collect_py_files(root, exclude, include)
    all_functions: List[FunctionRecord] = []
    all_classes: List[ClassRecord] = []
    errors: List[str] = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_extract_functions_from_file, f, root): f
            for f in py_files
        }
        for future in concurrent.futures.as_completed(futures):
            funcs, clses, err = future.result()
            all_functions.extend(funcs)
            all_classes.extend(clses)
            if err:
                errors.append(f"{futures[future]}: {err}")

    return all_functions, all_classes, errors


# ─────────────────────────────────────────────────────────────────────────────
#  Tokenization Helpers (for similarity)
# ─────────────────────────────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "self cls none true false return def class if else elif for while try "
    "except finally with as import from raise pass break continue yield "
    "lambda and or not in is assert del global nonlocal async await "
    "the a an of to is it that this be on at by do has was are were "
    "str int float bool list dict set tuple bytes type any all len "
    "range print open super init new call".split()
)

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


def _term_freq(tokens: List[str]) -> Counter:
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


def code_similarity(code_a: str, code_b: str) -> float:
    """Structural similarity between two code blocks (0–1)."""
    if not code_a or not code_b:
        return 0.0
    return SequenceMatcher(None, code_a, code_b).ratio()


# ─────────────────────────────────────────────────────────────────────────────
#  Semantic Similarity (behavioral / functional matching)
# ─────────────────────────────────────────────────────────────────────────────

def name_similarity(name_a: str, name_b: str) -> float:
    """Semantic similarity between two function names (0–1).

    Tokenizes both names (camelCase / snake_case aware) and computes
    the Jaccard index over the resulting token sets.
    """
    ta = set(tokenize(name_a))
    tb = set(tokenize(name_b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def signature_similarity(func_a: "FunctionRecord",
                         func_b: "FunctionRecord") -> float:
    """Compare two function signatures — param names, count, return type (0–1).

    Signals checked:
      - Parameter name overlap  (Jaccard)
      - Parameter count ratio   (min/max)
      - Return-type match       (bool)
      - Async-flag match        (bool)
    """
    scores: List[float] = []

    # Param-name overlap (tokenised)
    pa = set(tokenize(" ".join(func_a.parameters)))
    pb = set(tokenize(" ".join(func_b.parameters)))
    if pa or pb:
        scores.append(len(pa & pb) / len(pa | pb) if (pa | pb) else 0.0)
    else:
        scores.append(1.0)   # both have zero params → match

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
        scores.append(0.5)   # both unknown
    else:
        scores.append(0.0)

    # Async-flag match
    scores.append(1.0 if func_a.is_async == func_b.is_async else 0.0)

    return sum(scores) / len(scores) if scores else 0.0


def callgraph_overlap(func_a: "FunctionRecord",
                      func_b: "FunctionRecord") -> float:
    """Jaccard overlap of functions each function calls.

    Two functions that call the same helpers / stdlib APIs tend to perform
    the same work, even if their code looks different.
    """
    ca = set(func_a.calls_to)
    cb = set(func_b.calls_to)
    if not ca and not cb:
        return 0.0   # no calls → no signal
    if not ca or not cb:
        return 0.0
    return len(ca & cb) / len(ca | cb)


def semantic_similarity(func_a: "FunctionRecord",
                        func_b: "FunctionRecord") -> float:
    """Weighted composite of behavioural signals (0–1).

    Combines four independent channels:
      - Name meaning    (30%)  — do the names describe the same thing?
      - Signature shape  (25%)  — same params / return type?
      - Call-graph       (30%)  — calling the same helper functions?
      - Docstring tokens (15%)  — docstrings describe similar purpose?
    """
    w_name = 0.30
    w_sig  = 0.25
    w_call = 0.30
    w_doc  = 0.15

    ns = name_similarity(func_a.name, func_b.name)
    ss = signature_similarity(func_a, func_b)
    cg = callgraph_overlap(func_a, func_b)

    # Docstring similarity (token cosine)
    da = _term_freq(tokenize(func_a.docstring or ""))
    db = _term_freq(tokenize(func_b.docstring or ""))
    ds = cosine_similarity(da, db) if (da and db) else 0.0

    return w_name * ns + w_sig * ss + w_call * cg + w_doc * ds


# ─────────────────────────────────────────────────────────────────────────────
#  LLM Helper (optional)
# ─────────────────────────────────────────────────────────────────────────────

class LLMHelper:
    """Lazy-loading wrapper around Core.services.inference_engine."""

    def __init__(self, root: Path, model_path: Optional[str] = None):
        self._root = root
        self._llm = None
        self._available = None
        self._model_path = model_path
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def available(self) -> bool:
        if self._available is None:
            try:
                if str(self._root) not in sys.path:
                    sys.path.insert(0, str(self._root))
                from Core.services.inference_engine import FIFOLlamaCppInference
                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def _ensure_loaded(self):
        if self._llm is not None:
            return
        if not self.available:
            raise RuntimeError("LLM not available")

        from Core.services.inference_engine import FIFOLlamaCppInference

        # Smart model selection
        model_path = self._model_path
        if not model_path:
            possible_models = [
                Path(r"C:\AI\Models\qwen2.5-coder-7b-instruct-q4_k_m.gguf"),
                Path(r"C:\AI\Models\Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf"),
                Path(r"C:\AI\Models\Phi-3.5-mini-instruct-Q4_K_M.gguf"),
            ]
            for m in possible_models:
                if m.exists():
                    logger.info(f"LLM: Using {m.name}")
                    model_path = str(m)
                    break

        self._llm = FIFOLlamaCppInference(
            model_path=model_path, lazy_load=False, verbose=False
        )
        self._llm._setup_llm()
        if not self._llm._initialized:
            raise RuntimeError(f"LLM init failed: {self._llm._init_error}")

    def query_sync(self, prompt: str, max_tokens: int = 300,
                   temperature: float = 0.1) -> str:
        """Synchronous LLM query (collects streaming output)."""
        self._ensure_loaded()

        async def _run():
            text = ""
            async for chunk in self._llm.query(
                prompt, max_tokens=max_tokens, temperature=temperature
            ):
                text += chunk
            return text

        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(_run())

    def close(self):
        """Clean up event loop."""
        if self._loop and not self._loop.is_closed():
            self._loop.close()
            self._loop = None


# ─────────────────────────────────────────────────────────────────────────────
#  CODE SMELL DETECTOR
# ─────────────────────────────────────────────────────────────────────────────

# Thresholds (tunable)
SMELL_THRESHOLDS = {
    "long_function": 60,        # lines
    "very_long_function": 120,  # lines → critical
    "deep_nesting": 4,          # levels
    "very_deep_nesting": 6,     # levels → critical
    "high_complexity": 10,      # cyclomatic
    "very_high_complexity": 20, # cyclomatic → critical
    "too_many_params": 6,       # parameters
    "god_class": 15,            # methods
    "large_class": 500,         # lines
    "missing_docstring_size": 15,  # only flag if function > N lines
    "too_many_returns": 5,      # return statements
    "too_many_branches": 8,     # if/elif branches
}


class CodeSmellDetector:
    """
    Detects code smells via AST heuristics, optionally enriched by LLM.
    
    Two-stage approach:
      Stage 1 (fast):  AST metrics → flag suspects based on thresholds
      Stage 2 (slow):  Send suspects to LLM for detailed analysis + fix suggestions
    """

    def __init__(self, thresholds: Dict[str, int] = None):
        self.thresholds = {**SMELL_THRESHOLDS, **(thresholds or {})}
        self.smells: List[SmellIssue] = []

    def detect(self, functions: List[FunctionRecord],
               classes: List[ClassRecord]) -> List[SmellIssue]:
        """Run all heuristic smell detectors. Returns sorted list of SmellIssues."""
        self.smells = []
        for func in functions:
            self._check_function(func)
        for cls in classes:
            self._check_class(cls)
        # Sort: critical first, then by file/line
        self.smells.sort(key=lambda s: (
            0 if s.severity == Severity.CRITICAL else
            1 if s.severity == Severity.WARNING else 2,
            s.file_path, s.line
        ))
        return self.smells

    def _check_function(self, func: FunctionRecord):
        t = self.thresholds

        # Long function
        if func.size_lines >= t["very_long_function"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="very-long-function",
                severity=Severity.CRITICAL, name=func.name,
                metric_value=func.size_lines,
                message=f"Function '{func.name}' is {func.size_lines} lines (limit: {t['very_long_function']})",
                suggestion="Split into smaller focused functions. Extract logical blocks.",
            ))
        elif func.size_lines >= t["long_function"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="long-function",
                severity=Severity.WARNING, name=func.name,
                metric_value=func.size_lines,
                message=f"Function '{func.name}' is {func.size_lines} lines (limit: {t['long_function']})",
                suggestion="Consider splitting into smaller functions.",
            ))

        # Deep nesting
        if func.nesting_depth >= t["very_deep_nesting"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="very-deep-nesting",
                severity=Severity.CRITICAL, name=func.name,
                metric_value=func.nesting_depth,
                message=f"Function '{func.name}' has nesting depth {func.nesting_depth} (limit: {t['very_deep_nesting']})",
                suggestion="Use early returns, guard clauses, or extract nested blocks.",
            ))
        elif func.nesting_depth >= t["deep_nesting"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="deep-nesting",
                severity=Severity.WARNING, name=func.name,
                metric_value=func.nesting_depth,
                message=f"Function '{func.name}' has nesting depth {func.nesting_depth} (limit: {t['deep_nesting']})",
                suggestion="Flatten with early returns or extract helper functions.",
            ))

        # High cyclomatic complexity
        if func.complexity >= t["very_high_complexity"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="very-high-complexity",
                severity=Severity.CRITICAL, name=func.name,
                metric_value=func.complexity,
                message=f"Function '{func.name}' has cyclomatic complexity {func.complexity} (limit: {t['very_high_complexity']})",
                suggestion="Decompose into smaller, single-responsibility functions.",
            ))
        elif func.complexity >= t["high_complexity"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="high-complexity",
                severity=Severity.WARNING, name=func.name,
                metric_value=func.complexity,
                message=f"Function '{func.name}' has cyclomatic complexity {func.complexity} (limit: {t['high_complexity']})",
                suggestion="Simplify branching logic. Consider lookup tables or strategy pattern.",
            ))

        # Too many parameters
        if len(func.parameters) >= t["too_many_params"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="too-many-params",
                severity=Severity.WARNING, name=func.name,
                metric_value=len(func.parameters),
                message=f"Function '{func.name}' has {len(func.parameters)} parameters (limit: {t['too_many_params']})",
                suggestion="Group related parameters into a dataclass or config object.",
            ))

        # Missing docstring (only for non-trivial functions)
        if (not func.docstring
                and func.size_lines >= t["missing_docstring_size"]
                and not func.name.startswith("_")):
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="missing-docstring",
                severity=Severity.INFO, name=func.name,
                metric_value=func.size_lines,
                message=f"Function '{func.name}' ({func.size_lines} lines) has no docstring",
                suggestion="Add a docstring explaining purpose, parameters, and return value.",
            ))

        # Too many return statements (AST-based)
        try:
            _tree = ast.parse(func.code)
            return_count = sum(1 for _n in ast.walk(_tree) if isinstance(_n, ast.Return))
        except SyntaxError:
            return_count = 0
        if return_count >= t["too_many_returns"]:
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="too-many-returns",
                severity=Severity.WARNING, name=func.name,
                metric_value=return_count,
                message=f"Function '{func.name}' has {return_count} return statements (limit: {t['too_many_returns']})",
                suggestion="Consolidate exit points. Consider a result variable.",
            ))

        # Boolean blindness — function returns bool but name doesn't hint
        if (func.return_type and 'bool' in func.return_type.lower()
                and not any(func.name.startswith(p)
                            for p in ("is_", "has_", "can_", "should_", "check_",
                                      "validate_", "contains_", "exists_"))):
            self.smells.append(SmellIssue(
                file_path=func.file_path, line=func.line_start,
                end_line=func.line_end, category="boolean-blindness",
                severity=Severity.INFO, name=func.name,
                metric_value=0,
                message=f"Function '{func.name}' returns bool but name doesn't indicate a question",
                suggestion="Rename to is_/has_/can_/should_/check_ prefix for clarity.",
            ))

    def _check_class(self, cls: ClassRecord):
        t = self.thresholds

        # God class (too many methods)
        if cls.method_count >= t["god_class"]:
            self.smells.append(SmellIssue(
                file_path=cls.file_path, line=cls.line_start,
                end_line=cls.line_end, category="god-class",
                severity=Severity.CRITICAL, name=cls.name,
                metric_value=cls.method_count,
                message=f"Class '{cls.name}' has {cls.method_count} methods (limit: {t['god_class']})",
                suggestion="Split into smaller classes with single responsibility."
                           " Consider delegation or mixins.",
            ))

        # Large class (too many lines)
        if cls.size_lines >= t["large_class"]:
            self.smells.append(SmellIssue(
                file_path=cls.file_path, line=cls.line_start,
                end_line=cls.line_end, category="large-class",
                severity=Severity.WARNING, name=cls.name,
                metric_value=cls.size_lines,
                message=f"Class '{cls.name}' is {cls.size_lines} lines (limit: {t['large_class']})",
                suggestion="Extract logical groups of methods into separate classes or modules.",
            ))

        # Missing docstring on class
        if not cls.docstring and cls.size_lines > 30:
            self.smells.append(SmellIssue(
                file_path=cls.file_path, line=cls.line_start,
                end_line=cls.line_end, category="missing-class-docstring",
                severity=Severity.INFO, name=cls.name,
                metric_value=cls.size_lines,
                message=f"Class '{cls.name}' ({cls.size_lines} lines) has no docstring",
                suggestion="Add a docstring explaining the class's responsibility.",
            ))

        # Data class candidate — class with only __init__ setting attributes
        if (cls.method_count <= 3 and cls.has_init
                and not cls.base_classes):
            self.smells.append(SmellIssue(
                file_path=cls.file_path, line=cls.line_start,
                end_line=cls.line_end, category="dataclass-candidate",
                severity=Severity.INFO, name=cls.name,
                metric_value=cls.method_count,
                message=f"Class '{cls.name}' has only {cls.method_count} methods — consider @dataclass",
                suggestion="If this class mainly holds data, convert to @dataclass for less boilerplate.",
            ))

    def enrich_with_llm(self, llm: LLMHelper, max_calls: int = 20):
        """Send the worst smells to LLM for detailed analysis."""
        critical_smells = [
            s for s in self.smells
            if s.severity in (Severity.CRITICAL, Severity.WARNING)
               and not s.llm_analysis
        ][:max_calls]

        if not critical_smells:
            return

        logger.info(f"Enriching {len(critical_smells)} smells with LLM...")
        for smell in critical_smells:
            prompt = (
                f"You are a Senior Python Architect reviewing code.\n"
                f"Issue: {smell.message}\n"
                f"Category: {smell.category}\n"
                f"File: {smell.file_path}:{smell.line}\n\n"
                f"Give a 2-3 sentence actionable recommendation to fix this. "
                f"Be specific about WHAT to extract or refactor.\n\n"
                f"Recommendation:"
            )
            try:
                response = llm.query_sync(prompt, max_tokens=150)
                smell.llm_analysis = response.strip()
            except Exception as e:
                logger.debug(f"LLM enrichment failed: {e}")

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict of all smells."""
        by_severity = Counter(s.severity for s in self.smells)
        by_category = Counter(s.category for s in self.smells)
        by_file = Counter(s.file_path for s in self.smells)
        return {
            "total": len(self.smells),
            "critical": by_severity.get(Severity.CRITICAL, 0),
            "warning": by_severity.get(Severity.WARNING, 0),
            "info": by_severity.get(Severity.INFO, 0),
            "by_category": dict(by_category),
            "worst_files": dict(by_file.most_common(10)),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  DUPLICATE FINDER
# ─────────────────────────────────────────────────────────────────────────────

class DuplicateFinder:
    """
    Cross-file function similarity detector.
    
    Four-stage pipeline:
      1a. Exact hash match  → identical code
      1b. Structural hash   → same AST shape, different variable names
      2.  Token cosine + SequenceMatcher pre-filter → near-duplicates
      3.  Semantic similarity (name + signature + callgraph + docstring)
    """

    # Thresholds
    EXACT_THRESHOLD = 1.0
    NEAR_DUP_THRESHOLD = 0.70
    TOKEN_PREFILTER = 0.25
    SIZE_RATIO_MIN = 0.35       # skip if sizes wildly different
    SEMANTIC_THRESHOLD = 0.50   # semantic similarity threshold
    SEMANTIC_MIN_LINES = 8      # min function size for semantic matching

    # Boilerplate to skip
    _BOILERPLATE = frozenset({
        "__init__", "__repr__", "__str__", "__eq__", "__hash__",
        "__len__", "__iter__", "__next__", "__enter__", "__exit__",
        "__getitem__", "__setitem__", "__contains__",
        "setUp", "tearDown", "setup", "teardown",
    })

    def __init__(self):
        self.groups: List[DuplicateGroup] = []
        self._tokens: Dict[str, Counter] = {}

    def find(self, functions: List[FunctionRecord],
             cross_file_only: bool = True) -> List[DuplicateGroup]:
        """Find duplicate/similar function groups."""
        self.groups = []
        group_id = 0

        # Pre-compute tokens (name + metadata + code body for broad matching)
        for func in functions:
            text = " ".join([
                func.name,
                func.docstring or "",
                " ".join(func.parameters),
                func.return_type or "",
                " ".join(func.calls_to),
                func.code or "",
            ])
            self._tokens[func.key] = _term_freq(tokenize(text))

        # Stage 1: Exact hash matches
        hash_groups: Dict[str, List[FunctionRecord]] = defaultdict(list)
        for func in functions:
            if func.name not in self._BOILERPLATE:
                hash_groups[func.code_hash].append(func)

        seen_keys: Set[str] = set()
        for code_hash, group in hash_groups.items():
            if len(group) < 2:
                continue
            if cross_file_only:
                files = {f.file_path for f in group}
                if len(files) < 2:
                    continue
            self.groups.append(DuplicateGroup(
                group_id=group_id,
                similarity_type="exact",
                avg_similarity=1.0,
                functions=[
                    {"key": f.key, "name": f.name, "file": f.file_path,
                     "line": f.line_start, "size": f.size_lines,
                     "similarity": 1.0}
                    for f in group
                ],
            ))
            seen_keys.update(f.key for f in group)
            group_id += 1

        # Stage 1b: Structural hash matches (same AST, different variable names)
        struct_groups: Dict[str, List[FunctionRecord]] = defaultdict(list)
        for func in functions:
            if func.key not in seen_keys and func.name not in self._BOILERPLATE:
                if func.size_lines >= 4 and func.structure_hash:
                    struct_groups[func.structure_hash].append(func)

        for s_hash, group in struct_groups.items():
            if len(group) < 2:
                continue
            if cross_file_only:
                files = {f.file_path for f in group}
                if len(files) < 2:
                    continue
            self.groups.append(DuplicateGroup(
                group_id=group_id,
                similarity_type="structural",
                avg_similarity=1.0,
                functions=[
                    {"key": f.key, "name": f.name, "file": f.file_path,
                     "line": f.line_start, "size": f.size_lines,
                     "similarity": 1.0}
                    for f in group
                ],
                merge_suggestion="Logic is identical. Rename variables to unify."
            ))
            seen_keys.update(f.key for f in group)
            group_id += 1

        # Stage 2: Token cosine pre-filter → SequenceMatcher
        func_list = [f for f in functions
                     if f.key not in seen_keys
                     and f.name not in self._BOILERPLATE
                     and f.size_lines >= 5]

        # Pre-filter pairs with token cosine
        candidates: List[Tuple[FunctionRecord, FunctionRecord, float]] = []
        for i, f1 in enumerate(func_list):
            for f2 in func_list[i + 1:]:
                if cross_file_only and f1.file_path == f2.file_path:
                    continue
                # Size ratio check
                ratio = min(f1.size_lines, f2.size_lines) / max(f1.size_lines, f2.size_lines)
                if ratio < self.SIZE_RATIO_MIN:
                    continue
                # Token cosine
                tok_sim = cosine_similarity(
                    self._tokens.get(f1.key, Counter()),
                    self._tokens.get(f2.key, Counter()),
                )
                if tok_sim >= self.TOKEN_PREFILTER:
                    candidates.append((f1, f2, tok_sim))

        logger.info(f"Duplicate pre-filter: {len(candidates)} candidates from {len(func_list)} functions")

        # Expensive SequenceMatcher on candidates only
        near_pairs: List[Tuple[FunctionRecord, FunctionRecord, float]] = []
        for f1, f2, tok_sim in candidates:
            sim = code_similarity(f1.code, f2.code)
            if sim >= self.NEAR_DUP_THRESHOLD:
                near_pairs.append((f1, f2, sim))

        # Cluster near-pairs via union-find
        parent: Dict[str, str] = {}

        def find_root(x):
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find_root(a), find_root(b)
            if ra != rb:
                parent[ra] = rb

        for f1, f2, sim in near_pairs:
            parent.setdefault(f1.key, f1.key)
            parent.setdefault(f2.key, f2.key)
            union(f1.key, f2.key)

        # Build clusters
        clusters: Dict[str, List[Tuple[FunctionRecord, float]]] = defaultdict(list)
        func_map = {f.key: f for f in functions}
        pair_sims: Dict[Tuple[str, str], float] = {
            (f1.key, f2.key): sim for f1, f2, sim in near_pairs
        }

        for f1, f2, sim in near_pairs:
            root = find_root(f1.key)
            if not any(x[0].key == f1.key for x in clusters[root]):
                clusters[root].append((f1, 1.0))
            if not any(x[0].key == f2.key for x in clusters[root]):
                clusters[root].append((f2, sim))

        for root_key, members in clusters.items():
            if len(members) < 2:
                continue
            sims = [s for _, s in members]
            avg = sum(sims) / len(sims) if sims else 0

            self.groups.append(DuplicateGroup(
                group_id=group_id,
                similarity_type="near",
                avg_similarity=round(avg, 3),
                functions=[
                    {"key": f.key, "name": f.name, "file": f.file_path,
                     "line": f.line_start, "size": f.size_lines,
                     "similarity": round(sim, 3),
                     "signature": f.signature}
                    for f, sim in members
                ],
            ))
            group_id += 1

        # Stage 3: Semantic similarity (functional matching)
        # Catches functions that do the same thing but look different
        seen_stage2 = set(seen_keys)
        for root_key, members in clusters.items():
            for func, _ in members:
                seen_stage2.add(func.key)

        semantic_list = [
            f for f in functions
            if f.key not in seen_stage2
            and f.name not in self._BOILERPLATE
            and f.size_lines >= self.SEMANTIC_MIN_LINES
        ]

        sem_pairs: List[Tuple[FunctionRecord, FunctionRecord, float]] = []
        for i, f1 in enumerate(semantic_list):
            for f2 in semantic_list[i + 1:]:
                if cross_file_only and f1.file_path == f2.file_path:
                    continue
                sim = semantic_similarity(f1, f2)
                if sim >= self.SEMANTIC_THRESHOLD:
                    sem_pairs.append((f1, f2, sim))

        if sem_pairs:
            logger.info(f"Semantic stage: {len(sem_pairs)} functionally similar pairs")

        # Cluster semantic pairs with union-find
        sem_parent: Dict[str, str] = {}

        def sem_find(x):
            while sem_parent.get(x, x) != x:
                sem_parent[x] = sem_parent.get(sem_parent[x], sem_parent[x])
                x = sem_parent[x]
            return x

        def sem_union(a, b):
            ra, rb = sem_find(a), sem_find(b)
            if ra != rb:
                sem_parent[ra] = rb

        for f1, f2, sim in sem_pairs:
            sem_parent.setdefault(f1.key, f1.key)
            sem_parent.setdefault(f2.key, f2.key)
            sem_union(f1.key, f2.key)

        sem_clusters: Dict[str, List[Tuple[FunctionRecord, float]]] = defaultdict(list)
        for f1, f2, sim in sem_pairs:
            root = sem_find(f1.key)
            if not any(x[0].key == f1.key for x in sem_clusters[root]):
                sem_clusters[root].append((f1, 1.0))
            if not any(x[0].key == f2.key for x in sem_clusters[root]):
                sem_clusters[root].append((f2, sim))

        for root_key, members in sem_clusters.items():
            if len(members) < 2:
                continue
            sims = [s for _, s in members]
            avg = sum(sims) / len(sims) if sims else 0

            self.groups.append(DuplicateGroup(
                group_id=group_id,
                similarity_type="semantic",
                avg_similarity=round(avg, 3),
                functions=[
                    {"key": f.key, "name": f.name, "file": f.file_path,
                     "line": f.line_start, "size": f.size_lines,
                     "similarity": round(sim, 3),
                     "signature": f.signature}
                    for f, sim in members
                ],
            ))
            group_id += 1

        # Sort groups by avg similarity descending
        self.groups.sort(key=lambda g: g.avg_similarity, reverse=True)
        return self.groups

    def enrich_with_llm(self, llm: LLMHelper, functions: List[FunctionRecord],
                        max_calls: int = 15):
        """Ask LLM if near-duplicates should be merged."""
        func_map = {f.key: f for f in functions}
        enriched = 0

        for group in self.groups:
            if enriched >= max_calls:
                break
            if group.similarity_type == "exact":
                group.merge_suggestion = "Identical code — extract to a shared module."
                continue
            if len(group.functions) < 2:
                continue

            # Pick the two most similar functions for LLM review
            flist = group.functions[:2]
            f1 = func_map.get(flist[0]["key"])
            f2 = func_map.get(flist[1]["key"])
            if not f1 or not f2:
                continue

            prompt = (
                "You are a refactoring expert.\n"
                f"Function A: {f1.name} ({f1.file_path}:{f1.line_start})\n"
                f"```python\n{f1.code[:500]}\n```\n\n"
                f"Function B: {f2.name} ({f2.file_path}:{f2.line_start})\n"
                f"```python\n{f2.code[:500]}\n```\n\n"
                "Should these be merged? If yes, suggest a unified function name "
                "and signature. If no, explain why they're different.\n\n"
                "Answer (2-3 sentences):"
            )
            try:
                response = llm.query_sync(prompt, max_tokens=200)
                group.merge_suggestion = response.strip()
                enriched += 1
            except Exception as e:
                logger.debug(f"LLM merge suggestion failed: {e}")

    def summary(self) -> Dict[str, Any]:
        """Return a summary of duplicate findings."""
        exact = [g for g in self.groups if g.similarity_type == "exact"]
        near = [g for g in self.groups if g.similarity_type == "near"]
        structural = [g for g in self.groups if g.similarity_type == "structural"]
        semantic = [g for g in self.groups if g.similarity_type == "semantic"]
        total_funcs = sum(len(g.functions) for g in self.groups)
        return {
            "total_groups": len(self.groups),
            "exact_duplicates": len(exact),
            "structural_duplicates": len(structural),
            "near_duplicates": len(near),
            "semantic_duplicates": len(semantic),
            "total_functions_involved": total_funcs,
            "avg_similarity": (
                round(sum(g.avg_similarity for g in self.groups) / len(self.groups), 3)
                if self.groups else 0
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  LIBRARY ADVISOR
# ─────────────────────────────────────────────────────────────────────────────

class LibraryAdvisor:
    """
    Analyzes duplicate clusters and suggests shared library extraction.
    
    Works in two modes:
      - Heuristic: Groups by function name patterns and cross-file spread
      - LLM: Generates unified API proposals
    """

    MIN_CROSS_FILE_SPREAD = 2    # function must appear in >= N files
    MIN_GROUP_SIZE = 2

    def __init__(self):
        self.suggestions: List[LibrarySuggestion] = []

    def analyze(self, duplicate_groups: List[DuplicateGroup],
                functions: List[FunctionRecord]) -> List[LibrarySuggestion]:
        """Generate library extraction suggestions from duplicate analysis."""
        self.suggestions = []
        func_map = {f.key: f for f in functions}

        # Approach 1: Direct from duplicate groups
        for group in duplicate_groups:
            if len(group.functions) < self.MIN_GROUP_SIZE:
                continue
            files = {f["file"] for f in group.functions}
            if len(files) < self.MIN_CROSS_FILE_SPREAD:
                continue

            # Pick the "best" function (longest, has docstring)
            best = max(
                group.functions,
                key=lambda f: (
                    1 if func_map.get(f["key"], None)
                         and func_map[f["key"]].docstring else 0,
                    f.get("size", 0)
                )
            )
            best_func = func_map.get(best["key"])
            if not best_func:
                continue

            names = [f["name"] for f in group.functions]
            # Suggest a module name from common patterns
            module_name = self._suggest_module_name(names)

            self.suggestions.append(LibrarySuggestion(
                module_name=module_name,
                description=f"Consolidate {len(names)} similar implementations of '{names[0]}'",
                functions=[
                    {"name": f["name"], "file": f["file"],
                     "line": f["line"], "similarity": f.get("similarity", 1.0)}
                    for f in group.functions
                ],
                unified_api=best_func.signature,
                rationale=(
                    f"Found in {len(files)} files "
                    f"({', '.join(sorted(files)[:3])}{'...' if len(files) > 3 else ''}). "
                    f"Average similarity: {group.avg_similarity:.0%}. "
                    f"{'Merge suggestion: ' + group.merge_suggestion if group.merge_suggestion else ''}"
                ),
            ))

        # Approach 2: Cross-file function name analysis
        name_files: Dict[str, List[FunctionRecord]] = defaultdict(list)
        for func in functions:
            if func.name not in DuplicateFinder._BOILERPLATE:
                name_files[func.name].append(func)

        already_suggested = {
            f["name"] for s in self.suggestions for f in s.functions
        }

        for name, funcs in name_files.items():
            if name in already_suggested:
                continue
            files = {f.file_path for f in funcs}
            if len(files) < self.MIN_CROSS_FILE_SPREAD:
                continue
            if len(funcs) < self.MIN_GROUP_SIZE:
                continue

            best_func = max(funcs, key=lambda f: (
                1 if f.docstring else 0, f.size_lines
            ))
            module_name = self._suggest_module_name([name])
            self.suggestions.append(LibrarySuggestion(
                module_name=module_name,
                description=f"Function '{name}' reimplemented in {len(files)} files",
                functions=[
                    {"name": f.name, "file": f.file_path,
                     "line": f.line_start, "similarity": 1.0}
                    for f in funcs
                ],
                unified_api=best_func.signature,
                rationale=(
                    f"Identical name across: {', '.join(sorted(files)[:4])}. "
                    f"Consider extracting to a shared utilities module."
                ),
            ))

        self.suggestions.sort(key=lambda s: len(s.functions), reverse=True)
        return self.suggestions

    def enrich_with_llm(self, llm: LLMHelper, functions: List[FunctionRecord],
                        max_calls: int = 10):
        """LLM generates unified API proposals for each suggestion."""
        func_map = {f.key: f for f in functions}
        enriched = 0

        for suggestion in self.suggestions:
            if enriched >= max_calls:
                break

            # Gather code snippets
            snippets = []
            for finfo in suggestion.functions[:3]:  # limit context
                key = f"{Path(finfo['file']).stem}.{finfo['name']}"
                func = func_map.get(key)
                if func:
                    snippets.append(f"# From {func.file_path}\n{func.code[:400]}")

            if not snippets:
                continue

            prompt = (
                "You are designing a shared Python library.\n"
                f"Module name: {suggestion.module_name}\n\n"
                "These similar functions exist across multiple files:\n\n"
                + "\n---\n".join(snippets) +
                "\n\nDesign a unified function that covers all use cases.\n"
                "Output:\n"
                "1. Function signature (def ...)\n"
                "2. One-line docstring\n"
                "3. Key design decisions (2 sentences)\n"
            )
            try:
                response = llm.query_sync(prompt, max_tokens=250)
                suggestion.unified_api = response.strip()
                enriched += 1
            except Exception as e:
                logger.debug(f"LLM library suggestion failed: {e}")

    def _suggest_module_name(self, func_names: List[str]) -> str:
        """Suggest a module name from function naming patterns."""
        name = func_names[0].lower()
        # Common pattern-based groupings
        patterns = {
            "utils": ["format", "convert", "parse", "clean", "normalize", "strip"],
            "io_helpers": ["read", "write", "load", "save", "dump", "export", "import"],
            "validators": ["validate", "check", "verify", "assert", "ensure"],
            "search": ["search", "find", "query", "lookup", "filter", "match"],
            "config": ["config", "setting", "option", "default", "setup"],
            "cache": ["cache", "store", "memo", "persist"],
            "display": ["render", "display", "show", "print", "format", "draw"],
            "network": ["fetch", "request", "download", "upload", "connect"],
        }
        for module, keywords in patterns.items():
            if any(kw in name for kw in keywords):
                return module
        return "shared_utils"

    def summary(self) -> Dict[str, Any]:
        return {
            "total_suggestions": len(self.suggestions),
            "total_functions": sum(len(s.functions) for s in self.suggestions),
            "modules_proposed": list(set(s.module_name for s in self.suggestions)),
        }


# ─────────────────────────────────────────────────────────────────────────────
#  SMART GRAPH (Enhanced vis-network with health coloring)
# ─────────────────────────────────────────────────────────────────────────────

class SmartGraph:
    """
    Generates an interactive HTML graph with:
      - Health-colored file nodes (green/yellow/red based on smell count)
      - Enriched tooltips (smells, duplicates)
      - Duplicate connections shown as edges
    """

    def __init__(self):
        self.nodes: List[Dict] = []
        self.edges: List[Dict] = []
        self._smells: List[SmellIssue] = []
        self._duplicates: List[DuplicateGroup] = []
        self._root_name: str = ""

    def build(self, functions: List[FunctionRecord],
              smells: List[SmellIssue],
              duplicates: List[DuplicateGroup],
              root: Path):
        """Build graph data from analysis results."""
        self.nodes = []
        self.edges = []
        self._smells = list(smells)
        self._duplicates = list(duplicates)
        self._root_name = root.name

        # Per-file metrics
        file_smells: Dict[str, List[SmellIssue]] = defaultdict(list)
        for s in smells:
            file_smells[s.file_path].append(s)

        file_funcs: Dict[str, int] = Counter(f.file_path for f in functions)

        # Parse all unique files
        all_files = sorted(set(f.file_path for f in functions))
        node_ids: Dict[str, int] = {}

        for i, fpath in enumerate(all_files, 1):
            fsmells = file_smells.get(fpath, [])
            n_critical = sum(1 for s in fsmells if s.severity == Severity.CRITICAL)
            n_warning = sum(1 for s in fsmells if s.severity == Severity.WARNING)
            n_info = sum(1 for s in fsmells if s.severity == Severity.INFO)

            # Color based on health
            if n_critical > 0:
                color = "#e74c3c"  # red
                health = "critical"
            elif n_warning > 0:
                color = "#f39c12"  # yellow/orange
                health = "warning"
            else:
                color = "#2ecc71"  # green
                health = "healthy"

            # Tooltip (always Unicode — browsers handle it fine)
            tooltip_lines = [f"<b>{fpath}</b>"]
            tooltip_lines.append(f"Functions: {file_funcs.get(fpath, 0)}")
            if fsmells:
                tooltip_lines.append(f"<br/><b>Issues:</b>")
                for s in fsmells[:5]:
                    html_icon = Severity._ICONS_UNICODE.get(s.severity, "?")
                    tooltip_lines.append(
                        f"  {html_icon} {s.category}: {s.name}"
                    )
                if len(fsmells) > 5:
                    tooltip_lines.append(f"  ...+{len(fsmells) - 5} more")

            node_ids[fpath] = i
            self.nodes.append({
                "id": i,
                "label": Path(fpath).name,
                "title": "<br/>".join(tooltip_lines),
                "color": color,
                "shape": "dot",
                "size": max(10, min(40, file_funcs.get(fpath, 1) * 3)),
                "health": health,
                "full_path": fpath,
            })

        # Duplicate edges
        for group in duplicates:
            files_in_group = list(set(f["file"] for f in group.functions))
            for i, f1 in enumerate(files_in_group):
                for f2 in files_in_group[i + 1:]:
                    if f1 in node_ids and f2 in node_ids:
                        self.edges.append({
                            "from": node_ids[f1],
                            "to": node_ids[f2],
                            "label": f"{group.avg_similarity:.0%}",
                            "color": "#e67e22" if group.similarity_type == "near" else "#e74c3c",
                            "dashes": group.similarity_type == "near",
                            "title": (
                                f"Duplicate: {', '.join(f['name'] for f in group.functions[:3])}"
                            ),
                        })

    def write_html(self, output_path: Path):
        """Write the interactive graph with side-panel lists to an HTML file."""
        nodes_json = json.dumps(self.nodes, indent=2)
        edges_json = json.dumps(self.edges, indent=2)

        # Count health stats
        n_healthy = sum(1 for n in self.nodes if n.get("health") == "healthy")
        n_warning = sum(1 for n in self.nodes if n.get("health") == "warning")
        n_critical = sum(1 for n in self.nodes if n.get("health") == "critical")

        # Build duplicate groups data for the HTML panel
        dup_rows = []
        for g in self._duplicates:
            dup_rows.append({
                "id": g.group_id,
                "type": g.similarity_type,
                "sim": round(g.avg_similarity * 100),
                "funcs": [
                    {"name": f["name"], "file": f["file"], "line": f.get("line", 0)}
                    for f in g.functions
                ],
                "merge": g.merge_suggestion or "",
            })
        dup_json = json.dumps(dup_rows)

        # Build smell rows for the HTML panel
        smell_rows = []
        for s in self._smells:
            smell_rows.append({
                "sev": s.severity,
                "cat": s.category,
                "name": s.name,
                "file": s.file_path,
                "line": s.line,
                "msg": s.message,
                "sug": s.suggestion,
            })
        smell_json = json.dumps(smell_rows)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>X-RAY Claude v{__version__} — Smart Code Graph</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; overflow: hidden; }}

  /* ── Header ── */
  #header {{
    height: 52px; padding: 0 20px; background: linear-gradient(135deg, #0f3460 0%, #16213e 100%);
    display: flex; justify-content: space-between; align-items: center;
    box-shadow: 0 2px 10px rgba(0,0,0,.5); z-index: 100; position: relative;
  }}
  #header h1 {{ font-size: 17px; color: #00d4ff; white-space: nowrap; }}
  .tab-bar {{ display: flex; gap: 6px; }}
  .tab-btn {{
    padding: 6px 16px; background: rgba(255,255,255,.08); border: none;
    color: #ccc; cursor: pointer; border-radius: 5px; font-size: 13px; font-weight: 500;
    transition: .2s;
  }}
  .tab-btn:hover {{ background: rgba(255,255,255,.18); color: #fff; }}
  .tab-btn.active {{ background: #00d4ff; color: #000; }}

  /* ── Panels ── */
  .panel {{ display: none; width: 100%; height: calc(100vh - 52px); }}
  .panel.active {{ display: flex; }}

  /* Graph panel */
  #panel-graph {{ position: relative; }}
  #graph {{ width: 100%; height: 100%; }}
  .graph-legend {{
    position: absolute; bottom: 16px; right: 16px;
    background: rgba(0,0,0,.82); padding: 12px 16px; border-radius: 8px;
    font-size: 12px; line-height: 1.8;
  }}
  .ldot {{ width: 11px; height: 11px; border-radius: 50%; display: inline-block; margin-right: 6px; vertical-align: middle; }}

  /* List panels (duplicates + smells) */
  .list-panel {{ flex-direction: column; overflow: hidden; }}
  .list-panel .toolbar {{
    padding: 10px 20px; background: #16213e; display: flex; gap: 12px; align-items: center;
    flex-shrink: 0;
  }}
  .search-input {{
    flex: 1; max-width: 500px; padding: 8px 12px; background: rgba(255,255,255,.08);
    border: 1px solid #333; border-radius: 5px; color: #fff; font-size: 13px;
  }}
  .search-input:focus {{ outline: none; border-color: #00d4ff; }}
  .stat-chip {{
    padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600;
  }}
  .stat-chip.exact {{ background: #e74c3c; }}
  .stat-chip.near {{ background: #e67e22; }}
  .stat-chip.crit {{ background: #e74c3c; }}
  .stat-chip.warn {{ background: #f39c12; color: #111; }}
  .stat-chip.info {{ background: #2ecc71; color: #111; }}

  .list-scroll {{ flex: 1; overflow-y: auto; padding: 0 20px 20px 20px; }}

  /* Duplicate group cards */
  .dup-group {{
    margin: 12px 0; background: rgba(255,255,255,.04); border-radius: 8px;
    border-left: 4px solid #e74c3c; overflow: hidden;
  }}
  .dup-group.near {{ border-left-color: #e67e22; }}
  .dup-group-header {{
    padding: 10px 14px; display: flex; justify-content: space-between; align-items: center;
    cursor: pointer; user-select: none;
  }}
  .dup-group-header:hover {{ background: rgba(255,255,255,.04); }}
  .dup-type {{ font-weight: 700; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; }}
  .dup-type.exact {{ color: #e74c3c; }}
  .dup-type.near {{ color: #e67e22; }}
  .dup-sim {{ color: #aaa; font-size: 12px; }}
  .dup-funcs {{ padding: 0 14px 10px 14px; }}
  .dup-func {{
    display: flex; gap: 10px; padding: 4px 0; font-size: 13px; align-items: baseline;
  }}
  .func-name {{ font-family: 'Cascadia Code', 'Fira Code', monospace; color: #00d4ff; font-weight: 600; min-width: 200px; }}
  .func-file {{ color: #888; font-size: 12px; }}
  .dup-merge {{ padding: 6px 14px 10px 14px; font-size: 12px; color: #f39c12; font-style: italic; }}

  /* Smell table */
  .smell-table {{ width: 100%; border-collapse: collapse; }}
  .smell-table th {{
    position: sticky; top: 0; background: #16213e; padding: 10px 12px;
    text-align: left; font-size: 12px; font-weight: 600; cursor: pointer; user-select: none;
    border-bottom: 2px solid #0f3460;
  }}
  .smell-table th:hover {{ background: #1a4d7a; }}
  .smell-table td {{ padding: 8px 12px; font-size: 13px; border-bottom: 1px solid rgba(255,255,255,.06); }}
  .smell-table tr:hover {{ background: rgba(0,212,255,.08); }}
  .sev-badge {{
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 10px; font-weight: 700; text-transform: uppercase;
  }}
  .sev-badge.critical {{ background: #e74c3c; }}
  .sev-badge.warning {{ background: #f39c12; color: #111; }}
  .sev-badge.info {{ background: #2ecc71; color: #111; }}
  .cat-cell {{ font-family: monospace; color: #00d4ff; }}
  .msg-cell {{ color: #aaa; font-size: 12px; max-width: 350px; }}
</style>
</head>
<body>

<div id="header">
  <h1>&#x1F50D; X-RAY Claude v{__version__} — {self._root_name}</h1>
  <div class="tab-bar">
    <button class="tab-btn active" onclick="showTab('graph')">&#x1F30D; Graph</button>
    <button class="tab-btn" onclick="showTab('dups')">&#x1F534; Duplicates</button>
    <button class="tab-btn" onclick="showTab('smells')">&#x1F9EA; Smells</button>
  </div>
</div>

<!-- ── Graph Panel ── -->
<div id="panel-graph" class="panel active">
  <div id="graph"></div>
  <div class="graph-legend">
    <div><span class="ldot" style="background:#2ecc71"></span>Healthy ({n_healthy})</div>
    <div><span class="ldot" style="background:#f39c12"></span>Warnings ({n_warning})</div>
    <div><span class="ldot" style="background:#e74c3c"></span>Critical ({n_critical})</div>
    <div style="margin-top:6px;color:#e67e22;font-size:11px">--- Duplicate links ({len(self.edges)})</div>
    <div style="margin-top:8px;color:#666;font-size:11px">Scroll to zoom &middot; Drag to pan</div>
  </div>
</div>

<!-- ── Duplicates Panel ── -->
<div id="panel-dups" class="panel list-panel">
  <div class="toolbar">
    <input class="search-input" id="dupSearch" placeholder="&#x1F50D; Search function name or file..." oninput="filterDups()">
    <span class="stat-chip exact" id="dupExactChip"></span>
    <span class="stat-chip near" id="dupNearChip"></span>
  </div>
  <div class="list-scroll" id="dupList"></div>
</div>

<!-- ── Smells Panel ── -->
<div id="panel-smells" class="panel list-panel">
  <div class="toolbar">
    <input class="search-input" id="smellSearch" placeholder="&#x1F50D; Search name, file, category..." oninput="filterSmells()">
    <span class="stat-chip crit" id="smCritChip"></span>
    <span class="stat-chip warn" id="smWarnChip"></span>
    <span class="stat-chip info" id="smInfoChip"></span>
  </div>
  <div class="list-scroll" id="smellList">
    <table class="smell-table">
      <thead><tr>
        <th onclick="sortSmells(0)">Sev</th>
        <th onclick="sortSmells(1)">Category</th>
        <th onclick="sortSmells(2)">Name</th>
        <th onclick="sortSmells(3)">File</th>
        <th onclick="sortSmells(4)">Line</th>
        <th onclick="sortSmells(5)">Issue</th>
      </tr></thead>
      <tbody id="smellBody"></tbody>
    </table>
  </div>
</div>

<script>
// ── Data ──
const nodesData = {nodes_json};
const edgesData = {edges_json};
const dupData   = {dup_json};
const smellData = {smell_json};

// ── Tab switching ──
function showTab(name) {{
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  const idx = {{'graph':0,'dups':1,'smells':2}}[name];
  document.querySelectorAll('.tab-btn')[idx].classList.add('active');
}}

// ── Graph ──
const container = document.getElementById('graph');
const network = new vis.Network(container,
  {{ nodes: new vis.DataSet(nodesData), edges: new vis.DataSet(edgesData) }},
  {{
    physics: {{ solver:'barnesHut', barnesHut:{{ gravitationalConstant:-3000, springLength:150, damping:.3 }} }},
    interaction: {{ hover:true, tooltipDelay:100 }},
    edges: {{ width:2, font:{{ size:10, color:'#888' }} }},
  }}
);

// ── Duplicates list ──
const dupExact = dupData.filter(g => g.type==='exact').length;
const dupNear  = dupData.filter(g => g.type==='near').length;
document.getElementById('dupExactChip').textContent = dupExact + ' exact';
document.getElementById('dupNearChip').textContent  = dupNear + ' near';

function renderDups(data) {{
  const el = document.getElementById('dupList');
  if (!data.length) {{ el.innerHTML = '<p style="padding:20px;color:#888">No duplicates match your search.</p>'; return; }}
  let html = '';
  data.forEach(g => {{
    const cls = g.type === 'near' ? 'near' : '';
    html += '<div class="dup-group ' + cls + '">';
    html += '<div class="dup-group-header">';
    html += '<span><span class="dup-type ' + g.type + '">' + g.type + '</span> &nbsp;Group #' + g.id + ' &mdash; ' + g.funcs.length + ' functions</span>';
    html += '<span class="dup-sim">' + g.sim + '% similar</span>';
    html += '</div>';
    html += '<div class="dup-funcs">';
    g.funcs.forEach(f => {{
      html += '<div class="dup-func"><span class="func-name">' + f.name + '</span><span class="func-file">' + f.file + ':' + f.line + '</span></div>';
    }});
    html += '</div>';
    if (g.merge) html += '<div class="dup-merge">&#x1F4A1; ' + g.merge + '</div>';
    html += '</div>';
  }});
  el.innerHTML = html;
}}
renderDups(dupData);

function filterDups() {{
  const q = document.getElementById('dupSearch').value.toLowerCase();
  if (!q) {{ renderDups(dupData); return; }}
  renderDups(dupData.filter(g => g.funcs.some(f => f.name.toLowerCase().includes(q) || f.file.toLowerCase().includes(q))));
}}

// ── Smells table ──
const smCrit = smellData.filter(s => s.sev==='critical').length;
const smWarn = smellData.filter(s => s.sev==='warning').length;
const smInfo = smellData.filter(s => s.sev==='info').length;
document.getElementById('smCritChip').textContent = smCrit + ' critical';
document.getElementById('smWarnChip').textContent = smWarn + ' warning';
document.getElementById('smInfoChip').textContent = smInfo + ' info';

let smellSorted = [...smellData];
const sevOrder = {{'critical':0,'warning':1,'info':2}};

function renderSmells(data) {{
  const tbody = document.getElementById('smellBody');
  if (!data.length) {{ tbody.innerHTML = '<tr><td colspan="6" style="padding:20px;color:#888">No smells match.</td></tr>'; return; }}
  tbody.innerHTML = data.map(s =>
    '<tr>' +
    '<td><span class="sev-badge ' + s.sev + '">' + s.sev + '</span></td>' +
    '<td class="cat-cell">' + s.cat + '</td>' +
    '<td style="font-weight:600">' + s.name + '</td>' +
    '<td style="color:#aaa;font-size:12px">' + s.file + '</td>' +
    '<td>' + s.line + '</td>' +
    '<td class="msg-cell">' + s.msg + '</td>' +
    '</tr>'
  ).join('');
}}
renderSmells(smellSorted);

let smellSortDir = {{}};
function sortSmells(col) {{
  const keys = ['sev','cat','name','file','line','msg'];
  const key = keys[col];
  const dir = smellSortDir[col] === 'asc' ? 'desc' : 'asc';
  smellSortDir = {{}}; smellSortDir[col] = dir;
  smellSorted.sort((a,b) => {{
    let av = key==='sev' ? sevOrder[a.sev] : (key==='line' ? a.line : a[key].toLowerCase());
    let bv = key==='sev' ? sevOrder[b.sev] : (key==='line' ? b.line : b[key].toLowerCase());
    if (av < bv) return dir==='asc' ? -1 : 1;
    if (av > bv) return dir==='asc' ? 1 : -1;
    return 0;
  }});
  renderSmells(smellSorted);
}}

function filterSmells() {{
  const q = document.getElementById('smellSearch').value.toLowerCase();
  if (!q) {{ renderSmells(smellSorted); return; }}
  renderSmells(smellSorted.filter(s => s.name.toLowerCase().includes(q) || s.file.toLowerCase().includes(q) || s.cat.toLowerCase().includes(q)));
}}
</script>
</body>
</html>"""
        output_path.write_text(html, encoding="utf-8")
        logger.info(f"Smart graph written to {output_path}")


# ─────────────────────────────────────────────────────────────────────────────
#  REPORT PRINTER
# ─────────────────────────────────────────────────────────────────────────────

def print_smell_report(smells: List[SmellIssue], summary: Dict[str, Any]):
    """Pretty-print the code smell report."""
    print(f"\n  {'='*58}")
    print(f"    CODE SMELL REPORT")
    print(f"  {'='*58}")
    print(f"    Total issues: {summary['total']}  "
          f"({Severity.icon(Severity.CRITICAL)} {summary['critical']}  "
          f"{Severity.icon(Severity.WARNING)} {summary['warning']}  "
          f"{Severity.icon(Severity.INFO)} {summary['info']})")
    print(f"  {SEP*58}")

    if not smells:
        print(f"    No code smells detected! Clean code.")
        print(f"  {'='*58}\n")
        return

    # Group by file
    by_file: Dict[str, List[SmellIssue]] = defaultdict(list)
    for s in smells:
        by_file[s.file_path].append(s)

    for fpath, file_smells in sorted(by_file.items()):
        n_cr = sum(1 for s in file_smells if s.severity == Severity.CRITICAL)
        n_wr = sum(1 for s in file_smells if s.severity == Severity.WARNING)
        n_in = sum(1 for s in file_smells if s.severity == Severity.INFO)
        counts = f"{Severity.icon(Severity.CRITICAL)}{n_cr} {Severity.icon(Severity.WARNING)}{n_wr} {Severity.icon(Severity.INFO)}{n_in}"
        print(f"\n    {fpath}  [{counts}]")
        for s in file_smells:
            icon = Severity.icon(s.severity)
            print(f"      {icon} L{s.line:>4d}  {s.category:<25s} {s.name}")
            print(f"              {s.message}")
            print(f"              -> {s.suggestion}")
            if s.llm_analysis:
                for line in textwrap.wrap(s.llm_analysis, 65):
                    print(f"              [AI] {line}")

    # Worst files
    if summary["worst_files"]:
        print(f"\n    WORST FILES (by issue count)")
        for fpath, count in sorted(summary["worst_files"].items(),
                                    key=lambda x: -x[1])[:5]:
            print(f"      {count:>3d} issues  {fpath}")

    # Category breakdown
    if summary["by_category"]:
        print(f"\n    CATEGORY BREAKDOWN")
        for cat, count in sorted(summary["by_category"].items(),
                                  key=lambda x: -x[1]):
            print(f"      {count:>3d}  {cat}")

    print(f"\n  {'='*58}\n")


def print_duplicate_report(groups: List[DuplicateGroup],
                           summary: Dict[str, Any]):
    """Pretty-print the duplicate finder report."""
    print(f"\n  {'='*58}")
    print(f"    SIMILAR FUNCTIONS REPORT")
    print(f"  {'='*58}")
    print(f"    Groups found:      {summary['total_groups']}")
    print(f"    Exact duplicates:  {summary['exact_duplicates']}")
    print(f"    Near duplicates:   {summary['near_duplicates']}")
    print(f"    Semantic matches:  {summary['semantic_duplicates']}")
    print(f"    Functions involved: {summary['total_functions_involved']}")
    print(f"  {SEP*58}")

    if not groups:
        print(f"    No duplicates detected!")
        print(f"  {'='*58}\n")
        return

    for group in groups[:20]:
        if group.similarity_type == "exact":
            type_icon = Severity.icon(Severity.CRITICAL)
        elif group.similarity_type == "semantic":
            type_icon = Severity.icon(Severity.INFO)
        else:
            type_icon = Severity.icon(Severity.WARNING)
        print(f"\n    {type_icon} Group #{group.group_id} [{group.similarity_type.upper()}] "
              f"(avg: {group.avg_similarity:.0%})")
        for func in group.functions:
            print(f"      {func['name']:<30s} {func['file']}:{func['line']}")
            if func.get("signature"):
                print(f"        {func['signature']}")
        if group.merge_suggestion:
            print(f"      [MERGE] {group.merge_suggestion}")

    if len(groups) > 20:
        print(f"\n    ... and {len(groups) - 20} more groups")

    print(f"\n  {'='*58}\n")


def print_library_report(suggestions: List[LibrarySuggestion],
                         summary: Dict[str, Any]):
    """Pretty-print the library extraction suggestions."""
    print(f"\n  {'='*58}")
    print(f"    LIBRARY EXTRACTION ADVISOR")
    print(f"  {'='*58}")
    print(f"    Suggestions:       {summary['total_suggestions']}")
    print(f"    Functions to merge: {summary['total_functions']}")
    print(f"    Proposed modules:  {', '.join(summary['modules_proposed'][:5])}")
    print(f"  {SEP*58}")

    if not suggestions:
        print(f"    No library extraction opportunities found.")
        print(f"  {'='*58}\n")
        return

    for i, sug in enumerate(suggestions[:15], 1):
        print(f"\n    {i}. Module: {sug.module_name}")
        print(f"       {sug.description}")
        print(f"       API: {sug.unified_api}")
        for func in sug.functions[:5]:
            print(f"         - {func['name']}  ({func['file']}:{func['line']})")
        if len(sug.functions) > 5:
            print(f"         ... +{len(sug.functions) - 5} more")
        print(f"       Rationale: {sug.rationale}")

    if len(suggestions) > 15:
        print(f"\n    ... and {len(suggestions) - 15} more suggestions")

    print(f"\n  {'='*58}\n")


# ─────────────────────────────────────────────────────────────────────────────
#  JSON REPORT
# ─────────────────────────────────────────────────────────────────────────────

def build_json_report(
    root: Path,
    functions: List[FunctionRecord],
    classes: List[ClassRecord],
    smells: List[SmellIssue],
    duplicates: List[DuplicateGroup],
    library_suggestions: List[LibrarySuggestion],
    scan_time: float,
) -> Dict[str, Any]:
    """Build a comprehensive JSON report."""
    return {
        "version": __version__,
        "timestamp": datetime.now().isoformat(),
        "root": str(root),
        "scan_time_seconds": round(scan_time, 2),
        "stats": {
            "total_functions": len(functions),
            "total_classes": len(classes),
            "total_files": len(set(f.file_path for f in functions)),
            "total_lines": sum(f.size_lines for f in functions),
            "avg_function_size": (
                round(sum(f.size_lines for f in functions) / len(functions), 1)
                if functions else 0
            ),
            "avg_complexity": (
                round(sum(f.complexity for f in functions) / len(functions), 1)
                if functions else 0
            ),
        },
        "smells": {
            "total": len(smells),
            "issues": [
                {
                    "file": s.file_path, "line": s.line,
                    "category": s.category, "severity": s.severity,
                    "name": s.name, "message": s.message,
                    "suggestion": s.suggestion,
                    "metric": s.metric_value,
                    "llm_analysis": s.llm_analysis or None,
                }
                for s in smells
            ],
        },
        "duplicates": {
            "total_groups": len(duplicates),
            "groups": [
                {
                    "id": g.group_id, "type": g.similarity_type,
                    "avg_similarity": g.avg_similarity,
                    "functions": g.functions,
                    "merge_suggestion": g.merge_suggestion or None,
                }
                for g in duplicates
            ],
        },
        "library_suggestions": {
            "total": len(library_suggestions),
            "suggestions": [
                {
                    "module": s.module_name,
                    "description": s.description,
                    "unified_api": s.unified_api,
                    "functions": s.functions,
                    "rationale": s.rationale,
                }
                for s in library_suggestions
            ],
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        prog="X_RAY_Claude",
        description="Smart AI-Powered Code Analyzer (X-Ray 4.0)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          python X_RAY_Claude.py --path .           # scan current dir
          python X_RAY_Claude.py --smell            # code smell detection
          python X_RAY_Claude.py --duplicates       # find similar functions
          python X_RAY_Claude.py --suggest-library  # library extraction advisor
          python X_RAY_Claude.py --full-scan        # run everything
          python X_RAY_Claude.py --full-scan --use-llm  # with LLM enrichment
        """),
    )
    p.add_argument("--path", type=str, default=None,
                   help="Project root to scan (default: directory of this script)")
    p.add_argument("--exclude", nargs="*", default=[],
                   help="Folder prefixes to skip")
    p.add_argument("--include", nargs="*", default=[],
                   help="Only scan these folder prefixes")

    # AI Features
    p.add_argument("--smell", action="store_true",
                   help="[AI] Detect code smells (long functions, god classes, deep nesting, etc.)")
    p.add_argument("--duplicates", action="store_true",
                   help="[AI] Find cross-file similar/duplicate functions")
    p.add_argument("--suggest-library", action="store_true",
                   help="[AI] Suggest shared library extraction from duplicates")
    p.add_argument("--full-scan", action="store_true",
                   help="[AI] Run all analysis features")
    p.add_argument("--graph", action="store_true",
                   help="Generate interactive health-colored code graph (HTML)")

    # LLM options
    p.add_argument("--use-llm", action="store_true",
                   help="Enable LLM enrichment for deeper analysis (requires local model)")
    p.add_argument("--model-path", type=str, default=None,
                   help="Path to GGUF model file for LLM enrichment")
    p.add_argument("--max-llm-calls", type=int, default=20,
                   help="Max LLM calls per feature (default: 20)")

    # Output
    p.add_argument("--report", type=str, metavar="FILE",
                   help="Save full JSON report to FILE")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress detailed output (only show summary)")

    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    print(BANNER)

    # Resolve root
    if args.path:
        root = Path(args.path).resolve()
    else:
        root = Path(__file__).parent.resolve()

    if not root.exists():
        print(f"  Error: Path {root} does not exist.")
        sys.exit(1)

    # If --full-scan, enable everything
    if args.full_scan:
        args.smell = True
        args.duplicates = True
        args.suggest_library = True
        args.graph = True

    # Default: if nothing specified, run smell + duplicates
    if not (args.smell or args.duplicates or args.suggest_library or args.graph):
        args.smell = True
        args.duplicates = True

    # LLM helper (lazy)
    llm = LLMHelper(root, model_path=getattr(args, 'model_path', None)) if args.use_llm else None

    start_time = time.time()

    # ── Step 1: Scan codebase ──
    print(f"  Scanning {root.name}/...")
    py_files = collect_py_files(root, args.exclude, args.include)
    total_files = len(py_files)
    all_functions: List[FunctionRecord] = []
    all_classes: List[ClassRecord] = []
    errors: List[str] = []
    done = 0

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_extract_functions_from_file, f, root): f
            for f in py_files
        }
        for future in concurrent.futures.as_completed(futures):
            funcs, clses, err = future.result()
            all_functions.extend(funcs)
            all_classes.extend(clses)
            if err:
                errors.append(f"{futures[future]}: {err}")
            done += 1
            if total_files > 20 and done % max(1, total_files // 10) == 0:
                pct = done * 100 // total_files
                print(f"    [{pct:3d}%] {done}/{total_files} files scanned...", flush=True)

    functions = all_functions
    classes = all_classes
    scan_time = time.time() - start_time

    print(f"  Found {len(functions)} functions, {len(classes)} classes "
          f"in {len(set(f.file_path for f in functions))} files "
          f"({scan_time:.2f}s)")
    if errors:
        print(f"  Skipped {len(errors)} files with errors")

    if not functions:
        print("  No functions found — nothing to analyze.")
        return

    # ── Step 2: Code Smell Detection ──
    smells: List[SmellIssue] = []
    smell_summary: Dict[str, Any] = {}
    if args.smell:
        print(f"\n  Running code smell detection...")
        detector = CodeSmellDetector()
        smells = detector.detect(functions, classes)
        smell_summary = detector.summary()

        if args.use_llm and llm:
            detector.enrich_with_llm(llm, args.max_llm_calls)

        if not args.quiet:
            print_smell_report(smells, smell_summary)
        else:
            print(f"    {Severity.icon(Severity.CRITICAL)} {smell_summary['critical']}  "
                  f"{Severity.icon(Severity.WARNING)} {smell_summary['warning']}  "
                  f"{Severity.icon(Severity.INFO)} {smell_summary['info']}")

    # ── Step 3: Duplicate Detection ──
    duplicates: List[DuplicateGroup] = []
    dup_summary: Dict[str, Any] = {}
    if args.duplicates:
        print(f"\n  Running duplicate detection...")
        finder = DuplicateFinder()
        duplicates = finder.find(functions, cross_file_only=True)
        dup_summary = finder.summary()

        if args.use_llm and llm:
            finder.enrich_with_llm(llm, functions, args.max_llm_calls)

        if not args.quiet:
            print_duplicate_report(duplicates, dup_summary)
        else:
            print(f"    {dup_summary['total_groups']} groups, "
                  f"{dup_summary['total_functions_involved']} functions")

    # ── Step 4: Library Extraction Advisor ──
    library_suggestions: List[LibrarySuggestion] = []
    lib_summary: Dict[str, Any] = {}
    if args.suggest_library:
        print(f"\n  Running library extraction analysis...")
        advisor = LibraryAdvisor()
        library_suggestions = advisor.analyze(duplicates, functions)
        lib_summary = advisor.summary()

        if args.use_llm and llm:
            advisor.enrich_with_llm(llm, functions, args.max_llm_calls)

        if not args.quiet:
            print_library_report(library_suggestions, lib_summary)
        else:
            print(f"    {lib_summary['total_suggestions']} suggestions")

    # ── Step 5: Smart Graph ──
    if args.graph:
        print(f"\n  Generating smart code graph...")
        graph = SmartGraph()
        graph.build(functions, smells, duplicates, root)
        graph_path = root / "xray_claude_graph.html"
        graph.write_html(graph_path)
        print(f"    Written to {graph_path}")

    # ── Step 6: JSON Report ──
    total_time = time.time() - start_time
    if args.report:
        report = build_json_report(
            root, functions, classes, smells, duplicates,
            library_suggestions, total_time,
        )
        report_path = Path(args.report)
        if not report_path.is_absolute():
            report_path = root / args.report
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n  JSON report saved to {report_path}")

    # ── Final Summary ──
    print(f"\n  {'='*58}")
    print(f"    SCAN COMPLETE ({total_time:.2f}s)")
    print(f"  {SEP*58}")
    print(f"    Files:      {len(set(f.file_path for f in functions)):>6}")
    print(f"    Functions:  {len(functions):>6}")
    print(f"    Classes:    {len(classes):>6}")
    if smells:
        print(f"    Smells:     {len(smells):>6}  "
              f"({Severity.icon(Severity.CRITICAL)}{smell_summary.get('critical', 0)} "
              f"{Severity.icon(Severity.WARNING)}{smell_summary.get('warning', 0)} "
              f"{Severity.icon(Severity.INFO)}{smell_summary.get('info', 0)})")
    if duplicates:
        print(f"    Duplicates: {len(duplicates):>6} groups  "
              f"(exact:{dup_summary.get('exact_duplicates',0)} "
              f"near:{dup_summary.get('near_duplicates',0)} "
              f"semantic:{dup_summary.get('semantic_duplicates',0)})")
    if library_suggestions:
        print(f"    Library:    {len(library_suggestions):>6} suggestions")
    print(f"    LLM:        {'enabled' if args.use_llm else 'disabled'}")
    print(f"  {'='*58}\n")


if __name__ == "__main__":
    main()
