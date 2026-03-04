"""Auto-generated smell regression tests by X-Ray v7.0.

These tests verify that known code smells are acknowledged.
If a smell disappears (fixed), the test should be updated.
"""

import ast
from pathlib import Path


def _count_lines(filepath, func_name):
    """Count lines of a function by name using AST."""
    source = Path(filepath).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return node.end_lineno - node.lineno + 1
    return 0

def test_smell_regression_ProjectHealthAnalyzer_god_class():
    """Regression: ProjectHealthAnalyzer in Analysis/project_health.py — god class (16 methods)."""
    source = Path("Analysis/project_health.py").read_text(encoding="utf-8")
    assert "ProjectHealthAnalyzer" in source, "Class should still exist"

def test_smell_regression__gen_module_tests_long_function():
    """Regression: _gen_module_tests in Analysis/test_generator.py is 151 lines (limit ~60)."""
    size = _count_lines("Analysis/test_generator.py", "_gen_module_tests")
    # Originally 151 lines — track if it grows or gets refactored
    assert size > 0, "Function _gen_module_tests should still exist"
    # Uncomment to enforce size limit:
    # assert size <= 60, f"_gen_module_tests is {size} lines — refactor needed"

def test_smell_regression_IRBuilder_god_class():
    """Regression: IRBuilder in Analysis/transpiler.py — god class (55 methods)."""
    source = Path("Analysis/transpiler.py").read_text(encoding="utf-8")
    assert "IRBuilder" in source, "Class should still exist"

def test_smell_regression_build_function_long_function():
    """Regression: build_function in Analysis/transpiler.py is 157 lines (limit ~60)."""
    size = _count_lines("Analysis/transpiler.py", "build_function")
    # Originally 157 lines — track if it grows or gets refactored
    assert size > 0, "Function build_function should still exist"
    # Uncomment to enforce size limit:
    # assert size <= 60, f"build_function is {size} lines — refactor needed"

def test_smell_regression_build_function_deep_nesting():
    """Regression: build_function — deep-nesting (metric=12)."""
    source = Path("Analysis/transpiler.py").read_text(encoding="utf-8")
    assert "def build_function" in source or "async def build_function" in source

def test_smell_regression_WebSmellDetector_god_class():
    """Regression: WebSmellDetector in Analysis/web_smells.py — god class (16 methods)."""
    source = Path("Analysis/web_smells.py").read_text(encoding="utf-8")
    assert "WebSmellDetector" in source, "Class should still exist"

def test_smell_regression__find_matching_brace_deep_nesting():
    """Regression: _find_matching_brace — deep-nesting (metric=7)."""
    source = Path("Lang/js_ts_analyzer.py").read_text(encoding="utf-8")
    assert "def _find_matching_brace" in source or "async def _find_matching_brace" in source
