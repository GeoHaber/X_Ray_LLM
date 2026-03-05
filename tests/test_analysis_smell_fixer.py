"""
tests/test_analysis_smell_fixer.py
====================================
Tests for Analysis/smell_fixer.py — auto-fix engine for the --fix-smells flag.
"""

import textwrap
from pathlib import Path


from Analysis.smell_fixer import SmellFixer, SmellFixResult


def _write(tmp_path: Path, filename: str, content: str) -> Path:
    f = tmp_path / filename
    f.write_text(textwrap.dedent(content), encoding="utf-8")
    return f


# ── SmellFixResult ────────────────────────────────────────────────────────────


class TestSmellFixResult:
    def test_initial_state(self):
        r = SmellFixResult()
        assert r.fixes_applied == 0
        assert r.files_modified == []
        assert r.console_logs_commented == 0
        assert r.prints_commented == 0
        assert r.errors == []

    def test_to_dict(self):
        r = SmellFixResult()
        r.fixes_applied = 5
        r.console_logs_commented = 3
        d = r.to_dict()
        assert isinstance(d, dict)
        assert d["fixes_applied"] == 5
        assert d["console_logs_commented"] == 3


# ── _comment_console_lines ────────────────────────────────────────────────────


class TestCommentConsoleLines:
    def _run(self, content):
        fixer = SmellFixer(dry_run=True)
        return fixer._comment_console_lines(content)

    def test_comments_console_log(self):
        new, count = self._run('console.log("debug");\n')
        assert count == 1

    def test_comments_console_warn(self):
        new, count = self._run('console.warn("oops");\n')
        assert count >= 1

    def test_no_change_on_clean(self):
        new, count = self._run("function f() { return 1; }\n")
        assert count == 0

    def test_already_commented_skipped(self):
        new, count = self._run('// console.log("ok");\n')
        assert count == 0

    def test_multiple_logs(self):
        content = 'console.log("a");\nconsole.log("b");\nconsole.log("c");\n'
        new, count = self._run(content)
        assert count == 3

    def test_preserves_other_lines(self):
        content = "const x = 1;\nconsole.log(x);\nconst y = 2;\n"
        new, count = self._run(content)
        assert "const x = 1;" in new
        assert "const y = 2;" in new


# ── _comment_debug_prints ─────────────────────────────────────────────────────


class TestCommentDebugPrints:
    def _run(self, content):
        fixer = SmellFixer(dry_run=True)
        return fixer._comment_debug_prints(content)

    def test_comments_debug_print(self):
        new, count = self._run('print(f"DEBUG: {val}")\n')
        assert count >= 1

    def test_preserves_usage_print(self):
        new, count = self._run('print("Usage: run.py [options]")\n')
        assert count == 0
        assert new.strip().startswith("print")

    def test_preserves_error_print(self):
        new, count = self._run('print("Error: file not found")\n')
        assert count == 0

    def test_multiple_debug_prints(self):
        content = 'print(f"DEBUG: {a}")\nprint(f"DEBUG: {b}")\n'
        new, count = self._run(content)
        assert count >= 2


# ── File-level fixes ─────────────────────────────────────────────────────────


class TestFileLevel:
    def test_fix_js_console_logs(self, tmp_path):
        f = _write(
            tmp_path,
            "app.js",
            textwrap.dedent("""
            function debug() {
                console.log("value");
                console.log("other");
            }
        """),
        )
        SmellFixer(dry_run=False)._fix_console_logs(tmp_path, exclude=None)
        content = f.read_text()
        # [X-Ray auto-fix] is prefixed to commented-out lines
        assert "[X-Ray auto-fix]" in content or content.count("console.log") == 0

    def test_dry_run_js_unchanged(self, tmp_path):
        f = _write(tmp_path, "app.js", 'console.log("test");\n')
        original = f.read_text()
        SmellFixer(dry_run=True)._fix_console_logs(tmp_path, exclude=None)
        assert f.read_text() == original

    def test_excludes_vendor_dir(self, tmp_path):
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        f = _write(vendor, "lib.js", 'console.log("skip");\n')
        original = f.read_text()
        SmellFixer(dry_run=False)._fix_console_logs(tmp_path, exclude=["vendor"])
        assert f.read_text() == original

    def test_fix_python_debug_prints(self, tmp_path):
        f = _write(
            tmp_path,
            "debug.py",
            textwrap.dedent("""
            def process():
                print(f"DEBUG: starting")
                result = 42
                print(f"DEBUG: result={result}")
                return result
        """),
        )
        SmellFixer(dry_run=False)._fix_debug_prints(tmp_path, exclude=None)
        content = f.read_text()
        # [X-Ray auto-fix] is prefixed to commented-out debug prints
        assert "[X-Ray auto-fix]" in content or content.count('print(f"DEBUG') == 0


# ── SmellFixer.fix_all ────────────────────────────────────────────────────────


class TestFixAll:
    def test_returns_smell_fix_result(self, tmp_path):
        _write(tmp_path, "app.js", "function f() {}\n")
        result = SmellFixer(dry_run=True).fix_all(tmp_path)
        assert isinstance(result, SmellFixResult)

    def test_fix_console_counted(self, tmp_path):
        _write(tmp_path, "app.js", 'console.log("debug");\n')
        result = SmellFixer(dry_run=False).fix_all(
            tmp_path, fix_console=True, fix_prints=False, fix_project=False
        )
        assert result.console_logs_commented >= 1
        assert result.fixes_applied >= 1

    def test_dry_run_no_files_changed(self, tmp_path):
        f = _write(tmp_path, "app.js", 'console.log("hi");\n')
        original = f.read_text()
        SmellFixer(dry_run=True).fix_all(tmp_path)
        assert f.read_text() == original

    def test_fix_all_with_exclusions(self, tmp_path):
        skip = tmp_path / "vendor"
        skip.mkdir()
        f = _write(skip, "lib.js", 'console.log("skip");\n')
        original = f.read_text()
        SmellFixer(dry_run=False).fix_all(
            tmp_path,
            exclude=["vendor"],
            fix_console=True,
            fix_prints=False,
            fix_project=False,
        )
        assert f.read_text() == original

    def test_files_modified_reported(self, tmp_path):
        _write(tmp_path, "a.js", 'console.log("x");\n')
        _write(tmp_path, "b.js", 'console.log("y");\n')
        result = SmellFixer(dry_run=False).fix_all(
            tmp_path, fix_console=True, fix_prints=False, fix_project=False
        )
        assert len(result.files_modified) >= 1

    def test_to_dict_after_fix(self, tmp_path):
        _write(tmp_path, "app.js", 'console.log("test");\n')
        result = SmellFixer(dry_run=False).fix_all(tmp_path)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "fixes_applied" in d
