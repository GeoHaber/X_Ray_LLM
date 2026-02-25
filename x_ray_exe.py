#!/usr/bin/env python3
"""
X-Ray Standalone — Self-Contained Windows Code Quality Scanner
===============================================================

This is the standalone entry point for the X-Ray .exe build.
It bundles:
  - Hardware detection (CPU, OS, RAM)
  - Tool availability checks (ruff, bandit, Rust extensions)
  - Full code quality scanning (smells, duplicates, lint, security)
  - Rust porting advisor
  - JSON report export

Works on any Windows machine without requiring Python or any
external tools to be pre-installed (all bundled inside the .exe).

Usage::

    x_ray.exe                                        # interactive mode
    x_ray.exe --path C:\\my_project                  # full scan
    x_ray.exe --path . --smell                       # smells only
    x_ray.exe --path . --lint                        # lint only
    x_ray.exe --path . --security                    # security only
    x_ray.exe --path . --duplicates                  # duplicates only
    x_ray.exe --path . --full-scan                   # everything
    x_ray.exe --path . --rustify                     # Rust porting advisor
    x_ray.exe --path . --report out.json             # save JSON report
    x_ray.exe --hw                                   # hardware info only
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

# ---------------------------------------------------------------------------
# Fix for PyInstaller frozen bundles: ensure our package root is on sys.path
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    _BUNDLE_DIR = Path(sys._MEIPASS)
    _EXE_DIR = Path(sys.executable).parent
    # Add the bundle dir so our Core/Analysis/Lang packages are importable
    if str(_BUNDLE_DIR) not in sys.path:
        sys.path.insert(0, str(_BUNDLE_DIR))
else:
    _BUNDLE_DIR = Path(__file__).resolve().parent
    _EXE_DIR = _BUNDLE_DIR

# ---------------------------------------------------------------------------
# Imports from the X-Ray project
# ---------------------------------------------------------------------------
from Core.config import __version__
from Analysis._analyzer_base import _find_tool  # noqa: E402
from Core.scan_phases import (
    scan_codebase, run_smell_phase, run_duplicate_phase,
    run_lint_phase, run_security_phase, run_rustify_scan, collect_reports,
)
from Core.utils import check_trial_license as _check_trial_license

# ---------------------------------------------------------------------------
# ASCII Art banner
# ---------------------------------------------------------------------------

_EXE_BANNER = f"""
{'='*66}
  X-RAY v{__version__} — Standalone Code Quality Scanner (.exe)
  AST Smells + Ruff Lint + Bandit Security + Rust Advisor
{'='*66}
"""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

from Core.utils import setup_logger  # noqa: E402
log = setup_logger("x_ray_exe")


# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------

def _wmic_value(query: str, field: str) -> Optional[str]:
    """Run a wmic query and return the value for *field*, or None."""
    try:
        result = subprocess.run(
            ["wmic"] + query.split() + ["/value"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split('\n'):
            if line.startswith(f"{field}="):
                return line.split('=', 1)[1].strip()
    except Exception:
        pass
    return None


def _detect_rust_info() -> Dict[str, Any]:
    """Detect Rust toolchain and x_ray_core availability."""
    info: Dict[str, Any] = {}
    info["rust_available"] = shutil.which("rustc") is not None
    if info["rust_available"]:
        try:
            result = subprocess.run(
                ["rustc", "--version"],
                capture_output=True, text=True, timeout=5
            )
            info["rust_version"] = result.stdout.strip()
        except Exception:
            info["rust_version"] = "unknown"
    try:
        import x_ray_core  # noqa: F401
        info["rust_acceleration"] = True
    except ImportError:
        info["rust_acceleration"] = False
    return info


def detect_hardware() -> Dict[str, Any]:
    """Detect CPU, OS, RAM and other hardware info.

    Delegates to ``_mothership.hardware_detection`` for the core profile,
    then layers on Rust-toolchain specifics needed by the .exe workflow.
    """
    from _mothership.hardware_detection import detect_hardware as _detect_hw

    hw = _detect_hw()
    info = hw.to_dict()

    # Remap field names to match the dict keys print_hardware() expects
    info.setdefault("os", info.pop("os_name", platform.system()))
    info.setdefault("os_release", info.pop("os_version", platform.release()))
    info.setdefault("machine", info.get("arch", platform.machine()))
    info.setdefault("processor", info.get("cpu_brand", "Unknown"))
    info.setdefault("cpu_name", info.get("cpu_brand", info.get("processor", "")))
    info.setdefault("cpu_count_logical", info.get("cpu_cores", os.cpu_count() or 1))
    info.setdefault("cpu_count_physical", info.get("cpu_cores", info["cpu_count_logical"]))

    # Rust environment (x_ray_exe specific)
    info.update(_detect_rust_info())

    return info


def print_hardware(hw: Dict[str, Any]) -> None:
    """Pretty-print hardware information."""
    print(f"\n{'='*50}")
    print("  SYSTEM HARDWARE PROFILE")
    print(f"{'='*50}")
    print(f"  OS:           {hw['os']} {hw.get('os_release', '')} ({hw['machine']})")
    print(f"  CPU:          {hw.get('cpu_name', hw['processor'])}")
    print(f"  Cores:        {hw.get('cpu_count_physical', '?')} physical, "
          f"{hw['cpu_count_logical']} logical")
    if hw.get('ram_gb') and hw['ram_gb'] != 'unknown':
        print(f"  RAM:          {hw['ram_gb']} GB")
    if hw.get('rust_available'):
        print(f"  Rust:         {hw.get('rust_version', 'available')}")
    else:
        print("  Rust:         not installed")
    print(f"  Accelerator:  {'x_ray_core (Rust)' if hw.get('rust_acceleration') else 'Pure Python'}")
    print(f"{'='*50}\n")


# ---------------------------------------------------------------------------
# Tool availability (ruff / bandit)
# ---------------------------------------------------------------------------

# _find_tool is imported from Analysis._analyzer_base (canonical implementation)


def check_tools() -> Dict[str, str]:
    """Check availability of external tools."""
    tools = {}
    for name in ("ruff", "bandit"):
        path = _find_tool(name)
        tools[name] = path or ""
    return tools


# ---------------------------------------------------------------------------
# Scan phases and report collection imported from Core.scan_phases
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Interactive Mode — folder picker, scan menu, report prompt
# ---------------------------------------------------------------------------

def _pick_folder() -> Optional[str]:
    """Open a Windows folder-picker dialog. Returns path or None."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(
            title="X-Ray — Select project folder to scan",
        )
        root.destroy()
        return folder if folder else None
    except Exception:
        return None


