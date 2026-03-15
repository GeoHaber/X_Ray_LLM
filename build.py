#!/usr/bin/env python3
"""
Unified Build Script for X-Ray Scanner (Rust)

Detects OS + architecture, generates Rust rules from Python source of truth,
builds the Rust binary, runs tests, and optionally cross-validates against
the Python scanner.

Usage:
  python build.py                  # full build: generate → test → release
  python build.py --test-only      # just cargo test
  python build.py --validate       # build + cross-validate vs Python scanner
  python build.py --target linux   # cross-compile for Linux (if toolchain installed)
  python build.py --release-only   # skip tests, just build release
  python build.py --info           # show detected OS/arch/target info
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time

# ── OS / Architecture Detection ───────────────────────────────────────────

# Map (system, machine) → Rust target triple
TARGET_MAP = {
    # Windows
    ("Windows", "AMD64"):    "x86_64-pc-windows-msvc",
    ("Windows", "x86_64"):   "x86_64-pc-windows-msvc",
    ("Windows", "ARM64"):    "aarch64-pc-windows-msvc",
    # Linux
    ("Linux", "x86_64"):     "x86_64-unknown-linux-gnu",
    ("Linux", "aarch64"):    "aarch64-unknown-linux-gnu",
    ("Linux", "armv7l"):     "armv7-unknown-linux-gnueabihf",
    # macOS
    ("Darwin", "x86_64"):    "x86_64-apple-darwin",
    ("Darwin", "arm64"):     "aarch64-apple-darwin",
    ("Darwin", "aarch64"):   "aarch64-apple-darwin",
}

# Friendly names for cross-compile aliases
CROSS_ALIASES = {
    "windows":       "x86_64-pc-windows-msvc",
    "windows-arm":   "aarch64-pc-windows-msvc",
    "linux":         "x86_64-unknown-linux-gnu",
    "linux-arm":     "aarch64-unknown-linux-gnu",
    "macos":         "x86_64-apple-darwin",
    "macos-arm":     "aarch64-apple-darwin",
    "apple-silicon": "aarch64-apple-darwin",
}

# Binary name per OS
BINARY_NAME = {
    "Windows": "xray-scanner.exe",
    "Linux":   "xray-scanner",
    "Darwin":  "xray-scanner",
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
        print(f"WARNING: Unknown platform ({system}/{machine}), trying default x86_64",
              file=sys.stderr)
        fallback = {
            "Windows": "x86_64-pc-windows-msvc",
            "Linux": "x86_64-unknown-linux-gnu",
            "Darwin": "x86_64-apple-darwin",
        }
        target = fallback.get(system)
        if not target:
            print(f"ERROR: Unsupported OS: {system}", file=sys.stderr)
            sys.exit(1)
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
    print("=" * 60)
    print("X-Ray Scanner — Build Info")
    print("=" * 60)
    print(f"  OS:           {platform.system()} {platform.release()}")
    print(f"  Architecture: {platform.machine()}")
    print(f"  Python:       {platform.python_version()}")
    print(f"  Rust target:  {target}")
    print(f"  Binary:       {get_binary_path(target)}")
    print(f"  Scanner dir:  {SCANNER_DIR}")

    # Check Rust toolchain
    rustc = shutil.which("rustc")
    cargo = shutil.which("cargo")
    print(f"  rustc:        {rustc or 'NOT FOUND'}")
    print(f"  cargo:        {cargo or 'NOT FOUND'}")

    if rustc:
        result = subprocess.run(["rustc", "--version"], capture_output=True, text=True)
        print(f"  rustc ver:    {result.stdout.strip()}")

    # Check if target is installed
    result = subprocess.run(["rustup", "target", "list", "--installed"],
                            capture_output=True, text=True)
    installed = result.stdout.strip().split("\n") if result.returncode == 0 else []
    if target in installed:
        print(f"  Target:       INSTALLED")
    else:
        print(f"  Target:       NOT INSTALLED (run: rustup target add {target})")

    print("=" * 60)


def ensure_target_installed(target: str):
    """Ensure the Rust target triple is installed via rustup."""
    result = subprocess.run(["rustup", "target", "list", "--installed"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print("WARNING: Could not query rustup targets", file=sys.stderr)
        return

    installed = result.stdout.strip().split("\n")
    if target not in installed:
        print(f"Installing Rust target: {target}")
        result = subprocess.run(["rustup", "target", "add", target])
        if result.returncode != 0:
            print(f"ERROR: Failed to install target {target}", file=sys.stderr)
            sys.exit(1)


def run_cmd(args: list[str], label: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a command with progress reporting."""
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"  $ {' '.join(args)}")
    print(f"{'─' * 60}")
    start = time.perf_counter()
    result = subprocess.run(args, cwd=cwd or SCANNER_DIR)
    elapsed = time.perf_counter() - start
    status = "OK" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
    print(f"  [{status}] {elapsed:.1f}s")
    return result


# ── Build Steps ───────────────────────────────────────────────────────────

def step_generate_rules():
    """Step 1: Generate Rust rules from Python source of truth."""
    print("\n[1/4] Generating Rust rules from Python...")
    gen_script = os.path.join(ROOT, "generate_rust_rules.py")
    result = subprocess.run([sys.executable, gen_script], cwd=ROOT)
    if result.returncode != 0:
        print("ERROR: Rule generation failed", file=sys.stderr)
        sys.exit(1)


def step_test(target: str):
    """Step 2: Run cargo test."""
    result = run_cmd(
        ["cargo", "test", "--target", target],
        f"Running tests (target: {target})"
    )
    if result.returncode != 0:
        print("ERROR: Tests failed — fix before building release", file=sys.stderr)
        sys.exit(1)


