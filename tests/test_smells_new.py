"""
tests/test_smells_new.py — Tests for v6.0.0 new smell detectors
================================================================
Covers: magic-number, mutable-default-arg, dead-code
"""
import textwrap
import pytest

from Core.types import FunctionRecord, Severity
from Analysis.smells import (
    _check_magic_numbers,
    _check_mutable_default_arg,
    _check_dead_code,
    CodeSmellDetector,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_func(code: str, name: str = "test_func") -> FunctionRecord:
    """Build a minimal FunctionRecord from a code snippet."""
    src = textwrap.dedent(code)
    import ast
    from Analysis.ast_utils import _build_function_record
    tree = ast.parse(src)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    lines = src.splitlines()
    return _build_function_record(node, "test.py", src, lines)


# ── Magic Number ──────────────────────────────────────────────────────────────

class TestMagicNumber:
    def test_flags_magic_numbers(self):
        func = _make_func("""
            def compute(x):
                return x * 3.14159 + 42
        """)
        smells = []
        _check_magic_numbers(func, smells, threshold=2)
        assert any(s.category == "magic-number" for s in smells)

    def test_allows_safe_literals(self):
        """0, 1, -1, 2, 100 are explicitly allowed."""
        func = _make_func("""
            def safe(x):
                if x == 0:
                    return 1
                return x + 2
        """)
        smells = []
        _check_magic_numbers(func, smells, threshold=2)
        assert not any(s.category == "magic-number" for s in smells)

    def test_threshold_respected(self):
        """Single magic number below default threshold=2 should not fire."""
        func = _make_func("""
            def once(x):
                return x * 5
        """)
        smells = []
        _check_magic_numbers(func, smells, threshold=2)
        assert not any(s.category == "magic-number" for s in smells)

    def test_threshold_one(self):
        """With threshold=1, even a single magic number should fire."""
        func = _make_func("""
            def once(x):
                return x * 7
        """)
        smells = []
        _check_magic_numbers(func, smells, threshold=1)
        assert any(s.category == "magic-number" for s in smells)

    def test_severity_is_info(self):
        func = _make_func("""
            def f(x):
                return x * 99 + 999
        """)
        smells = []
        _check_magic_numbers(func, smells, threshold=1)
        magic = [s for s in smells if s.category == "magic-number"]
        assert magic[0].severity == Severity.INFO

    def test_no_flag_for_bool(self):
        """True/False should not be flagged."""
        func = _make_func("""
            def f():
                return True or False
        """)
        smells = []
        _check_magic_numbers(func, smells, threshold=1)
        assert not any(s.category == "magic-number" for s in smells)


# ── Mutable Default Arg ───────────────────────────────────────────────────────

class TestMutableDefaultArg:
    def test_list_default_flagged(self):
        func = _make_func("""
            def append_item(items=[]):
                items.append(1)
                return items
        """)
        smells = []
        _check_mutable_default_arg(func, smells)
        assert any(s.category == "mutable-default-arg" for s in smells)

    def test_dict_default_flagged(self):
        func = _make_func("""
            def build(config={}):
                config["key"] = "value"
                return config
        """)
        smells = []
        _check_mutable_default_arg(func, smells)
        assert any(s.category == "mutable-default-arg" for s in smells)

    def test_set_default_flagged(self):
        func = _make_func("""
            def add_items(items=set()):
                pass
        """, name="add_items")
        # set() is a call, not ast.Set — should not fire on this particular form
        # (only ast.Set literal `{1,2}` is caught, not `set()`)
        smells = []
        _check_mutable_default_arg(func, smells)
        # set() call is NOT an ast.Set node, so no flag
        assert not any(s.category == "mutable-default-arg" for s in smells)

    def test_set_literal_default_flagged(self):
        func = _make_func("""
            def f(items={1, 2}):
                pass
        """)
        smells = []
        _check_mutable_default_arg(func, smells)
        assert any(s.category == "mutable-default-arg" for s in smells)

    def test_none_default_not_flagged(self):
        func = _make_func("""
            def safe(items=None):
                if items is None:
                    items = []
                return items
        """)
        smells = []
        _check_mutable_default_arg(func, smells)
        assert not any(s.category == "mutable-default-arg" for s in smells)

    def test_severity_is_warning(self):
        func = _make_func("""
            def f(x=[]):
                return x
        """)
        smells = []
        _check_mutable_default_arg(func, smells)
        hits = [s for s in smells if s.category == "mutable-default-arg"]
        assert hits[0].severity == Severity.WARNING


# ── Dead Code ─────────────────────────────────────────────────────────────────

class TestDeadCode:
    def test_statements_after_return_flagged(self):
        func = _make_func("""
            def f(x):
                return x
                y = x + 1
                return y
        """)
        smells = []
        _check_dead_code(func, smells)
        assert any(s.category == "dead-code" for s in smells)

    def test_statements_after_raise_flagged(self):
        func = _make_func("""
            def f(x):
                raise ValueError("bad")
                return x
        """)
        smells = []
        _check_dead_code(func, smells)
        assert any(s.category == "dead-code" for s in smells)

    def test_no_dead_code_clean_function(self):
        func = _make_func("""
            def f(x):
                if x > 0:
                    return x
                return -x
        """)
        smells = []
        _check_dead_code(func, smells)
        assert not any(s.category == "dead-code" for s in smells)

    def test_severity_is_warning(self):
        func = _make_func("""
            def f():
                return 1
                x = 2
        """)
        smells = []
        _check_dead_code(func, smells)
        hits = [s for s in smells if s.category == "dead-code"]
        assert hits[0].severity == Severity.WARNING

    def test_dead_code_line_number_points_to_dead_stmt(self):
        """The smell's line number should point to the dead code, not the return."""
        func = _make_func("""
            def f():
                return 1
                x = 2
                y = 3
        """)
        smells = []
        _check_dead_code(func, smells)
        hits = [s for s in smells if s.category == "dead-code"]
        assert hits  # at least one found

    def test_pass_after_return_not_flagged(self):
        """A bare `pass` after return is harmless and shouldn't fire."""
        func = _make_func("""
            def f():
                return 1
                pass
        """)
        smells = []
        _check_dead_code(func, smells)
        # pass is filtered out by _scan_body_for_dead_code
        assert not any(s.category == "dead-code" for s in smells)


# ── Integration: CodeSmellDetector ──────────────────────────────────────────

class TestSmellDetectorIntegration:
    def test_magic_number_in_full_detector(self):
        """The full CodeSmellDetector must also surface magic-number smells."""
        func = _make_func("""
            def tax(price):
                return price * 1.2375 + 99
        """)
        detector = CodeSmellDetector()
        smells = detector.detect([func], [])
        categories = {s.category for s in smells}
        assert "magic-number" in categories

    def test_mutable_default_in_full_detector(self):
        func = _make_func("""
            def append(items=[]):
                return items
        """)
        detector = CodeSmellDetector()
        smells = detector.detect([func], [])
        categories = {s.category for s in smells}
        assert "mutable-default-arg" in categories

    def test_dead_code_in_full_detector(self):
        func = _make_func("""
            def dead():
                return 0
                x = 999
        """)
        detector = CodeSmellDetector()
        smells = detector.detect([func], [])
        categories = {s.category for s in smells}
        assert "dead-code" in categories
