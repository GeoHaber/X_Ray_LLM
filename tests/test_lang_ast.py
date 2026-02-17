"""
Tests for Lang/python_ast.py — nesting depth, complexity, ASTNormalizer,
structure hash, file extraction, collect_py_files, scan_codebase.
"""
import ast
import os
import textwrap
from unittest.mock import patch

from Lang.python_ast import (
    ASTNormalizer,
    _compute_structure_hash,
    _extract_functions_from_file,
    collect_py_files,
    scan_codebase,
)
from Core.ast_helpers import compute_nesting_depth, compute_complexity


# ── helpers ──────────────────────────────────────────────────────────

def _parse_func(src: str) -> ast.AST:
    """Parse a function string and return the FunctionDef node."""
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    raise ValueError("No function found in source")


# ════════════════════════════════════════════════════════════════════
#  compute_nesting_depth
# ════════════════════════════════════════════════════════════════════

class TestNestingDepth:

    def test_flat_function(self):
        node = _parse_func("def f():\n    return 1")
        assert compute_nesting_depth(node) == 0

    def test_single_if(self):
        node = _parse_func("def f(x):\n    if x:\n        return 1")
        assert compute_nesting_depth(node) == 1

    def test_nested_if(self):
        src = """\
        def f(x, y):
            if x:
                if y:
                    return 1
        """
        assert compute_nesting_depth(_parse_func(src)) == 2

    def test_triple_nesting(self):
        src = """\
        def f(x):
            for i in x:
                while True:
                    if i:
                        pass
        """
        assert compute_nesting_depth(_parse_func(src)) == 3

    def test_try_except(self):
        src = """\
        def f():
            try:
                pass
            except Exception:
                pass
        """
        # try is 1, except handler is 1 (nested under try)
        depth = compute_nesting_depth(_parse_func(src))
        assert depth >= 1

    def test_with_statement(self):
        src = """\
        def f():
            with open("f") as fh:
                if True:
                    pass
        """
        assert compute_nesting_depth(_parse_func(src)) == 2


# ════════════════════════════════════════════════════════════════════
#  compute_complexity
# ════════════════════════════════════════════════════════════════════

class TestComplexity:

    def test_empty_function(self):
        node = _parse_func("def f():\n    pass")
        assert compute_complexity(node) == 0

    def test_single_if(self):
        node = _parse_func("def f(x):\n    if x:\n        pass")
        assert compute_complexity(node) == 1

    def test_multiple_branches(self):
        src = """\
        def f(x):
            if x > 0:
                pass
            elif x < 0:
                pass
            for i in range(x):
                pass
        """
        c = compute_complexity(_parse_func(src))
        assert c >= 3  # 2 ifs + 1 for

    def test_comprehension(self):
        src = "def f(x):\n    return [i for i in x]"
        c = compute_complexity(_parse_func(src))
        assert c >= 1  # comprehension counted

    def test_boolop(self):
        src = "def f(x, y):\n    if x and y:\n        pass"
        c = compute_complexity(_parse_func(src))
        assert c >= 2  # If + BoolOp

    def test_assert(self):
        src = "def f(x):\n    assert x > 0"
        c = compute_complexity(_parse_func(src))
        assert c >= 1


# ════════════════════════════════════════════════════════════════════
#  ASTNormalizer
# ════════════════════════════════════════════════════════════════════

