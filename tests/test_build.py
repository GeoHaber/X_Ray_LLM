"""
Tests for build.py — platform detection, target resolution, binary paths, cross-compile aliases.
No actual Rust compilation; just logic tests.

Run:  python -m pytest tests/test_build.py -v --tb=short
"""

import os
import sys
from unittest.mock import patch

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from build import (
    BINARY_NAME,
    CROSS_ALIASES,
    TARGET_MAP,
    detect_target,
    get_binary_path,
    resolve_target,
)


# ═════════════════════════════════════════════════════════════════════════════
# 1. TARGET_MAP completeness
# ═════════════════════════════════════════════════════════════════════════════

class TestTargetMap:
    """Verify the target map covers all major platforms."""

    def test_windows_x86_64(self):
        assert TARGET_MAP[("Windows", "AMD64")] == "x86_64-pc-windows-msvc"

    def test_windows_x86_64_alt(self):
        assert TARGET_MAP[("Windows", "x86_64")] == "x86_64-pc-windows-msvc"

    def test_windows_arm64(self):
        assert TARGET_MAP[("Windows", "ARM64")] == "aarch64-pc-windows-msvc"

    def test_linux_x86_64(self):
        assert TARGET_MAP[("Linux", "x86_64")] == "x86_64-unknown-linux-gnu"

    def test_linux_aarch64(self):
        assert TARGET_MAP[("Linux", "aarch64")] == "aarch64-unknown-linux-gnu"

    def test_linux_armv7l(self):
        assert TARGET_MAP[("Linux", "armv7l")] == "armv7-unknown-linux-gnueabihf"

    def test_macos_x86_64(self):
        assert TARGET_MAP[("Darwin", "x86_64")] == "x86_64-apple-darwin"

    def test_macos_arm64(self):
        assert TARGET_MAP[("Darwin", "arm64")] == "aarch64-apple-darwin"

    def test_macos_aarch64(self):
        assert TARGET_MAP[("Darwin", "aarch64")] == "aarch64-apple-darwin"


# ═════════════════════════════════════════════════════════════════════════════
# 2. detect_target()
# ═════════════════════════════════════════════════════════════════════════════

class TestDetectTarget:
    """Verify auto-detection works and falls back correctly."""

    def test_returns_string(self):
        target = detect_target()
        assert isinstance(target, str)
        assert len(target) > 5

    def test_matches_current_platform(self):
        """detect_target() must return a valid Rust target triple."""
        target = detect_target()
        # All valid triples contain at least 2 hyphens
        assert target.count("-") >= 2, f"Unexpected target: {target}"

    @patch("build.platform.system", return_value="Windows")
    @patch("build.platform.machine", return_value="AMD64")
    def test_windows_amd64_detected(self, mock_machine, mock_system):
        assert detect_target() == "x86_64-pc-windows-msvc"

    @patch("build.platform.system", return_value="Linux")
    @patch("build.platform.machine", return_value="x86_64")
    def test_linux_x86_64_detected(self, mock_machine, mock_system):
        assert detect_target() == "x86_64-unknown-linux-gnu"

    @patch("build.platform.system", return_value="Darwin")
    @patch("build.platform.machine", return_value="arm64")
    def test_macos_arm64_detected(self, mock_machine, mock_system):
        assert detect_target() == "aarch64-apple-darwin"

    @patch("build.platform.system", return_value="Windows")
    @patch("build.platform.machine", return_value="IA64")
    def test_unknown_arch_falls_back(self, mock_machine, mock_system):
        """Unknown arch on known OS should fall back to x86_64."""
        target = detect_target()
        assert "x86_64" in target

    @patch("build.platform.system", return_value="FreeBSD")
    @patch("build.platform.machine", return_value="amd64")
    def test_unsupported_os_exits(self, mock_machine, mock_system):
        with pytest.raises(SystemExit):
            detect_target()


# ═════════════════════════════════════════════════════════════════════════════
# 3. resolve_target()
# ═════════════════════════════════════════════════════════════════════════════

class TestResolveTarget:
    """Verify target resolution from aliases and auto-detect."""

    def test_none_auto_detects(self):
        target = resolve_target(None)
        assert isinstance(target, str)
        assert len(target) > 5

    @pytest.mark.parametrize("alias,expected", list(CROSS_ALIASES.items()))
    def test_all_aliases(self, alias, expected):
        assert resolve_target(alias) == expected

    def test_alias_case_insensitive(self):
        assert resolve_target("LINUX") == "x86_64-unknown-linux-gnu"
        assert resolve_target("Linux") == "x86_64-unknown-linux-gnu"

    def test_alias_with_spaces(self):
        assert resolve_target("apple silicon") == "aarch64-apple-darwin"

    def test_full_triple_passed_through(self):
        """A full Rust target triple should be returned as-is."""
        triple = "riscv64gc-unknown-linux-gnu"
        assert resolve_target(triple) == triple


# ═════════════════════════════════════════════════════════════════════════════
# 4. get_binary_path()
# ═════════════════════════════════════════════════════════════════════════════

class TestGetBinaryPath:
    """Verify binary path construction."""

    def test_windows_target_has_exe(self):
        path = get_binary_path("x86_64-pc-windows-msvc")
        assert path.endswith(".exe")
        assert "release" in path

    def test_linux_target_no_exe(self):
        path = get_binary_path("x86_64-unknown-linux-gnu")
        assert not path.endswith(".exe")
        assert "xray-scanner" in path

    def test_macos_target_no_exe(self):
        path = get_binary_path("aarch64-apple-darwin")
        assert not path.endswith(".exe")

    def test_target_in_path(self):
        """The target triple should appear in the binary path."""
        target = "x86_64-unknown-linux-gnu"
        path = get_binary_path(target)
        assert target in path

    def test_path_under_scanner_dir(self):
        path = get_binary_path("x86_64-unknown-linux-gnu")
        assert "scanner" in path
        assert "target" in path


# ═════════════════════════════════════════════════════════════════════════════
# 5. BINARY_NAME map
# ═════════════════════════════════════════════════════════════════════════════

class TestBinaryName:
    """Verify binary name map is complete."""

    def test_all_major_oses(self):
        assert "Windows" in BINARY_NAME
        assert "Linux" in BINARY_NAME
        assert "Darwin" in BINARY_NAME

    def test_windows_has_exe(self):
        assert BINARY_NAME["Windows"].endswith(".exe")

    def test_unix_no_exe(self):
        assert not BINARY_NAME["Linux"].endswith(".exe")
        assert not BINARY_NAME["Darwin"].endswith(".exe")
