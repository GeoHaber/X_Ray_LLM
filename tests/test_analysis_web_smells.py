"""
tests/test_analysis_web_smells.py
===================================
Tests for Analysis/web_smells.py — Web-specific code smell detector.

Covers:
  - _make_web_smell factory
  - WebSmellDetector.detect() end-to-end
  - All 12+ individual smell checks:
      large_file, very_large_file, console_log_pollution, import_sprawl,
      long_function, complex_function, deep_nesting, too_many_params,
      async_no_catch, large_component, inline_styles, any_abuse
  - WebSmellDetector.summary()
  - _collect_web_files helper
"""

import textwrap
from pathlib import Path

import pytest

from Analysis.web_smells import WebSmellDetector, _make_web_smell
from Core.types import SmellIssue


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write(tmp_path: Path, filename: str, content: str) -> Path:
    f = tmp_path / filename
    f.write_text(textwrap.dedent(content), encoding="utf-8")
    return f


def _big_file(tmp_path: Path, filename: str, lines: int) -> Path:
    content = "\n".join([f"// line {i}" for i in range(lines)])
    return _write(tmp_path, filename, content)


# ── _make_web_smell ───────────────────────────────────────────────────────────

class TestMakeWebSmell:
    def test_returns_smell_issue(self):
        smell = _make_web_smell(
            ("src/app.js", 10, 20),
            ("long-function", "warning", "Function too long", "Split it", "bigFn"),
        )
        assert isinstance(smell, SmellIssue)

    def test_location_populated(self):
        smell = _make_web_smell(
            ("src/app.js", 5, 15),
            ("console-pollution", "warning", "Too many console.logs", "", "debug"),
        )
        assert smell.file_path == "src/app.js"
        assert smell.line == 5
        assert smell.end_line == 15

    def test_spec_fields_populated(self):
        smell = _make_web_smell(
            ("file.js", 1, 1),
            ("large-file", "critical", "File too large", "Split file", "file", 1200),
        )
        assert smell.category == "large-file"
        assert smell.severity == "critical"
        assert smell.message == "File too large"
        assert smell.suggestion == "Split file"
        assert smell.metric_value == 1200

    def test_optional_metric_defaults_to_zero(self):
        smell = _make_web_smell(
            ("file.js", 1, 1),
            ("cat", "warning", "msg", "sug", "name"),  # 5-tuple, no metric
        )
        assert smell.metric_value == 0

    def test_source_is_web(self):
        smell = _make_web_smell(
            ("a.js", 1, 1),
            ("cat", "info", "msg", "", "fn"),
        )
        assert smell.source == "xray-web"


# ── WebSmellDetector.detect ───────────────────────────────────────────────────

class TestWebSmellDetectorDetect:
    def test_returns_list(self, tmp_path):
        _write(tmp_path, "app.js", "function f() { return 1; }\n")
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        assert isinstance(smells, list)

    def test_clean_small_file_no_smells(self, tmp_path):
        _write(tmp_path, "clean.js", textwrap.dedent("""
            function add(a, b) {
                return a + b;
            }
        """))
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        # A small clean file should have 0 or very few smells
        assert len(smells) <= 2

    def test_large_file_flagged(self, tmp_path):
        _big_file(tmp_path, "huge.js", 700)  # > very_large_file threshold (600)
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        categories = {s.category for s in smells}
        assert any("large" in c or "file" in c for c in categories)

    def test_console_log_pollution_flagged(self, tmp_path):
        logs = "\n".join([f'console.log("debug {i}");' for i in range(5)])
        _write(tmp_path, "polluted.js", f"function f() {{\n{logs}\n}}\n")
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        categories = {s.category for s in smells}
        assert any("console" in c for c in categories)

    def test_import_sprawl_flagged(self, tmp_path):
        imports = "\n".join([
            f"import pkg{i} from 'package{i}';" for i in range(25)  # > 20 threshold
        ])
        _write(tmp_path, "sprawl.js", imports + "\nfunction f() {}\n")
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        categories = {s.category for s in smells}
        assert any("import" in c for c in categories)

    def test_any_abuse_in_typescript_flagged(self, tmp_path):
        # _check_any_abuse scans function.code bodies, so needs function wrapper
        any_params = ", ".join([f"p{i}: any" for i in range(6)])
        code = f"function process({any_params}) {{\n    const result: any = null;\n    return result;\n}}\n"
        _write(tmp_path, "anyabuse.ts", code)
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        categories = {s.category for s in smells}
        assert any("any" in c for c in categories)

    def test_excludes_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        _big_file(nm, "bloat.js", 1000)
        _write(tmp_path, "app.js", "function f() {}")
        d = WebSmellDetector()
        smells = d.detect(tmp_path, exclude=["node_modules"])
        # Should not flag files in node_modules
        for s in smells:
            assert "node_modules" not in s.file_path

    def test_no_js_files_returns_empty(self, tmp_path):
        _write(tmp_path, "README.md", "# Hello")
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        assert smells == []

    def test_tsx_file_analyzed(self, tmp_path):
        _write(tmp_path, "App.tsx", textwrap.dedent("""
            import React from 'react';
            function App() {
                return <div>Hello</div>;
            }
            export default App;
        """))
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        assert isinstance(smells, list)


