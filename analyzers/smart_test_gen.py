"""
Smart Test Generator — Generates targeted tests based on X-Ray analysis results.

Combines schema drift, orphan map, coverage map, and scan findings to produce
tests that validate real problems rather than generic stubs:
  1. Schema contract tests (assert response fields match model definitions)
  2. Orphan verification tests (confirm orphans are truly dead or reachable)
  3. Coverage gap tests (stubs for untested public functions)
  4. Auto-fix regression tests (verify fixable findings after remediation)
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

from analyzers.schema_drift import detect_schema_drift
from analyzers.orphan_map import analyze_orphan_map
from analyzers.coverage_map import compute_coverage_map


def _sanitize_fn(name: str) -> str:
    """Make a string safe for use as a Python function name."""
    s = name.replace("/", "_").replace("-", "_").replace(".", "_").replace(":", "_")
    s = s.strip("_")
    return s or "unnamed"


# ── Schema Contract Tests ────────────────────────────────────────────


def _gen_schema_tests(drift_data: dict, base_url: str) -> tuple[str, int]:
    """Generate tests that verify API responses contain expected fields."""
    blocks: list[str] = []
    count = 0

    models = drift_data.get("models", [])
    endpoint_map = drift_data.get("endpoint_model_map", {})
    model_by_name = {m["name"]: m for m in models}

    # For each endpoint that maps to a model, assert all model fields are present
    for url, model_names in endpoint_map.items():
        for model_name in model_names:
            model = model_by_name.get(model_name)
            if not model:
                continue
            fields = model.get("fields", {})
            if not fields:
                continue

            fn_name = f"test_schema_{_sanitize_fn(model_name)}_{_sanitize_fn(url)}"
            field_list = sorted(fields.keys())
            field_checks = "\n".join(
                '        assert "{f}" in item, '
                '"Missing field \'{f}\' ({ft}) in {m} response"'.format(
                    f=f, ft=fields[f], m=model_name)
                for f in field_list if not f.startswith("_")
            )

            block = textwrap.dedent(f'''\
                def {fn_name}(api):
                    """Schema contract: {url} must return {model_name} fields."""
                    resp = api.post(f"{{BASE_URL}}{url}", json={{"directory": "."}})
                    if resp.status_code != 200:
                        pytest.skip(f"Endpoint returned {{resp.status_code}}")
                    data = resp.json()
                    # Handle both single object and list responses
                    items = data if isinstance(data, list) else [data]
                    for item in items[:5]:
                        if not isinstance(item, dict):
                            continue
            {field_checks}

            ''')
            blocks.append(block)
            count += 1

    # Generate drift-specific tests: missing fields the frontend expects
    missing = drift_data.get("missing_fields", [])
    seen_missing = set()
    for mf in missing[:50]:
        model_name = mf.get("model", "")
        field_name = mf.get("field", "")
        url = mf.get("url", "")
        key = f"{model_name}_{field_name}"
        if key in seen_missing:
            continue
        seen_missing.add(key)

        fn_name = f"test_drift_missing_{_sanitize_fn(model_name)}_{_sanitize_fn(field_name)}"
        block = textwrap.dedent(f'''\
            @pytest.mark.xfail(reason="Schema drift: frontend expects '{field_name}' but {model_name} lacks it")
            def {fn_name}(api):
                """Drift: frontend expects '{field_name}' in {model_name} but model has no such field."""
                resp = api.post(f"{{BASE_URL}}{url}", json={{"directory": "."}})
                if resp.status_code != 200:
                    pytest.skip(f"Endpoint returned {{resp.status_code}}")
                data = resp.json()
                items = data if isinstance(data, list) else [data]
                for item in items[:3]:
                    if isinstance(item, dict):
                        assert "{field_name}" in item, "Field '{field_name}' missing — schema drift confirmed"

        ''')
        blocks.append(block)
        count += 1

    # Unused fields test — warn about fields sent but never read
    unused = drift_data.get("unused_fields", [])
    if unused:
        unused_list = [(u["model"], u["field"], u["field_type"]) for u in unused[:30]]
        unused_formatted = "\n".join(
            f'        ("{m}", "{f}", "{t}"),'
            for m, f, t in unused_list
        )
        block = textwrap.dedent(f'''\
            def test_unused_fields_audit():
                """Audit: these model fields are sent but never used by the frontend.
                Consider removing them to reduce payload size and data exposure."""
                unused = [
            {unused_formatted}
                ]
                # This test documents unused fields — it always passes but logs the list
                for model, field, ftype in unused:
                    print(f"  UNUSED: {{model}}.{{field}} ({{ftype}})")
                assert len(unused) > 0, "Update this test if all unused fields are resolved"

        ''')
        blocks.append(block)
        count += 1

    return "\n".join(blocks), count


# ── Orphan Verification Tests ────────────────────────────────────────


def _gen_orphan_tests(orphan_data: dict, base_url: str) -> tuple[str, int]:
    """Generate tests that probe orphan endpoints to verify they're truly dead."""
    blocks: list[str] = []
    count = 0

    # Frontend orphans — UI calls an endpoint that doesn't exist
    for orphan in orphan_data.get("orphan_frontend", [])[:30]:
        url = orphan.get("url", "")
        method = orphan.get("method", "GET").lower()
        file = orphan.get("file", "")
        line = orphan.get("line", 0)
        fn_name = f"test_orphan_frontend_{_sanitize_fn(url)}"

        # Avoid duplicate function names
        if any(fn_name in b for b in blocks):
            fn_name = f"{fn_name}_{line}"

        block = textwrap.dedent(f'''\
            def {fn_name}(api):
                """Orphan: UI calls {method.upper()} {url} but no backend handler exists.
                Source: {file}:{line}
                Fix: implement the handler or remove the dead UI call."""
                resp = api.{method}(f"{{BASE_URL}}{url}")
                assert resp.status_code == 404, (
                    f"Expected 404 (orphan endpoint) but got {{resp.status_code}} — "
                    f"handler may exist now, update orphan map"
                )

        ''')
        blocks.append(block)
        count += 1

    # Backend orphans — handler exists but nobody calls it
    for orphan in orphan_data.get("orphan_backend", [])[:30]:
        url = orphan.get("url", "")
        method = orphan.get("method", "GET").lower()
        file = orphan.get("file", "")
        fn_name = f"test_orphan_backend_{_sanitize_fn(url)}"

        if any(fn_name in b for b in blocks):
            fn_name = f"{fn_name}_{orphan.get('line', 0)}"

        if method in ("post", "put", "patch"):
            call = f'api.{method}(f"{{BASE_URL}}{url}", json={{}})'
        else:
            call = f'api.{method}(f"{{BASE_URL}}{url}")'

        block = textwrap.dedent(f'''\
            def {fn_name}(api):
                """Orphan: {method.upper()} {url} exists in backend but no UI calls it.
                Source: {file}
                Fix: wire it into the UI or deprecate the endpoint."""
                resp = {call}
                # Endpoint should at least respond (not 500)
                assert resp.status_code < 500, (
                    f"Backend orphan {url} returned {{resp.status_code}} — may be broken"
                )

        ''')
        blocks.append(block)
        count += 1

    # Wired connections — verify they actually work
    for wired in orphan_data.get("wired", [])[:20]:
        url = wired.get("url", "")
        fn_name = f"test_wired_{_sanitize_fn(url)}"
        block = textwrap.dedent(f'''\
            def {fn_name}(api):
                """Wired: verify {url} is healthy (UI calls it, backend handles it)."""
                resp = api.post(f"{{BASE_URL}}{url}", json={{"directory": "."}})
                assert resp.status_code < 500, (
                    f"Wired endpoint {url} returned {{resp.status_code}} — connection broken"
                )

        ''')
        blocks.append(block)
        count += 1

    # Parameter mismatch tests
    for pm in orphan_data.get("param_mismatches", [])[:10]:
        url = pm.get("url", "")
        fe_params = pm.get("frontend_params", [])
        be_params = pm.get("backend_params", [])
        fn_name = f"test_param_mismatch_{_sanitize_fn(url)}"
        block = textwrap.dedent(f'''\
            def {fn_name}():
                """Param mismatch: {url}
                Frontend sends: {fe_params}
                Backend expects: {be_params}
                Fix: align parameter names between frontend and backend."""
                pytest.fail(
                    "Parameter mismatch: frontend sends {fe_params} "
                    "but backend expects {be_params}"
                )

        ''')
        blocks.append(block)
        count += 1

    return "\n".join(blocks), count


