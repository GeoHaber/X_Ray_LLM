"""Tests for Analysis.llm_transpiler — hybrid AST + LLM transpilation."""

import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Analysis.llm_transpiler import (
    LLMTranspiler,
    _check_rust_compiles,
    _extract_fn_block,
    get_llm_transpiler,
    hybrid_transpile,
    llm_transpile_function,
)


# ═══════════════════════════════════════════════════════════════════════════
#  _extract_fn_block — parsing LLM output
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractFnBlock:
    """Tests for extracting Rust fn from noisy LLM output."""

    def test_clean_fn(self):
        code = "fn add(a: i64, b: i64) -> i64 {\n    a + b\n}"
        assert _extract_fn_block(code) == code

    def test_strip_markdown_fences(self):
        code = "```rust\nfn add(a: i64, b: i64) -> i64 {\n    a + b\n}\n```"
        result = _extract_fn_block(code)
        assert result.startswith("fn add")
        assert "```" not in result

    def test_strip_explanation(self):
        code = (
            "Here is the Rust function:\n\n"
            "fn greet(name: String) -> String {\n"
            '    format!("Hello, {}!", name)\n'
            "}\n\n"
            "This function takes a name and returns a greeting."
        )
        result = _extract_fn_block(code)
        assert result.startswith("fn greet")
        assert result.endswith("}")
        assert "This function" not in result

    def test_pub_fn(self):
        code = "pub fn double(x: i64) -> i64 {\n    x * 2\n}"
        result = _extract_fn_block(code)
        assert "pub fn double" in result

    def test_nested_braces(self):
        code = textwrap.dedent("""\
            fn complex(x: i64) -> String {
                if x > 0 {
                    format!("{}", x)
                } else {
                    "negative".to_string()
                }
            }""")
        result = _extract_fn_block(code)
        assert result.startswith("fn complex")
        assert result.count("{") == result.count("}")

    def test_preserves_use_statement(self):
        code = (
            "use std::collections::HashMap;\n\n"
            "fn make_map() -> HashMap<String, i64> {\n"
            "    HashMap::new()\n"
            "}"
        )
        result = _extract_fn_block(code)
        assert "use std::collections::HashMap;" in result
        assert "fn make_map" in result

    def test_empty_input(self):
        assert _extract_fn_block("") == ""

    def test_no_fn_returns_as_is(self):
        code = "let x = 42;"
        assert _extract_fn_block(code) == code


# ═══════════════════════════════════════════════════════════════════════════
#  _check_rust_compiles — compiler validation
# ═══════════════════════════════════════════════════════════════════════════


class TestRustCompileCheck:
    """Tests for the rustc --check validation."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_rustc(self):
        """Skip these tests if rustc isn't installed."""
        import shutil

        if shutil.which("rustc") is None:
            pytest.skip("rustc not found")

    def test_valid_fn_compiles(self):
        code = "fn add(a: i64, b: i64) -> i64 { a + b }"
        ok, err = _check_rust_compiles(code)
        assert ok, f"Valid Rust should compile: {err}"

    def test_invalid_fn_fails(self):
        code = "fn broken() -> i64 { let x: String = 42; }"
        ok, err = _check_rust_compiles(code)
        assert not ok
        assert err  # should have error text

    def test_hashmap_fn_compiles(self):
        code = textwrap.dedent("""\
            fn make_map() -> HashMap<String, i64> {
                let mut m = HashMap::new();
                m.insert("hello".to_string(), 42);
                m
            }""")
        ok, err = _check_rust_compiles(code)
        assert ok, f"HashMap fn should compile: {err}"

    def test_empty_fn_compiles(self):
        code = "fn noop() {}"
        ok, err = _check_rust_compiles(code)
        assert ok

    def test_todo_fn_compiles(self):
        code = 'fn stub() -> String { todo!("not implemented") }'
        ok, err = _check_rust_compiles(code)
        assert ok


# ═══════════════════════════════════════════════════════════════════════════
#  LLMTranspiler — engine tests (mocked LLM)
# ═══════════════════════════════════════════════════════════════════════════


class FakeLLM:
    """Mock LLM that returns predefined Rust code."""

    def __init__(self, responses=None, available=True):
        self._responses = list(responses or [])
        self._call_count = 0
        self._available = available

    @property
    def available(self):
        return self._available

    def completion(self, prompt, system_prompt=""):
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        if idx < 0 or not self._responses:
            return ""
        return self._responses[idx]


