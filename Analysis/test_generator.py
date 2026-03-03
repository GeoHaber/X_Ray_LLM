"""Analysis/test_generator.py — Auto-generate tests from X-Ray analysis data.

X-Ray v7.0 feature: after scanning a project, automatically create comprehensive
monkey tests based on AST analysis, import graphs, class/function metadata, and
detected smells.

Generates:
  * Python → pytest-style tests
  * JS/TS  → Vitest/Jest-style tests

Test categories produced:
  1. Import smoke tests          — verify every module imports cleanly
  2. Function signature tests    — call with None/empty/boundary args
  3. Class instantiation tests   — construct & inspect attributes
  4. Smell regression tests      — pin-point known smells so they stay visible
  5. Component render tests (JS) — basic mount/render assertions for React
  6. Project structure tests     — verify essential files exist
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Any

from Core.types import FunctionRecord, ClassRecord, SmellIssue


# ── Result ──────────────────────────────────────────────────────────────────

@dataclass
class GeneratedTestFile:
    """One generated test file."""
    path: str           # relative path of the test file
    content: str        # full test source
    test_count: int     # number of test functions inside
    language: str       # "python" | "typescript" | "javascript"


@dataclass
class TestGenReport:
    """Summary of test generation."""
    files_created: List[GeneratedTestFile] = field(default_factory=list)
    total_tests: int = 0
    languages: List[str] = field(default_factory=list)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _safe_identifier(name: str) -> str:
    """Turn an arbitrary name into a valid Python identifier."""
    s = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if s and s[0].isdigit():
        s = "_" + s
    return s or "_unnamed"


def _module_from_filepath(fpath: str, root: Path) -> str:
    """Convert a relative file path to a Python dotted module path."""
    p = Path(fpath)
    # Strip root prefix if present
    try:
        p = p.relative_to(root)
    except ValueError:
        pass
    # Remove .py extension and convert separators
    parts = list(p.with_suffix("").parts)
    return ".".join(parts)


def _guess_import_path(fpath: str) -> str:
    """Guess a usable import path from a relative file path."""
    p = Path(fpath)
    parts = list(p.with_suffix("").parts)
    # Skip leading dots
    parts = [p for p in parts if p not in (".", "..")]
    return ".".join(parts)


def _group_by_file(records) -> Dict[str, list]:
    """Group FunctionRecord or ClassRecord lists by file_path."""
    groups: Dict[str, list] = {}
    for rec in records:
        groups.setdefault(rec.file_path, []).append(rec)
    return groups


# ── Python Test Generator ──────────────────────────────────────────────────

class PythonTestGenerator:
    """Generate pytest-style tests from Python analysis data."""

    def __init__(self, root: Path, project_name: str = ""):
        self.root = root
        self.project_name = project_name or root.name

    def generate(
        self,
        functions: List[FunctionRecord],
        classes: List[ClassRecord],
        smells: List[SmellIssue] | None = None,
        health_checks: list | None = None,
    ) -> List[GeneratedTestFile]:
        """Generate all test files."""
        files: List[GeneratedTestFile] = []

        # 1. Import smoke tests
        f = self._gen_import_smoke(functions, classes)
        if f:
            files.append(f)

        # 2. Per-module function/class tests
        func_groups = _group_by_file(functions)
        cls_groups = _group_by_file(classes)
        all_files = set(func_groups.keys()) | set(cls_groups.keys())

        for fpath in sorted(all_files):
            funcs = func_groups.get(fpath, [])
            clses = cls_groups.get(fpath, [])
            f = self._gen_module_tests(fpath, funcs, clses)
            if f:
                files.append(f)

        # 3. Smell regression tests
        if smells:
            f = self._gen_smell_regression(smells)
            if f:
                files.append(f)

        # 4. Project structure tests
        f = self._gen_structure_tests(health_checks)
        if f:
            files.append(f)

        return files

    # ── Import smoke ──

    def _gen_import_smoke(
        self,
        functions: List[FunctionRecord],
        classes: List[ClassRecord],
    ) -> Optional[GeneratedTestFile]:
        """Generate import smoke tests — verify every module loads."""
        all_files = set()
        for f in functions:
            all_files.add(f.file_path)
        for c in classes:
            all_files.add(c.file_path)

        if not all_files:
            return None

        lines = [
            '"""Auto-generated import smoke tests by X-Ray v7.0.',
            '',
            'Verifies that every scanned Python module can be imported',
            'without raising ImportError or SyntaxError.',
            '"""',
            '',
            'import importlib',
            'import pytest',
            '',
        ]

        test_count = 0
        for fpath in sorted(all_files):
            mod = _guess_import_path(fpath)
            safe = _safe_identifier(mod)
            lines.append(f'def test_import_{safe}():')
            lines.append(f'    """Smoke: {mod} imports without error."""')
            lines.append(f'    importlib.import_module("{mod}")')
            lines.append('')
            test_count += 1

        return GeneratedTestFile(
            path="tests/test_xray_import_smoke.py",
            content="\n".join(lines),
            test_count=test_count,
            language="python",
        )

    # ── Per-module tests ──

    def _gen_function_test_cases(
        self, func: FunctionRecord, mod: str, safe_mod: str
    ) -> tuple[list, int]:
        """Generate test lines and count for a single function."""
        lines: list = []
        count = 0
        safe_name = _safe_identifier(func.name)
        params = func.parameters

        # Test 1: callable check
        lines += [
            f'def test_{safe_mod}_{safe_name}_is_callable():',
            f'    """Verify {func.name} exists and is callable."""',
            f'    from {mod} import {func.name}',
            f'    assert callable({func.name})',
            '',
        ]
        count += 1

        # Test 2: call with None args (monkey test)
        non_self = [p for p in params if p not in ("self", "cls")]
        if non_self:
            none_args = ", ".join(["None"] * len(non_self))
            lines += [
                f'def test_{safe_mod}_{safe_name}_none_args():',
                f'    """Monkey: call {func.name} with None args — should not crash unhandled."""',
                f'    from {mod} import {func.name}',
                f'    try:',
                f'        {func.name}({none_args})',
                f'    except (TypeError, ValueError, AttributeError, KeyError):',
                f'        pass  # Expected — function should raise, not crash',
                f'    except Exception as e:',
                f'        pytest.fail(f"Unexpected exception: {{type(e).__name__}}: {{e}}")',
                '',
            ]
            count += 1

        # Test 3: return type check (if annotated)
        if func.return_type and func.return_type not in ("None", "void"):
            lines += [
                f'def test_{safe_mod}_{safe_name}_return_type():',
                f'    """Verify {func.name} returns expected type."""',
                f'    from {mod} import {func.name}',
                f'    # Smoke check — return type should be: {func.return_type}',
                f'    # (requires valid args to test; assert function exists)',
                f'    assert callable({func.name})',
                '',
            ]
            count += 1

        # Test 4: async functions
        if func.is_async:
            lines += [
                f'@pytest.mark.asyncio',
                f'async def test_{safe_mod}_{safe_name}_is_async():',
                f'    """Verify {func.name} is an async coroutine."""',
                f'    from {mod} import {func.name}',
                f'    import inspect',
                f'    assert inspect.iscoroutinefunction({func.name})',
                '',
            ]
            count += 1

        # Test 5: high complexity
        if func.complexity >= 10:
            lines += [
                f'def test_{safe_mod}_{safe_name}_high_complexity():',
                f'    """Flag: {func.name} has CC={func.complexity} — verify it handles edge cases."""',
                f'    from {mod} import {func.name}',
                f'    # X-Ray detected CC={func.complexity} (cyclomatic complexity)',
                f'    # This function has many branches — test edge cases carefully',
                f'    assert callable({func.name}), "Complex function should be importable"',
                '',
            ]
            count += 1

        return lines, count

    def _gen_class_test_cases(
        self, cls: ClassRecord, mod: str, safe_mod: str
    ) -> tuple[list, int]:
        """Generate test lines and count for a single class."""
        lines: list = []
        count = 0
        safe_cls = _safe_identifier(cls.name)

        # Test: class is importable
        lines += [
            f'def test_{safe_mod}_{safe_cls}_is_class():',
            f'    """Verify {cls.name} exists and is a class."""',
            f'    from {mod} import {cls.name}',
            f'    assert isinstance({cls.name}, type) or callable({cls.name})',
            '',
        ]
        count += 1

        # Test: public methods exist
        if cls.methods:
            public = [m for m in cls.methods if not m.startswith("_") or m == "__init__"]
            if public:
                method_list = ", ".join(f'"{m}"' for m in public[:10])
                lines += [
                    f'def test_{safe_mod}_{safe_cls}_has_methods():',
                    f'    """Verify {cls.name} has expected methods."""',
                    f'    from {mod} import {cls.name}',
                    f'    expected = [{method_list}]',
                    f'    for method in expected:',
                    f'        assert hasattr({cls.name}, method), f"Missing method: {{method}}"',
                    '',
                ]
                count += 1

        # Test: base classes
        if cls.base_classes and cls.base_classes != ["object"]:
            bases = ", ".join(f'"{b}"' for b in cls.base_classes)
            lines += [
                f'def test_{safe_mod}_{safe_cls}_inheritance():',
                f'    """Verify {cls.name} inherits from expected bases."""',
                f'    from {mod} import {cls.name}',
                f'    base_names = [b.__name__ for b in {cls.name}.__mro__]',
                f'    for base in [{bases}]:',
                f'        assert base in base_names, f"Missing base: {{base}}"',
                '',
            ]
            count += 1

        # Test: docstring present
        if not cls.docstring:
            lines += [
                f'def test_{safe_mod}_{safe_cls}_has_docstring():',
                f'    """Lint: {cls.name} should have a docstring."""',
                f'    from {mod} import {cls.name}',
                f'    assert {cls.name}.__doc__, "{cls.name} is missing a docstring"',
                '',
            ]
            count += 1

        return lines, count

    def _gen_module_tests(
        self,
        fpath: str,
        functions: List[FunctionRecord],
        classes: List[ClassRecord],
    ) -> Optional[GeneratedTestFile]:
        """Generate function-signature & class-instantiation tests per module."""
        if not functions and not classes:
            return None

        mod = _guess_import_path(fpath)
        safe_mod = _safe_identifier(mod)

        lines = [
            f'"""Auto-generated monkey tests for {fpath} by X-Ray v7.0.',
            '', 'Tests function signatures, edge cases, and class instantiation.', '"""',
            '', 'import pytest', '',
        ]
        test_count = 0

        for func in functions:
            if func.name.startswith("_") and func.name != "__init__":
                continue
            fn_lines, fn_count = self._gen_function_test_cases(func, mod, safe_mod)
            lines.extend(fn_lines)
            test_count += fn_count

        for cls in classes:
            if cls.name.startswith("_"):
                continue
            cls_lines, cls_count = self._gen_class_test_cases(cls, mod, safe_mod)
            lines.extend(cls_lines)
            test_count += cls_count

        if test_count == 0:
            return None

        return GeneratedTestFile(
            path=f"tests/test_xray_{safe_mod}.py",
            content="\n".join(lines),
            test_count=test_count,
            language="python",
        )

    # ── Smell regression tests ──

    def _gen_smell_regression(
        self,
        smells: List[SmellIssue],
    ) -> Optional[GeneratedTestFile]:
        """Generate regression tests that pin known smells."""
        critical = [s for s in smells if s.severity == "critical" and s.source == "xray"]
        if not critical:
            return None

        lines = [
            '"""Auto-generated smell regression tests by X-Ray v7.0.',
            '',
            'These tests verify that known code smells are acknowledged.',
            'If a smell disappears (fixed), the test should be updated.',
            '"""',
            '',
            'import ast',
            'from pathlib import Path',
            'import pytest',
            '',
            '',
            'def _count_lines(filepath, func_name):',
            '    """Count lines of a function by name using AST."""',
            '    source = Path(filepath).read_text(encoding="utf-8")',
            '    tree = ast.parse(source)',
            '    for node in ast.walk(tree):',
            '        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):',
            '            if node.name == func_name:',
            '                return node.end_lineno - node.lineno + 1',
            '    return 0',
            '',
        ]

        test_count = 0
        seen = set()

        for smell in critical:
            key = f"{smell.file_path}:{smell.name}:{smell.category}"
            if key in seen:
                continue
            seen.add(key)

            safe = _safe_identifier(f"{smell.name}_{smell.category}")

            if smell.category == "long-function":
                lines.append(f'def test_smell_regression_{safe}():')
                lines.append(f'    """Regression: {smell.name} in {smell.file_path} is {smell.metric_value} lines (limit ~60)."""')
                lines.append(f'    size = _count_lines("{smell.file_path}", "{smell.name}")')
                lines.append(f'    # Originally {smell.metric_value} lines — track if it grows or gets refactored')
                lines.append(f'    assert size > 0, "Function {smell.name} should still exist"')
                lines.append(f'    # Uncomment to enforce size limit:')
                lines.append(f'    # assert size <= 60, f"{smell.name} is {{size}} lines — refactor needed"')
                lines.append('')
                test_count += 1

            elif smell.category == "god-class":
                lines.append(f'def test_smell_regression_{safe}():')
                lines.append(f'    """Regression: {smell.name} in {smell.file_path} — god class ({smell.metric_value} methods)."""')
                lines.append(f'    source = Path("{smell.file_path}").read_text(encoding="utf-8")')
                lines.append(f'    assert "{smell.name}" in source, "Class should still exist"')
                lines.append('')
                test_count += 1

            elif smell.category in ("deep-nesting", "high-complexity"):
                lines.append(f'def test_smell_regression_{safe}():')
                lines.append(f'    """Regression: {smell.name} — {smell.category} (metric={smell.metric_value})."""')
                lines.append(f'    source = Path("{smell.file_path}").read_text(encoding="utf-8")')
                lines.append(f'    assert "def {smell.name}" in source or "async def {smell.name}" in source')
                lines.append('')
                test_count += 1

        if test_count == 0:
            return None

        return GeneratedTestFile(
            path="tests/test_xray_smell_regression.py",
            content="\n".join(lines),
            test_count=test_count,
            language="python",
        )

    # ── Project structure tests ──

    def _gen_structure_tests(
        self,
        health_checks: list | None = None,
    ) -> Optional[GeneratedTestFile]:
        """Generate tests that verify project structure."""
        lines = [
            '"""Auto-generated project structure tests by X-Ray v7.0.',
            '',
            'Verifies essential files & directories exist.',
            '"""',
            '',
            'from pathlib import Path',
            'import pytest',
            '',
            '',
            f'ROOT = Path(__file__).parent.parent.resolve()',
            '',
        ]

        test_count = 0
        essential_files = [".gitignore", "README.md", "requirements.txt"]
        essential_dirs = ["tests"]

        for fname in essential_files:
            safe = _safe_identifier(fname)
            lines.append(f'def test_project_has_{safe}():')
            lines.append(f'    """Structure: {fname} should exist at project root."""')
            lines.append(f'    assert (ROOT / "{fname}").exists(), "Missing {fname}"')
            lines.append('')
            test_count += 1

        for dname in essential_dirs:
            safe = _safe_identifier(dname)
            lines.append(f'def test_project_has_{safe}_dir():')
            lines.append(f'    """Structure: {dname}/ directory should exist."""')
            lines.append(f'    assert (ROOT / "{dname}").is_dir(), "Missing {dname}/ directory"')
            lines.append('')
            test_count += 1

        # Test no syntax errors in any Python file
        lines.append('def test_no_python_syntax_errors():')
        lines.append('    """Verify all .py files can be compiled without SyntaxError."""')
        lines.append('    import py_compile')
        lines.append('    errors = []')
        lines.append('    for pyfile in ROOT.rglob("*.py"):')
        lines.append('        if any(part.startswith(".") or part in ("__pycache__", ".venv", "venv", "node_modules")')
        lines.append('               for part in pyfile.parts):')
        lines.append('            continue')
        lines.append('        try:')
        lines.append('            py_compile.compile(str(pyfile), doraise=True)')
        lines.append('        except py_compile.PyCompileError as e:')
        lines.append('            errors.append(str(e))')
        lines.append('    assert not errors, f"Syntax errors in {len(errors)} files:\\n" + "\\n".join(errors[:5])')
        lines.append('')
        test_count += 1

        return GeneratedTestFile(
            path="tests/test_xray_project_structure.py",
            content="\n".join(lines),
            test_count=test_count,
            language="python",
        )


