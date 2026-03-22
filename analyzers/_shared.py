"""
X-Ray LLM — Shared constants and helpers for analyzers package.
"""

import ast
import os

from xray.constants import PY_EXTS as _PY_EXTS  # noqa: F401 (re-export)
from xray.constants import SKIP_DIRS as _SKIP_DIRS
from xray.constants import TEXT_EXTS as _TEXT_EXTS  # noqa: F401 (re-export)
from xray.constants import WEB_EXTS as _WEB_EXTS  # noqa: F401 (re-export)
from xray.constants import fwd as _fwd  # noqa: F401 (re-export)


def _walk_py(directory: str):
    """Yield (filepath, relative_path) for all .py files."""
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if fname.endswith(".py"):
                fpath = os.path.join(dirpath, fname)
                rel = os.path.relpath(fpath, directory).replace("\\", "/")
                yield fpath, rel


def _walk_ext(directory: str, exts: set):
    """Yield (filepath, relative_path) for files with given extensions."""
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in exts:
                fpath = os.path.join(dirpath, fname)
                rel = os.path.relpath(fpath, directory).replace("\\", "/")
                yield fpath, rel


def _safe_parse(fpath: str):
    """Parse a Python file into AST, return None on failure."""
    try:
        with open(fpath, encoding="utf-8", errors="ignore") as f:
            return ast.parse(f.read(), filename=fpath)
    except (SyntaxError, ValueError, RecursionError):
        return None