class TestLLMTranspiler:
    """Tests for the LLMTranspiler engine with mocked LLM."""

    def _make_engine(self, responses, available=True, verify=False):
        engine = LLMTranspiler(max_retries=2, verify_compilation=verify)
        engine._llm = FakeLLM(responses=responses, available=available)
        return engine

    def test_basic_transpile_no_verify(self):
        """LLM returns clean Rust, no compilation check."""
        engine = self._make_engine(
            ["fn add(a: i64, b: i64) -> i64 {\n    a + b\n}"],
            verify=False,
        )
        result = engine.transpile("def add(a, b): return a + b", name_hint="add")
        assert result is not None
        assert "fn add" in result
        assert engine.stats["success"] == 1

    def test_llm_unavailable_returns_none(self):
        engine = self._make_engine([], available=False)
        result = engine.transpile("def foo(): pass", name_hint="foo")
        assert result is None
        assert engine.stats["llm_fail"] == 1

    def test_llm_empty_response_returns_none(self):
        engine = self._make_engine([""], verify=False)
        result = engine.transpile("def foo(): pass")
        assert result is None

    def test_strips_markdown_fences(self):
        engine = self._make_engine(
            ['```rust\nfn greet() -> String {\n    "hi".to_string()\n}\n```'],
            verify=False,
        )
        result = engine.transpile("def greet(): return 'hi'")
        assert result is not None
        assert "```" not in result
        assert "fn greet" in result

    def test_source_info_comment(self):
        engine = self._make_engine(
            ["fn foo() {}"],
            verify=False,
        )
        result = engine.transpile(
            "def foo(): pass", name_hint="foo", source_info="mod.py:10"
        )
        assert "mod.py:10" in result
        assert "LLM-assisted" in result

    def test_stats_tracking(self):
        engine = self._make_engine(
            ["fn a() {}", "fn b() {}"],
            verify=False,
        )
        engine.transpile("def a(): pass", name_hint="a")
        engine.transpile("def b(): pass", name_hint="b")
        assert engine.stats["attempted"] == 2
        assert engine.stats["success"] == 2
        assert engine.stats["compile_fail"] == 0

    @pytest.fixture
    def _skip_if_no_rustc(self):
        import shutil

        if shutil.which("rustc") is None:
            pytest.skip("rustc not found")

    def test_compile_check_valid(self, _skip_if_no_rustc):
        """LLM returns valid Rust, compilation check passes."""
        engine = self._make_engine(
            ["fn add(a: i64, b: i64) -> i64 { a + b }"],
            verify=True,
        )
        result = engine.transpile("def add(a, b): return a + b", name_hint="add")
        assert result is not None
        assert "fn add" in result

    def test_compile_check_invalid_then_fix(self, _skip_if_no_rustc):
        """LLM first returns bad Rust, then fixes it on retry."""
        engine = self._make_engine(
            [
                "fn bad() -> i64 { let x: String = 42; }",  # won't compile
                "fn bad() -> i64 { 42 }",  # fixed
            ],
            verify=True,
        )
        result = engine.transpile("def bad(): return 42", name_hint="bad")
        assert result is not None
        assert "42" in result

    def test_compile_check_all_fail_returns_none(self, _skip_if_no_rustc):
        """LLM keeps returning broken Rust — gives up."""
        engine = self._make_engine(
            [
                "fn x() -> i64 { let s: String = 42; }",
                "fn x() -> i64 { let s: String = 42; }",
                "fn x() -> i64 { let s: String = 42; }",
            ],
            verify=True,
        )
        engine._max_retries = 2
        result = engine.transpile("def x(): return 42", name_hint="x")
        assert result is None
        assert engine.stats["compile_fail"] >= 1


# ═══════════════════════════════════════════════════════════════════════════
#  hybrid_transpile — end-to-end integration
# ═══════════════════════════════════════════════════════════════════════════


class TestHybridTranspile:
    """Tests for the hybrid AST + LLM pipeline."""

    def test_simple_fn_uses_ast_only(self):
        """Simple functions should be handled by AST — no LLM needed."""
        result = hybrid_transpile(
            "def add(a: int, b: int) -> int:\n    return a + b",
            name_hint="add",
        )
        assert "fn add" in result
        assert "todo!" not in result
        # Should NOT mention LLM
        assert "LLM" not in result

    def test_complex_fn_falls_back_to_llm_if_available(self):
        """When AST produces todo!(), hybrid_transpile tries the LLM."""
        good_rust = (
            'fn complex_op(data: Vec<String>) -> String {\n    data.join(", ")\n}'
        )
        fake_llm = FakeLLM(responses=[good_rust], available=True)
        engine = LLMTranspiler(verify_compilation=False)
        engine._llm = fake_llm

        # Patch the singleton
        import Analysis.llm_transpiler as mod

        old = mod._default_engine
        mod._default_engine = engine
        try:
            # This Python uses json.dumps — AST will produce todo!()
            result = hybrid_transpile(
                textwrap.dedent("""\
                    def complex_op(data):
                        import json
                        return json.dumps(data)
                """),
                name_hint="complex_op",
            )
            # Should have used LLM result (no todo!)
            assert "todo!" not in result
            assert "fn complex_op" in result
        finally:
            mod._default_engine = old

    def test_complex_fn_keeps_todo_if_no_llm(self):
        """When LLM is unavailable, complex functions keep todo!()."""
        fake_llm = FakeLLM(responses=[], available=False)
        engine = LLMTranspiler(verify_compilation=False)
        engine._llm = fake_llm

        import Analysis.llm_transpiler as mod

        old = mod._default_engine
        mod._default_engine = engine
        try:
            result = hybrid_transpile(
                textwrap.dedent("""\
                    def complex_op(data):
                        import json
                        return json.dumps(data)
                """),
                name_hint="complex_op",
            )
            # Should keep AST's todo!() stub
            assert "todo!" in result
        finally:
            mod._default_engine = old


