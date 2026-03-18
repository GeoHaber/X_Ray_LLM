#!/usr/bin/env python3
"""
Unified Build Script for X-Ray Scanner (Rust)

Detects OS + architecture, generates Rust rules from Python source of truth,
builds the Rust binary, runs tests, and optionally cross-validates against
the Python scanner.

Usage:
  python build.py                  # full build: generate -> test -> release
  python build.py --test-only      # just cargo test
  python build.py --validate       # build + cross-validate vs Python scanner
  python build.py --target linux   # cross-compile for Linux (if toolchain installed)
  python build.py --release-only   # skip tests, just build release
  python build.py --info           # show detected OS/arch/target info
"""

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

# -- OS / Architecture Detection -------------------------------------------

# Map (system, machine) -> Rust target triple
TARGET_MAP = {
    # Windows
    ("Windows", "AMD64"): "x86_64-pc-windows-msvc",
    ("Windows", "x86_64"): "x86_64-pc-windows-msvc",
    ("Windows", "ARM64"): "aarch64-pc-windows-msvc",
    # Linux
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
    ("Linux", "armv7l"): "armv7-unknown-linux-gnueabihf",
    # macOS
    ("Darwin", "x86_64"): "x86_64-apple-darwin",
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Darwin", "aarch64"): "aarch64-apple-darwin",
}

# Friendly names for cross-compile aliases
CROSS_ALIASES = {
    "windows": "x86_64-pc-windows-msvc",
    "windows-arm": "aarch64-pc-windows-msvc",
    "linux": "x86_64-unknown-linux-gnu",
    "linux-arm": "aarch64-unknown-linux-gnu",
    "macos": "x86_64-apple-darwin",
    "macos-arm": "aarch64-apple-darwin",
    "apple-silicon": "aarch64-apple-darwin",
}

# Binary name per OS
BINARY_NAME = {
    "Windows": "xray-scanner.exe",
    "Linux": "xray-scanner",
    "Darwin": "xray-scanner",
}

ROOT = os.path.dirname(os.path.abspath(__file__))
SCANNER_DIR = os.path.join(ROOT, "scanner")


def detect_target() -> str:
    """Detect the current OS + arch and return the Rust target triple."""
    system = platform.system()
    machine = platform.machine()
    target = TARGET_MAP.get((system, machine))
    if not target:
        # Fallback: try just the system with common arch
        logger.warning("Unknown platform (%s/%s), trying default x86_64", system, machine)
        fallback = {
            "Windows": "x86_64-pc-windows-msvc",
            "Linux": "x86_64-unknown-linux-gnu",
            "Darwin": "x86_64-apple-darwin",
        }
        target = fallback.get(system)
        if not target:
            logger.error("Unsupported OS: %s", system)
            raise SystemExit(1)
    return target


def resolve_target(user_target: str | None) -> str:
    """Resolve user-specified target alias or auto-detect."""
    if user_target is None:
        return detect_target()

    # Check if it's a friendly alias
    alias = user_target.lower().replace(" ", "-")
    if alias in CROSS_ALIASES:
        return CROSS_ALIASES[alias]

    # Assume it's a full Rust target triple
    return user_target


def get_binary_path(target: str) -> str:
    """Get the expected output binary path for a given target."""
    name = "xray-scanner.exe" if "windows" in target else "xray-scanner"
    return os.path.join(SCANNER_DIR, "target", target, "release", name)


def show_info(target: str):
    """Display detected platform and build info."""
    logger.info("=" * 60)
    logger.info("X-Ray Scanner — Build Info")
    logger.info("=" * 60)
    logger.info("  OS:           %s %s", platform.system(), platform.release())
    logger.info("  Architecture: %s", platform.machine())
    logger.info("  Python:       %s", platform.python_version())
    logger.info("  Rust target:  %s", target)
    logger.info("  Binary:       %s", get_binary_path(target))
    logger.info("  Scanner dir:  %s", SCANNER_DIR)

    # Check Rust toolchain
    rustc = shutil.which("rustc")
    cargo = shutil.which("cargo")
    logger.info("  rustc:        %s", rustc or "NOT FOUND")
    logger.info("  cargo:        %s", cargo or "NOT FOUND")

    if rustc:
        result = subprocess.run(["rustc", "--version"], capture_output=True, text=True)
        logger.info("  rustc ver:    %s", result.stdout.strip())

    # Check if target is installed
    result = subprocess.run(
        ["rustup", "target", "list", "--installed"],
        capture_output=True,
        text=True,
    )
    installed = result.stdout.strip().split("\n") if result.returncode == 0 else []
    if target in installed:
        logger.info("  Target:       INSTALLED")
    else:
        logger.info("  Target:       NOT INSTALLED (run: rustup target add %s)", target)

    logger.info("=" * 60)


