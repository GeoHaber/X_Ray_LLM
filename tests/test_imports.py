import importlib
import pytest

def test_imports():
    """Verify that affected modules can be imported without crashing (broken singletons fixed)."""
    modules_to_test = [
        "_mothership.models",
        "Analysis.tracer",
        "Analysis.ui_compat",
        "Analysis.ui_health",
        "Analysis.verification",
    ]
    
    for module_name in modules_to_test:
        try:
            importlib.import_module(module_name)
        except Exception as e:
            pytest.fail(f"Failed to import {module_name}: {e}")