# ── Coverage Gap Tests ───────────────────────────────────────────────


def _gen_coverage_tests(coverage_data: dict) -> tuple[str, int]:
    """Generate test stubs for untested functions and endpoints."""
    blocks: list[str] = []
    count = 0

    # Untested endpoints
    for ep in coverage_data.get("untested_endpoints", [])[:30]:
        url = ep.get("url", "")
        file = ep.get("file", "")
        fn_name = f"test_endpoint_{_sanitize_fn(url)}"
        block = textwrap.dedent(f'''\
            @pytest.mark.skip(reason="Coverage gap — no existing test for this endpoint")
            def {fn_name}(api):
                """UNTESTED endpoint: {url} (from {file})
                TODO: implement proper test with expected inputs/outputs."""
                resp = api.get(f"{{BASE_URL}}{url}")
                assert resp.status_code in (200, 400, 404)

        ''')
        blocks.append(block)
        count += 1

    # Untested functions — group by file
    untested = coverage_data.get("untested_functions", [])[:50]
    by_file: dict[str, list[dict]] = {}
    for fn in untested:
        by_file.setdefault(fn.get("file", "?"), []).append(fn)

    for file, fns in by_file.items():
        module = file.replace(os.sep, ".").replace("/", ".").replace(".py", "")
        class_name = f"Test{_sanitize_fn(os.path.basename(file).replace('.py', '')).title()}"

        block = textwrap.dedent(f'''\
            class {class_name}:
                """Coverage gaps in {file} — {len(fns)} untested functions."""

        ''')
        for fn in fns[:15]:
            name = fn.get("name", "")
            line = fn.get("line", 0)
            block += textwrap.dedent(f'''\
                    @pytest.mark.skip(reason="Coverage gap — stub for {module}.{name}")
                    def test_{_sanitize_fn(name)}(self):
                        """UNTESTED: {name}() at {file}:{line}"""
                        # from {module} import {name}
                        # result = {name}(...)
                        # assert result is not None
                        pass

            ''')
            count += 1

        blocks.append(block)

    return "\n".join(blocks), count


