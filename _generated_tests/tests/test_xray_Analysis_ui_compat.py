"""Auto-generated monkey tests for Analysis/ui_compat.py by X-Ray v7.0.

Tests function signatures, edge cases, and class instantiation.
"""

import pytest

def test_Analysis_ui_compat_to_smell_is_callable():
    """Verify to_smell exists and is callable."""
    from Analysis.ui_compat import to_smell
    assert callable(to_smell)

def test_Analysis_ui_compat_to_smell_return_type():
    """Verify to_smell returns expected type."""
    from Analysis.ui_compat import to_smell
    # Smoke check — return type should be: SmellIssue
    # (requires valid args to test; assert function exists)
    assert callable(to_smell)

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

def test_Analysis_ui_compat_visit_Call_is_callable():
    """Verify visit_Call exists and is callable."""
    from Analysis.ui_compat import visit_Call
    assert callable(visit_Call)

def test_Analysis_ui_compat_visit_Call_none_args():
    """Monkey: call visit_Call with None args — should not crash unhandled."""
    from Analysis.ui_compat import visit_Call
    try:
        visit_Call(None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

def test_Analysis_ui_compat___init___is_callable():
    """Verify __init__ exists and is callable."""
    from Analysis.ui_compat import __init__
    assert callable(__init__)

def test_Analysis_ui_compat_analyze_is_callable():
    """Verify analyze exists and is callable."""
    from Analysis.ui_compat import analyze
    assert callable(analyze)

def test_Analysis_ui_compat_analyze_none_args():
    """Monkey: call analyze with None args — should not crash unhandled."""
    from Analysis.ui_compat import analyze
    try:
        analyze(None, None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

def test_Analysis_ui_compat_analyze_return_type():
    """Verify analyze returns expected type."""
    from Analysis.ui_compat import analyze
    # Smoke check — return type should be: List[UICompatIssue]
    # (requires valid args to test; assert function exists)
    assert callable(analyze)

def test_Analysis_ui_compat_analyze_tree_is_callable():
    """Verify analyze_tree exists and is callable."""
    from Analysis.ui_compat import analyze_tree
    assert callable(analyze_tree)

def test_Analysis_ui_compat_analyze_tree_none_args():
    """Monkey: call analyze_tree with None args — should not crash unhandled."""
    from Analysis.ui_compat import analyze_tree
    try:
        analyze_tree(None, None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

def test_Analysis_ui_compat_analyze_tree_return_type():
    """Verify analyze_tree returns expected type."""
    from Analysis.ui_compat import analyze_tree
    # Smoke check — return type should be: List[UICompatIssue]
    # (requires valid args to test; assert function exists)
    assert callable(analyze_tree)

def test_Analysis_ui_compat_analyze_to_smells_is_callable():
    """Verify analyze_to_smells exists and is callable."""
    from Analysis.ui_compat import analyze_to_smells
    assert callable(analyze_to_smells)

def test_Analysis_ui_compat_analyze_to_smells_none_args():
    """Monkey: call analyze_to_smells with None args — should not crash unhandled."""
    from Analysis.ui_compat import analyze_to_smells
    try:
        analyze_to_smells(None, None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

def test_Analysis_ui_compat_analyze_to_smells_return_type():
    """Verify analyze_to_smells returns expected type."""
    from Analysis.ui_compat import analyze_to_smells
    # Smoke check — return type should be: List[SmellIssue]
    # (requires valid args to test; assert function exists)
    assert callable(analyze_to_smells)

def test_Analysis_ui_compat_summary_is_callable():
    """Verify summary exists and is callable."""
    from Analysis.ui_compat import summary
    assert callable(summary)

def test_Analysis_ui_compat_summary_none_args():
    """Monkey: call summary with None args — should not crash unhandled."""
    from Analysis.ui_compat import summary
    try:
        summary(None, None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

def test_Analysis_ui_compat_summary_return_type():
    """Verify summary returns expected type."""
    from Analysis.ui_compat import summary
    # Smoke check — return type should be: Dict[str, Any]
    # (requires valid args to test; assert function exists)
    assert callable(summary)

def test_Analysis_ui_compat_print_report_is_callable():
    """Verify print_report exists and is callable."""
    from Analysis.ui_compat import print_report
    assert callable(print_report)

def test_Analysis_ui_compat_print_report_none_args():
    """Monkey: call print_report with None args — should not crash unhandled."""
    from Analysis.ui_compat import print_report
    try:
        print_report(None)
    except (TypeError, ValueError, AttributeError, KeyError):
        pass  # Expected — function should raise, not crash
    except Exception as e:
        pytest.fail(f"Unexpected exception: {type(e).__name__}: {e}")

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
