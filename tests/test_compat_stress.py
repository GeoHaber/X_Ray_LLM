"""Tough stress tests for xray.compat — version parsing, comparison, API compat.

These tests hammer edge cases, simulate upgrade disasters, and verify
the checker catches real-world breaking-change scenarios.
"""

import importlib
import importlib.metadata
import types
from unittest.mock import MagicMock, patch

import pytest

from xray.compat import (
    API_REGISTRY,
    APICheckResult,
    DEPENDENCIES,
    MIN_PYTHON,
    _fmt,
    _parse_version,
    _resolve_attr_chain,
    _version_gte,
    api_compatibility_summary,
    check_api_compatibility,
    check_dependency,
    check_environment,
    check_python_version,
    environment_summary,
    require_environment,
)


# ═══════════════════════════════════════════════════════════════════════════
#  PART 1 — Version parsing edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestParseVersionEdgeCases:
    """Stress _parse_version with exotic version strings from PyPI."""

    @pytest.mark.parametrize("version_str, expected", [
        ("0.0.0", (0, 0, 0)),
        ("0.0.1", (0, 0, 1)),
        ("999.999.999", (999, 999, 999)),
        ("1.0.0a1", (1, 0, 0)),
        ("1.0.0b2", (1, 0, 0)),
        ("1.0.0rc3", (1, 0, 0)),
        ("1.0.0.dev4", (1, 0, 0)),
        ("1.0.0.post5", (1, 0, 0)),
        ("2024.1.1", (2024, 1, 1)),          # CalVer used by pip, black
        ("0.3.16", (0, 3, 16)),              # llama-cpp-python style
        ("9.0.2", (9, 0, 2)),                # pytest style
        ("0.80.5", (0, 80, 5)),              # flet style (high minor)
        ("2.32.5", (2, 32, 5)),              # requests style
        ("1.1.408", (1, 1, 408)),            # pyright style (high patch)
    ])
    def test_real_world_versions(self, version_str, expected):
        assert _parse_version(version_str) == expected

    def test_empty_string(self):
        # Shouldn't crash, returns empty tuple
        assert _parse_version("") == ()

    def test_only_text(self):
        # e.g. "unknown" — no digits at all
        assert _parse_version("unknown") == ()

    def test_leading_v(self):
        # "v1.2.3" — the "v" prefix some projects use in git tags.
        # Parser strips non-digit prefix, losing the "v1" segment
        # entirely (it sees "v1" as non-numeric). This is fine since
        # PEP 440 never uses "v" prefixes.
        result = _parse_version("v1.2.3")
        assert result == (2, 3)

    def test_four_part_version(self):
        assert _parse_version("1.2.3.4") == (1, 2, 3, 4)

    def test_version_with_local_identifier(self):
        # PEP 440 local: "1.0+local.1"
        result = _parse_version("1.0+local.1")
        # "1" → 1, "0+local" → 0 (stops at +), "1" → 1
        assert result[0] == 1
        assert result[1] == 0


# ═══════════════════════════════════════════════════════════════════════════
#  PART 2 — Version comparison stress tests
# ═══════════════════════════════════════════════════════════════════════════


class TestVersionGteStress:
    """Boundary cases and tricky comparisons."""

    @pytest.mark.parametrize("installed, minimum, expected", [
        # Exact boundary
        ((3, 10), (3, 10), True),
        ((3, 10, 0), (3, 10, 0), True),
        ((3, 9, 99), (3, 10, 0), False),    # 3.9.99 < 3.10.0
        ((3, 10, 0), (3, 9, 99), True),     # 3.10.0 > 3.9.99
        # Zero-fill asymmetry
        ((1,), (1, 0, 0), True),
        ((1, 0, 0), (1,), True),
        ((0,), (0, 0, 1), False),
        # Major bump always wins
        ((4, 0, 0), (3, 99, 99), True),
        ((2, 99, 99), (3, 0, 0), False),
        # Empty tuples (degenerate)
        ((), (), True),
        ((0,), (), True),
        ((), (0,), True),                    # () pads to (0,)
        # Real-world: llama-cpp-python 0.3.16 vs 0.3.0
        ((0, 3, 16), (0, 3, 0), True),
        # Real-world: flet 0.80.5 vs 0.25
        ((0, 80, 5), (0, 25), True),
        # Real-world: would flet 0.24 fail?
        ((0, 24), (0, 25), False),
    ])
    def test_comparison(self, installed, minimum, expected):
        assert _version_gte(installed, minimum) is expected


