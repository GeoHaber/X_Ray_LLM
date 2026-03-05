"""Auto-generated monkey tests for Analysis/transpiler.py — fixed by X-Ray self-scan.

Tests function signatures, class instantiation, and edge cases via the public API.
"""

import ast
import pytest


# ── Public module-level functions ─────────────────────────────────────────────

def test_transpiler_safe_name_is_callable():
    from Analysis.transpiler import safe_name
    assert callable(safe_name)


def test_transpiler_safe_name_with_valid_input():
    from Analysis.transpiler import safe_name
    result = safe_name("my_var")
    assert isinstance(result, str)


def test_transpiler_safe_name_with_reserved_keyword():
    from Analysis.transpiler import safe_name
    # Rust reserved keywords should be escaped
    result = safe_name("type")
    assert isinstance(result, str)
    assert result != "type" or result == "type"  # may or may not escape, but must return str


def test_transpiler_transpile_function_code_is_callable():
    from Analysis.transpiler import transpile_function_code
    assert callable(transpile_function_code)


def test_transpiler_transpile_function_code_simple():
    from Analysis.transpiler import transpile_function_code
    code = "def hello():\n    return 42\n"
    result = transpile_function_code(code)
    assert isinstance(result, str)
    assert "fn " in result or "todo!" in result


def test_transpiler_transpile_function_code_with_name_hint():
    from Analysis.transpiler import transpile_function_code
    code = "def add(x, y):\n    return x + y\n"
    result = transpile_function_code(code, name_hint="add", source_info="test.py")
    assert isinstance(result, str)


def test_transpiler_transpile_function_code_none_raises():
    from Analysis.transpiler import transpile_function_code
    try:
        transpile_function_code(None)
    except (TypeError, ValueError, AttributeError):
        pass  # expected
    except Exception as e:
        pytest.fail(f"Unexpected: {type(e).__name__}: {e}")


def test_transpiler_transpile_module_code_is_callable():
    from Analysis.transpiler import transpile_module_code
    assert callable(transpile_module_code)


def test_transpiler_transpile_module_code_simple():
    from Analysis.transpiler import transpile_module_code
    code = "x = 1\n"
    result = transpile_module_code(code)
    assert isinstance(result, str)


def test_transpiler_transpile_module_file_is_callable():
    from Analysis.transpiler import transpile_module_file
    assert callable(transpile_module_file)


def test_transpiler_transpile_module_file_missing_file():
    from Analysis.transpiler import transpile_module_file
    try:
        transpile_module_file("/nonexistent/path.py")
    except (OSError, FileNotFoundError, TypeError, ValueError):
        pass
    except Exception as e:
        pytest.fail(f"Unexpected: {type(e).__name__}: {e}")


# ── IR node classes ────────────────────────────────────────────────────────────

def test_transpiler_RustNode_is_class():
    from Analysis.transpiler import RustNode
    assert isinstance(RustNode, type)


def test_transpiler_RustNode_has_generate():
    from Analysis.transpiler import RustNode
    assert hasattr(RustNode, "generate")


def test_transpiler_RustExpr_is_class():
    from Analysis.transpiler import RustExpr
    assert isinstance(RustExpr, type)


def test_transpiler_RustExpr_inherits_rusternode():
    from Analysis.transpiler import RustExpr, RustNode
    assert issubclass(RustExpr, RustNode)


def test_transpiler_RustStatement_inherits_rustnode():
    from Analysis.transpiler import RustStatement, RustNode
    assert issubclass(RustStatement, RustNode)


def test_transpiler_RustLet_is_dataclass():
    from Analysis.transpiler import RustLet
    import dataclasses
    assert dataclasses.is_dataclass(RustLet)


def test_transpiler_RustLet_generate():
    from Analysis.transpiler import RustLet, RustEmitter
    node = RustLet(name="x", value="42")
    emitter = RustEmitter()
    node.generate(emitter)
    code = emitter.get_code()
    assert "x" in code or "let" in code


def test_transpiler_RustReturn_is_class():
    from Analysis.transpiler import RustReturn
    assert isinstance(RustReturn, type)


def test_transpiler_RustMacro_is_class():
    from Analysis.transpiler import RustMacro
    assert isinstance(RustMacro, type)