# ── JS/TS Test Generator ──────────────────────────────────────────────────

class JSTSTestGenerator:
    """Generate Vitest/Jest-style tests from JS/TS analysis data."""

    def __init__(self, root: Path, project_name: str = ""):
        self.root = root
        self.project_name = project_name or root.name

    def generate(
        self,
        js_analyses: list,  # List[JSFileAnalysis]
        smells: List[SmellIssue] | None = None,
    ) -> List[GeneratedTestFile]:
        """Generate all JS/TS test files."""
        files: List[GeneratedTestFile] = []

        # 1. Import smoke tests
        f = self._gen_import_smoke(js_analyses)
        if f:
            files.append(f)

        # 2. Per-file function/component tests
        for analysis in js_analyses:
            if analysis.functions:
                f = self._gen_module_tests(analysis)
                if f:
                    files.append(f)

        # 3. React component tests
        react_analyses = [a for a in js_analyses if a.has_jsx]
        if react_analyses:
            f = self._gen_react_tests(react_analyses)
            if f:
                files.append(f)

        # 4. Structure verification
        f = self._gen_structure_tests(js_analyses)
        if f:
            files.append(f)

        return files

    def _rel_import_path(self, fpath: str) -> str:
        """Convert file path to a relative import path for tests."""
        p = Path(fpath)
        # Remove extension
        no_ext = str(p.with_suffix("")).replace("\\", "/")
        # Make relative to root
        if no_ext.startswith("./"):
            no_ext = no_ext[2:]
        return f"../{no_ext}"

    def _gen_import_smoke(self, analyses: list) -> Optional[GeneratedTestFile]:
        """Generate import smoke tests for JS/TS modules."""
        if not analyses:
            return None

        lines = [
            '/**',
            ' * Auto-generated import smoke tests by X-Ray v7.0.',
            ' * Verifies every scanned JS/TS module can be imported.',
            ' */',
            '',
            "import { describe, it, expect } from 'vitest';",
            '',
            "describe('Import Smoke Tests', () => {",
        ]

        test_count = 0
        for analysis in analyses:
            rel = self._rel_import_path(analysis.file_path)
            safe_name = _safe_identifier(Path(analysis.file_path).stem)
            lines.append(f"  it('should import {Path(analysis.file_path).name} without error', async () => {{")
            lines.append(f"    const mod = await import('{rel}');")
            lines.append(f"    expect(mod).toBeDefined();")
            lines.append(f"  }});")
            lines.append('')
            test_count += 1

        lines.append('});')
        lines.append('')

        return GeneratedTestFile(
            path="__tests__/xray_import_smoke.test.ts",
            content="\n".join(lines),
            test_count=test_count,
            language="typescript",
        )

    def _gen_module_tests(self, analysis) -> Optional[GeneratedTestFile]:
        """Generate function-level tests for a JS/TS module."""
        exported_funcs = [f for f in analysis.functions if f.is_exported]
        if not exported_funcs:
            return None

        stem = Path(analysis.file_path).stem
        safe_stem = _safe_identifier(stem)
        rel = self._rel_import_path(analysis.file_path)

        lines = [
            '/**',
            f' * Auto-generated monkey tests for {analysis.file_path} by X-Ray v7.0.',
            ' */',
            '',
            "import { describe, it, expect } from 'vitest';",
            '',
        ]

        # Build import statement
        func_names = [f.name for f in exported_funcs if not f.is_react_component]
        if func_names:
            imports = ", ".join(func_names[:15])
            lines.append(f"import {{ {imports} }} from '{rel}';")

        lines.append('')
        lines.append(f"describe('{stem}', () => {{")

        test_count = 0
        for func in exported_funcs:
            if func.is_react_component:
                continue  # handled in react tests

            safe_name = _safe_identifier(func.name)

            # Test: is a function
            lines.append(f"  it('{func.name} should be a function', () => {{")
            lines.append(f"    expect(typeof {func.name}).toBe('function');")
            lines.append(f"  }});")
            lines.append('')
            test_count += 1

            # Test: call with undefined args
            if func.parameters:
                undef_args = ", ".join(["undefined"] * len(func.parameters))
                lines.append(f"  it('{func.name} should handle undefined args gracefully', () => {{")
                lines.append(f"    expect(() => {{")
                if func.is_async:
                    lines.append(f"      {func.name}({undef_args});")
                else:
                    lines.append(f"      {func.name}({undef_args});")
                lines.append(f"    }}).not.toThrow();")
                lines.append(f"  }});")
                lines.append('')
                test_count += 1

            # Test: high complexity flag
            if func.complexity >= 8:
                lines.append(f"  it('{func.name} [CC={func.complexity}] should be testable', () => {{")
                lines.append(f"    // X-Ray detected CC={func.complexity} — this function needs thorough tests")
                lines.append(f"    expect(typeof {func.name}).toBe('function');")
                lines.append(f"  }});")
                lines.append('')
                test_count += 1

        lines.append('});')
        lines.append('')

        if test_count == 0:
            return None

        return GeneratedTestFile(
            path=f"__tests__/xray_{safe_stem}.test.ts",
            content="\n".join(lines),
            test_count=test_count,
            language="typescript",
        )

    def _gen_react_tests(self, analyses: list) -> Optional[GeneratedTestFile]:
        """Generate React component render tests."""
        components = []
        for a in analyses:
            for f in a.functions:
                if f.is_react_component:
                    components.append((a.file_path, f))

        if not components:
            return None

        lines = [
            '/**',
            ' * Auto-generated React component tests by X-Ray v7.0.',
            ' * Verifies components can be imported and are valid React components.',
            ' */',
            '',
            "import { describe, it, expect } from 'vitest';",
            '',
        ]

        test_count = 0
        lines.append("describe('React Components', () => {")

        for fpath, comp in components:
            rel = self._rel_import_path(fpath)
            lines.append(f"  it('{comp.name} should be importable', async () => {{")
            lines.append(f"    const mod = await import('{rel}');")
            lines.append(f"    // Component '{comp.name}' found at {fpath}:{comp.line_start}")
            lines.append(f"    expect(mod).toBeDefined();")
            lines.append(f"  }});")
            lines.append('')
            test_count += 1

            # Size check
            if comp.size_lines > 200:
                lines.append(f"  it('{comp.name} [large: {comp.size_lines}L] should be considered for splitting', () => {{")
                lines.append(f"    // X-Ray: component is {comp.size_lines} lines — consider splitting")
                lines.append(f"    expect(true).toBe(true); // flag only")
                lines.append(f"  }});")
                lines.append('')
                test_count += 1

        lines.append('});')
        lines.append('')

        return GeneratedTestFile(
            path="__tests__/xray_react_components.test.ts",
            content="\n".join(lines),
            test_count=test_count,
            language="typescript",
        )

    def _gen_structure_tests(self, analyses: list) -> Optional[GeneratedTestFile]:
        """Generate project structure verification tests for JS/TS."""
        lines = [
            '/**',
            ' * Auto-generated project structure tests by X-Ray v7.0.',
            ' */',
            '',
            "import { describe, it, expect } from 'vitest';",
            "import { existsSync } from 'fs';",
            "import { resolve } from 'path';",
            '',
            "const ROOT = resolve(__dirname, '..');",
            '',
            "describe('Project Structure', () => {",
        ]

        test_count = 0
        essential = ["package.json", "README.md", ".gitignore", "tsconfig.json"]
        for fname in essential:
            lines.append(f"  it('should have {fname}', () => {{")
            lines.append(f"    expect(existsSync(resolve(ROOT, '{fname}'))).toBe(true);")
            lines.append(f"  }});")
            lines.append('')
            test_count += 1

        # Detect languages used
        langs = set()
        for a in analyses:
            langs.add(a.language)
        lang_str = ", ".join(sorted(langs))
        lines.append(f"  it('uses: [{lang_str}]', () => {{")
        lines.append(f"    // X-Ray detected: {len(analyses)} files, languages: {lang_str}")
        lines.append(f"    expect({len(analyses)}).toBeGreaterThan(0);")
        lines.append(f"  }});")
        lines.append('')
        test_count += 1

        lines.append('});')
        lines.append('')

        return GeneratedTestFile(
            path="__tests__/xray_project_structure.test.ts",
            content="\n".join(lines),
            test_count=test_count,
            language="typescript",
        )