def _step_pick_folder() -> str:
    """Interactive step 1: pick the folder to scan."""
    print(f"\n{'─'*50}")
    print("  WELCOME TO X-RAY!")
    print(f"{'─'*50}")
    print()
    print("  Let's scan your code! First, pick a folder...")
    print()

    folder = _pick_folder()
    if not folder:
        print("  No folder selected. Type the path manually:")
        folder = input("  Path> ").strip().strip('"')
    if not folder or not Path(folder).is_dir():
        print(f"  ERROR: '{folder}' is not a valid directory.")
        sys.exit(1)

    print(f"  ✓ Selected: {folder}")
    print()
    return folder


_SCAN_FLAG_MAP = {
    "1": {"smell": True, "lint": True, "security": True, "duplicates": True, "full_scan": True},
    "2": {"smell": True, "lint": True, "security": True},
    "3": {"smell": True},
    "4": {"lint": True},
    "5": {"security": True},
    "6": {"duplicates": True},
    "7": {"rustify": True},
}

_SCAN_MODE_NAMES = {
    "1": "Full Scan", "2": "Quick Scan", "3": "Code Smells",
    "4": "Lint", "5": "Security", "6": "Duplicates", "7": "Rust Advisor",
}


def _step_choose_mode(args: argparse.Namespace) -> str:
    """Interactive step 2: choose scan mode."""
    print(f"{'─'*50}")
    print("  WHAT DO YOU WANT TO SCAN?")
    print(f"{'─'*50}")
    print()
    print("  [1]  Full Scan          — Smells + Lint + Security + Duplicates (recommended)")
    print("  [2]  Quick Scan         — Smells + Lint + Security  (faster)")
    print("  [3]  Code Smells only   — Function length, complexity, nesting")
    print("  [4]  Lint only          — Ruff code style & errors")
    print("  [5]  Security only      — Bandit vulnerability scan")
    print("  [6]  Duplicates only    — Find copy-pasted code")
    print("  [7]  Rust Advisor       — Rank functions for Rust porting")
    print()

    choice = input("  Choose [1-7] (default: 2) > ").strip() or "2"
    for k, v in _SCAN_FLAG_MAP.get(choice, _SCAN_FLAG_MAP["2"]).items():
        setattr(args, k, v)

    print(f"  ✓ Mode: {_SCAN_MODE_NAMES.get(choice, 'Quick Scan')}")
    print()
    return choice


def _step_report_option(args: argparse.Namespace) -> None:
    """Interactive step 3: choose report save option."""
    print(f"{'─'*50}")
    print("  SAVE A JSON REPORT?")
    print(f"{'─'*50}")
    print()
    print("  [1]  Yes — save next to the scanned folder")
    print("  [2]  Yes — let me choose where")
    print("  [3]  No  — just show results on screen")
    print()

    report_choice = input("  Choose [1-3] (default: 1) > ").strip() or "1"

    if report_choice == "1":
        project_name = Path(args.path).name
        args.report = str(Path(args.path) / f"x_ray_report_{project_name}.json")
        print(f"  ✓ Report: {args.report}")
    elif report_choice == "2":
        args.report = _save_report_dialog(args.path)
    else:
        print("  ✓ No report — results on screen only")

    print()
    print(f"{'─'*50}")
    print("  Starting scan...")
    print(f"{'─'*50}")
    print()


