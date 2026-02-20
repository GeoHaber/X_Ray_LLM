"""
Lang/python_ast.py — Thin wrapper around Analysis.ast_utils
=============================================================

This module re-exports the canonical extraction/scanning functions
so that any code importing from ``Lang.python_ast`` keeps working
without carrying duplicate implementations.
"""

import concurrent.futures
from pathlib import Path
from typing import List, Tuple

from Core.types import FunctionRecord, ClassRecord
from Analysis.ast_utils import (
    ASTNormalizer,                       # noqa: F401  re-export for backward compatibility
    _compute_structure_hash,             # noqa: F401  re-export for backward compatibility
    extract_functions_from_file,         # canonical extractor
    collect_py_files,                    # canonical file walker
)

# Legacy alias — old callers used the private name
_extract_functions_from_file = extract_functions_from_file


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
            executor.submit(extract_functions_from_file, f, root): f
            for f in py_files
        }
        for future in concurrent.futures.as_completed(futures):
            funcs, clses, err = future.result()
            all_functions.extend(funcs)
            all_classes.extend(clses)
            if err:
                errors.append(f"{futures[future]}: {err}")

    return all_functions, all_classes, errors
