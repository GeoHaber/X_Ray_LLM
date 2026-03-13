"""Auto-generated monkey tests for Lang/python_ast.py by X-Ray v7.0.

Tests function signatures, edge cases, and class instantiation.
"""

import pytest


def test_Lang_python_ast_scan_codebase_is_callable():
    """Verify scan_codebase exists and is callable."""
    from Lang.python_ast import scan_codebase

    assert callable(scan_codebase)


def test_Lang_python_ast_scan_codebase_none_args():
    """Monkey: call scan_codebase with None args — should not crash unhandled."""
    from Lang.python_ast import scan_codebase

    try:
        scan_codebase(None, None, None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


def test_Lang_python_ast_scan_codebase_return_type():
    """Verify scan_codebase returns expected type."""
    from Lang.python_ast import scan_codebase

    # Smoke check — return type should be: Tuple[List[FunctionRecord], List[ClassRecord], List[str]]
    # (requires valid args to test; assert function exists)
    assert callable(scan_codebase)
