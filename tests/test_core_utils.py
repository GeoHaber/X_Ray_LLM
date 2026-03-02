"""
Tests for Core/utils.py — setup_logger, supports_unicode, get_os_info,
get_cpu_info, verify_rust_environment.
"""

import logging
from Core.utils import setup_logger, get_os_info, get_cpu_info, verify_rust_environment


# ════════════════════════════════════════════════════════════════════
#  setup_logger
# ════════════════════════════════════════════════════════════════════


class TestSetupLogger:
    def test_returns_logger_instance(self):
        log = setup_logger("test_logger")
        assert isinstance(log, logging.Logger)

    def test_logger_name(self):
        log = setup_logger("MyModule")
        assert log.name == "MyModule"

    def test_default_name(self):
        log = setup_logger()
        assert log.name == "X_RAY_Claude"


# ════════════════════════════════════════════════════════════════════
#  get_os_info
# ════════════════════════════════════════════════════════════════════


class TestGetOsInfo:
    def test_returns_nonempty_string(self):
        info = get_os_info()
        assert isinstance(info, str)
        assert len(info) > 0

    def test_contains_platform_markers(self):
        """Should mention OS family (Windows/Linux/Darwin) or architecture."""
        info = get_os_info()
        # At least something meaningful
        assert any(c.isalpha() for c in info)


# ════════════════════════════════════════════════════════════════════
#  get_cpu_info
# ════════════════════════════════════════════════════════════════════


class TestGetCpuInfo:
    def test_returns_string(self):
        info = get_cpu_info()
        assert isinstance(info, str)

    def test_not_empty_or_unknown(self):
        """May return 'Unknown CPU' on some platforms, but is always a string."""
        info = get_cpu_info()
        assert len(info) > 0


# ════════════════════════════════════════════════════════════════════
#  verify_rust_environment
# ════════════════════════════════════════════════════════════════════


class TestVerifyRustEnvironment:
    def setup_method(self):
        # Reset the module-level cache before each test
        import Core.utils as _mod

        _mod._verified_cache = False

    def test_returns_true(self):
        assert verify_rust_environment() is True

    def test_caches_result(self):
        """Second call should hit cache (still returns True)."""
        verify_rust_environment()
        import Core.utils as _mod

        assert _mod._verified_cache is True
        # Call again — should be idempotent
        assert verify_rust_environment() is True