# ═══════════════════════════════════════════════════════════════════════════
#  PART 3 — Dependency checker with simulated upgrades / downgrades
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckDependencyScenarios:
    """Simulate library upgrade/downgrade scenarios."""

    def test_exact_minimum_passes(self):
        """Version exactly at minimum should pass."""
        fake_meta = {"Version": "7.0"}
        with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
            result = check_dependency("pytest", (7, 0))
        assert result is None

    def test_one_patch_below_fails(self):
        """Version one patch below minimum should fail."""
        fake_meta = {"Version": "6.99.9"}
        with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
            result = check_dependency("pytest", (7, 0))
        assert result is not None
        assert "too old" in result

    def test_major_upgrade_passes(self):
        """Major version bump above minimum passes."""
        fake_meta = {"Version": "10.0.0"}
        with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
            result = check_dependency("pytest", (7, 0))
        assert result is None

    def test_prerelease_version(self):
        """Pre-release of target version passes (7.0rc1 >= 7.0)."""
        fake_meta = {"Version": "7.0rc1"}
        with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
            result = check_dependency("pytest", (7, 0))
        assert result is None

    def test_calver_package(self):
        """CalVer packages like pip (24.3.1) should compare correctly."""
        fake_meta = {"Version": "2024.3.1"}
        with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
            result = check_dependency("pip", (2024, 1))
        assert result is None

    def test_error_message_includes_versions(self):
        """Error message should state both installed and required versions."""
        fake_meta = {"Version": "0.2.5"}
        with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
            result = check_dependency("llama-cpp-python", (0, 3, 0))
        assert "0.2.5" in result
        assert "0.3.0" in result

    def test_error_message_for_missing(self):
        result = check_dependency("absolutely-not-a-real-pkg", (1, 0))
        assert "not installed" in result
        assert "1.0" in result


# ═══════════════════════════════════════════════════════════════════════════
#  PART 4 — API compatibility: simulate breaking changes
# ═══════════════════════════════════════════════════════════════════════════


class TestAPIBreakingChangeScenarios:
    """Simulate real-world library upgrade disasters."""

    def _make_module(self, name: str, **attrs) -> types.ModuleType:
        """Create a fake module with given attributes."""
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        return mod

    def test_class_renamed(self):
        """Library renames Llama → LlamaModel — should detect the break."""
        mod = self._make_module("llama_cpp", LlamaModel=type("LlamaModel", (), {}))
        # "Llama" is gone, "LlamaModel" exists
        registry = [("llama_cpp", "Llama", "xray/llm.py", "Core class")]
        with patch("xray.compat.API_REGISTRY", registry):
            with patch("xray.compat.importlib.import_module", return_value=mod):
                results = check_api_compatibility()
        assert results[0].found is False
        assert "'Llama' not found" in results[0].error

    def test_method_removed_from_class(self):
        """Library removes create_chat_completion — should detect."""
        FakeLlama = type("Llama", (), {"generate": lambda self: None})
        mod = self._make_module("llama_cpp", Llama=FakeLlama)
        registry = [("llama_cpp", "Llama.create_chat_completion", "xray/llm.py", "Chat API")]
        with patch("xray.compat.API_REGISTRY", registry):
            with patch("xray.compat.importlib.import_module", return_value=mod):
                results = check_api_compatibility()
        assert results[0].found is False
        assert "'create_chat_completion'" in results[0].error

    def test_submodule_restructured(self):
        """Library restructures: pytest.mark.parametrize → pytest.parametrize."""
        mod = self._make_module("pytest", parametrize=lambda: None)
        # pytest.mark doesn't exist anymore
        registry = [("pytest", "mark.parametrize", "tests/", "Parametrize")]
        with patch("xray.compat.API_REGISTRY", registry):
            with patch("xray.compat.importlib.import_module", return_value=mod):
                results = check_api_compatibility()
        assert results[0].found is False
        assert "'mark'" in results[0].error

    def test_requests_response_removed(self):
        """requests removes Response class — should detect."""
        mod = self._make_module("requests", get=lambda: None, post=lambda: None)
        # Response class is missing
        registry = [("requests", "Response", "wire.py", "Response object")]
        with patch("xray.compat.API_REGISTRY", registry):
            with patch("xray.compat.importlib.import_module", return_value=mod):
                results = check_api_compatibility()
        assert results[0].found is False

    def test_multiple_breaks_all_caught(self):
        """Multiple API breaks in same library — all should be reported."""
        mod = self._make_module("broken_lib")  # empty — nothing exists
        registry = [
            ("broken_lib", "ClassA", "a.py", "first"),
            ("broken_lib", "ClassB", "b.py", "second"),
            ("broken_lib", "func_c", "c.py", "third"),
        ]
        with patch("xray.compat.API_REGISTRY", registry):
            with patch("xray.compat.importlib.import_module", return_value=mod):
                results = check_api_compatibility()
        assert len(results) == 3
        assert all(not r.found for r in results)

    def test_partial_breakage(self):
        """Some APIs still work, others broken — reports correctly."""
        mod = self._make_module("half_broke", get=lambda: None)
        # "get" exists, "post" and "Response" are gone
        registry = [
            ("half_broke", "get", "w.py", "GET"),
            ("half_broke", "post", "w.py", "POST"),
            ("half_broke", "Response", "w.py", "Response"),
        ]
        with patch("xray.compat.API_REGISTRY", registry):
            with patch("xray.compat.importlib.import_module", return_value=mod):
                results = check_api_compatibility()
        found_flags = [r.found for r in results]
        assert found_flags == [True, False, False]


