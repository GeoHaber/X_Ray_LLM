"""Tests for xray.compat — Python & dependency version verification + API compat."""

import importlib
import importlib.metadata
import json
import types
from unittest.mock import MagicMock, patch

from xray.compat import (
    API_REGISTRY,
    DEPENDENCIES,
    APICheckResult,
    DependencyStatus,
    _fetch_pypi_version,
    _is_major_upgrade,
    _parse_version,
    _resolve_attr_chain,
    _version_gte,
    api_compatibility_summary,
    check_api_compatibility,
    check_dependency,
    check_dependency_freshness,
    check_environment,
    check_python_version,
    dependency_freshness_summary,
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
        _ok, problems = check_environment(warn_optional=False)
        python_issues = [p for p in problems if "Python" in p]
        assert python_issues == []

    def test_warns_on_missing_optional(self):
        _ok, problems = check_environment(warn_optional=True)
        # At minimum this shouldn't crash; optional warnings are fine
        assert isinstance(problems, list)

    def test_required_failure_sets_ok_false(self):
        with patch("xray.compat.check_dependency", return_value="missing"):
            with patch("xray.compat.DEPENDENCIES", [("fake-pkg", (1, 0), "fake", True)]):
                ok, _problems = check_environment()
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
        found, _error = _resolve_attr_chain(mod, "foo.bar")
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
        found, _error = _resolve_attr_chain(mod, "a.b.c.d")
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
            _ok, problems = check_environment(warn_optional=False)
        api_breaks = [p for p in problems if "[API BREAK]" in p]
        assert api_breaks == []


# ── _fetch_pypi_version ──────────────────────────────────────────────────

class TestFetchPypiVersion:
    def test_returns_string_for_known_package(self):
        # Mock a successful PyPI response
        fake_response = json.dumps({
            "info": {"version": "2.32.5"},
            "releases": {},
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("xray.compat.urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_pypi_version("requests")
        assert result == "2.32.5"

    def test_returns_none_on_network_error(self):
        import urllib.error

        with patch("xray.compat.urllib.request.urlopen",
                    side_effect=urllib.error.URLError("no network")):
            result = _fetch_pypi_version("requests", timeout=1)
        assert result is None

    def test_returns_none_on_bad_json(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("xray.compat.urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_pypi_version("requests")
        assert result is None

    def test_falls_back_to_releases_dict(self):
        fake_response = json.dumps({
            "info": {"version": ""},
            "releases": {
                "2.30.0": [],
                "2.31.0": [],
                "2.32.5": [],
                "3.0.0a1": [],  # pre-release, should be skipped
            },
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("xray.compat.urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_pypi_version("requests")
        assert result == "2.32.5"


# ── _is_major_upgrade ────────────────────────────────────────────────────

class TestIsMajorUpgrade:
    def test_same_major(self):
        assert _is_major_upgrade("2.30.0", "2.32.5") is False

    def test_different_major(self):
        assert _is_major_upgrade("1.9.0", "2.0.0") is True

    def test_empty_strings(self):
        assert _is_major_upgrade("", "") is False


# ── DependencyStatus ─────────────────────────────────────────────────────

class TestDependencyStatus:
    def test_to_dict_fields(self):
        ds = DependencyStatus("requests", "requests", False)
        ds.installed_version = "2.31.0"
        ds.latest_version = "2.32.5"
        ds.is_outdated = True
        d = ds.to_dict()
        assert d["package"] == "requests"
        assert d["installed_version"] == "2.31.0"
        assert d["latest_version"] == "2.32.5"
        assert d["is_outdated"] is True
        assert "api_symbols_used" in d
        assert "upgrade_risk" in d

    def test_default_values(self):
        ds = DependencyStatus("pkg", "pkg", True)
        assert ds.upgrade_risk == "unknown"
        assert ds.api_symbols_used == []
        assert ds.api_symbols_broken == []


# ── check_dependency_freshness ───────────────────────────────────────────

class TestCheckDependencyFreshness:
    def _mock_pypi(self, versions: dict[str, str]):
        """Return a patcher that makes _fetch_pypi_version return from a dict."""
        def fake_fetch(pkg, timeout=5):
            return versions.get(pkg)
        return patch("xray.compat._fetch_pypi_version", side_effect=fake_fetch)

    def test_returns_list_of_dependency_status(self):
        with self._mock_pypi({}):
            results = check_dependency_freshness(timeout=1)
        assert isinstance(results, list)
        assert all(isinstance(r, DependencyStatus) for r in results)
        assert len(results) == len(DEPENDENCIES)

    def test_detects_outdated_package(self):
        fake_deps = [("pytest", (7, 0), "pytest", True)]
        fake_meta = {"Version": "7.0.0"}
        with patch("xray.compat.DEPENDENCIES", fake_deps):
            with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
                with self._mock_pypi({"pytest": "9.0.0"}):
                    results = check_dependency_freshness(timeout=1)
        assert len(results) == 1
        assert results[0].is_outdated is True
        assert results[0].latest_version == "9.0.0"
        assert results[0].installed_version == "7.0.0"

    def test_up_to_date_package(self):
        fake_deps = [("pytest", (7, 0), "pytest", True)]
        fake_meta = {"Version": "9.0.0"}
        with patch("xray.compat.DEPENDENCIES", fake_deps):
            with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
                with self._mock_pypi({"pytest": "9.0.0"}):
                    results = check_dependency_freshness(timeout=1)
        assert results[0].is_outdated is False
        assert results[0].upgrade_risk == "none"

    def test_missing_package_handled(self):
        fake_deps = [("nonexistent-pkg-xyz", (1, 0), "nonexistent", False)]
        with patch("xray.compat.DEPENDENCIES", fake_deps), self._mock_pypi({}):
            results = check_dependency_freshness(timeout=1)
        assert results[0].error == "not installed"

    def test_major_upgrade_detected(self):
        fake_deps = [("pytest", (7, 0), "pytest", True)]
        fake_meta = {"Version": "7.4.0"}
        with patch("xray.compat.DEPENDENCIES", fake_deps):
            with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
                with self._mock_pypi({"pytest": "10.0.0"}):
                    results = check_dependency_freshness(timeout=1)
        assert results[0].is_major_upgrade is True
        assert results[0].upgrade_risk == "high"

    def test_api_symbols_cross_referenced(self):
        fake_deps = [("pytest", (7, 0), "pytest", True)]
        fake_meta = {"Version": "9.0.0"}
        with patch("xray.compat.DEPENDENCIES", fake_deps):
            with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
                with self._mock_pypi({"pytest": "9.0.0"}):
                    results = check_dependency_freshness(timeout=1)
        # pytest has entries in API_REGISTRY
        assert len(results[0].api_symbols_used) > 0
        # All should pass since pytest is installed and current
        assert results[0].api_symbols_ok == results[0].api_symbols_used

    def test_broken_api_shows_high_risk(self):
        fake_deps = [("fake_lib", (1, 0), "fake_mod", True)]
        fake_meta = {"Version": "1.0.0"}
        fake_registry = [("fake_mod", "Missing.method", "test.py", "gone")]
        fake_mod = types.ModuleType("fake_mod")

        real_import = importlib.import_module

        def fake_import(name):
            if name == "fake_mod":
                return fake_mod
            return real_import(name)

        with patch("xray.compat.DEPENDENCIES", fake_deps), \
             patch("xray.compat.API_REGISTRY", fake_registry), \
             patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta), \
             patch("xray.compat.importlib.import_module", side_effect=fake_import), \
             patch("xray.compat._fetch_pypi_version", return_value="2.0.0"):
            results = check_dependency_freshness(timeout=1)
        assert results[0].api_symbols_broken == ["Missing.method"]
        assert results[0].upgrade_risk == "high"


# ── dependency_freshness_summary ─────────────────────────────────────────

class TestDependencyFreshnessSummary:
    def test_returns_dict_with_expected_keys(self):
        ds = DependencyStatus("pkg", "pkg", False)
        ds.installed_version = "1.0.0"
        ds.latest_version = "1.1.0"
        ds.is_outdated = True
        ds.upgrade_risk = "low"

        result = dependency_freshness_summary([ds])
        assert "dependencies" in result
        assert "summary" in result
        assert result["summary"]["total"] == 1
        assert result["summary"]["outdated"] == 1

    def test_summary_counts(self):
        s1 = DependencyStatus("a", "a", True)
        s1.installed_version = "1.0"
        s1.is_outdated = False

        s2 = DependencyStatus("b", "b", False)
        s2.installed_version = "2.0"
        s2.is_outdated = True
        s2.is_major_upgrade = True

        s3 = DependencyStatus("c", "c", False)
        s3.error = "not installed"

        result = dependency_freshness_summary([s1, s2, s3])
        assert result["summary"]["total"] == 3
        assert result["summary"]["up_to_date"] == 1
        assert result["summary"]["outdated"] == 1
        assert result["summary"]["major_upgrades"] == 1
        assert result["summary"]["not_installed"] == 1
