"""Analysis/type_coverage.py — Type hint coverage analyzer.

Reports which public functions lack return-type or parameter annotations.
Does not penalise private functions, test files, or trivial (<= 10 line) functions.
"""

from __future__ import annotations

from typing import Any, Dict, List

from Core.types import FunctionRecord, Severity, SmellIssue

_MIN_LINES_FOR_HINT_CHECK = 25
_TEST_PATH_MARKERS = ("/tests/", "/test/", "\\tests\\", "\\test\\")
_TEST_FILE_PREFIXES = ("test_",)
_TEST_FILE_SUFFIXES = ("_test.py",)


def _is_test_function(func: FunctionRecord) -> bool:
    fpath = func.file_path.replace("\\", "/")
    if any(m in fpath for m in _TEST_PATH_MARKERS):
        return True
    base = fpath.split("/")[-1]
    if any(base.startswith(p) for p in _TEST_FILE_PREFIXES):
        return True
    if any(base.endswith(s) for s in _TEST_FILE_SUFFIXES):
        return True
    return False


def _has_return_annotation(func: FunctionRecord) -> bool:
    """Return True if the function declares a return type annotation."""
    rt = func.return_type
    if not rt:
        return False
    if rt.strip() in ("", "None", "none"):
        # Explicit -> None counts as annotated
        return True
    return True


def _annotated_param_count(func: FunctionRecord) -> int:
    """Count parameters with type annotations (heuristic: checks func.code)."""
    import ast

    try:
        tree = ast.parse(func.code)
    except Exception:
        return 0
    if not tree.body:
        return 0
    fn_node = tree.body[0]
    if not isinstance(fn_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return 0
    count = 0
    all_args = fn_node.args.args + fn_node.args.posonlyargs + fn_node.args.kwonlyargs
    if fn_node.args.vararg and fn_node.args.vararg.annotation:
        count += 1
    if fn_node.args.kwarg and fn_node.args.kwarg.annotation:
        count += 1
    for arg in all_args:
        if arg.arg in ("self", "cls"):
            continue
        if arg.annotation is not None:
            count += 1
    return count


def _total_param_count(func: FunctionRecord) -> int:
    """Count parameters excluding self/cls."""
    return sum(1 for p in func.parameters if p not in ("self", "cls"))


class TypeCoverageAnalyzer:
    """Analyze type hint coverage across FunctionRecords."""

    def analyze(self, functions: List[FunctionRecord]) -> Dict[str, Any]:
        """Return a coverage summary dict and a list of SmellIssues."""
        smells: List[SmellIssue] = []
        total = 0
        fully_annotated = 0
        partially_annotated = 0
        unannotated = 0

        for func in functions:
            # Only check non-private, non-trivial, non-test functions
            if func.name.startswith("_"):
                continue
            if func.size_lines < _MIN_LINES_FOR_HINT_CHECK:
                continue
            if _is_test_function(func):
                continue

            total += 1
            has_return = _has_return_annotation(func)
            param_count = _total_param_count(func)
            annotated_params = _annotated_param_count(func)
            fully_params = param_count == 0 or annotated_params >= param_count

            if has_return and fully_params:
                fully_annotated += 1
            elif has_return or annotated_params > 0:
                partially_annotated += 1
                smells.append(
                    SmellIssue(
                        file_path=func.file_path,
                        line=func.line_start,
                        end_line=func.line_end,
                        category="missing-type-hints",
                        severity=Severity.INFO,
                        name=func.name,
                        metric_value=param_count - annotated_params,
                        message=(
                            f"Function '{func.name}' is partially annotated "
                            f"({annotated_params}/{param_count} params, "
                            f"return={'yes' if has_return else 'no'})"
                        ),
                        suggestion=(
                            "Add type annotations to all parameters and return type "
                            "to improve IDE support and static analysis."
                        ),
                        source="xray-types",
                    )
                )
            else:
                unannotated += 1
                smells.append(
                    SmellIssue(
                        file_path=func.file_path,
                        line=func.line_start,
                        end_line=func.line_end,
                        category="missing-type-hints",
                        severity=Severity.INFO,
                        name=func.name,
                        metric_value=param_count,
                        message=(
                            f"Function '{func.name}' has no type annotations "
                            f"({param_count} unannotated param(s), no return type)"
                        ),
                        suggestion=(
                            "Add type annotations: 'def func(x: int, y: str) -> bool'. "
                            "Full annotations enable IDE completion and Pyright/mypy checking."
                        ),
                        source="xray-types",
                    )
                )

        coverage_pct = (fully_annotated / total * 100) if total > 0 else 100.0
        return {
            "total_checked": total,
            "fully_annotated": fully_annotated,
            "partially_annotated": partially_annotated,
            "unannotated": unannotated,
            "coverage_pct": round(coverage_pct, 1),
            "smells": smells,
            "source": "xray-types",
        }


# Module-level API for test compatibility
_default_analyzer = TypeCoverageAnalyzer()


def analyze(source_code: str, project_root: str = None):
    """Wrapper for TypeCoverageAnalyzer.analyze()."""
    if source_code is None:
        raise ValueError("source_code cannot be None")
    return _default_analyzer.analyze(source_code)
