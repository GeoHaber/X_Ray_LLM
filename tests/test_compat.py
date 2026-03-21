"""Tests for xray.compat — Python & dependency version verification + API compat."""

import importlib.metadata
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from xray.compat import (
    API_REGISTRY,
    APICheckResult,
    DEPENDENCIES,
    MIN_PYTHON,
    _parse_version,
    _resolve_attr_chain,
    _version_gte,
    api_compatibility_summary,
    check_api_compatibility,
    check_dependency,
    check_environment,
    check_python_version,
    environment_summary,
)


# ── _parse_version ───────────────────────────────────────────────────────

class TestParseVersion:
    def test_simple(self):
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_two_part(self):
        assert _parse_version("7.0") == (7, 0)

    def test_rc_suffix(self):
        assert _parse_version("1.2.3rc1") == (1, 2, 3)

    def test_alpha_suffix(self):
        assert _parse_version("2.0.0a5") == (2, 0, 0)

    def test_post_suffix(self):
        assert _parse_version("3.1.2.post1") == (3, 1, 2)

    def test_single(self):
        assert _parse_version("42") == (42,)


# ── _version_gte ─────────────────────────────────────────────────────────

class TestVersionGte:
    def test_equal(self):
        assert _version_gte((3, 10, 0), (3, 10)) is True

    def test_greater(self):
        assert _version_gte((3, 12, 1), (3, 10)) is True

    def test_less(self):
        assert _version_gte((3, 9), (3, 10)) is False

    def test_patch_level(self):
        assert _version_gte((0, 3, 16), (0, 3, 0)) is True

    def test_shorter_installed(self):
        assert _version_gte((7,), (7, 0)) is True

    def test_shorter_minimum(self):
        assert _version_gte((7, 1), (7,)) is True


# ── check_python_version ─────────────────────────────────────────────────

class TestCheckPythonVersion:
    def test_current_python_passes(self):
        # We're running >= 3.10, so this should succeed
        assert check_python_version() == []

    def test_old_python_fails(self):
        with patch("xray.compat.sys") as mock_sys:
            mock_sys.version_info = (3, 8, 0)
            problems = check_python_version()
        assert len(problems) == 1
        assert "3.8.0" in problems[0]
        assert "too old" in problems[0]


# ── check_dependency ─────────────────────────────────────────────────────

class TestCheckDependency:
    def test_pytest_installed(self):
        # pytest is installed (we're running it right now)
        result = check_dependency("pytest", (7, 0))
        assert result is None  # no error

    def test_missing_package(self):
        result = check_dependency("nonexistent-package-xyzzy", (1, 0))
        assert result is not None
        assert "not installed" in result

    def test_too_old_version(self):
        # Pretend pytest is version 1.0
        fake_meta = {"Version": "1.0.0"}
        with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
            result = check_dependency("pytest", (7, 0))
        assert result is not None
        assert "too old" in result


# ── check_environment ────────────────────────────────────────────────────

class TestCheckEnvironment:
    def test_current_env_ok_for_python(self):
        ok, problems = check_environment(warn_optional=False)
        python_issues = [p for p in problems if "Python" in p]
        assert python_issues == []

    def test_warns_on_missing_optional(self):
        _ok, problems = check_environment(warn_optional=True)
        # At minimum this shouldn't crash; optional warnings are fine
        assert isinstance(problems, list)

    def test_required_failure_sets_ok_false(self):
        with patch("xray.compat.check_dependency", return_value="missing"):
            with patch("xray.compat.DEPENDENCIES", [("fake-pkg", (1, 0), "fake", True)]):
                ok, problems = check_environment()
        assert ok is False


# ── environment_summary ──────────────────────────────────────────────────

class TestEnvironmentSummary:
    def test_returns_string(self):
        summary = environment_summary()
        assert isinstance(summary, str)
        assert "Python" in summary

    def test_lists_all_deps(self):
        summary = environment_summary()
        for pkg_name, _, _, _ in DEPENDENCIES:
            assert pkg_name in summary


# ── _resolve_attr_chain ──────────────────────────────────────────────────

class TestResolveAttrChain:
    def test_single_attr_found(self):
        mod = types.SimpleNamespace(foo=42)
        found, error = _resolve_attr_chain(mod, "foo")
        assert found is True
        assert error == ""

    def test_nested_attr_found(self):
        inner = types.SimpleNamespace(bar=99)
        mod = types.SimpleNamespace(foo=inner)
        found, error = _resolve_attr_chain(mod, "foo.bar")
        assert found is True

    def test_missing_attr(self):
        mod = types.SimpleNamespace(foo=42)
        found, error = _resolve_attr_chain(mod, "missing")
        assert found is False
        assert "'missing'" in error

    def test_missing_nested_attr(self):
        inner = types.SimpleNamespace(x=1)
        mod = types.SimpleNamespace(foo=inner)
        found, error = _resolve_attr_chain(mod, "foo.nonexistent")
        assert found is False
        assert "'nonexistent'" in error
        assert "foo" in error

    def test_deep_chain(self):
        c = types.SimpleNamespace(d=True)
        b = types.SimpleNamespace(c=c)
        a = types.SimpleNamespace(b=b)
        mod = types.SimpleNamespace(a=a)
        found, error = _resolve_attr_chain(mod, "a.b.c.d")
        assert found is True


