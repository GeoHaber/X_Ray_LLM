"""
Tests for Core/types.py — FunctionRecord, ClassRecord, SmellIssue,
DuplicateGroup, LibrarySuggestion, Severity.
"""
from Core.types import (
    FunctionRecord, ClassRecord, SmellIssue,
    DuplicateGroup, LibrarySuggestion, Severity,
)


# ── helpers ──────────────────────────────────────────────────────────

def _func(name="foo", file_path="utils/helpers.py", **overrides):
    defaults = dict(
        name=name, file_path=file_path,
        line_start=1, line_end=5, size_lines=5,
        parameters=["a", "b"], return_type="int",
        decorators=[], docstring="docstring",
        calls_to=["bar"], complexity=2, nesting_depth=1,
        code_hash="abc123", structure_hash="def456",
        code="def foo(a, b): return a + b",
        is_async=False,
    )
    defaults.update(overrides)
    return FunctionRecord(**defaults)


def _cls(name="MyClass", **overrides):
    defaults = dict(
        name=name, file_path="models.py",
        line_start=1, line_end=50, size_lines=50,
        method_count=3, base_classes=["Base"],
        docstring="A class", methods=["__init__", "run", "stop"],
        has_init=True,
    )
    defaults.update(overrides)
    return ClassRecord(**defaults)


# ════════════════════════════════════════════════════════════════════
#  FunctionRecord
# ════════════════════════════════════════════════════════════════════

class TestFunctionRecord:

    def test_key_uses_stem(self):
        """Core.types uses full path with / and :: separator."""
        f = _func(file_path="some/deep/utils.py", name="do_stuff")
        assert f.key == "some/deep/utils::do_stuff"

    def test_key_strips_extension(self):
        f = _func(file_path="app.py", name="main")
        assert f.key == "app::main"

    def test_key_windows_paths(self):
        f = _func(file_path="dir\\sub\\module.py", name="fn")
        assert f.key == "dir/sub/module::fn"

    def test_location(self):
        f = _func(file_path="foo.py", line_start=42)
        assert f.location == "foo.py:42"

    def test_signature_with_return(self):
        f = _func(parameters=["x", "y"], return_type="str")
        assert f.signature == "foo(x, y) -> str"

    def test_signature_without_return(self):
        f = _func(parameters=["x"], return_type=None)
        assert f.signature == "foo(x)"

    def test_signature_no_params(self):
        f = _func(parameters=[], return_type=None)
        assert f.signature == "foo()"

    def test_is_async_default_false(self):
        f = _func()
        assert f.is_async is False

    def test_is_async_true(self):
        f = _func(is_async=True)
        assert f.is_async is True

    def test_all_fields_stored(self):
        f = _func(decorators=["@staticmethod"], docstring="hello")
        assert f.decorators == ["@staticmethod"]
        assert f.docstring == "hello"
        assert f.complexity == 2
        assert f.nesting_depth == 1


# ════════════════════════════════════════════════════════════════════
#  ClassRecord
# ════════════════════════════════════════════════════════════════════

class TestClassRecord:

    def test_fields(self):
        c = _cls()
        assert c.name == "MyClass"
        assert c.has_init is True
        assert c.method_count == 3
        assert c.base_classes == ["Base"]

    def test_no_init(self):
        c = _cls(has_init=False, methods=["run"])
        assert c.has_init is False

    def test_multiple_bases(self):
        c = _cls(base_classes=["A", "B", "C"])
        assert len(c.base_classes) == 3


# ════════════════════════════════════════════════════════════════════
#  SmellIssue
# ════════════════════════════════════════════════════════════════════

class TestSmellIssue:

    def test_defaults(self):
        s = SmellIssue(
            file_path="f.py", line=1, end_line=10,
            category="long-function", severity=Severity.WARNING,
            message="too long", suggestion="split it",
            name="big_fn", metric_value=120,
        )
        assert s.llm_analysis == ""

    def test_llm_analysis_override(self):
        s = SmellIssue(
            file_path="f.py", line=1, end_line=10,
            category="x", severity="info",
            message="m", suggestion="s",
            name="n", metric_value=1,
            llm_analysis="Use early return",
        )
        assert s.llm_analysis == "Use early return"


# ════════════════════════════════════════════════════════════════════
#  DuplicateGroup
# ════════════════════════════════════════════════════════════════════

class TestDuplicateGroup:

    def test_defaults(self):
        g = DuplicateGroup(
            group_id=0, similarity_type="exact",
            avg_similarity=1.0, functions=[],
        )
        assert g.merge_suggestion == ""

    def test_with_suggestion(self):
        g = DuplicateGroup(
            group_id=1, similarity_type="structural",
            avg_similarity=0.95,
            functions=[{"key": "a.foo"}, {"key": "b.foo"}],
            merge_suggestion="Unify names",
        )
        assert len(g.functions) == 2


# ════════════════════════════════════════════════════════════════════
#  LibrarySuggestion
# ════════════════════════════════════════════════════════════════════

class TestLibrarySuggestion:

    def test_fields(self):
        lib = LibrarySuggestion(
            module_name="utils", description="Shared helpers",
            functions=[{"name": "do"}],
            unified_api="def do(x): ...",
            rationale="DRY",
        )
        assert lib.module_name == "utils"
        assert lib.rationale == "DRY"


# ════════════════════════════════════════════════════════════════════
#  Severity
# ════════════════════════════════════════════════════════════════════

class TestSeverity:

    def test_constants(self):
        assert Severity.CRITICAL == "critical"
        assert Severity.WARNING == "warning"
        assert Severity.INFO == "info"

    def test_icon_returns_string(self):
        icon = Severity.icon("critical")
        assert isinstance(icon, str)
        assert len(icon) > 0

    def test_icon_warning(self):
        icon = Severity.icon("warning")
        assert isinstance(icon, str)

    def test_icon_info(self):
        icon = Severity.icon("info")
        assert isinstance(icon, str)

    def test_icon_unknown_returns_question_mark(self):
        assert Severity.icon("nonexistent") == "?"
