import sys
from pathlib import Path

# Add project root (one level up from tests/) to sys.path
# This ensures that "import Core.types" works regardless of CWD
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
    print(f"Added {project_root} to sys.path")

from Core.types import FunctionRecord, ClassRecord  # noqa: E402


# ── Shared test factories ────────────────────────────────────────────────────


def make_func(
    name="foo", file_path="test.py", size_lines=10, complexity=1, code=None, **kw
):
    """Create a FunctionRecord with sensible defaults for tests.

    Accepts any extra keyword arguments and forwards them to FunctionRecord.
    When code is provided and return_count/branch_count are not in kw,
    they are auto-computed from the AST.
    """
    import ast as _ast
    import hashlib

    if code is None:
        code = f"def {name}(): pass"
    if "return_count" not in kw and "branch_count" not in kw:
        try:
            _tree = _ast.parse(code)
            kw["return_count"] = sum(
                1 for n in _ast.walk(_tree) if isinstance(n, _ast.Return)
            )
            kw["branch_count"] = sum(
                1 for n in _ast.walk(_tree) if isinstance(n, _ast.If)
            )
        except SyntaxError:
            kw.setdefault("return_count", 0)
            kw.setdefault("branch_count", 0)
    if "code_hash" not in kw:
        kw["code_hash"] = hashlib.sha256(code.encode()).hexdigest()
    if "structure_hash" not in kw:
        kw["structure_hash"] = hashlib.sha256(code.encode()).hexdigest()
    line_start = kw.pop("line_start", 1)
    defaults = dict(
        name=name,
        file_path=file_path,
        line_start=line_start,
        line_end=line_start + size_lines - 1,
        size_lines=size_lines,
        parameters=kw.pop("parameters", []),
        return_type=kw.pop("return_type", None),
        decorators=kw.pop("decorators", []),
        docstring=kw.pop("docstring", "doc"),
        calls_to=kw.pop("calls_to", []),
        complexity=complexity,
        nesting_depth=kw.pop("nesting_depth", 0),
        code_hash=kw.pop("code_hash"),
        structure_hash=kw.pop("structure_hash"),
        code=code,
        is_async=kw.pop("is_async", False),
    )
    defaults.update(kw)
    return FunctionRecord(**defaults)


def make_cls(name="Cls", file_path="test.py", size_lines=50, method_count=3, **kw):
    """Create a ClassRecord with sensible defaults for tests."""
    line_start = kw.pop("line_start", 1)
    defaults = dict(
        name=name,
        file_path=file_path,
        line_start=line_start,
        line_end=line_start + size_lines - 1,
        size_lines=size_lines,
        method_count=method_count,
        base_classes=kw.pop("base_classes", ["object"]),
        docstring=kw.pop("docstring", "doc"),
        methods=kw.pop("methods", ["__init__", "run"]),
        has_init=kw.pop("has_init", True),
    )
    defaults.update(kw)
    return ClassRecord(**defaults)
