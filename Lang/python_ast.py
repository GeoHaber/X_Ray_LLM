"""
Lang/python_ast.py — Thin wrapper around Analysis.ast_utils
=============================================================

This module re-exports the canonical extraction/scanning functions
so that any code importing from ``Lang.python_ast`` keeps working
without carrying duplicate implementations.
"""

from pathlib import Path
from typing import List, Tuple

from Core.types import FunctionRecord, ClassRecord
from Analysis.ast_utils import (
    ASTNormalizer,                       # noqa: F401  re-export for backward compatibility
    _compute_structure_hash,             # noqa: F401  re-export for backward compatibility
    collect_py_files,                    # noqa: F401  re-export for backward compatibility
    extract_functions_from_file,         # canonical extractor
    )

# Legacy alias — old callers used the private name
_extract_functions_from_file = extract_functions_from_file


def scan_codebase(root: Path, exclude: List[str] = None,
                  include: List[str] = None) -> Tuple[
        List[FunctionRecord], List[ClassRecord], List[str]]:
    """Parallel-scan the codebase, returning functions, classes, and errors.

    Delegates to ``Core.scan_phases.scan_codebase`` which is the canonical
    implementation.
    """
    from Core.scan_phases import scan_codebase as _scan
    return _scan(root, exclude=exclude, include=include)