def _save_report_dialog(folder: str) -> Optional[str]:
    """Show a save-as dialog for the report file."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        rpath = filedialog.asksaveasfilename(
            title="Save X-Ray report as...",
            defaultextension=".json",
            initialfile=f"x_ray_report_{Path(folder).name}.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        root.destroy()
        if rpath:
            print(f"  ✓ Report: {rpath}")
            return rpath
    except Exception:
        pass
    print("  ✓ No report — results on screen only")
    return None


def _interactive_menu() -> argparse.Namespace:
    """Show a friendly interactive menu when no CLI args are given."""
    folder = _step_pick_folder()

    args = argparse.Namespace(
        path=folder, smell=False, duplicates=False, lint=False,
        security=False, full_scan=False, rustify=False,
        report=None, exclude=None, hw=False, verbose=False,
    )

    _step_choose_mode(args)
    _step_report_option(args)
    return args


def _needs_interactive() -> bool:
    """Check if we should launch interactive mode (no meaningful CLI args)."""
    # If running from command line with actual arguments, use CLI mode
    # sys.argv[0] is the script/exe name
    real_args = sys.argv[1:]
    return len(real_args) == 0


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    """Parse and normalise CLI arguments."""
    from Core.cli_args import add_common_scan_args, normalize_scan_args

    parser = argparse.ArgumentParser(
        description=_EXE_BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_scan_args(parser)
    # x_ray_exe-specific flags
    parser.add_argument("--hw", action="store_true", help="Show hardware info and exit")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # --hw bypasses default-selection logic
    if not args.hw:
        normalize_scan_args(args)

    return args


def _print_tool_status(tools: dict) -> None:
    """Print tool availability status."""
    print("  Tool Status:")
    for name, path in tools.items():
        status = f"OK ({path})" if path else "not found (skipped)"
        print(f"    {name:10s}  {status}")
    try:
        import x_ray_core  # noqa: F401
        print(f"    {'x_ray_core':10s}  OK (Rust acceleration)")
    except ImportError:
        print(f"    {'x_ray_core':10s}  not available (using pure Python)")
    print()


def _resolve_target(args) -> Path:
    """Resolve and validate target path."""
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"  ERROR: {root} is not a directory.")
        sys.exit(1)
    print(f"  Target: {root}\n")
    return root


def _run_scan_phases(args, root: Path):
    """Execute all requested scan phases and collect results."""
    all_issues = []

    if args.smell or args.duplicates:
        functions, classes, errors = scan_codebase(
            root, exclude=args.exclude, verbose=args.verbose)
        print(f"  Found {len(functions)} functions, {len(classes)} classes")
        if errors:
            print(f"  ({len(errors)} parse errors)")
    else:
        functions, classes = [], []

    detector = None
    if args.smell:
        detector, smell_issues = run_smell_phase(functions, classes)
        all_issues.extend(smell_issues)

    finder = run_duplicate_phase(functions) if args.duplicates else None

    if args.lint:
        linter, lint_issues = run_lint_phase(root, exclude=args.exclude)
        all_issues.extend(lint_issues)
    else:
        linter, lint_issues = None, []

    if args.security:
        sec_analyzer, sec_issues = run_security_phase(root, exclude=args.exclude)
        all_issues.extend(sec_issues)
    else:
        sec_analyzer, sec_issues = None, []

    return detector, finder, linter, lint_issues, sec_analyzer, sec_issues


def main():
    """Main entry point for x_ray.exe."""
    print(_EXE_BANNER)

    # --- Trial license gate ---
    if not _check_trial_license():
        sys.exit(1)

    # --- Interactive or CLI mode ---
    if _needs_interactive():
        args = _interactive_menu()
    else:
        args = _parse_args()

    hw = detect_hardware()
    print_hardware(hw)
    if args.hw:
        return

    _print_tool_status(check_tools())
    root = _resolve_target(args)

    # Rustify mode — separate workflow
    if args.rustify:
        results = run_rustify_scan(root, exclude=args.exclude)
        if args.report:
            with open(args.report, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)
            print(f"\n  Report saved to {args.report}")
        return

    # Standard scan
    start_time = time.time()
    detector, finder, linter, lint_issues, sec_analyzer, sec_issues = \
        _run_scan_phases(args, root)

    from Core.scan_phases import AnalysisComponents
    results = collect_reports(AnalysisComponents(
        detector, finder, linter, lint_issues,
        sec_analyzer, sec_issues))
    results["hardware"] = hw

    duration = time.time() - start_time
    print(f"\n  Total scan time: {duration:.2f}s")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"  Report saved to {args.report}")

    print(f"\n{'='*66}")
    print("  X-Ray scan complete.")
    print(f"{'='*66}\n")


def _is_interactive_console() -> bool:
    """Return True when the .exe was likely double-clicked (not piped)."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Interrupted.")
    except Exception as exc:
        print(f"\n  FATAL ERROR: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        # Keep the window open when double-clicked from Explorer
        if getattr(sys, 'frozen', False) and _is_interactive_console():
            print()
            input("  Press Enter to exit...")