# ═══════════════════════════════════════════════════════════════════════════
#  PART 5 — Full environment check integration (tough combos)
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckEnvironmentTough:
    """Simulate complex multi-failure scenarios."""

    def test_old_python_plus_missing_required(self):
        """Both Python too old AND required dep missing → ok=False, multiple problems."""
        with patch("xray.compat.sys") as mock_sys:
            mock_sys.version_info = (3, 8, 0)
            with patch("xray.compat.DEPENDENCIES", [("pytest", (7, 0), "pytest", True)]):
                with patch("xray.compat.check_dependency", return_value="pytest not installed"):
                    with patch("xray.compat.check_api_compatibility", return_value=[]):
                        ok, problems = check_environment(warn_optional=False)
        assert ok is False
        assert len(problems) >= 2
        has_python = any("Python" in p and "too old" in p for p in problems)
        has_dep = any("[REQUIRED]" in p for p in problems)
        assert has_python
        assert has_dep

    def test_api_break_overrides_version_ok(self):
        """Even if version is OK, an API break should fail the environment."""
        broken = [
            APICheckResult("requests", "get", "wire.py", "HTTP GET",
                           found=False, error="'get' not found on (root)"),
        ]
        with patch("xray.compat.check_api_compatibility", return_value=broken):
            ok, problems = check_environment(warn_optional=False)
        assert ok is False
        api_breaks = [p for p in problems if "[API BREAK]" in p]
        assert len(api_breaks) == 1
        assert "requests.get" in api_breaks[0]

    def test_optional_missing_AND_api_break_on_required(self):
        """Optional missing = warning, required API break = failure."""
        api_results = [
            APICheckResult("nonexistent", "Foo", "x.py", "opt",
                           found=False, error="library not installed"),
            APICheckResult("pytest", "gone_method", "tests/", "critical",
                           found=False, error="'gone_method' not found on (root)"),
        ]
        with patch("xray.compat.DEPENDENCIES", []):
            with patch("xray.compat.check_api_compatibility", return_value=api_results):
                ok, problems = check_environment(warn_optional=True)
        assert ok is False
        # Only the real break should be flagged, not the uninstalled one
        api_breaks = [p for p in problems if "[API BREAK]" in p]
        assert len(api_breaks) == 1
        assert "pytest.gone_method" in api_breaks[0]

    def test_all_good_returns_ok_true(self):
        """When everything is fine, ok should be True."""
        good_api = [
            APICheckResult("pytest", "raises", "tests/", "ok", found=True),
        ]
        with patch("xray.compat.DEPENDENCIES", []):
            with patch("xray.compat.check_api_compatibility", return_value=good_api):
                ok, problems = check_environment(warn_optional=False)
        assert ok is True
        assert problems == []

    def test_warn_optional_false_suppresses_optional_warnings(self):
        """warn_optional=False should hide optional dep warnings."""
        with patch("xray.compat.DEPENDENCIES",
                   [("nonexistent-pkg", (1, 0), "nope", False)]):
            with patch("xray.compat.check_api_compatibility", return_value=[]):
                _ok, problems = check_environment(warn_optional=False)
        optional_warnings = [p for p in problems if "[optional]" in p]
        assert optional_warnings == []


# ═══════════════════════════════════════════════════════════════════════════
#  PART 6 — require_environment exits on failure
# ═══════════════════════════════════════════════════════════════════════════


class TestRequireEnvironment:
    def test_exits_on_failure(self):
        """require_environment should call sys.exit when ok=False."""
        with patch("xray.compat.check_environment", return_value=(False, ["[REQUIRED] bad"])):
            with pytest.raises(SystemExit):
                require_environment()

    def test_does_not_exit_when_ok(self):
        """require_environment should return normally when ok=True."""
        with patch("xray.compat.check_environment", return_value=(True, [])):
            require_environment()  # should not raise


