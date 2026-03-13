"""Auto-generated monkey tests for Analysis/typecheck.py by X-Ray v7.0.

Tests function signatures, edge cases, and class instantiation.
"""


def test_Analysis_typecheck_TypecheckAnalyzer_is_class():
    """Verify TypecheckAnalyzer exists and is a class."""
    from Analysis.typecheck import TypecheckAnalyzer

    assert isinstance(TypecheckAnalyzer, type) or callable(TypecheckAnalyzer)


def test_Analysis_typecheck_TypecheckAnalyzer_inheritance():
    """Verify TypecheckAnalyzer inherits from expected bases."""
    from Analysis.typecheck import TypecheckAnalyzer

    base_names = [b.__name__ for b in TypecheckAnalyzer.__mro__]
    for base in ["BaseStaticAnalyzer"]:
        assert base in base_names, f"Missing base: {base}"