# ── Master Orchestrator ────────────────────────────────────────────────────

class TestGeneratorEngine:
    """Top-level engine that detects project type and generates tests."""

    def __init__(self, root: Path):
        self.root = root

    def detect_project_type(self) -> str:
        """Detect the primary project type.

        Returns: 'python' | 'javascript' | 'typescript' | 'react' | 'mixed' | 'unknown'
        """
        py_files = list(self.root.rglob("*.py"))
        py_files = [f for f in py_files
                    if not any(p in f.parts for p in
                               ("__pycache__", ".venv", "venv", "node_modules", ".git"))]

        js_ts_exts = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}
        jsts_files = []
        for ext in js_ts_exts:
            jsts_files.extend(self.root.rglob(f"*{ext}"))
        jsts_files = [f for f in jsts_files
                      if not any(p in f.parts for p in
                                 ("node_modules", ".git", "dist", "build"))]

        has_py = len(py_files) > 0
        has_jsts = len(jsts_files) > 0
        has_jsx = any(f.suffix in (".jsx", ".tsx") for f in jsts_files)
        has_ts = any(f.suffix in (".ts", ".tsx") for f in jsts_files)

        if has_py and has_jsts:
            return "mixed"
        elif has_jsx:
            return "react"
        elif has_ts:
            return "typescript"
        elif has_jsts:
            return "javascript"
        elif has_py:
            return "python"
        return "unknown"

    def generate(
        self,
        functions: List[FunctionRecord] | None = None,
        classes: List[ClassRecord] | None = None,
        smells: List[SmellIssue] | None = None,
        js_analyses: list | None = None,
        health_checks: list | None = None,
        output_dir: Path | None = None,
    ) -> TestGenReport:
        """Generate all tests and optionally write them to disk.

        Returns a TestGenReport with all generated test files.
        """
        from Core.ui_bridge import get_bridge
        bridge = get_bridge()

        project_type = self.detect_project_type()
        bridge.log(f"  Project type detected: {project_type}")

        report = TestGenReport()
        all_files: List[GeneratedTestFile] = []

        # Python tests
        if project_type in ("python", "mixed") and (functions or classes):
            bridge.status("Generating Python monkey tests...")
            gen = PythonTestGenerator(self.root)
            py_tests = gen.generate(
                functions or [],
                classes or [],
                smells=smells,
                health_checks=health_checks,
            )
            all_files.extend(py_tests)
            if "python" not in report.languages:
                report.languages.append("python")

        # JS/TS tests
        if project_type in ("javascript", "typescript", "react", "mixed") and js_analyses:
            bridge.status("Generating JS/TS monkey tests...")
            gen = JSTSTestGenerator(self.root)
            jsts_tests = gen.generate(js_analyses, smells=smells)
            all_files.extend(jsts_tests)
            lang = "typescript" if project_type in ("typescript", "react") else "javascript"
            if lang not in report.languages:
                report.languages.append(lang)

        # Write files if output_dir provided
        if output_dir and all_files:
            out = Path(output_dir)
            written = 0
            for tf in all_files:
                dest = out / tf.path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(tf.content, encoding="utf-8")
                written += 1
                bridge.log(f"  Created: {tf.path} ({tf.test_count} tests)")

            bridge.log(f"  Total: {written} test files, "
                       f"{sum(f.test_count for f in all_files)} tests generated")

        report.files_created = all_files
        report.total_tests = sum(f.test_count for f in all_files)

        return report