# ═══════════════════════════════════════════════════════════════════════════
#  get_llm_transpiler / llm_transpile_function — API tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAPI:
    """Tests for the convenience API."""

    def test_singleton_returns_same_instance(self):
        import Analysis.llm_transpiler as mod

        old = mod._default_engine
        mod._default_engine = None
        try:
            a = get_llm_transpiler()
            b = get_llm_transpiler()
            assert a is b
        finally:
            mod._default_engine = old

    def test_llm_transpile_function_when_unavailable(self):
        """Should return None gracefully when no LLM server."""
        import Analysis.llm_transpiler as mod

        engine = LLMTranspiler(verify_compilation=False)
        engine._llm = FakeLLM(responses=[], available=False)
        old = mod._default_engine
        mod._default_engine = engine
        try:
            result = llm_transpile_function("def foo(): pass", name_hint="foo")
            assert result is None
        finally:
            mod._default_engine = old


# ═══════════════════════════════════════════════════════════════════════════
#  Model catalog — verify transpiler models exist
# ═══════════════════════════════════════════════════════════════════════════


class TestModelCatalog:
    """Verify transpiler-specialized models are in the catalog."""

    def test_transpiler_model_ids_exist(self):
        from Core.llm_manager import MODEL_CATALOG, TRANSPILER_MODEL_IDS

        catalog_ids = {m.id for m in MODEL_CATALOG}
        for tid in TRANSPILER_MODEL_IDS:
            assert tid in catalog_ids, f"Missing model in catalog: {tid}"

    def test_transpiler_models_are_code_focused(self):
        from Core.llm_manager import MODEL_CATALOG, TRANSPILER_MODEL_IDS

        catalog = {m.id: m for m in MODEL_CATALOG}
        for tid in TRANSPILER_MODEL_IDS:
            m = catalog[tid]
            # Should have at least 3 stars for code
            assert m.code_quality.count("★") >= 3, (
                f"{tid} has too few code stars: {m.code_quality}"
            )

    def test_recommend_includes_transpiler_models(self):
        from Core.llm_manager import recommend_models, HardwareProfile

        hw = HardwareProfile(
            os_name="Windows",
            os_version="11",
            arch="x86_64",
            cpu_brand="Intel i7",
            cpu_cores=8,
            ram_gb=32.0,
            gpu_name="RTX 3090",
            gpu_vram_gb=24.0,
            avx2=True,
        )
        recs = recommend_models(hw)
        rec_ids = {m.id for m in recs}
        # At least one transpiler model should be recommended for high-end hw
        from Core.llm_manager import TRANSPILER_MODEL_IDS

        overlap = rec_ids & set(TRANSPILER_MODEL_IDS)
        assert len(overlap) >= 1, "No transpiler models recommended for high-end hw"


# ═══════════════════════════════════════════════════════════════════════════
#  Transpiler batch_json — verify hybrid wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestBatchJsonHybridWiring:
    """Verify that transpile_batch_json uses the hybrid path."""

    def test_batch_json_header_says_hybrid(self):
        """The generated source header should mention Hybrid."""
        from Analysis.transpiler import transpile_batch_json
        import json

        candidates = [
            {
                "name": "add",
                "code": "def add(a: int, b: int) -> int:\n    return a + b",
                "file_path": "test.py",
                "line_start": 1,
            }
        ]
        result = transpile_batch_json(json.dumps(candidates))
        assert "Hybrid" in result

    def test_batch_json_simple_fn_no_todo(self):
        """Simple functions should transpile without todo!() even without LLM."""
        from Analysis.transpiler import transpile_batch_json
        import json

        candidates = [
            {
                "name": "double",
                "code": "def double(x: int) -> int:\n    return x * 2",
                "file_path": "test.py",
                "line_start": 1,
            }
        ]
        result = transpile_batch_json(json.dumps(candidates))
        assert "fn double" in result
        # The double function itself shouldn't have todo! (it's simple)
        fn_start = result.index("fn double")
        fn_block = result[fn_start : result.index("\n\n", fn_start)]
        assert "todo!" not in fn_block