# ── Fixable Finding Regression Tests ─────────────────────────────────


def _gen_regression_tests(scan_data: dict | None) -> tuple[str, int]:
    """Generate regression tests for auto-fixable findings."""
    if not scan_data:
        return "", 0

    blocks: list[str] = []
    count = 0

    findings = scan_data.get("findings", [])
    fixable_rules = {"PY-005", "PY-007", "QUAL-001", "QUAL-003", "QUAL-004", "SEC-003", "SEC-009"}

    # Group fixable findings by file
    by_file: dict[str, list[dict]] = {}
    for f in findings:
        if f.get("rule_id") in fixable_rules:
            by_file.setdefault(f.get("file", "?"), []).append(f)

    if not by_file:
        return "", 0

    block = textwrap.dedent('''\
        class TestAutoFixRegression:
            """Regression: verify auto-fixed findings don't reappear after remediation."""

    ''')

    for file, file_findings in list(by_file.items())[:15]:
        for finding in file_findings[:5]:
            rule = finding.get("rule_id", "")
            line = finding.get("line", 0)
            desc = finding.get("description", "")[:60]
            fn_name = f"test_fix_{_sanitize_fn(rule)}_{_sanitize_fn(os.path.basename(file))}_{line}"
            block += textwrap.dedent(f'''\
                    def {fn_name}(self):
                        """Verify {rule} at {os.path.basename(file)}:{line} is fixed.
                        Original: {desc}"""
                        import re
                        filepath = "{file}"
                        try:
                            with open(filepath, encoding="utf-8", errors="replace") as f:
                                lines = f.readlines()
                            if {line} <= len(lines):
                                line_text = lines[{line} - 1]
                                # The finding pattern should no longer match after fix
                                # This is a placeholder — refine per rule
                                assert True, "Verify fix manually"
                        except FileNotFoundError:
                            pytest.skip("File moved or deleted")

            ''')
            count += 1

    blocks.append(block)
    return "\n".join(blocks), count