def step_build_release(target: str):
    """Step 3: Build release binary."""
    result = run_cmd(
        ["cargo", "build", "--release", "--target", target],
        f"Building release (target: {target})"
    )
    if result.returncode != 0:
        print("ERROR: Release build failed", file=sys.stderr)
        sys.exit(1)

    binary = get_binary_path(target)
    if os.path.exists(binary):
        size_mb = os.path.getsize(binary) / (1024 * 1024)
        print(f"\n  Binary: {binary}")
        print(f"  Size:   {size_mb:.1f} MB")
    else:
        print(f"WARNING: Expected binary not found at {binary}", file=sys.stderr)


def step_cross_validate(target: str, scan_path: str):
    """Step 4: Cross-validate Rust binary vs Python scanner."""
    binary = get_binary_path(target)
    if not os.path.exists(binary):
        print("ERROR: Binary not found — build first", file=sys.stderr)
        sys.exit(1)

    # Check that the target matches the current OS (can't run cross-compiled binaries)
    current_os = platform.system()
    if "windows" in target and current_os != "Windows":
        print("SKIP: Can't run Windows binary on non-Windows OS")
        return
    if "linux" in target and current_os != "Linux":
        print("SKIP: Can't run Linux binary on non-Linux OS")
        return
    if "darwin" in target and current_os != "Darwin":
        print("SKIP: Can't run macOS binary on non-macOS OS")
        return

    scan_path = os.path.abspath(scan_path)
    if not os.path.isdir(scan_path):
        print(f"ERROR: Scan path not found: {scan_path}", file=sys.stderr)
        sys.exit(1)

    print(f"\n[4/4] Cross-validating against Python scanner...")
    print(f"  Scanning: {scan_path}")

    # ── Python scan ──
    sys.path.insert(0, ROOT)
    from xray.scanner import scan_project
    start = time.perf_counter()
    py_result = scan_project(scan_path)
    py_ms = round((time.perf_counter() - start) * 1000, 1)

    py_by_rule = {}
    for f in py_result.findings:
        py_by_rule[f.rule_id] = py_by_rule.get(f.rule_id, 0) + 1

    # ── Rust scan ──
    start = time.perf_counter()
    proc = subprocess.run(
        [binary, scan_path, "--severity", "LOW", "--json"],
        capture_output=True, text=True
    )
    rust_ms = round((time.perf_counter() - start) * 1000, 1)

    if proc.returncode != 0:
        print(f"ERROR: Rust scanner failed:\n{proc.stderr}", file=sys.stderr)
        sys.exit(1)

    rust_data = json.loads(proc.stdout)

    rust_by_rule = {}
    for finding in rust_data["findings"]:
        rust_by_rule[finding["rule_id"]] = rust_by_rule.get(finding["rule_id"], 0) + 1

    # ── Compare ──
    print("\n" + "=" * 60)
    print("CROSS-VALIDATION: Python vs Rust")
    print("=" * 60)
    print(f"  Python: {py_result.files_scanned} files, {len(py_result.findings)} findings  ({py_ms} ms)")
    rust_total = rust_data["summary"]["total"]
    print(f"  Rust:   {rust_data['files_scanned']} files, {rust_total} findings  ({rust_ms} ms)")
    if rust_ms > 0:
        print(f"  Speedup: {py_ms / rust_ms:.1f}x")
    print()

    all_rules = sorted(set(list(py_by_rule.keys()) + list(rust_by_rule.keys())))
    mismatches = 0
    for rid in all_rules:
        pc = py_by_rule.get(rid, 0)
        rc = rust_by_rule.get(rid, 0)
        match = "OK" if pc == rc else "MISMATCH"
        if pc != rc:
            mismatches += 1
        print(f"  {rid:12s}  Python={pc:3d}  Rust={rc:3d}  {match}")

    print()
    if mismatches == 0:
        print("RESULT: PERFECT PARITY — all rule counts match!")
    else:
        print(f"RESULT: {mismatches} MISMATCHES found")
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Build X-Ray Rust scanner — auto-detects OS + architecture",
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
"""
    )
    parser.add_argument("--target", "-t", type=str, default=None,
                        help="Rust target triple or alias (default: auto-detect)")
    parser.add_argument("--info", action="store_true",
                        help="Show platform info and exit")
    parser.add_argument("--test-only", action="store_true",
                        help="Only run cargo test")
    parser.add_argument("--release-only", action="store_true",
                        help="Skip tests, only build release")
    parser.add_argument("--validate", type=str, nargs="?", const="../Swarm",
                        metavar="PATH",
                        help="Cross-validate vs Python scanner on PATH (default: ../Swarm)")
    parser.add_argument("--skip-generate", action="store_true",
                        help="Skip rule generation (use existing mod.rs)")

    args = parser.parse_args()
    target = resolve_target(args.target)

    if args.info:
        show_info(target)
        return

    print("=" * 60)
    print(f"X-Ray Scanner Build — {platform.system()} {platform.machine()}")
    print(f"Target: {target}")
    print("=" * 60)

    # Ensure target is installed
    ensure_target_installed(target)

    # Step 1: Generate rules
    if not args.skip_generate:
        step_generate_rules()
    else:
        print("\n[1/4] Skipping rule generation (--skip-generate)")

    # Step 2: Test
    if args.release_only:
        print("\n[2/4] Skipping tests (--release-only)")
    else:
        step_test(target)
        if args.test_only:
            print("\nDone (test-only mode).")
            return

    # Step 3: Build release
    step_build_release(target)

    # Step 4: Cross-validate (optional)
    if args.validate is not None:
        step_cross_validate(target, args.validate)

    print("\nBuild complete!")


if __name__ == "__main__":
    main()
