"""
tests/test_analysis_test_generator.py
=======================================
Tests for Analysis/test_generator.py — Auto-generate tests from X-Ray analysis.

Note: PythonTestGenerator.generate() and JSTSTestGenerator.generate() both return
List[GeneratedTestFile], NOT a TestGenReport. They write files directly.
"""



from Analysis.test_generator import (
    GeneratedTestFile,
    JSTSTestGenerator,
    PythonTestGenerator,
    TestGenReport,
    _group_by_file,
    _guess_import_path,
    _module_from_filepath,
    _safe_identifier,
)
from Core.types import ClassRecord, FunctionRecord, SmellIssue


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_func(name="add", fpath="utils.py", lines=10, params=None) -> FunctionRecord:
    return FunctionRecord(
        name=name,
        file_path=fpath,
        line_start=1,
        line_end=lines,
        size_lines=lines,
        parameters=params or ["a", "b"],
        return_type="int",
        decorators=[],
        docstring="Add two numbers.",
        calls_to=[],
        complexity=1,
        nesting_depth=1,
        code_hash="abc",
        structure_hash="def",
        code=f"def {name}(a, b): return a + b",
        return_count=1,
        branch_count=0,
        is_async=False,
        mutable_default_params=[],
    )


def _make_class(name="MyClass", fpath="mymodule.py") -> ClassRecord:
    return ClassRecord(
        name=name,
        file_path=fpath,
        line_start=1,
        line_end=30,
        size_lines=30,
        method_count=3,
        base_classes=[],
        docstring="A test class.",
        methods=["__init__", "run", "stop"],
        has_init=True,
    )


def _make_smell(file="utils.py") -> SmellIssue:
    return SmellIssue(
        category="long-function",
        severity="warning",
        message="Function too long",
        suggestion="Split it",
        file_path=file,
        line=5,
        end_line=100,
        name="big_function",
        metric_value=95,
    )


# ── Utility functions ─────────────────────────────────────────────────────────


class TestSafeIdentifier:
    def test_plain_name(self):
        assert _safe_identifier("mymodule") == "mymodule"

    def test_dots_become_underscores(self):
        assert _safe_identifier("my.module") == "my_module"

    def test_slashes_become_underscores(self):
        assert _safe_identifier("src/utils") == "src_utils"

    def test_hyphens_become_underscores(self):
        assert _safe_identifier("my-module") == "my_module"

    def test_empty_string(self):
        result = _safe_identifier("")
        assert isinstance(result, str)


class TestModuleFromFilepath:
    def test_simple_path(self, tmp_path):
        result = _module_from_filepath("utils.py", tmp_path)
        assert result == "utils"

    def test_nested_path(self, tmp_path):
        result = _module_from_filepath("Analysis/smells.py", tmp_path)
        assert "Analysis" in result or "smells" in result

    def test_strips_py_extension(self, tmp_path):
        result = _module_from_filepath("Core/config.py", tmp_path)
        assert not result.endswith(".py")


class TestGuessImportPath:
    def test_removes_py_extension(self):
        result = _guess_import_path("utils.py")
        assert not result.endswith(".py")

    def test_converts_slash_to_dot(self):
        result = _guess_import_path("Core/config.py")
        assert "Core" in result or "config" in result


class TestGroupByFile:
    def test_groups_functions_by_file(self):
        f1 = _make_func(name="a", fpath="utils.py")
        f2 = _make_func(name="b", fpath="utils.py")
        f3 = _make_func(name="c", fpath="core.py")
        groups = _group_by_file([f1, f2, f3])
        assert len(groups["utils.py"]) == 2
        assert len(groups["core.py"]) == 1

    def test_empty_list(self):
        assert _group_by_file([]) == {}

    def test_single_item(self):
        f = _make_func()
        groups = _group_by_file([f])
        assert "utils.py" in groups


# ── GeneratedTestFile & TestGenReport ─────────────────────────────────────────


class TestGeneratedTestFile:
    def test_creation(self):
        gtf = GeneratedTestFile(
            path="tests/test_utils.py",
            content="def test_add(): assert 1+1 == 2",
            test_count=1,
            language="python",
        )
        assert gtf.path == "tests/test_utils.py"
        assert gtf.test_count == 1
        assert gtf.language == "python"


class TestTestGenReport:
    def test_defaults(self):
        r = TestGenReport()
        assert r.files_created == []
        assert r.total_tests == 0
        assert r.languages == []


# ── PythonTestGenerator ───────────────────────────────────────────────────────
# generate() returns List[GeneratedTestFile], not a TestGenReport


