"""Auto-generated monkey tests for Analysis/ui_compat.py by X-Ray v7.0.

Tests function signatures, edge cases, and class instantiation.
"""

import pytest



def test_Analysis_ui_compat___init___is_callable():
    """Verify __init__ exists and is callable."""
    from Analysis.ui_compat import __init__
    assert callable(__init__)

def test_Analysis_ui_compat___init___none_args():
    """Monkey: call __init__ with None args — should not crash unhandled."""
    from Analysis.ui_compat import __init__
    try:
        __init__(None, None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")



def test_Analysis_ui_compat___init___is_callable():
    """Verify __init__ exists and is callable."""
    from Analysis.ui_compat import __init__
    assert callable(__init__)















def test_Analysis_ui_compat_main_is_callable():
    """Verify main exists and is callable."""
    from Analysis.ui_compat import main
    assert callable(main)

def test_Analysis_ui_compat_UICallSite_is_class():
    """Verify UICallSite exists and is a class."""
    from Analysis.ui_compat import UICallSite
    assert isinstance(UICallSite, type) or callable(UICallSite)

def test_Analysis_ui_compat_UICompatIssue_is_class():
    """Verify UICompatIssue exists and is a class."""
    from Analysis.ui_compat import UICompatIssue
    assert isinstance(UICompatIssue, type) or callable(UICompatIssue)

def test_Analysis_ui_compat_UICompatIssue_has_methods():
    """Verify UICompatIssue has expected methods."""
    from Analysis.ui_compat import UICompatIssue
    expected = ["to_smell"]
    for method in expected:
        assert hasattr(UICompatIssue, method), f"Missing method: {method}"

def test_Analysis_ui_compat_UICompatAnalyzer_is_class():
    """Verify UICompatAnalyzer exists and is a class."""
    from Analysis.ui_compat import UICompatAnalyzer
    assert isinstance(UICompatAnalyzer, type) or callable(UICompatAnalyzer)

def test_Analysis_ui_compat_UICompatAnalyzer_has_methods():
    """Verify UICompatAnalyzer has expected methods."""
    from Analysis.ui_compat import UICompatAnalyzer
    expected = ["__init__", "analyze", "analyze_tree", "analyze_to_smells", "summary", "print_report"]
    for method in expected:
        assert hasattr(UICompatAnalyzer, method), f"Missing method: {method}"