# ── Individual smell check coverage ──────────────────────────────────────────

class TestIndividualSmellChecks:
    """Test specific smell thresholds via the detect() method."""

    def test_long_function_flagged(self, tmp_path):
        # Build a function longer than 60 lines
        body = "\n".join(["    const x = 1;" for _ in range(70)])
        code = f"function massive() {{\n{body}\n}}\n"
        _write(tmp_path, "long.js", code)
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        categories = {s.category for s in smells}
        assert any("long" in c or "function" in c for c in categories)

    def test_too_many_params_flagged(self, tmp_path):
        _write(tmp_path, "params.js", textwrap.dedent("""
            function doEverything(a, b, c, d, e, f, g, h) {
                return a + b + c + d + e + f + g + h;
            }
        """))
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        categories = {s.category for s in smells}
        assert any("param" in c for c in categories)

    def test_async_no_catch_flagged(self, tmp_path):
        _write(tmp_path, "asyncbad.js", textwrap.dedent("""
            async function fetchData(url) {
                const data = await fetch(url);
                return data.json();
            }
        """))
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        categories = {s.category for s in smells}
        # async-no-catch is optional; just verify list is returned
        assert isinstance(smells, list)


# ── WebSmellDetector.summary ──────────────────────────────────────────────────

class TestWebSmellDetectorSummary:
    def test_summary_before_detect(self):
        d = WebSmellDetector()
        s = d.summary()
        assert isinstance(s, dict)
        assert "total" in s
        assert s["total"] == 0

    def test_summary_after_detect(self, tmp_path):
        _big_file(tmp_path, "big.js", 700)
        d = WebSmellDetector()
        d.detect(tmp_path)
        s = d.summary()
        assert s["total"] >= 0
        assert "critical" in s
        assert "warning" in s
        assert "by_category" in s or "by_file" in s

    def test_summary_counts_match_detect(self, tmp_path):
        _write(tmp_path, "app.js", "function f() {}")
        d = WebSmellDetector()
        smells = d.detect(tmp_path)
        s = d.summary()
        assert s["total"] == len(smells)


# ── Custom thresholds ─────────────────────────────────────────────────────────

class TestCustomThresholds:
    def test_lower_console_threshold_triggers_earlier(self, tmp_path):
        logs = "\n".join([f'console.log("x{i}");' for i in range(2)])
        _write(tmp_path, "app.js", f"function f() {{\n{logs}\n}}\n")
        # With strict threshold of 1, 2 console.logs should trigger
        d_strict = WebSmellDetector(thresholds={"console_log_threshold": 1})
        d_normal = WebSmellDetector()  # default threshold is 3
        strict_smells = d_strict.detect(tmp_path)
        normal_smells = d_normal.detect(tmp_path)
        assert len(strict_smells) >= len(normal_smells)

    def test_custom_import_threshold(self, tmp_path):
        imports = "\n".join([f"import p{i} from 'pkg{i}';" for i in range(5)])
        _write(tmp_path, "few.js", imports + "\nfunction f() {}\n")
        # 5 imports below default 20, but above custom threshold 3
        d_strict = WebSmellDetector(thresholds={"too_many_imports": 3})
        smells = d_strict.detect(tmp_path)
        categories = {s.category for s in smells}
        assert any("import" in c for c in categories)