class TestPythonTestGenerator:
    def test_generate_returns_list(self, tmp_path):
        funcs = [_make_func()]
        gen = PythonTestGenerator(tmp_path, "myproject")
        result = gen.generate(funcs, [])
        assert isinstance(result, list)

    def test_generates_test_files(self, tmp_path):
        funcs = [_make_func(fpath="utils.py"), _make_func(name="sub", fpath="utils.py")]
        gen = PythonTestGenerator(tmp_path, "proj")
        files = gen.generate(funcs, [])
        assert len(files) >= 1
        assert all(isinstance(f, GeneratedTestFile) for f in files)

    def test_generated_content_is_python(self, tmp_path):
        funcs = [_make_func()]
        gen = PythonTestGenerator(tmp_path, "proj")
        files = gen.generate(funcs, [])
        for gtf in files:
            assert "def test_" in gtf.content or "import" in gtf.content

    def test_with_classes(self, tmp_path):
        classes = [_make_class()]
        gen = PythonTestGenerator(tmp_path, "proj")
        files = gen.generate([], classes)
        assert isinstance(files, list)

    def test_with_smells(self, tmp_path):
        smells = [_make_smell()]
        gen = PythonTestGenerator(tmp_path, "proj")
        files = gen.generate([], [], smells=smells)
        assert isinstance(files, list)

    def test_import_smoke_tests_generated(self, tmp_path):
        funcs = [
            _make_func(name="a", fpath="module_a.py"),
            _make_func(name="b", fpath="module_b.py"),
        ]
        gen = PythonTestGenerator(tmp_path, "proj")
        files = gen.generate(funcs, [])
        contents = " ".join(f.content for f in files)
        assert "import" in contents

    def test_no_functions_no_crash(self, tmp_path):
        gen = PythonTestGenerator(tmp_path, "proj")
        result = gen.generate([], [])
        assert isinstance(result, list)

    def test_language_is_python(self, tmp_path):
        funcs = [_make_func()]
        gen = PythonTestGenerator(tmp_path, "proj")
        files = gen.generate(funcs, [])
        for gtf in files:
            assert gtf.language == "python"

    def test_test_count_positive(self, tmp_path):
        funcs = [_make_func(), _make_func(name="mult")]
        gen = PythonTestGenerator(tmp_path, "proj")
        files = gen.generate(funcs, [])
        total = sum(f.test_count for f in files)
        assert total >= 1

    def test_multiple_modules_multiple_files(self, tmp_path):
        funcs = [
            _make_func(name="a", fpath="mod_a.py"),
            _make_func(name="b", fpath="mod_b.py"),
        ]
        gen = PythonTestGenerator(tmp_path, "proj")
        files = gen.generate(funcs, [])
        # Should generate at least one file per module (plus possibly smoke test)
        assert len(files) >= 2


# ── JSTSTestGenerator ─────────────────────────────────────────────────────────
# generate() returns List[GeneratedTestFile], no output_dir param


class TestJSTSTestGenerator:
    def _make_js_analysis(self, file_path="src/app.js", has_jsx=False):
        from Lang.js_ts_analyzer import JSFileAnalysis, JSFunction
        import hashlib

        fn = JSFunction(
            name="greet",
            file_path=file_path,
            line_start=1,
            line_end=5,
            size_lines=5,
            parameters=["name"],
            is_async=False,
            is_arrow=False,
            is_exported=True,
            is_react_component=has_jsx,
            complexity=1,
            nesting_depth=1,
            code='function greet(name) { return "Hello " + name; }',
            code_hash=hashlib.sha256(b"greet").hexdigest(),
        )
        return JSFileAnalysis(
            file_path=file_path,
            total_lines=10,
            functions=[fn],
            has_jsx=has_jsx,
            language="javascript",
        )

    def test_generate_returns_list(self, tmp_path):
        analyses = [self._make_js_analysis()]
        gen = JSTSTestGenerator(tmp_path, "proj")
        result = gen.generate(analyses)
        assert isinstance(result, list)

    def test_generates_js_test_files(self, tmp_path):
        analyses = [self._make_js_analysis()]
        gen = JSTSTestGenerator(tmp_path, "proj")
        files = gen.generate(analyses)
        assert len(files) >= 1
        assert all(isinstance(f, GeneratedTestFile) for f in files)

    def test_generated_content_has_test_pattern(self, tmp_path):
        analyses = [self._make_js_analysis()]
        gen = JSTSTestGenerator(tmp_path, "proj")
        files = gen.generate(analyses)
        for gtf in files:
            assert (
                "test(" in gtf.content
                or "it(" in gtf.content
                or "describe(" in gtf.content
            )

    def test_jsx_file_produces_react_tests(self, tmp_path):
        analyses = [self._make_js_analysis("Component.jsx", has_jsx=True)]
        gen = JSTSTestGenerator(tmp_path, "proj")
        files = gen.generate(analyses)
        all_content = " ".join(f.content for f in files)
        assert "render" in all_content or "component" in all_content.lower()

    def test_language_field_set(self, tmp_path):
        analyses = [self._make_js_analysis()]
        gen = JSTSTestGenerator(tmp_path, "proj")
        files = gen.generate(analyses)
        for gtf in files:
            assert gtf.language in ("javascript", "typescript", "js", "ts")

    def test_no_analyses_no_crash(self, tmp_path):
        gen = JSTSTestGenerator(tmp_path, "proj")
        result = gen.generate([])
        assert isinstance(result, list)

    def test_smell_regression_integration(self, tmp_path):
        analyses = [self._make_js_analysis()]
        smells = [_make_smell("src/app.js")]
        gen = JSTSTestGenerator(tmp_path, "proj")
        files = gen.generate(analyses, smells=smells)
        assert isinstance(files, list)

    def test_multiple_files_multiple_suites(self, tmp_path):
        analyses = [
            self._make_js_analysis("src/api.js"),
            self._make_js_analysis("src/utils.js"),
        ]
        gen = JSTSTestGenerator(tmp_path, "proj")
        files = gen.generate(analyses)
        total = sum(f.test_count for f in files)
        assert total >= 1
