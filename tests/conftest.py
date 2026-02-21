
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

def make_func(name="foo", file_path="test.py", size_lines=10,
              complexity=1, code=None, **kw):
    """Create a FunctionRecord with sensible defaults for tests.

    Accepts any extra keyword arguments and forwards them to FunctionRecord
    so callers can override any field (e.g. return_count, branch_count).
    """
    if code is None:
        code = f"def {name}(): pass"
    line_start = kw.pop('line_start', 1)
    defaults = dict(
        name=name,
        file_path=file_path,
        line_start=line_start,
        line_end=line_start + size_lines - 1,
        size_lines=size_lines,
        parameters=kw.pop('parameters', []),
        return_type=kw.pop('return_type', None),
        decorators=kw.pop('decorators', []),
        docstring=kw.pop('docstring', 'doc'),
        calls_to=kw.pop('calls_to', []),
        complexity=complexity,
        nesting_depth=kw.pop('nesting_depth', 0),
        code_hash=kw.pop('code_hash', 'h'),
        structure_hash=kw.pop('structure_hash', 's'),
        code=code,
        is_async=kw.pop('is_async', False),
    )
    defaults.update(kw)
    return FunctionRecord(**defaults)


def make_cls(name="Cls", file_path="test.py", size_lines=50,
             method_count=3, **kw):
    """Create a ClassRecord with sensible defaults for tests."""
    line_start = kw.pop('line_start', 1)
    defaults = dict(
        name=name,
        file_path=file_path,
        line_start=line_start,
        line_end=line_start + size_lines - 1,
        size_lines=size_lines,
        method_count=method_count,
        base_classes=kw.pop('base_classes', ["object"]),
        docstring=kw.pop('docstring', 'doc'),
        methods=kw.pop('methods', ["__init__", "run"]),
        has_init=kw.pop('has_init', True),
    )
    defaults.update(kw)
    return ClassRecord(**defaults)