# ── APICheckResult ───────────────────────────────────────────────────────

class TestAPICheckResult:
    def test_repr_ok(self):
        r = APICheckResult("mod", "Klass", "file.py", "desc", found=True)
        assert "OK" in repr(r)

    def test_repr_missing(self):
        r = APICheckResult("mod", "Klass", "file.py", "desc",
                           found=False, error="not found")
        assert "MISSING" in repr(r)
        assert "not found" in repr(r)


# ── check_api_compatibility (live) ───────────────────────────────────────

class TestCheckAPICompatibility:
    def test_returns_list(self):
        results = check_api_compatibility()
        assert isinstance(results, list)
        assert len(results) == len(API_REGISTRY)

    def test_pytest_apis_found(self):
        """pytest is installed — its APIs must all be found."""
        results = check_api_compatibility()
        pytest_results = [r for r in results if r.import_path == "pytest"]
        assert len(pytest_results) > 0
        for r in pytest_results:
            assert r.found is True, f"pytest.{r.attr_chain} not found: {r.error}"

    def test_requests_apis_found(self):
        """requests is installed — its APIs must all be found."""
        results = check_api_compatibility()
        req_results = [r for r in results if r.import_path == "requests"]
        for r in req_results:
            assert r.found is True, f"requests.{r.attr_chain} not found: {r.error}"

    def test_uninstalled_library_skipped(self):
        """Libraries not installed get error='library not installed'."""
        fake_registry = [("nonexistent_lib_xyz", "Foo", "test.py", "fake")]
        with patch("xray.compat.API_REGISTRY", fake_registry):
            results = check_api_compatibility()
        assert len(results) == 1
        assert results[0].found is False
        assert results[0].error == "library not installed"

    def test_broken_api_detected(self):
        """If a library exists but the symbol is gone, it's caught."""
        fake_mod = types.ModuleType("fake_mod")
        fake_mod.RealClass = True  # exists
        # "MissingClass" does NOT exist on fake_mod

        fake_registry = [("fake_mod", "MissingClass", "test.py", "should fail")]
        with patch("xray.compat.API_REGISTRY", fake_registry):
            with patch("xray.compat.importlib.import_module", return_value=fake_mod):
                results = check_api_compatibility()
        assert len(results) == 1
        assert results[0].found is False
        assert "not found" in results[0].error


# ── api_compatibility_summary ────────────────────────────────────────────

class TestAPICompatibilitySummary:
    def test_returns_string(self):
        summary = api_compatibility_summary()
        assert isinstance(summary, str)
        assert "API compatibility" in summary

    def test_includes_libraries(self):
        summary = api_compatibility_summary()
        assert "pytest" in summary

    def test_broken_api_shows_warning(self):
        fake_results = [
            APICheckResult("fake_lib", "Broken.method", "test.py",
                           "gone", found=False, error="'method' not found on Broken"),
        ]
        with patch("xray.compat.check_api_compatibility", return_value=fake_results):
            summary = api_compatibility_summary()
        assert "BREAKING CHANGES" in summary
        assert "Broken.method" in summary

    def test_empty_registry(self):
        with patch("xray.compat.API_REGISTRY", []):
            summary = api_compatibility_summary()
        assert "No API checks registered" in summary


# ── check_environment includes API checks ────────────────────────────────

class TestCheckEnvironmentWithAPI:
    def test_api_break_fails_environment(self):
        """An API break should cause check_environment to return ok=False."""
        broken = [
            APICheckResult("pytest", "nonexistent_method", "tests/",
                           "fake", found=False, error="'nonexistent_method' not found"),
        ]
        with patch("xray.compat.check_api_compatibility", return_value=broken):
            ok, problems = check_environment(warn_optional=False)
        assert ok is False
        api_breaks = [p for p in problems if "[API BREAK]" in p]
        assert len(api_breaks) == 1

    def test_uninstalled_lib_does_not_fail(self):
        """Missing optional libraries don't set ok=False via API check."""
        skipped = [
            APICheckResult("nonexistent", "Foo", "test.py",
                           "fake", found=False, error="library not installed"),
        ]
        with patch("xray.compat.check_api_compatibility", return_value=skipped):
            ok, problems = check_environment(warn_optional=False)
        api_breaks = [p for p in problems if "[API BREAK]" in p]
        assert api_breaks == []