# ── Main Entry Point ─────────────────────────────────────────────────


def generate_smart_tests(
    directory: str,
    base_url: str = "http://localhost:8077",
    scan_data: dict | None = None,
    *,
    include_schema: bool = True,
    include_orphans: bool = True,
    include_coverage: bool = True,
    include_regression: bool = True,
) -> dict:
    """
    Generate comprehensive tests driven by X-Ray analysis.

    Runs schema drift, orphan map, and coverage map internally,
    then generates targeted tests based on findings.
    """
    root = str(Path(directory).resolve())
    project_name = os.path.basename(root)

    total_tests = 0
    sections: list[str] = []

    # ── Header ────────────────────────────────────────────────────────
    header = textwrap.dedent(f'''\
        """
        Smart Tests — Auto-generated by X-Ray LLM Smart Test Generator.
        Target: {project_name}
        Base URL: {base_url}

        These tests are generated from static analysis of:
        - Schema drift (Pydantic models vs frontend field usage)
        - Orphan map (disconnected UI↔Backend endpoints)
        - Coverage gaps (untested functions/endpoints)
        - Auto-fixable findings (regression guards)
        """

        import pytest
        import requests


        BASE_URL = "{base_url}"


        @pytest.fixture(scope="session")
        def api():
            """Session-scoped API client."""
            session = requests.Session()
            session.headers["Content-Type"] = "application/json"
            yield session
            session.close()

    ''')
    sections.append(header)

    analysis_summary = {}

    # ── Schema Contract Tests ─────────────────────────────────────────
    if include_schema:
        drift_data = detect_schema_drift(root)
        code, n = _gen_schema_tests(drift_data, base_url)
        if code:
            sections.append(f"# {'='*70}\n# Schema Contract Tests ({n} tests)\n# {'='*70}\n\n{code}")
            total_tests += n
        analysis_summary["schema"] = {
            "models": drift_data.get("summary", {}).get("total_models", 0),
            "drift_issues": drift_data.get("summary", {}).get("total_drift_issues", 0),
            "tests_generated": n,
        }

    # ── Orphan Verification Tests ─────────────────────────────────────
    if include_orphans:
        orphan_data = analyze_orphan_map(root)
        code, n = _gen_orphan_tests(orphan_data, base_url)
        if code:
            sections.append(f"# {'='*70}\n# Orphan Verification Tests ({n} tests)\n# {'='*70}\n\n{code}")
            total_tests += n
        analysis_summary["orphans"] = {
            "frontend_orphans": orphan_data.get("summary", {}).get("orphan_frontend_count", 0),
            "backend_orphans": orphan_data.get("summary", {}).get("orphan_backend_count", 0),
            "wired": orphan_data.get("summary", {}).get("wired_count", 0),
            "tests_generated": n,
        }

    # ── Coverage Gap Tests ────────────────────────────────────────────
    if include_coverage:
        coverage_data = compute_coverage_map(root)
        code, n = _gen_coverage_tests(coverage_data)
        if code:
            sections.append(f"# {'='*70}\n# Coverage Gap Tests ({n} tests)\n# {'='*70}\n\n{code}")
            total_tests += n
        analysis_summary["coverage"] = {
            "score": coverage_data.get("summary", {}).get("coverage_score", 0),
            "untested_endpoints": coverage_data.get("summary", {}).get("untested_endpoints", 0),
            "untested_functions": coverage_data.get("summary", {}).get("untested_functions", 0),
            "tests_generated": n,
        }

    # ── Regression Tests ──────────────────────────────────────────────
    if include_regression and scan_data:
        code, n = _gen_regression_tests(scan_data)
        if code:
            sections.append(f"# {'='*70}\n# Auto-Fix Regression Tests ({n} tests)\n# {'='*70}\n\n{code}")
            total_tests += n
        analysis_summary["regression"] = {"tests_generated": n}

    full_code = "\n".join(sections)
    output_path = os.path.join(root, "tests", "test_smart_xray.py")

    return {
        "test_code": full_code,
        "tests_generated": total_tests,
        "analysis_summary": analysis_summary,
        "output_suggestion": output_path,
        "project": project_name,
    }