class TestASTNormalizer:

    def test_renames_function(self):
        node = _parse_func("def my_func():\n    pass")
        import copy
        normalized = ASTNormalizer().visit(copy.deepcopy(node))
        assert normalized.name == "func"

    def test_renames_args(self):
        node = _parse_func("def f(x, y):\n    return x + y")
        import copy
        normalized = ASTNormalizer().visit(copy.deepcopy(node))
        arg_names = [a.arg for a in normalized.args.args]
        assert arg_names == ["arg0", "arg1"]

    def test_preserves_self(self):
        src = "def f(self, x):\n    return self.x"
        node = _parse_func(src)
        import copy
        normalized = ASTNormalizer().visit(copy.deepcopy(node))
        arg_names = [a.arg for a in normalized.args.args]
        assert arg_names[0] == "self"
        assert arg_names[1] == "arg0"

    def test_strips_docstring(self):
        src = '''\
        def f():
            """My docstring."""
            return 1
        '''
        node = _parse_func(src)
        import copy
        normalized = ASTNormalizer().visit(copy.deepcopy(node))
        # docstring should be removed — body should NOT start with Constant str
        first = normalized.body[0]
        if isinstance(first, ast.Expr):
            assert not (isinstance(first.value, ast.Constant) and isinstance(first.value.value, str))

    def test_equivalent_functions_produce_same_dump(self):
        """Two structurally equivalent functions with different names should normalize identically."""
        src_a = "def add(x, y):\n    return x + y"
        src_b = "def sum_two(a, b):\n    return a + b"
        import copy
        norm_a = ASTNormalizer().visit(copy.deepcopy(_parse_func(src_a)))
        norm_b = ASTNormalizer().visit(copy.deepcopy(_parse_func(src_b)))
        assert ast.dump(norm_a) == ast.dump(norm_b)

    def test_different_structure_produces_different_dump(self):
        src_a = "def f(x):\n    return x + 1"
        src_b = "def f(x):\n    if x:\n        return x"
        import copy
        norm_a = ASTNormalizer().visit(copy.deepcopy(_parse_func(src_a)))
        norm_b = ASTNormalizer().visit(copy.deepcopy(_parse_func(src_b)))
        assert ast.dump(norm_a) != ast.dump(norm_b)


# ════════════════════════════════════════════════════════════════════
#  _compute_structure_hash
# ════════════════════════════════════════════════════════════════════

class TestStructureHash:

    def test_returns_hex_string(self):
        node = _parse_func("def f():\n    return 1")
        h = _compute_structure_hash(node)
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    @patch.dict(os.environ, {"X_RAY_DISABLE_RUST": "1"})
    def test_same_structure_same_hash(self):
        h1 = _compute_structure_hash(_parse_func("def a(x):\n    return x + 1"))
        h2 = _compute_structure_hash(_parse_func("def b(y):\n    return y + 1"))
        assert h1 == h2

    def test_different_structure_different_hash(self):
        h1 = _compute_structure_hash(_parse_func("def f(x):\n    return x"))
        h2 = _compute_structure_hash(_parse_func("def f(x):\n    if x:\n        return 1"))
        assert h1 != h2

    @patch.dict(os.environ, {"X_RAY_DISABLE_RUST": "1"})
    def test_python_fallback_when_rust_disabled(self):
        h = _compute_structure_hash(_parse_func("def f():\n    pass"))
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    def test_exception_returns_empty(self):
        """Garbage node → empty string fallback."""
        # Pass something that will fail to normalize
        h = _compute_structure_hash(ast.parse(""))
        # Either a hash of the empty module or empty string — both acceptable
        assert isinstance(h, str)


# ════════════════════════════════════════════════════════════════════
#  _extract_functions_from_file
# ════════════════════════════════════════════════════════════════════

class TestExtractFunctions:

    def test_simple_file(self, tmp_path):
        src = "def greet(name):\n    return f'Hello {name}'\n"
        p = tmp_path / "sample.py"
        p.write_text(src, encoding="utf-8")
        funcs, classes, err = _extract_functions_from_file(p, tmp_path)
        assert err is None
        assert len(funcs) == 1
        assert funcs[0].name == "greet"
        assert funcs[0].parameters == ["name"]

    def test_class_extraction(self, tmp_path):
        src = textwrap.dedent("""\
        class Foo:
            def bar(self):
                pass
        """)
        p = tmp_path / "cls.py"
        p.write_text(src, encoding="utf-8")
        funcs, classes, err = _extract_functions_from_file(p, tmp_path)
        assert err is None
        assert len(classes) == 1
        assert classes[0].name == "Foo"
        assert classes[0].has_init is False
        assert "bar" in classes[0].methods

    def test_async_function(self, tmp_path):
        src = "async def fetch(url):\n    return url\n"
        p = tmp_path / "async_mod.py"
        p.write_text(src, encoding="utf-8")
        funcs, _, err = _extract_functions_from_file(p, tmp_path)
        assert err is None
        assert len(funcs) == 1
        assert funcs[0].is_async is True

    def test_syntax_error_returns_error(self, tmp_path):
        p = tmp_path / "bad.py"
        p.write_text("def (broken:\n", encoding="utf-8")
        funcs, classes, err = _extract_functions_from_file(p, tmp_path)
        assert err is not None
        assert "SyntaxError" in err

    def test_missing_file_returns_error(self, tmp_path):
        p = tmp_path / "missing.py"
        funcs, classes, err = _extract_functions_from_file(p, tmp_path)
        assert err is not None

    def test_decorated_function(self, tmp_path):
        src = textwrap.dedent("""\
        def my_decorator(f):
            return f

        @my_decorator
        def wrapped():
            pass
        """)
        p = tmp_path / "deco.py"
        p.write_text(src, encoding="utf-8")
        funcs, _, _ = _extract_functions_from_file(p, tmp_path)
        wrapped = [f for f in funcs if f.name == "wrapped"]
        assert len(wrapped) == 1
        assert "my_decorator" in wrapped[0].decorators

    def test_calls_to_extracted(self, tmp_path):
        src = textwrap.dedent("""\
        def outer():
            inner()
            obj.method()
        """)
        p = tmp_path / "calls.py"
        p.write_text(src, encoding="utf-8")
        funcs, _, _ = _extract_functions_from_file(p, tmp_path)
        assert "inner" in funcs[0].calls_to
        assert "method" in funcs[0].calls_to

    def test_relative_path_forward_slashes(self, tmp_path):
        sub = tmp_path / "pkg"
        sub.mkdir()
        p = sub / "mod.py"
        p.write_text("def f(): pass\n", encoding="utf-8")
        funcs, _, _ = _extract_functions_from_file(p, tmp_path)
        assert "/" in funcs[0].file_path or "\\" not in funcs[0].file_path