def ensure_target_installed(target: str):
    """Ensure the Rust target triple is installed via rustup."""
    result = subprocess.run(
        ["rustup", "target", "list", "--installed"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("Could not query rustup targets")
        return

    installed = result.stdout.strip().split("\n")
    if target not in installed:
        logger.info("Installing Rust target: %s", target)
        result = subprocess.run(["rustup", "target", "add", target])
        if result.returncode != 0:
            logger.error("Failed to install target %s", target)
            raise SystemExit(1)


def run_cmd(args: list[str], label: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a command with progress reporting."""
    logger.info("\n%s", "\u2500" * 60)
    logger.info("  %s", label)
    logger.info("  $ %s", " ".join(args))
    logger.info("%s", "\u2500" * 60)
    start = time.perf_counter()
    result = subprocess.run(args, cwd=cwd or SCANNER_DIR)
    elapsed = time.perf_counter() - start
    status = "OK" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
    logger.info("  [%s] %.1fs", status, elapsed)
    return result


# -- Build Steps -----------------------------------------------------------


def step_generate_rules():
    """Step 1: Generate Rust rules from Python source of truth."""
    logger.info("\n[1/4] Generating Rust rules from Python...")
    gen_script = os.path.join(ROOT, "generate_rust_rules.py")
    result = subprocess.run([sys.executable, gen_script], cwd=ROOT)
    if result.returncode != 0:
        logger.error("Rule generation failed")
        raise SystemExit(1)


def step_test(target: str):
    """Step 2: Run cargo test."""
    result = run_cmd(
        ["cargo", "test", "--target", target],
        f"Running tests (target: {target})",
    )
    if result.returncode != 0:
        logger.error("Tests failed -- fix before building release")
        raise SystemExit(1)


def step_build_release(target: str):
    """Step 3: Build release binary."""
    result = run_cmd(
        ["cargo", "build", "--release", "--target", target],
        f"Building release (target: {target})",
    )
    if result.returncode != 0:
        logger.error("Release build failed")
        raise SystemExit(1)

    binary = get_binary_path(target)
    if os.path.exists(binary):
        size_mb = os.path.getsize(binary) / (1024 * 1024)
        logger.info("\n  Binary: %s", binary)
        logger.info("  Size:   %.1f MB", size_mb)
    else:
        logger.warning("Expected binary not found at %s", binary)


def step_cross_validate(target: str, scan_path: str):
    """Step 4: Cross-validate Rust binary vs Python scanner."""
    binary = get_binary_path(target)
    if not os.path.exists(binary):
        logger.error("Binary not found -- build first")
        raise SystemExit(1)

    # Check that the target matches the current OS (can't run cross-compiled binaries)
    current_os = platform.system()
    if "windows" in target and current_os != "Windows":
        logger.info("SKIP: Can't run Windows binary on non-Windows OS")
        return
    if "linux" in target and current_os != "Linux":
        logger.info("SKIP: Can't run Linux binary on non-Linux OS")
        return
    if "darwin" in target and current_os != "Darwin":
        logger.info("SKIP: Can't run macOS binary on non-macOS OS")
        return

    scan_path = os.path.abspath(scan_path)
    if not os.path.isdir(scan_path):
        logger.error("Scan path not found: %s", scan_path)
        raise SystemExit(1)

    logger.info("\n[4/4] Cross-validating against Python scanner...")
    logger.info("  Scanning: %s", scan_path)

    # -- Python scan --
    sys.path.insert(0, ROOT)
    from xray.scanner import scan_project

    start = time.perf_counter()
    py_result = scan_project(scan_path)
    py_ms = round((time.perf_counter() - start) * 1000, 1)

    py_by_rule: dict[str, int] = {}
    for f in py_result.findings:
        py_by_rule[f.rule_id] = py_by_rule.get(f.rule_id, 0) + 1

    # -- Rust scan --
    start = time.perf_counter()
    proc = subprocess.run(
        [binary, scan_path, "--severity", "LOW", "--json"],
        capture_output=True,
        text=True,
    )
    rust_ms = round((time.perf_counter() - start) * 1000, 1)

    if proc.returncode != 0:
        logger.error("Rust scanner failed:\n%s", proc.stderr)
        raise SystemExit(1)

    try:
        rust_data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Rust scanner output: %s", e)
        raise SystemExit(1) from e

    rust_by_rule: dict[str, int] = {}
    for finding in rust_data["findings"]:
        rust_by_rule[finding["rule_id"]] = rust_by_rule.get(finding["rule_id"], 0) + 1

    # -- Compare --
    logger.info("\n%s", "=" * 60)
    logger.info("CROSS-VALIDATION: Python vs Rust")
    logger.info("=" * 60)
    logger.info(
        "  Python: %d files, %d findings  (%s ms)",
        py_result.files_scanned,
        len(py_result.findings),
        py_ms,
    )
    rust_total = rust_data["summary"]["total"]
    logger.info(
        "  Rust:   %d files, %d findings  (%s ms)",
        rust_data["files_scanned"],
        rust_total,
        rust_ms,
    )
    if rust_ms > 0:
        logger.info("  Speedup: %.1fx", py_ms / rust_ms)
    logger.info("")

    all_rules = sorted(set(list(py_by_rule.keys()) + list(rust_by_rule.keys())))
    mismatches = 0
    for rid in all_rules:
        pc = py_by_rule.get(rid, 0)
        rc = rust_by_rule.get(rid, 0)
        match = "OK" if pc == rc else "MISMATCH"
        if pc != rc:
            mismatches += 1
        logger.info("  %12s  Python=%3d  Rust=%3d  %s", rid, pc, rc, match)

    logger.info("")
    if mismatches == 0:
        logger.info("RESULT: PERFECT PARITY -- all rule counts match!")
    else:
        logger.error("RESULT: %d MISMATCHES found", mismatches)
        raise SystemExit(1)


# -- Main ------------------------------------------------------------------


def main():
    """Entry point for the build script."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(
        description="Build X-Ray Rust scanner -- auto-detects OS + architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Target aliases (--target):
  windows         x86_64-pc-windows-msvc
  windows-arm     aarch64-pc-windows-msvc
  linux           x86_64-unknown-linux-gnu
  linux-arm       aarch64-unknown-linux-gnu
  macos           x86_64-apple-darwin
  macos-arm       aarch64-apple-darwin  (Apple Silicon)
  apple-silicon   aarch64-apple-darwin

Or pass a full Rust target triple directly.
If omitted, auto-detects from current OS + architecture.
""",
    )
    parser.add_argument(
        "--target",
        "-t",
        type=str,
        default=None,
        help="Rust target triple or alias (default: auto-detect)",
    )
    parser.add_argument("--info", action="store_true", help="Show platform info and exit")
    parser.add_argument("--test-only", action="store_true", help="Only run cargo test")
    parser.add_argument(
        "--release-only",
        action="store_true",
        help="Skip tests, only build release",
    )
    parser.add_argument(
        "--validate",
        type=str,
        nargs="?",
        const="../Swarm",
        metavar="PATH",
        help="Cross-validate vs Python scanner on PATH (default: ../Swarm)",
    )
    parser.add_argument(
        "--skip-generate",
        action="store_true",
        help="Skip rule generation (use existing mod.rs)",
    )

    args = parser.parse_args()
    target = resolve_target(args.target)

    if args.info:
        show_info(target)
        return

    logger.info("=" * 60)
    logger.info("X-Ray Scanner Build -- %s %s", platform.system(), platform.machine())
    logger.info("Target: %s", target)
    logger.info("=" * 60)

    # Ensure target is installed
    ensure_target_installed(target)

    # Step 1: Generate rules
    if not args.skip_generate:
        step_generate_rules()
    else:
        logger.info("\n[1/4] Skipping rule generation (--skip-generate)")

    # Step 2: Test
    if args.release_only:
        logger.info("\n[2/4] Skipping tests (--release-only)")
    else:
        step_test(target)
        if args.test_only:
            logger.info("\nDone (test-only mode).")
            return

    # Step 3: Build release
    step_build_release(target)

    # Step 4: Cross-validate (optional)
    if args.validate is not None:
        step_cross_validate(target, args.validate)

    logger.info("\nBuild complete!")


if __name__ == "__main__":
    main()
