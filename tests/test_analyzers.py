"""
Tests for analyzers.py — comprehensive coverage of all analyzer functions.
================================
Run:  python -m pytest tests/test_analyzers.py -v --tb=short
"""

import os
import sys
import textwrap

# Allow importing from the project root
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from analyzers import (  # noqa: E402
    analyze_connections,
    check_format,
    check_project_health,
    check_release_readiness,
    compute_architecture_map,
    compute_call_graph,
    compute_confidence_meter,
    compute_coupling_metrics,
    compute_module_cards,
    compute_project_review,
    compute_risk_heatmap,
    compute_sprint_batches,
    detect_ai_code,
    detect_circular_calls,
    detect_code_smells,
    detect_dead_functions,
    detect_duplicates,
    detect_unused_imports,
    detect_web_smells,
    estimate_remediation_time,
    generate_test_stubs,
    run_bandit,
)

# scan_satd, analyze_git_hotspots, parse_imports live in ui_server.py
from ui_server import analyze_git_hotspots, parse_imports, scan_satd  # noqa: E402


def _write_file(directory, name, content):
    """Helper: write a file under *directory* and return its path."""
    fpath = os.path.join(str(directory), name)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(content))
    return fpath


class TestAnalyzers:
    """Tests for every public analyzer function."""

    # ── 1. detect_code_smells ────────────────────────────────────────
    def test_detect_code_smells(self, tmp_path):
        """A function >50 lines should be flagged as long_function."""
        body = "\n".join(f"    x_{i} = {i}" for i in range(55))
        _write_file(tmp_path, "big.py", f"def huge():\n{body}\n")

        result = detect_code_smells(str(tmp_path))
        assert isinstance(result, dict)
        assert "smells" in result
        assert len(result["smells"]) > 0
        smell_types = [s["smell"] for s in result["smells"]]
        assert "long_function" in smell_types

    # ── 2. detect_duplicates ─────────────────────────────────────────
    def test_detect_duplicates(self, tmp_path):
        """Two files with the same 8-line block should produce a duplicate group."""
        block = "\n".join(f"x_{i} = {i} + 1" for i in range(10))
        _write_file(tmp_path, "a.py", block + "\n")
        _write_file(tmp_path, "b.py", block + "\n")

        result = detect_duplicates(str(tmp_path))
        assert isinstance(result, dict)
        assert "duplicate_groups" in result
        assert len(result["duplicate_groups"]) > 0

    # ── 3. scan_satd ─────────────────────────────────────────────────
    def test_scan_satd(self, tmp_path):
        """TODO and FIXME markers should be detected as SATD items."""
        _write_file(
            tmp_path,
            "debt.py",
            """\
            # TODO: fix this
            # FIXME: urgent
            x = 1
            """,
        )

        result = scan_satd(str(tmp_path))
        assert isinstance(result, dict)
        assert "items" in result
        assert result["total_items"] >= 2
        assert result["total_hours"] > 0

    # ── 4. analyze_git_hotspots ──────────────────────────────────────
    def test_analyze_git_hotspots(self):
        """Running on the X-Ray repo itself should return a dict with hotspots key."""
        result = analyze_git_hotspots(REPO_ROOT)
        assert isinstance(result, dict)
        assert "hotspots" in result

    # ── 5. parse_imports ─────────────────────────────────────────────
    def test_parse_imports(self, tmp_path):
        """A file with two imports should produce nodes and edges."""
        _write_file(
            tmp_path,
            "mod.py",
            """\
            import os
            import sys
            """,
        )

        result = parse_imports(str(tmp_path))
        assert isinstance(result, dict)
        assert "nodes" in result
        assert "edges" in result

    # ── 6. detect_dead_functions ─────────────────────────────────────
    def test_detect_dead_functions(self, tmp_path):
        """A function that is never called should be detected as dead."""
        _write_file(
            tmp_path,
            "funcs.py",
            """\
            def used():
                a = 1
                b = 2
                c = 3
                d = 4
                return a + b + c + d

            def unused():
                a = 1
                b = 2
                c = 3
                d = 4
                return a + b + c + d

            used()
            """,
        )

        result = detect_dead_functions(str(tmp_path))
        assert isinstance(result, dict)
        assert "dead_functions" in result
        dead_names = [f["name"] for f in result["dead_functions"]]
        assert "unused" in dead_names

    # ── 7. run_bandit ────────────────────────────────────────────────
    def test_run_bandit(self, tmp_path):
        """run_bandit should return a dict with bandit_issues key regardless of bandit availability."""
        _write_file(
            tmp_path,
            "insecure.py",
            """\
            x = eval(input())
            """,
        )

        result = run_bandit(str(tmp_path))
        assert isinstance(result, dict)
        assert "bandit_issues" in result
        assert "secrets" in result
        assert "total_issues" in result

    # ── 8. check_format ──────────────────────────────────────────────
    def test_check_format(self, tmp_path):
        """check_format should return a dict with needs_format and files keys."""
        _write_file(tmp_path, "sample.py", "x=1\n")

        result = check_format(str(tmp_path))
        assert isinstance(result, dict)
        # If ruff is not installed, result will have 'error' key instead
        if "error" not in result:
            assert "needs_format" in result
            assert "files" in result

    # ── 9. check_project_health ──────────────────────────────────────
    def test_check_project_health(self, tmp_path):
        """check_project_health on an empty dir returns a dict with score and checks."""
        result = check_project_health(str(tmp_path))
        assert isinstance(result, dict)
        assert "score" in result
        assert isinstance(result["score"], (int, float))
        assert "checks" in result
        assert isinstance(result["checks"], list)

    # ── 10. detect_ai_code ───────────────────────────────────────────
    def test_detect_ai_code(self, tmp_path):
        """A file with an AI generation comment should be flagged."""
        _write_file(
            tmp_path,
            "ai_gen.py",
            """\
            # Generated by AI assistant
            def hello():
                pass
            """,
        )

        result = detect_ai_code(str(tmp_path))
        assert isinstance(result, dict)
        assert "indicators" in result
        assert len(result["indicators"]) > 0

    # ── 11. detect_web_smells ────────────────────────────────────────
    def test_detect_web_smells(self, tmp_path):
        """A JS file with document.write should be flagged as a web smell."""
        _write_file(tmp_path, "bad.js", 'document.write("hello");\n')

        result = detect_web_smells(str(tmp_path))
        assert isinstance(result, dict)
        assert "smells" in result
        assert len(result["smells"]) > 0

    # ── 12. generate_test_stubs ──────────────────────────────────────
    def test_generate_test_stubs(self, tmp_path):
        """A Python file with a public function should generate a test stub."""
        _write_file(
            tmp_path,
            "lib.py",
            """\
            def my_func(x):
                a = x * 2
                return a
            """,
        )

        result = generate_test_stubs(str(tmp_path))
        assert isinstance(result, dict)
        assert "stubs" in result
        assert result["total_functions"] >= 1

    # ── 13. check_release_readiness ──────────────────────────────────
    def test_check_release_readiness(self, tmp_path):
        """check_release_readiness returns dict with score, checks, and ready keys."""
        result = check_release_readiness(str(tmp_path))
        assert isinstance(result, dict)
        assert "score" in result
        assert "checks" in result
        assert "ready" in result

    # ── 14. estimate_remediation_time ────────────────────────────────
    def test_estimate_remediation_time(self):
        """Dummy findings should produce non-zero total_minutes."""
        findings = [
            {"rule_id": "SEC-001"},
            {"rule_id": "PY-001"},
        ]
        result = estimate_remediation_time(findings)
        assert isinstance(result, dict)
        assert result["total_minutes"] > 0
        assert "total_hours" in result
        assert "per_finding" in result

    # ── 15. compute_risk_heatmap ─────────────────────────────────────
    def test_compute_risk_heatmap(self, tmp_path):
        """compute_risk_heatmap on an empty-ish dir returns a dict."""
        _write_file(tmp_path, "empty.py", "x = 1\n")

        result = compute_risk_heatmap(str(tmp_path))
        assert isinstance(result, dict)
        assert "files" in result
        assert "total_files" in result

    # ── 16. compute_module_cards ─────────────────────────────────────
    def test_compute_module_cards(self, tmp_path):
        """compute_module_cards returns a dict with modules key."""
        _write_file(tmp_path, "mod.py", "x = 1\n")

        result = compute_module_cards(str(tmp_path))
        assert isinstance(result, dict)
        assert "modules" in result
        assert "total_modules" in result

    # ── 17. compute_confidence_meter ─────────────────────────────────
    def test_compute_confidence_meter(self, tmp_path):
        """compute_confidence_meter returns a dict with a numeric confidence score."""
        _write_file(tmp_path, "app.py", "x = 1\n")

        result = compute_confidence_meter(str(tmp_path))
        assert isinstance(result, dict)
        assert "confidence" in result
        assert isinstance(result["confidence"], (int, float))

    # ── 18. compute_sprint_batches ───────────────────────────────────
    def test_compute_sprint_batches(self):
        """Dummy findings should be grouped into batches."""
        findings = [
            {"rule_id": "SEC-001", "severity": "HIGH", "file": "a.py", "line": 1},
            {"rule_id": "QUAL-001", "severity": "MEDIUM", "file": "b.py", "line": 2},
        ]
        result = compute_sprint_batches(findings=findings)
        assert isinstance(result, dict)
        assert "batches" in result
        assert isinstance(result["batches"], list)
        assert len(result["batches"]) > 0
        assert result["total_items"] == 2

    # ── 19. compute_architecture_map ─────────────────────────────────
    def test_compute_architecture_map(self, tmp_path):
        """compute_architecture_map on a dir with .py files returns a dict with nodes/edges."""
        _write_file(tmp_path, "main.py", "import os\nx = 1\n")

        result = compute_architecture_map(str(tmp_path))
        assert isinstance(result, dict)
        assert "nodes" in result
        assert "edges" in result
        assert "layers" in result

    # ── 20. compute_call_graph ───────────────────────────────────────
    def test_compute_call_graph(self, tmp_path):
        """A file with two functions (one calling the other) produces a call graph."""
        _write_file(
            tmp_path,
            "calls.py",
            """\
            def a():
                b()

            def b():
                pass
            """,
        )

        result = compute_call_graph(str(tmp_path))
        assert isinstance(result, dict)
        assert "nodes" in result
        assert "edges" in result
        assert result["total_functions"] >= 2

    # ── 21. detect_circular_calls ────────────────────────────────────
    def test_detect_circular_calls(self, tmp_path):
        """detect_circular_calls returns a dict with expected keys."""
        _write_file(
            tmp_path,
            "circular.py",
            """\
            def alpha():
                beta()

            def beta():
                alpha()
            """,
        )

        result = detect_circular_calls(str(tmp_path))
        assert isinstance(result, dict)
        assert "circular_calls" in result
        assert "total_functions" in result
        assert "recursive_functions" in result

    # ── 22. compute_coupling_metrics ─────────────────────────────────
    def test_compute_coupling_metrics(self, tmp_path):
        """compute_coupling_metrics returns a dict with modules and summary."""
        _write_file(tmp_path, "a.py", "x = 1\n")
        _write_file(tmp_path, "b.py", "import a\ny = 2\n")

        result = compute_coupling_metrics(str(tmp_path))
        assert isinstance(result, dict)
        assert "modules" in result
        assert "total_modules" in result
        assert "health_summary" in result

    # ── 23. detect_unused_imports ────────────────────────────────────
    def test_detect_unused_imports(self, tmp_path):
        """An unused import (sys imported but never used) should be detected."""
        _write_file(
            tmp_path,
            "unused.py",
            """\
            import sys
            x = 1
            """,
        )

        result = detect_unused_imports(str(tmp_path))
        assert isinstance(result, dict)
        assert "unused_imports" in result
        unused_names = [i["import_name"] for i in result["unused_imports"]]
        assert "sys" in unused_names

    # ── 24. compute_project_review ───────────────────────────────────
    def test_compute_project_review(self, tmp_path):
        """compute_project_review returns a dict with score and letter grade."""
        _write_file(tmp_path, "app.py", "x = 1\n")

        result = compute_project_review(str(tmp_path))
        assert isinstance(result, dict)
        assert "score" in result
        assert "letter" in result

    # ── 25. analyze_connections ──────────────────────────────────────
    def test_analyze_connections(self, tmp_path):
        """analyze_connections returns a dict with wired, orphan_ui, orphan_backend keys."""
        _write_file(tmp_path, "app.py", "x = 1\n")

        result = analyze_connections(str(tmp_path))
        assert isinstance(result, dict)
        assert "wired" in result
        assert "orphan_ui" in result
        assert "orphan_backend" in result
        assert "summary" in result