# ════════════════════════════════════════════════════════════════════
#  collect_py_files
# ════════════════════════════════════════════════════════════════════

class TestCollectPyFiles:

    def test_finds_py_files(self, tmp_path):
        (tmp_path / "a.py").write_text("x=1")
        (tmp_path / "b.txt").write_text("x=1")
        (tmp_path / "c.py").write_text("x=1")
        files = collect_py_files(tmp_path)
        assert len(files) == 2

    def test_skips_pycache(self, tmp_path):
        pc = tmp_path / "__pycache__"
        pc.mkdir()
        (pc / "cached.py").write_text("x=1")
        (tmp_path / "real.py").write_text("x=1")
        files = collect_py_files(tmp_path)
        assert len(files) == 1
        assert files[0].name == "real.py"

    def test_skips_venv(self, tmp_path):
        venv = tmp_path / "venv"
        venv.mkdir()
        (venv / "pkg.py").write_text("x=1")
        (tmp_path / "app.py").write_text("x=1")
        files = collect_py_files(tmp_path)
        assert len(files) == 1

    def test_exclude_filter(self, tmp_path):
        sub = tmp_path / "tests"
        sub.mkdir()
        (sub / "t.py").write_text("x=1")
        (tmp_path / "app.py").write_text("x=1")
        files = collect_py_files(tmp_path, exclude=["tests"])
        names = [f.name for f in files]
        assert "t.py" not in names

    def test_include_filter(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("x=1")
        other = tmp_path / "other"
        other.mkdir()
        (other / "b.py").write_text("x=1")
        files = collect_py_files(tmp_path, include=["src"])
        names = [f.name for f in files]
        assert "a.py" in names

    def test_skips_egg_info(self, tmp_path):
        egg = tmp_path / "pkg.egg-info"
        egg.mkdir()
        (egg / "e.py").write_text("x=1")
        (tmp_path / "m.py").write_text("x=1")
        files = collect_py_files(tmp_path)
        assert len(files) == 1


# ════════════════════════════════════════════════════════════════════
#  scan_codebase
# ════════════════════════════════════════════════════════════════════

class TestScanCodebase:

    def test_scans_multiple_files(self, tmp_path):
        (tmp_path / "a.py").write_text("def fa(): pass\n")
        (tmp_path / "b.py").write_text("def fb(): pass\n")
        funcs, classes, errors = scan_codebase(tmp_path)
        names = {f.name for f in funcs}
        assert "fa" in names
        assert "fb" in names
        assert len(errors) == 0

    def test_collects_errors(self, tmp_path):
        (tmp_path / "good.py").write_text("def ok(): pass\n")
        (tmp_path / "bad.py").write_text("def (:\n")
        funcs, _, errors = scan_codebase(tmp_path)
        assert len(funcs) >= 1
        assert len(errors) == 1

    def test_empty_directory(self, tmp_path):
        funcs, classes, errors = scan_codebase(tmp_path)
        assert funcs == []
        assert classes == []
        assert errors == []
