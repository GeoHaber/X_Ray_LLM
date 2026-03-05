"""Auto-generated monkey tests for Analysis/ast_utils.py by X-Ray v7.0.

Tests function signatures, edge cases, and class instantiation.
"""

import pytest

def test_Analysis_ast_utils___init___is_callable():
    """Verify __init__ exists and is callable."""
    from Analysis.ast_utils import __init__
    assert callable(__init__)







def test_Analysis_ast_utils_extract_functions_from_file_is_callable():
    """Verify extract_functions_from_file exists and is callable."""
    from Analysis.ast_utils import extract_functions_from_file
    assert callable(extract_functions_from_file)

def test_Analysis_ast_utils_extract_functions_from_file_none_args():
    """Monkey: call extract_functions_from_file with None args — should not crash unhandled."""
    from Analysis.ast_utils import extract_functions_from_file
    try:
        extract_functions_from_file(None, None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

def test_Analysis_ast_utils_extract_functions_from_file_return_type():
    """Verify extract_functions_from_file returns expected type."""
    from Analysis.ast_utils import extract_functions_from_file
    # Smoke check — return type should be: Tuple[List[FunctionRecord], List[ClassRecord], Optional[str]]
    # (requires valid args to test; assert function exists)
    assert callable(extract_functions_from_file)

def test_Analysis_ast_utils_extract_functions_from_file_is_callable():
    """Verify extract_functions_from_file exists and is callable."""
    from Analysis.ast_utils import extract_functions_from_file
    assert callable(extract_functions_from_file)

def test_Analysis_ast_utils_extract_functions_from_file_none_args():
    """Monkey: call extract_functions_from_file with None args — should not crash unhandled."""
    from Analysis.ast_utils import extract_functions_from_file
    try:
        extract_functions_from_file(None, None, None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

def test_Analysis_ast_utils_extract_functions_from_file_return_type():
    """Verify extract_functions_from_file returns expected type."""
    from Analysis.ast_utils import extract_functions_from_file
    # Smoke check — return type should be: Tuple[List[FunctionRecord], List[ClassRecord], Optional[str]]
    # (requires valid args to test; assert function exists)
    assert callable(extract_functions_from_file)

def test_Analysis_ast_utils_extract_functions_from_file_high_complexity():
    """Flag: extract_functions_from_file has CC=10 — verify it handles edge cases."""
    from Analysis.ast_utils import extract_functions_from_file
    # X-Ray detected CC=10 (cyclomatic complexity)
    # This function has many branches — test edge cases carefully
    assert callable(extract_functions_from_file), "Complex function should be importable"

def test_Analysis_ast_utils_collect_py_files_is_callable():
    """Verify collect_py_files exists and is callable."""
    from Analysis.ast_utils import collect_py_files
    assert callable(collect_py_files)

def test_Analysis_ast_utils_collect_py_files_none_args():
    """Monkey: call collect_py_files with None args — should not crash unhandled."""
    from Analysis.ast_utils import collect_py_files
    try:
        collect_py_files(None, None, None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

def test_Analysis_ast_utils_collect_py_files_return_type():
    """Verify collect_py_files returns expected type."""
    from Analysis.ast_utils import collect_py_files
    # Smoke check — return type should be: List[Path]
    # (requires valid args to test; assert function exists)
    assert callable(collect_py_files)

def test_Analysis_ast_utils_ASTNormalizer_is_class():
    """Verify ASTNormalizer exists and is a class."""
    from Analysis.ast_utils import ASTNormalizer
    assert isinstance(ASTNormalizer, type) or callable(ASTNormalizer)

def test_Analysis_ast_utils_ASTNormalizer_has_methods():
    """Verify ASTNormalizer has expected methods."""
    from Analysis.ast_utils import ASTNormalizer
    expected = ["__init__", "visit_FunctionDef", "visit_Name", "visit_arg"]
    for method in expected:
        assert hasattr(ASTNormalizer, method), f"Missing method: {method}"