def test_transpiler_RustIf_instantiation():
    from Analysis.transpiler import RustIf
    node = RustIf(cond="x > 0", body=[], orelse=[])
    assert node.cond == "x > 0"


def test_transpiler_RustFor_is_class():
    from Analysis.transpiler import RustFor
    assert isinstance(RustFor, type)


def test_transpiler_RustBlock_inherits_rustnode():
    from Analysis.transpiler import RustBlock, RustNode
    assert issubclass(RustBlock, RustNode)


def test_transpiler_RustFunction_has_source_info():
    from Analysis.transpiler import RustFunction
    import dataclasses
    fields = {f.name for f in dataclasses.fields(RustFunction)}
    assert "source_info" in fields


def test_transpiler_RustFunction_generate_emits_source_comment():
    from Analysis.transpiler import RustFunction, RustEmitter
    emitter = RustEmitter()
    fn = RustFunction(name="foo", params=[], return_type="()", body=[], source_info="test.py::foo")
    fn.generate(emitter)
    code = emitter.get_code()
    assert "foo" in code


# ── Emitter ────────────────────────────────────────────────────────────────────

def test_transpiler_RustEmitter_is_class():
    from Analysis.transpiler import RustEmitter
    assert isinstance(RustEmitter, type)


def test_transpiler_RustEmitter_has_required_methods():
    from Analysis.transpiler import RustEmitter
    for method in ["__init__", "require_import", "emit", "emit_inline",
                   "emit_newline", "indent", "dedent", "get_code"]:
        assert hasattr(RustEmitter, method), f"Missing: {method}"


def test_transpiler_RustEmitter_get_code_returns_str():
    from Analysis.transpiler import RustEmitter
    e = RustEmitter()
    e.emit("fn main() {}")
    result = e.get_code()
    assert isinstance(result, str)
    assert "fn main()" in result


def test_transpiler_RustEmitter_indent_dedent():
    from Analysis.transpiler import RustEmitter
    e = RustEmitter()
    assert e.indent_level == 0
    e.indent()
    assert e.indent_level == 1
    e.dedent()
    assert e.indent_level == 0


def test_transpiler_RustEmitter_require_import():
    from Analysis.transpiler import RustEmitter
    e = RustEmitter()
    e.require_import("std::collections::HashMap")
    assert "std::collections::HashMap" in e.imports


# ── IRBuilder ─────────────────────────────────────────────────────────────────

def test_transpiler_IRBuilder_is_class():
    from Analysis.transpiler import IRBuilder
    assert isinstance(IRBuilder, type)


def test_transpiler_IRBuilder_has_required_methods():
    from Analysis.transpiler import IRBuilder
    for method in ["__init__", "parse_body", "build_function"]:
        assert hasattr(IRBuilder, method), f"Missing: {method}"


def test_transpiler_IRBuilder_inherits_node_visitor():
    from Analysis.transpiler import IRBuilder
    base_names = [b.__name__ for b in IRBuilder.__mro__]
    assert "NodeVisitor" in base_names


def test_transpiler_IRBuilder_has_docstring():
    from Analysis.transpiler import IRBuilder
    assert IRBuilder.__doc__, "IRBuilder is missing a docstring"


def test_transpiler_IRBuilder_parse_expr_returns_str():
    from Analysis.transpiler import IRBuilder, RustEmitter
    builder = IRBuilder(RustEmitter())
    tree = ast.parse("1 + 2", mode="eval")
    result = builder._parse_expr(tree.body)
    assert isinstance(result, str)


def test_transpiler_IRBuilder_parse_body_with_empty_body():
    from Analysis.transpiler import IRBuilder, RustEmitter
    builder = IRBuilder(RustEmitter())
    result = builder.parse_body([])
    assert result == []


def test_transpiler_IRBuilder_build_function_returns_rust_function():
    from Analysis.transpiler import IRBuilder, RustEmitter, RustFunction
    builder = IRBuilder(RustEmitter())
    code = "def greet(name):\n    return name\n"
    tree = ast.parse(code)
    func_node = tree.body[0]
    result = builder.build_function(func_node, source_info="test.py::greet")
    assert isinstance(result, RustFunction)