# ═══════════════════════════════════════════════════════════════════════════
#  PART 7 — Summary / reporting format validation
# ═══════════════════════════════════════════════════════════════════════════


class TestReportingFormats:
    def test_environment_summary_shows_upgrade_needed(self):
        """If a dep is too old, summary should say UPGRADE."""
        fake_meta = {"Version": "0.1.0"}
        with patch("xray.compat.DEPENDENCIES",
                   [("fake-dep", (99, 0), "fake", False)]):
            with patch("xray.compat.importlib.metadata.metadata", return_value=fake_meta):
                summary = environment_summary()
        assert "UPGRADE" in summary

    def test_environment_summary_shows_missing(self):
        """If a dep is not installed, summary should say MISSING."""
        with patch("xray.compat.DEPENDENCIES",
                   [("nonexistent-pkg-xxx", (1, 0), "nope", False)]):
            summary = environment_summary()
        assert "MISSING" in summary

    def test_api_summary_groups_by_library(self):
        """Summary should organize results by library name."""
        results = [
            APICheckResult("libA", "foo", "a.py", "d1", found=True),
            APICheckResult("libA", "bar", "a.py", "d2", found=True),
            APICheckResult("libB", "baz", "b.py", "d3", found=True),
        ]
        with patch("xray.compat.check_api_compatibility", return_value=results):
            summary = api_compatibility_summary()
        assert "libA" in summary
        assert "libB" in summary
        # Both libA entries appear together
        a_pos = summary.index("libA")
        b_pos = summary.index("libB")
        foo_pos = summary.index(".foo")
        bar_pos = summary.index(".bar")
        assert a_pos < foo_pos < bar_pos < b_pos

    def test_api_summary_counts_correct(self):
        """OK/issue counts should be accurate."""
        results = [
            APICheckResult("lib", "ok1", "f.py", "d", found=True),
            APICheckResult("lib", "ok2", "f.py", "d", found=True),
            APICheckResult("lib", "broken", "f.py", "d", found=False, error="gone"),
        ]
        with patch("xray.compat.check_api_compatibility", return_value=results):
            summary = api_compatibility_summary()
        assert "2 OK" in summary
        assert "1 issues" in summary


# ═══════════════════════════════════════════════════════════════════════════
#  PART 8 — Live integration: verify our ACTUAL registry against installed libs
# ═══════════════════════════════════════════════════════════════════════════


class TestLiveRegistryIntegrity:
    """These tests run against the REAL installed libraries — no mocks.
    If any of these fail, it means a library upgrade broke an API we use."""

    def test_every_registry_entry_has_four_fields(self):
        for entry in API_REGISTRY:
            assert len(entry) == 4, f"Bad registry entry: {entry}"
            import_path, attr_chain, used_in, description = entry
            assert isinstance(import_path, str) and import_path
            assert isinstance(attr_chain, str) and attr_chain
            assert isinstance(used_in, str) and used_in
            assert isinstance(description, str) and description

    def test_all_installed_apis_resolve(self):
        """Every API in the registry for an installed library must resolve."""
        results = check_api_compatibility()
        for r in results:
            if r.error == "library not installed":
                continue  # skip uninstalled, that's fine
            assert r.found is True, (
                f"LIVE API BREAK: {r.import_path}.{r.attr_chain} — {r.error}\n"
                f"  Used in: {r.used_in}\n"
                f"  Description: {r.description}\n"
                f"  This means a library upgrade broke an API X-Ray depends on!"
            )

    def test_live_pytest_mark_parametrize_is_callable(self):
        """pytest.mark.parametrize must be callable (not just exist)."""
        import pytest as pt
        assert callable(pt.mark.parametrize)

    def test_live_requests_response_has_status_code(self):
        """requests.Response must have status_code attribute."""
        import requests
        resp = requests.Response()
        assert hasattr(resp, "status_code")
        assert hasattr(resp, "text")
        assert hasattr(resp, "headers")

    def test_live_dependency_versions_match_requirements(self):
        """Every DEPENDENCIES entry that's installed must meet its minimum."""
        for pkg_name, min_ver, _import, _req in DEPENDENCIES:
            issue = check_dependency(pkg_name, min_ver)
            if issue and "not installed" in issue:
                continue  # optional, skip
            assert issue is None, (
                f"Installed {pkg_name} fails version check: {issue}"
            )

    def test_fmt_helper(self):
        """_fmt should produce clean dotted version strings."""
        assert _fmt((3, 10, 0)) == "3.10.0"
        assert _fmt((1,)) == "1"
        assert _fmt(()) == ""
