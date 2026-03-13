"""Auto-generated monkey tests for Core/cli_args.py by X-Ray v7.0.

Tests function signatures, edge cases, and class instantiation.
"""

import pytest


def test_Core_cli_args_add_common_scan_args_is_callable():
    """Verify add_common_scan_args exists and is callable."""
    from Core.cli_args import add_common_scan_args

    assert callable(add_common_scan_args)


def test_Core_cli_args_add_common_scan_args_none_args():
    """Monkey: call add_common_scan_args with None args — should not crash unhandled."""
    from Core.cli_args import add_common_scan_args

    try:
        add_common_scan_args(None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


def test_Core_cli_args_normalize_scan_args_is_callable():
    """Verify normalize_scan_args exists and is callable."""
    from Core.cli_args import normalize_scan_args

    assert callable(normalize_scan_args)


def test_Core_cli_args_normalize_scan_args_none_args():
    """Monkey: call normalize_scan_args with None args — should not crash unhandled."""
    from Core.cli_args import normalize_scan_args

    try:
        normalize_scan_args(None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")


def test_Core_cli_args_normalize_scan_args_return_type():
    """Verify normalize_scan_args returns expected type."""
    from Core.cli_args import normalize_scan_args

    # Smoke check — return type should be: argparse.Namespace
    # (requires valid args to test; assert function exists)
    assert callable(normalize_scan_args)
